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
from ..notifications.service import notify
from .models import LocationPost

logger = logging.getLogger(__name__)

# integrations/ lives at the repo root; make it importable like localith does.
_API_ROOT = Path(__file__).resolve().parents[4]
_REPO_ROOT = _API_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

PUBLISHABLE_FROM = ("draft", "scheduled", "failed")

# Scheduling primitives live in one place (app.modules.scheduling) and are
# re-exported here under their historic names so callers and tests don't
# churn. Same behavior, single implementation.
from ..scheduling import (
    MAX_PUBLISH_ATTEMPTS,
    is_postgres as _is_postgres,
    provider_post_id as _google_post_id,
    release_lock,
    retry_delay as _retry_delay,
    take_lock,
)

# Safety cap per worker pass (API quotas + bounded pass duration).
MAX_PER_PASS = 50

# Per-post advisory locks: publishing is NOT idempotent (double call =
# double Google post), so the same post never publishes twice at once —
# across workers, manual clicks, and the background loop. Different posts
# proceed in parallel.
_POST_LOCK_PREFIX = "sayvors:post-publish:"


async def _acquire_post_lock(db: AsyncSession, post_id: str) -> bool:
    """Blocking take. Trivially held where Postgres locks don't exist."""
    return await take_lock(db, True, _POST_LOCK_PREFIX, post_id)


async def _try_post_lock(db: AsyncSession, post_id: str) -> bool:
    """Non-blocking take for worker passes: miss means SKIP, not wait."""
    return await take_lock(db, False, _POST_LOCK_PREFIX, post_id)


async def _release_post_lock(db: AsyncSession, post_id: str) -> None:
    await release_lock(db, _POST_LOCK_PREFIX, post_id)


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
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "coupon_code": p.coupon_code,
        "terms_conditions": p.terms_conditions,
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


def _google_caption(description: str | None, terms: str | None) -> str:
    """Caption text Google shows. Localith's wrapper exposes no separate
    terms field, so offer terms travel inside the caption."""
    text = (description or "").strip()
    terms = (terms or "").strip()
    if terms:
        text = f"{text}\n\nTerms: {terms}" if text else f"Terms: {terms}"
    return text


def _effective_end_date(post: LocationPost) -> datetime | None:
    """Google-side removal for dated posts: an event/offer ends when its
    end date passes — Google takes it down itself. When the merchant set a
    scheduled deletion but no explicit end, the deletion time doubles as
    the end date, so the Google copy actually disappears too (updates
    ignore end dates on Google's side, so this only affects event/offer)."""
    if post.end_date is not None:
        return post.end_date
    if post.post_type in ("event", "offer") and post.delete_at is not None:
        return post.delete_at
    return None


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
    start_date = _parse_dt(data.get("start_date"))
    post_type = data.get("post_type", "update")
    if post_type not in ("update", "event", "offer"):
        raise ValueError("post_type must be update, event or offer.")
    if post_type == "event" and start_date is None:
        raise ValueError("Events need a start date — Google requires it.")

    post = LocationPost(
        id=str(uuid.uuid4()),
        user_id=user_id,
        listing_id=data["listing_id"],
        location_name=(data.get("location_name") or "")[:255],
        business_name=(data.get("business_name") or "Sayvors")[:255],
        title=(data.get("title") or "")[:500],
        post_type=post_type,
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
        start_date=start_date,
        coupon_code=(str(data.get("coupon_code") or "")[:64] or None),
        terms_conditions=(str(data.get("terms_conditions") or "")[:2000] or None),
    )
    db.add(post)
    await db.flush()

    if action == "publish":
        return await publish_post(db, user_id, post.id)
    if action == "schedule":
        when = scheduled_on.strftime("%b %d, %H:%M") if scheduled_on else "soon"
        await notify(
            db, user_id, "post_scheduled",
            f"Post scheduled — {post.title or 'Untitled'}",
            f"Publishes {when}.",
            data={"post_id": post.id, "listing_id": post.listing_id},
            href="/dashboard/posts",
        )
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
    for field in ("tags", "keywords", "image_urls"):
        if data.get(field) is not None:
            setattr(post, field, list(data[field]))
    if "coupon_code" in data:
        post.coupon_code = (str(data.get("coupon_code") or "")[:64] or None)
    if "terms_conditions" in data:
        post.terms_conditions = (str(data.get("terms_conditions") or "")[:2000] or None)
    if "start_date" in data:
        post.start_date = _parse_dt(data.get("start_date"))
    if data.get("post_type") in ("update", "event", "offer"):
        post.post_type = data["post_type"]
        if post.post_type == "event" and post.start_date is None:
            raise ValueError("Events need a start date — Google requires it.")

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


async def publish_post(
    db: AsyncSession, user_id: str, post_id: str, notify_user: bool = True
) -> dict:
    """Publish one post to Google via Localith right now.

    Publishing is NOT idempotent (a double call posts twice on Google), so
    the post's advisory lock is held for the whole call: manual clicks, the
    background loop, and racing workers serialize per post while different
    posts proceed in parallel. notify_user=False lets batch callers (worker)
    emit one summary instead of a row per post.
    """
    locked = await _acquire_post_lock(db, post_id)
    try:
        return await _publish_post_inner(db, user_id, post_id, notify_user)
    finally:
        if locked:
            await _release_post_lock(db, post_id)


async def _publish_post_inner(
    db: AsyncSession, user_id: str, post_id: str, notify_user: bool = True
) -> dict:
    from integrations.channels import embedsocial

    post = await _owned_post(db, user_id, post_id)
    if post is None:
        raise ValueError("Post not found.")
    if post.status not in PUBLISHABLE_FROM:
        raise ValueError(f"Cannot publish a {post.status} post.")
    await _require_localith_listing(db, user_id, post.listing_id)

    sent = [u for u in (post.image_urls or []) if u.startswith("http")]
    skipped = len(post.image_urls or []) - len(sent)
    effective_end = _effective_end_date(post)
    try:
        response = await asyncio.to_thread(
            embedsocial.publish_media_post,
            post.listing_id,
            post_type=post.post_type,
            title=post.title or None,
            caption=_google_caption(post.description, post.terms_conditions),
            image_urls=sent,
            cta_type=post.cta_type,
            cta_url=post.cta_url,
            start_date=post.start_date.isoformat() if post.start_date else None,
            end_date=effective_end.isoformat() if effective_end else None,
            voucher_code=post.coupon_code or None,
        )
    except Exception as e:
        _register_publish_failure(post, str(e)[:500])
        if notify_user and post.status == "failed":
            # Parked (not merely retrying): this needs the human.
            await notify(
                db, user_id, "post_failed",
                f"Post failed to publish — {post.title or 'Untitled'}",
                (post.error or "")[:160],
                data={"post_id": post.id, "listing_id": post.listing_id},
                href="/dashboard/posts",
            )
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
    if notify_user:
        await notify(
            db, user_id, "post_published",
            f"Published to Google — {post.title or 'Untitled'}",
            (post.description or "")[:160] or None,
            data={"post_id": post.id, "listing_id": post.listing_id},
            href="/dashboard/posts",
        )
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
    per_user: dict[str, dict[str, int]] = {}
    for post in rows:
        post_id, user_id = post.id, post.user_id
        held = await _try_post_lock(db, post_id)
        if not held:
            totals["skipped"] += 1
            continue
        try:
            await publish_post(db, user_id, post_id, notify_user=False)
            totals["published"] += 1
            per_user.setdefault(user_id, {"published": 0, "failed": 0})
            per_user[user_id]["published"] += 1
        except Exception as e:
            fresh = await _owned_post(db, user_id, post_id)
            if fresh is not None and fresh.status == "scheduled":
                totals["retried"] += 1
            else:
                totals["failed"] += 1
                per_user.setdefault(user_id, {"published": 0, "failed": 0})
                per_user[user_id]["failed"] += 1
            totals["errors"].append(f"{post_id[:8]}: {str(e)[:120]}")
            try:
                await db.rollback()
            except Exception:
                pass
        finally:
            await _release_post_lock(db, post_id)
    # One summary row per active user per pass — never a row per post.
    for uid, counts in per_user.items():
        parts = []
        if counts["published"]:
            parts.append(f"published {counts['published']}")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        await notify(
            db, uid,
            "post_published" if counts["published"] else "post_failed",
            f"Scheduled posts: {', '.join(parts)}",
            None,
            data={"published": counts["published"], "failed": counts["failed"]},
            href="/dashboard/posts",
        )
    try:
        await db.commit()
    except Exception:
        pass
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


def _parse_ai_draft(text: str) -> dict:
    """Parse the model reply into description/tags/keywords. Never raises:
    garbage in gives empty fields out (the composer stays usable)."""
    import json as _json
    import re as _re

    try:
        data = _json.loads(text)
    except Exception:
        match = _re.search(r"\{.*\}", text, _re.S)
        try:
            data = _json.loads(match.group(0)) if match else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    def _words(value: object) -> list[str]:
        if isinstance(value, str):
            parts = [p.strip().lower() for p in value.replace(",", " ").split()]
        elif isinstance(value, list):
            parts = [str(x).strip().lower() for x in value]
        else:
            parts = []
        seen: list[str] = []
        for part in parts:
            part = part.strip("# ")[:40]
            if part and part not in seen:
                seen.append(part)
        return seen[:5]

    description = str(data.get("description") or "")[:1500]
    return {
        "description": description,
        "tags": _words(data.get("tags")),
        "keywords": _words(data.get("keywords")),
    }


async def draft_post_content(
    db: AsyncSession,
    user_id: str,
    title: str,
    post_type: str = "update",
    business_name: str | None = None,
) -> dict:
    """AI-draft the composer fields (description + tags + keywords) from a
    title. Model comes from the tenant's enabled list — no default, no
    fallback. Raises ValueError for bad input, RuntimeError when the
    single attempt fails."""
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model, resolve_tenant_model

    title = (title or "").strip()
    if not title:
        raise ValueError("A title is required to draft content.")
    if post_type not in ("update", "offer", "event"):
        post_type = "update"
    kind_line = {
        "update": "a general news/announcement post",
        "offer": "a promotional offer post",
        "event": "an event announcement post",
    }[post_type]
    model_id = await resolve_tenant_model(db)
    # Ground the draft in the tenant's own facts via the Retrieval Layer:
    # owner identity (category, sells, services) + business-profile evidence
    # from the Data Bank (structured, hybrid — never invented specifics).
    from ..retrieval.evidence import EvidenceNeed
    from ..retrieval.layer import identity as _layer_identity
    from ..retrieval.layer import retrieve_evidence

    identity_block = ""
    bank_facts = ""
    try:
        identity_block = await _layer_identity(db, user_id)
    except Exception as e:
        logger.warning("Business identity unavailable for post draft: %s", e)
    try:
        res = await retrieve_evidence(
            [EvidenceNeed(kind="business_profile", query=title)],
            tenant_id=user_id, db=db,
        )
        bank_facts = (res.get("business_profile").rendered
                      if res.get("business_profile") else "")
    except Exception as e:
        logger.warning("Databank facts unavailable for post draft: %s", e)
    system = (
        "You write Google Business Profile posts for small businesses. "
        "Reply with STRICT JSON only, no other text: "
        '{"description": "<120-400 chars of post text>", '
        '"tags": ["up to 5 short lowercase labels"], '
        '"keywords": ["up to 5 search terms"]}. No em dashes."'
    )
    context_parts = []
    if identity_block:
        context_parts.append(identity_block)
    if bank_facts:
        context_parts.append(
            "Facts from the business Databank (use these for specifics):\n" + bank_facts
        )
    grounding_rule = (
        "Write ONLY about what the business facts above support — never invent "
        "products, prices, offers, hours or services not stated there."
    )
    user_msg = (
        f"Business: {(business_name or '').strip() or 'local business'}\n"
        + ("\n".join(context_parts) + "\n" if context_parts else "")
        + f"{grounding_rule}\n"
        f"Post type: {kind_line}\nTitle: {title}\nWrite the post content."
    )

    def _build(mid: str):
        provider = get_provider_for_model(mid)
        api_model, _ = _resolve_model(mid)
        return provider, LLMRequest(
            model=api_model,
            messages=[LLMMessage(role="user", content=user_msg)],
            system_prompt=system,
            temperature=0.7,
            # Reasoning models spend tokens thinking before the answer —
            # a tight cap makes them return 200 with EMPTY content
            # (finish_reason="length"). Keep generous headroom.
            max_tokens=2000,
            stream=False,
            tenant_id=user_id,
            model_id=mid,
            purpose="posts.ai_draft",
        )

    provider, req = _build(model_id)
    try:
        resp = await provider.complete(req)
    except Exception as e:
        logger.warning("Post drafting failed on first attempt: %s", e)
        raise RuntimeError("AI drafting failed.")
    content = (resp.content or "").strip()
    if not content:
        # Empty replies happen when a reasoning model exhausts its token
        # budget thinking, or on provider hiccups: log WHY, retry once on
        # the SAME model, then give up loudly.
        logger.warning(
            "Post drafting returned empty content (finish_reason=%s); retrying once",
            getattr(resp, "finish_reason", "?"),
        )
        try:
            resp = await provider.complete(req)
        except Exception as e:
            raise RuntimeError("AI drafting failed.")
        content = (resp.content or "").strip()
    if not content:
        raise RuntimeError("AI drafting returned nothing.")
    return _parse_ai_draft(content)
