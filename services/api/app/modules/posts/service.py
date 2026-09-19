"""Posts service: CRUD + Google publishing via Localith.

Sayvors is the schedule of record. Publishing pushes a post through
Localith's content_publishing_media endpoint right away (publish now) or
when its time comes (background worker over due scheduled rows). Localith
exposes no read/update/delete for posts, so edits and deletes apply to
our stored copy only.
"""
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..localith.models import LocalithConnection
from .models import LocationPost

logger = logging.getLogger(__name__)

# integrations/ lives at the repo root; make it importable like localith does.
_API_ROOT = Path(__file__).resolve().parents[4]
_REPO_ROOT = _API_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

PUBLISHABLE_FROM = ("draft", "scheduled", "failed")

# Retry-then-park: failed scheduled publishes retry with backoff this many
# times, then park as failed for the manual Retry button.
MAX_PUBLISH_ATTEMPTS = 5
RETRY_BASE_SECONDS = 300
RETRY_MAX_SECONDS = 7200
# Safety cap per worker pass (API quotas + bounded pass duration).
MAX_PER_PASS = 50

# Per-post advisory locks: publishing is NOT idempotent (double call =
# double Google post), so the same post never publishes twice at once —
# across workers, manual clicks, and the background loop. Different posts
# proceed in parallel.
_POST_LOCK_PREFIX = "sayvors:post-publish:"


def _is_postgres(db: AsyncSession) -> bool:
    """Advisory locks exist only on Postgres. Anywhere else (sqlite tests,
    single-process dev) there is nothing to coordinate with: take the lock
    as trivially held."""
    try:
        bind = db.get_bind() if hasattr(db, "get_bind") else db.bind  # type: ignore[union-attr]
        return bind is not None and bind.dialect.name == "postgresql"
    except Exception:
        return False


def _post_lock_stmt(blocking: bool, post_id: str):
    fn = "pg_advisory_lock" if blocking else "pg_try_advisory_lock"
    return sa_text(f"SELECT {fn}(hashtext('{_POST_LOCK_PREFIX}' || :pid))").bindparams(
        pid=str(post_id)
    )


async def _acquire_post_lock(db: AsyncSession, post_id: str) -> bool:
    """Blocking take. Trivially held where Postgres locks don't exist."""
    if not _is_postgres(db):
        return True
    try:
        await db.execute(_post_lock_stmt(True, post_id))
        return True
    except Exception as e:
        logger.debug("Post lock unavailable, proceeding unlocked: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return False


async def _try_post_lock(db: AsyncSession, post_id: str) -> bool:
    """Non-blocking take for worker passes: miss means SKIP, not wait."""
    if not _is_postgres(db):
        return True
    try:
        row = (await db.execute(_post_lock_stmt(False, post_id))).scalar()
        if row:
            return True
        try:
            await db.rollback()
        except Exception:
            pass
        return False
    except Exception as e:
        logger.debug("Post try-lock unavailable, proceeding unlocked: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return False


async def _release_post_lock(db: AsyncSession, post_id: str) -> None:
    try:
        await db.execute(
            sa_text(
                f"SELECT pg_advisory_unlock(hashtext('{_POST_LOCK_PREFIX}' || :pid))"
            ).bindparams(pid=str(post_id))
        )
    except Exception:
        pass


def _retry_delay(attempts: int) -> timedelta:
    """Backoff after N consecutive failures: 5m, 10m, 20m … capped at 2h."""
    seconds = min(RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1)), RETRY_MAX_SECONDS)
    return timedelta(seconds=seconds)


def _google_post_id(response: object) -> str | None:
    """Provider's post id, when it returns one (reserved for future remote
    deletion: per-tenant native Google or a Localith delete endpoint)."""
    if not isinstance(response, dict):
        return None
    for key in ("id", "postId", "post_id", "mediaId", "media_id"):
        value = response.get(key)
        if value:
            return str(value)
    for value in response.values():
        if isinstance(value, dict):
            nested = _google_post_id(value)
            if nested:
                return nested
    return None


def _serialize(p: LocationPost) -> dict:
    return {
        "id": p.id,
        "listing_id": p.listing_id,
        "location_name": p.location_name,
        "business_name": p.business_name,
        "title": p.title,
        "post_type": p.post_type,
        "description": p.description,
        "tags": list(p.tags or []),
        "keywords": list(p.keywords or []),
        "image_urls": list(p.image_urls or []),
        "cta_type": p.cta_type,
        "cta_url": p.cta_url,
        "status": p.status,
        "scheduled_on": p.scheduled_on.isoformat() if p.scheduled_on else None,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "delete_at": p.delete_at.isoformat() if p.delete_at else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "google_post_id": p.google_post_id,
        "error": p.error,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def _owned_post(db: AsyncSession, user_id: str, post_id: str) -> LocationPost | None:
    result = await db.execute(
        select(LocationPost).where(
            LocationPost.id == post_id,
            LocationPost.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _require_localith_listing(db: AsyncSession, user_id: str, listing_id: str) -> LocalithConnection:
    """Posts can only publish to a connected Localith listing (any branch)."""
    result = await db.execute(
        select(LocalithConnection).where(
            LocalithConnection.user_id == user_id,
            LocalithConnection.listing_id == listing_id,
        )
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise ValueError("Connect that branch in Localith before publishing posts.")
    return connection


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Bad datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_delete_at(delete_at: datetime | None, scheduled_on: datetime | None) -> None:
    """Auto-deletion must be in the future — and after the scheduled
    publish when both are set (deleting before publishing is nonsense)."""
    if delete_at is None:
        return
    if delete_at <= datetime.now(timezone.utc):
        raise ValueError("delete_at must be in the future.")
    if scheduled_on is not None and delete_at <= scheduled_on:
        raise ValueError("delete_at must be after the scheduled publish time.")


async def list_posts(
    db: AsyncSession, user_id: str, listing_id: str | None = None
) -> list[dict]:
    filters = [LocationPost.user_id == user_id]
    if listing_id:
        filters.append(LocationPost.listing_id == listing_id)
    rows = (
        await db.execute(
            select(LocationPost).where(*filters).order_by(LocationPost.created_at.desc()).limit(200)
        )
    ).scalars().all()
    return [_serialize(p) for p in rows]


async def create_post(db: AsyncSession, user_id: str, data: dict) -> dict:
    action = data.get("action", "publish")
    scheduled_on = _parse_dt(data.get("scheduled_on"))
    if action == "schedule" and scheduled_on is None:
        raise ValueError("scheduled_on is required to schedule a post.")
    if action == "schedule" and scheduled_on <= datetime.now(timezone.utc):  # type: ignore[operator]
        raise ValueError("scheduled_on must be in the future.")
    delete_at = _parse_dt(data.get("delete_at"))
    _validate_delete_at(delete_at, scheduled_on)
    end_date = _parse_dt(data.get("end_date"))

    post = LocationPost(
        id=str(uuid.uuid4()),
        user_id=user_id,
        listing_id=data["listing_id"],
        location_name=(data.get("location_name") or "")[:255],
        business_name=(data.get("business_name") or "Sayvors")[:255],
        title=(data.get("title") or "")[:500],
        post_type=data.get("post_type", "update"),
        description=(data.get("description") or "")[:1500],
        tags=[str(t)[:80] for t in data.get("tags", [])][:20],
        keywords=[str(k)[:80] for k in data.get("keywords", [])][:20],
        image_urls=[str(u)[:2000] for u in data.get("image_urls", [])][:5],
        cta_type=data.get("cta_type"),
        cta_url=data.get("cta_url"),
        status="scheduled" if action == "schedule" else "draft",
        scheduled_on=scheduled_on,
        delete_at=delete_at,
        end_date=end_date,
    )
    db.add(post)
    await db.flush()

    if action == "publish":
        return await publish_post(db, user_id, post.id)
    await db.commit()
    await db.refresh(post)
    return {"post": _serialize(post), "google_published": False, "images_sent": 0, "images_skipped": 0}


async def update_post(
    db: AsyncSession, user_id: str, post_id: str, data: dict
) -> dict:
    post = await _owned_post(db, user_id, post_id)
    if post is None:
        raise ValueError("Post not found.")
    if post.status == "published":
        raise ValueError("Published posts live on Google now — archive instead of editing.")

    for field in ("location_name", "business_name", "title", "description", "cta_type", "cta_url"):
        if data.get(field) is not None:
            setattr(post, field, data[field])
    if data.get("post_type") in ("update", "event", "offer"):
        post.post_type = data["post_type"]
    for field in ("tags", "keywords", "image_urls"):
        if data.get(field) is not None:
            setattr(post, field, list(data[field]))

    # delete_at: explicit null cancels, absent key leaves untouched
    # (router passes exclude_unset).
    if "delete_at" in data:
        post.delete_at = _parse_dt(data.get("delete_at"))
    if "end_date" in data:
        post.end_date = _parse_dt(data.get("end_date"))

    new_status = data.get("status")
    if new_status is not None and new_status != post.status:
        if new_status == "published" and post.status in PUBLISHABLE_FROM:
            # Publish now (scheduled/draft/failed -> Google).
            await db.flush()
            return await publish_post(db, user_id, post.id)
        if new_status == "published":
            # Restore an archived record: it already went live on Google
            # once, so flip the flag without re-pushing.
            post.status = "published"
        elif new_status in ("draft", "scheduled", "archived"):
            post.status = new_status
            if new_status == "scheduled":
                post.scheduled_on = _parse_dt(data.get("scheduled_on")) or post.scheduled_on
                if post.scheduled_on is None:
                    raise ValueError("scheduled_on is required to schedule a post.")
        else:
            raise ValueError(f"Cannot transition to {new_status}.")
    if "delete_at" in data or "scheduled_on" in data:
        _validate_delete_at(post.delete_at, post.scheduled_on)
    post.error = None
    await db.commit()
    await db.refresh(post)
    return {"post": _serialize(post), "google_published": False, "images_sent": 0, "images_skipped": 0}


async def delete_post(db: AsyncSession, user_id: str, post_id: str) -> None:
    post = await _owned_post(db, user_id, post_id)
    if post is None:
        raise ValueError("Post not found.")
    await db.delete(post)
    await db.commit()


async def publish_post(db: AsyncSession, user_id: str, post_id: str) -> dict:
    """Publish one post to Google via Localith right now.

    Publishing is NOT idempotent (a double call posts twice on Google), so
    the post's advisory lock is held for the whole call: manual clicks, the
    background loop, and racing workers serialize per post while different
    posts proceed in parallel.
    """
    from integrations.channels import embedsocial

    locked = await _acquire_post_lock(db, post_id)
    try:
        return await _publish_post_inner(db, user_id, post_id)
    finally:
        if locked:
            await _release_post_lock(db, post_id)


async def _publish_post_inner(db: AsyncSession, user_id: str, post_id: str) -> dict:
    from integrations.channels import embedsocial

    post = await _owned_post(db, user_id, post_id)
    if post is None:
        raise ValueError("Post not found.")
    if post.status not in PUBLISHABLE_FROM:
        raise ValueError(f"Cannot publish a {post.status} post.")
    await _require_localith_listing(db, user_id, post.listing_id)

    sent = [u for u in (post.image_urls or []) if u.startswith("http")]
    skipped = len(post.image_urls or []) - len(sent)
    try:
        response = await asyncio.to_thread(
            embedsocial.publish_media_post,
            post.listing_id,
            post_type=post.post_type,
            title=post.title or None,
            caption=post.description,
            image_urls=sent,
            cta_type=post.cta_type,
            cta_url=post.cta_url,
            end_date=post.end_date.isoformat() if post.end_date else None,
        )
    except Exception as e:
        _register_publish_failure(post, str(e)[:500])
        await db.commit()
        raise RuntimeError(f"Google publish failed: {e}")

    post.status = "published"
    post.published_at = datetime.now(timezone.utc)
    post.error = None
    post.attempts = 0
    post.next_retry_at = None
    post.localith_response = response
    google_id = _google_post_id(response)
    if google_id:
        post.google_post_id = google_id
    await db.commit()
    await db.refresh(post)
    return {
        "post": _serialize(post),
        "google_published": True,
        "images_sent": len(sent),
        "images_skipped": skipped,
    }


def _register_publish_failure(post: LocationPost, error: str) -> None:
    """Retry-then-park: stay scheduled with backoff until MAX_PUBLISH_ATTEMPTS,
    then park as failed for the manual Retry button. Non-scheduled rows
    (manual draft publishes) park immediately — the UI already shows the
    error and offers Retry."""
    post.error = error
    post.attempts = (post.attempts or 0) + 1
    if post.status == "scheduled" and post.attempts < MAX_PUBLISH_ATTEMPTS:
        post.next_retry_at = datetime.now(timezone.utc) + _retry_delay(post.attempts)
    else:
        post.status = "failed"
        post.next_retry_at = None


async def publish_due(db: AsyncSession) -> dict:
    """Publish due scheduled posts across all users. Returns counts.

    Due = publish time passed AND (never tried OR retry time passed).
    Each post is try-locked: a parallel worker or manual click holding it
    means SKIP, not wait — publishing twice on Google is the one outcome
    that must never happen.
    """
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LocationPost)
            .where(
                LocationPost.status == "scheduled",
                LocationPost.scheduled_on.is_not(None),
                LocationPost.scheduled_on <= now,
                (LocationPost.next_retry_at.is_(None))
                | (LocationPost.next_retry_at <= now),
            )
            .order_by(LocationPost.scheduled_on)
            .limit(MAX_PER_PASS)
        )
    ).scalars().all()
    totals = {
        "checked": len(rows), "published": 0, "failed": 0,
        "retried": 0, "skipped": 0, "errors": [],
    }
    for post in rows:
        post_id, user_id = post.id, post.user_id
        held = await _try_post_lock(db, post_id)
        if not held:
            totals["skipped"] += 1
            continue
        try:
            await publish_post(db, user_id, post_id)
            totals["published"] += 1
        except Exception as e:
            fresh = await _owned_post(db, user_id, post_id)
            if fresh is not None and fresh.status == "scheduled":
                totals["retried"] += 1
            else:
                totals["failed"] += 1
            totals["errors"].append(f"{post_id[:8]}: {str(e)[:120]}")
            try:
                await db.rollback()
            except Exception:
                pass
        finally:
            await _release_post_lock(db, post_id)
    return totals


async def delete_due(db: AsyncSession) -> dict:
    """Delete rows whose delete_at has passed (any status — the schedule
    wins). Local rows only: Google follows its own lifecycle (end_date).
    Deletes are naturally idempotent, so no locking needed."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LocationPost).where(
                LocationPost.delete_at.is_not(None),
                LocationPost.delete_at <= now,
            )
        )
    ).scalars().all()
    totals = {"checked": len(rows), "deleted": 0}
    for post in rows:
        try:
            await db.delete(post)
            await db.flush()
            totals["deleted"] += 1
        except Exception as e:
            logger.warning("Scheduled post deletion failed for %s: %s", post.id, e)
            try:
                await db.rollback()
            except Exception:
                pass
    try:
        await db.commit()
    except Exception:
        pass
    return totals
