"""Media service: scheduled photos that go live on Google inside posts.

Localith has no photo-library upload — image URLs travel inside
content_publishing_media posts. So publishing one photo = publishing one
Google post carrying it. Same robustness contract as posts: per-item
advisory locks (double publish impossible), retry-then-park, delete-due.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.providers import GOOGLE, google_not_ready, media_publish_provider
from ..localith.models import LocalithConnection
from ..notifications.service import notify
from ..scheduling import (
    MAX_PUBLISH_ATTEMPTS,
    provider_post_id as _google_post_id,
    release_lock,
    retry_delay as _retry_delay,
    take_lock,
)
from .models import LocationMedia

logger = logging.getLogger(__name__)

PUBLISHABLE_FROM = ("draft", "scheduled", "failed")
MAX_PER_PASS = 50

# Per-item advisory locks: publishing is NOT idempotent, so the same photo
# never publishes twice at once. Different photos proceed in parallel.
# Implementation lives in app.modules.scheduling (single copy).
_MEDIA_LOCK_PREFIX = "sayvors:media-publish:"


async def _acquire_media_lock(db: AsyncSession, media_id: str) -> bool:
    return await take_lock(db, True, _MEDIA_LOCK_PREFIX, media_id)


async def _try_media_lock(db: AsyncSession, media_id: str) -> bool:
    return await take_lock(db, False, _MEDIA_LOCK_PREFIX, media_id)


async def _release_media_lock(db: AsyncSession, media_id: str) -> None:
    await release_lock(db, _MEDIA_LOCK_PREFIX, media_id)


# File uploads from the owner's computer. Stored in shared storage: GCS
# public bucket when configured, otherwise local disk served publicly at
# <api-origin>/media-files/... The provider fetches the photo from that
# URL at publish time, which is why it must be public, not just on disk.
UPLOAD_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov")
VIDEO_EXTENSIONS = (".mp4", ".mov")


def detect_media_type(filename: str, content_type: str | None) -> str:
    name = (filename or "").lower()
    if name.endswith(VIDEO_EXTENSIONS) or (content_type or "").startswith("video/"):
        return "VIDEO"
    return "PHOTO"


async def save_upload(
    user_id: str, filename: str, content_type: str | None, data: bytes, base_url: str
) -> dict:
    """Store one uploaded file and return its public URL + detected type."""
    from ...core.storage import local_media_url, put_media

    max_bytes = max(1, settings.MEDIA_MAX_MB) * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"File is too big — max {settings.MEDIA_MAX_MB}MB.")
    if not data:
        raise ValueError("Empty file.")
    ext = Path(filename or "").suffix.lower()
    if ext not in UPLOAD_EXTENSIONS:
        raise ValueError("Only JPG, PNG, WEBP, GIF, MP4 or MOV files.")
    ctype = content_type or ""
    if ctype and not (ctype.startswith("image/") or ctype.startswith("video/")):
        raise ValueError("Only image or video files.")
    storage_key, public_url = put_media(user_id, filename, data, ctype or None)
    if not public_url:
        public_url = local_media_url(base_url, user_id, storage_key)
    return {
        "image_url": public_url,
        "type": detect_media_type(filename, content_type),
        "size": len(data),
        "content_type": ctype or None,
    }


def _serialize(m: LocationMedia) -> dict:
    return {
        "id": m.id,
        "listing_id": m.listing_id,
        "image_url": m.image_url,
        "type": m.type,
        "category": m.category,
        "caption": m.caption or "",
        "status": m.status,
        "scheduled_on": m.scheduled_on.isoformat() if m.scheduled_on else None,
        "published_at": m.published_at.isoformat() if m.published_at else None,
        "delete_at": m.delete_at.isoformat() if m.delete_at else None,
        "publish_method": m.publish_method or "post",
        "google_post_id": m.google_post_id,
        "is_profile": bool(m.is_profile),
        "is_cover": bool(m.is_cover),
        "error": m.error,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _owned_media(db: AsyncSession, user_id: str, media_id: str) -> LocationMedia | None:
    result = await db.execute(
        select(LocationMedia).where(
            LocationMedia.id == media_id,
            LocationMedia.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


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
    if delete_at is None:
        return
    if delete_at <= datetime.now(timezone.utc):
        raise ValueError("delete_at must be in the future.")
    if scheduled_on is not None and delete_at <= scheduled_on:
        raise ValueError("delete_at must be after the scheduled publish time.")


def _require_http_url(url: str) -> str:
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("image_url must be a hosted http(s) URL.")
    return url


def _check_method_publishable(method: str | None, action: str) -> None:
    """Only the post path is wired (Localith). Gallery/profile are stored
    intent until per-tenant native Google lands — fail loudly, never
    silently pretend."""
    if action in ("publish", "schedule") and (method or "post") != "post":
        raise ValueError(
            "Direct gallery/profile publishing needs the native Google "
            "connection — coming soon. Publish inside a post for now."
        )


async def list_media(
    db: AsyncSession, user_id: str, listing_id: str | None = None
) -> list[dict]:
    filters = [LocationMedia.user_id == user_id]
    if listing_id:
        filters.append(LocationMedia.listing_id == listing_id)
    rows = (
        await db.execute(
            select(LocationMedia).where(*filters).order_by(LocationMedia.created_at.desc()).limit(200)
        )
    ).scalars().all()
    return [_serialize(m) for m in rows]


async def create_media(db: AsyncSession, user_id: str, data: dict) -> dict:
    action = data.get("action", "publish")
    scheduled_on = _parse_dt(data.get("scheduled_on"))
    if action == "schedule" and scheduled_on is None:
        raise ValueError("scheduled_on is required to schedule media.")
    if action == "schedule" and scheduled_on <= datetime.now(timezone.utc):  # type: ignore[operator]
        raise ValueError("scheduled_on must be in the future.")
    delete_at = _parse_dt(data.get("delete_at"))
    _validate_delete_at(delete_at, scheduled_on)
    image_url = _require_http_url(data.get("image_url") or "")
    media_type = data.get("type", "PHOTO")
    if media_type not in ("PHOTO", "VIDEO"):
        raise ValueError("type must be PHOTO or VIDEO.")
    publish_method = data.get("publish_method") or "post"
    if publish_method not in ("post", "gallery", "profile"):
        raise ValueError("publish_method must be post, gallery or profile.")
    _check_method_publishable(publish_method, action)

    item = LocationMedia(
        id=str(uuid.uuid4()),
        user_id=user_id,
        listing_id=data["listing_id"],
        image_url=image_url,
        type=media_type,
        category=(data.get("category") or "EXTERIOR")[:32],
        caption=(data.get("caption") or "")[:500],
        status="scheduled" if action == "schedule" else "draft",
        scheduled_on=scheduled_on,
        delete_at=delete_at,
        publish_method=publish_method,
    )
    db.add(item)
    await db.flush()

    if action == "publish":
        return await publish_media(db, user_id, item.id)
    if action == "schedule":
        when = scheduled_on.strftime("%b %d, %H:%M") if scheduled_on else "soon"
        await notify(
            db, user_id, "media_scheduled",
            f"Photo scheduled — {item.caption or item.category.replace('_', ' ').title()}",
            f"Publishes {when}.",
            data={"media_id": item.id, "listing_id": item.listing_id},
            href="/dashboard/media",
        )
    await db.commit()
    await db.refresh(item)
    return {"media": _serialize(item), "google_published": False}


async def update_media(
    db: AsyncSession, user_id: str, media_id: str, data: dict
) -> dict:
    item = await _owned_media(db, user_id, media_id)
    if item is None:
        raise ValueError("Media not found.")
    if item.status == "published":
        raise ValueError("Published photos live on Google now — archive the post instead of editing.")
    for field in ("category", "caption"):
        if data.get(field) is not None:
            setattr(item, field, data[field])
    for field in ("is_profile", "is_cover"):
        if field in data and data[field] is not None:
            setattr(item, field, bool(data[field]))
    # delete_at: explicit null cancels, absent key leaves untouched
    # (router passes exclude_unset).
    if "delete_at" in data:
        item.delete_at = _parse_dt(data.get("delete_at"))

    new_status = data.get("status")
    if new_status is not None and new_status != item.status:
        if new_status == "published" and item.status in PUBLISHABLE_FROM:
            await db.flush()
            return await publish_media(db, user_id, item.id)
        if new_status == "published":
            item.status = "published"
        elif new_status in ("draft", "scheduled", "archived"):
            item.status = new_status
            if new_status == "scheduled":
                item.scheduled_on = _parse_dt(data.get("scheduled_on")) or item.scheduled_on
                if item.scheduled_on is None:
                    raise ValueError("scheduled_on is required to schedule media.")
        else:
            raise ValueError(f"Cannot transition to {new_status}.")
    if "delete_at" in data or "scheduled_on" in data:
        _validate_delete_at(item.delete_at, item.scheduled_on)
    item.error = None
    await db.commit()
    await db.refresh(item)
    return {"media": _serialize(item), "google_published": False}


async def delete_media(db: AsyncSession, user_id: str, media_id: str) -> None:
    item = await _owned_media(db, user_id, media_id)
    if item is None:
        raise ValueError("Media not found.")
    await db.delete(item)
    await db.commit()


async def publish_media(
    db: AsyncSession, user_id: str, media_id: str, notify_user: bool = True
) -> dict:
    """Publish one photo to Google right now (inside a Google post).

    Held under the item's advisory lock: a double publish would post the
    photo twice on Google. Videos are library-only — the provider takes
    image URLs, not video. notify_user=False lets batch callers (worker)
    emit one summary instead of a row per photo.
    """
    locked = await _acquire_media_lock(db, media_id)
    try:
        return await _publish_media_inner(db, user_id, media_id, notify_user)
    finally:
        if locked:
            await _release_media_lock(db, media_id)


async def _publish_media_inner(
    db: AsyncSession, user_id: str, media_id: str, notify_user: bool = True
) -> dict:
    from integrations.channels import embedsocial

    item = await _owned_media(db, user_id, media_id)
    if item is None:
        raise ValueError("Media not found.")
    if item.status not in PUBLISHABLE_FROM:
        raise ValueError(f"Cannot publish {item.status} media.")
    if (item.publish_method or "post") != "post":
        raise ValueError(
            "Direct gallery/profile publishing needs the native Google "
            "connection — coming soon. Publish inside a post for now."
        )
    if item.type != "PHOTO":
        raise ValueError("Video auto-publishing is not supported by the provider yet — photos only.")
    conn = (
        await db.execute(
            select(LocalithConnection).where(
                LocalithConnection.user_id == user_id,
                LocalithConnection.listing_id == item.listing_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise ValueError("Connect that branch in Localith before publishing media.")

    # Provider seam: Localith today; the google branch lands with GBP API
    # access (see app/core/providers.py). Checked BEFORE the try below so
    # a premature flip fails loudly — never registered as a publish
    # failure, never notified, never retried.
    if media_publish_provider() == GOOGLE:
        raise google_not_ready("media publishing")

    try:
        response = await asyncio.to_thread(
            embedsocial.publish_media_post,
            item.listing_id,
            post_type="update",
            caption=item.caption or item.category.replace("_", " ").title(),
            image_urls=[item.image_url],
        )
    except Exception as e:
        _register_publish_failure(item, str(e)[:500])
        if notify_user and item.status == "failed":
            # Parked (not merely retrying): this needs the human.
            await notify(
                db, user_id, "media_failed",
                f"Photo failed to publish — {item.caption or item.category.replace('_', ' ').title()}",
                (item.error or "")[:160],
                data={"media_id": item.id, "listing_id": item.listing_id},
                href="/dashboard/media",
            )
        await db.commit()
        raise RuntimeError(f"Google media publish failed: {e}")

    item.status = "published"
    item.published_at = datetime.now(timezone.utc)
    item.error = None
    item.attempts = 0
    item.next_retry_at = None
    item.localith_response = response
    google_id = _google_post_id(response)
    if google_id:
        item.google_post_id = google_id
    if notify_user:
        await notify(
            db, user_id, "media_published",
            f"Photo published to Google — {item.caption or item.category.replace('_', ' ').title()}",
            None,
            data={"media_id": item.id, "listing_id": item.listing_id},
            href="/dashboard/media",
        )
    await db.commit()
    await db.refresh(item)
    return {"media": _serialize(item), "google_published": True}


def _register_publish_failure(item: LocationMedia, error: str) -> None:
    """Retry-then-park, same policy as posts."""
    item.error = error
    item.attempts = (item.attempts or 0) + 1
    if item.status == "scheduled" and item.attempts < MAX_PUBLISH_ATTEMPTS:
        item.next_retry_at = datetime.now(timezone.utc) + _retry_delay(item.attempts)
    else:
        item.status = "failed"
        item.next_retry_at = None


async def publish_due(db: AsyncSession) -> dict:
    """Publish due scheduled photos across all users. Returns counts."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LocationMedia)
            .where(
                LocationMedia.status == "scheduled",
                LocationMedia.scheduled_on.is_not(None),
                LocationMedia.scheduled_on <= now,
                (LocationMedia.next_retry_at.is_(None))
                | (LocationMedia.next_retry_at <= now),
            )
            .order_by(LocationMedia.scheduled_on)
            .limit(MAX_PER_PASS)
        )
    ).scalars().all()
    totals = {
        "checked": len(rows), "published": 0, "failed": 0,
        "retried": 0, "skipped": 0, "errors": [],
    }
    per_user: dict[str, dict[str, int]] = {}
    for item in rows:
        media_id, user_id = item.id, item.user_id
        held = await _try_media_lock(db, media_id)
        if not held:
            totals["skipped"] += 1
            continue
        try:
            await publish_media(db, user_id, media_id, notify_user=False)
            totals["published"] += 1
            per_user.setdefault(user_id, {"published": 0, "failed": 0})
            per_user[user_id]["published"] += 1
        except Exception as e:
            fresh = await _owned_media(db, user_id, media_id)
            if fresh is not None and fresh.status == "scheduled":
                totals["retried"] += 1
            else:
                totals["failed"] += 1
                per_user.setdefault(user_id, {"published": 0, "failed": 0})
                per_user[user_id]["failed"] += 1
            totals["errors"].append(f"{media_id[:8]}: {str(e)[:120]}")
            try:
                await db.rollback()
            except Exception:
                pass
        finally:
            await _release_media_lock(db, media_id)
    # One summary row per active user per pass — never a row per photo.
    for uid, counts in per_user.items():
        parts = []
        if counts["published"]:
            parts.append(f"published {counts['published']}")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        await notify(
            db, uid,
            "media_published" if counts["published"] else "media_failed",
            f"Scheduled photos: {', '.join(parts)}",
            None,
            data={"published": counts["published"], "failed": counts["failed"]},
            href="/dashboard/media",
        )
    try:
        await db.commit()
    except Exception:
        pass
    return totals


async def delete_due(db: AsyncSession) -> dict:
    """Delete rows whose delete_at has passed. Local rows only."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LocationMedia).where(
                LocationMedia.delete_at.is_not(None),
                LocationMedia.delete_at <= now,
            )
        )
    ).scalars().all()
    totals = {"checked": len(rows), "deleted": 0}
    for item in rows:
        try:
            await db.delete(item)
            await db.flush()
            totals["deleted"] += 1
        except Exception as e:
            logger.warning("Scheduled media deletion failed for %s: %s", item.id, e)
            try:
                await db.rollback()
            except Exception:
                pass
    try:
        await db.commit()
    except Exception:
        pass
    return totals
