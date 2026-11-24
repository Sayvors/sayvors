"""Google cover-photo drift monitoring.

``record_publish`` is called when a "Promotion" (banner) publish succeeds. Every
check compares the cover Google currently reports for that location with the
media item we uploaded. A different name means Google replaced it; the row
becomes ``changed`` and the UI can offer "Replace again".

The GBP API cannot tell us which photo Google publicly displays, so this is a
check of the *designated* cover — the closest honest signal the API exposes.
"""
from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select

from ...database import AsyncSession
from .models import CoverMonitor

logger = logging.getLogger(__name__)

# Default freshness for the worker loop; a manual check ignores it.
DEFAULT_MIN_INTERVAL_HOURS = 6
MAX_MONITORS_PER_PASS = 100
MAX_ERROR_LEN = 500

# Bounded auto-replace. Two attempts with a half-day gap quietly repairs a
# one-off swap; a third failure is evidence Google is refusing the image, so
# the merchant is told instead of the loop hammering Google.
MAX_AUTO_REPLACES = 3
AUTO_REPLACE_COOLDOWN_HOURS = 12


async def record_publish(
    db: AsyncSession,
    *,
    tenant_id: str,
    channel_id: str,
    user_id: str,
    account_id: str,
    location_id: str,
    expected_name: str,
    image_url: str,
    google_url: str = "",
) -> CoverMonitor:
    """Create or reset the monitor after a successful cover upload."""
    row = (
        await db.execute(
            select(CoverMonitor).where(
                CoverMonitor.tenant_id == tenant_id,
                CoverMonitor.channel_id == channel_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = CoverMonitor(
            tenant_id=tenant_id,
            channel_id=channel_id,
            user_id=user_id,
            account_id=account_id,
            location_id=location_id,
        )
        db.add(row)
    else:
        row.drift_count = 0
        row.error = None
    row.user_id = user_id
    row.account_id = account_id
    row.location_id = location_id
    row.expected_name = expected_name
    row.expected_image_url = image_url
    row.actual_name = expected_name
    row.actual_image_url = google_url or image_url
    row.status = "ok"
    row.last_checked_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


def _current_cover(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the COVER item from a GBP list_media response."""
    items = payload.get("mediaItems") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        category = str(
            (item.get("locationAssociation") or {}).get("category") or ""
        ).upper()
        if category == "COVER":
            return item
    return None


async def check_one(
    db: AsyncSession, row: CoverMonitor, client: Any
) -> dict[str, Any]:
    """Compare the expected cover with what Google reports now."""
    try:
        payload = await client.list_media(
            row.account_id, row.location_id, category="COVER"
        )
    except Exception as exc:  # provider outage must not mark a cover as changed
        logger.warning("Cover check failed for %s: %s", row.channel_id, exc)
        row.status = "error"
        row.error = str(exc)[:MAX_ERROR_LEN]
        row.last_checked_at = datetime.now(timezone.utc)
        await db.commit()
        return {"status": "error", "message": str(exc)[:MAX_ERROR_LEN]}

    current = _current_cover(payload or {})
    if current is None:
        row.status = "error"
        row.error = "Google reports no cover photo for this location"
        row.last_checked_at = datetime.now(timezone.utc)
        await db.commit()
        return {"status": "error", "message": row.error}

    name = str(current.get("name") or "")
    image_url = (
        str(current.get("googleUrl") or current.get("thumbnailUrl") or "")
        or row.actual_image_url
        or ""
    )
    row.actual_name = name or None
    row.actual_image_url = image_url or None
    row.last_checked_at = datetime.now(timezone.utc)
    if name and name != row.expected_name:
        row.status = "changed"
        row.drift_count = (row.drift_count or 0) + 1
        row.error = None
        result = {
            "status": "changed",
            "message": "Google replaced your cover photo. Replace it again.",
        }
    else:
        row.status = "ok"
        row.error = None
        result = {"status": "ok", "message": "Your cover is still set."}
    await db.commit()
    return result


def should_auto_replace(row: CoverMonitor, now: datetime | None = None) -> bool:
    """True only for a genuine change, under the cap and outside the cooldown."""
    if row.status != "changed" or not row.auto_replace:
        return False
    if (row.auto_replace_count or 0) >= MAX_AUTO_REPLACES:
        return False
    moment = now or datetime.now(timezone.utc)
    last = row.last_auto_replace_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if moment - last < timedelta(hours=AUTO_REPLACE_COOLDOWN_HOURS):
            return False
    return True


async def maybe_auto_replace(
    db: AsyncSession,
    row: CoverMonitor,
    *,
    enqueue: Callable[..., Any],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Queue a silent re-upload of the cover we already published.

    ``enqueue`` is injected so the decision is testable without the job queue.
    When the cap is reached the row keeps its warning and records why, so the
    merchant sees "Google keeps replacing it" instead of silence.
    """
    moment = now or datetime.now(timezone.utc)
    if not should_auto_replace(row, moment):
        if (
            row.status == "changed"
            and row.auto_replace
            and (row.auto_replace_count or 0) >= MAX_AUTO_REPLACES
        ):
            row.error = (
                "Google keeps replacing this photo. Replace it manually with a "
                "different, higher-quality image."
            )
            await db.commit()
        return None
    payload = {
        "media_url": row.expected_image_url,
        "media_type": "image",
        "media_key": "",
        "caption": "",
        "description": "",
        "platform": "google_reviews",
        "external_asset_id": row.channel_id,
        "method": "banner",
        "scheduled_at": None,
    }
    queued = enqueue(
        tenant_id=row.tenant_id,
        payload=payload,
        idempotency_key=f"cover-auto:{row.id}:{(row.auto_replace_count or 0) + 1}",
        subject_id=row.id,
        lane_key=f"{row.tenant_id}:cover:{row.id}",
    )
    if hasattr(queued, "__await__"):
        queued = await queued
    row.auto_replace_count = (row.auto_replace_count or 0) + 1
    row.last_auto_replace_at = moment
    await db.commit()
    return payload


def _job_enqueuer(db: AsyncSession) -> Callable[..., Any]:
    """Real enqueue used by the worker: a post.publish job in the publishing lane."""

    async def enqueue(**kwargs: Any) -> Any:
        from ..jobs.service import submit_job
        from ..jobs.types import JobType

        job = await submit_job(
            db,
            tenant_id=kwargs["tenant_id"],
            job_type=JobType.post_publish.value,
            payload=kwargs["payload"],
            lane="publishing",
            priority=60,
            max_attempts=3,
            idempotency_key=kwargs.get("idempotency_key"),
            subject_type="cover",
            subject_id=kwargs.get("subject_id"),
            lane_key=kwargs.get("lane_key"),
        )
        await db.commit()
        return job

    return enqueue


async def check_due(
    db: AsyncSession,
    client_for: Callable[[str], Any],
    *,
    min_interval_hours: int = DEFAULT_MIN_INTERVAL_HOURS,
) -> dict[str, int]:
    """Check monitors whose last check is older than the interval."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, min_interval_hours))
    rows = (
        await db.execute(
            select(CoverMonitor)
            .where(
                (CoverMonitor.last_checked_at.is_(None))
                | (CoverMonitor.last_checked_at <= cutoff)
            )
            .order_by(CoverMonitor.last_checked_at.asc().nullsfirst())
            .limit(MAX_MONITORS_PER_PASS)
        )
    ).scalars().all()
    checked = changed = errors = 0
    for row in rows:
        try:
            client = client_for(row.channel_id)
            if inspect.isawaitable(client):
                client = await client
            if client is None:
                continue
            result = await check_one(db, row, client)
        except Exception as exc:
            logger.exception("Cover monitor crashed for %s", row.channel_id)
            errors += 1
            continue
        checked += 1
        if result["status"] == "changed":
            changed += 1
            # Repair it quietly when the merchant left auto-replace on.
            await maybe_auto_replace(db, row, enqueue=_job_enqueuer(db))
        elif result["status"] == "error":
            errors += 1
    return {"checked": checked, "changed": changed, "errors": errors}


async def acknowledge(db: AsyncSession, tenant_id: str, monitor_id: str) -> dict[str, Any]:
    """Accept the current cover as the new baseline after a manual replace."""
    row = (
        await db.execute(
            select(CoverMonitor).where(
                CoverMonitor.id == monitor_id,
                CoverMonitor.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"status": "not_found"}
    if row.actual_name:
        row.expected_name = row.actual_name
    if row.actual_image_url:
        row.expected_image_url = row.actual_image_url
    row.status = "ok"
    row.drift_count = 0
    row.error = None
    row.last_checked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok"}


async def set_auto_replace(
    db: AsyncSession, tenant_id: str, monitor_id: str, enabled: bool
) -> dict[str, Any] | None:
    """Turn silent auto-repair on/off. Re-enabling restarts the retry budget."""
    row = (
        await db.execute(
            select(CoverMonitor).where(
                CoverMonitor.id == monitor_id,
                CoverMonitor.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.auto_replace = bool(enabled)
    if enabled:
        row.auto_replace_count = 0
        row.last_auto_replace_at = None
        if row.status == "changed":
            row.error = None
    await db.commit()
    return serialize(row)


def channel_client_factory(db: AsyncSession) -> Callable[[str], Any]:
    """Build a GBP client for a monitor's channel id (``google:<uuid>``).

    Imports are local so importing the media module never pulls in the channel
    adapter graph, and a missing/disconnected channel simply skips that check.
    """

    async def factory(channel_id: str) -> Any:
        from ..channels.google_business import GoogleBusinessClient
        from ..channels.models import Channel
        from ..channels.service import decrypt_token

        raw = str(channel_id or "")
        channel_pk = raw.split(":", 1)[1] if raw.startswith("google:") else raw
        channel = await db.get(Channel, channel_pk)
        if channel is None or str(channel.platform) != "google_reviews":
            return None
        access = decrypt_token(channel.access_token) if channel.access_token else ""
        refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
        return GoogleBusinessClient(access or "", refresh)

    return factory


def serialize(row: CoverMonitor) -> dict[str, Any]:
    """Public shape consumed by the cover section of the publish composer."""
    return {
        "id": row.id,
        "channel_id": row.channel_id,
        "status": row.status,
        "image_url": row.actual_image_url or row.expected_image_url,
        "expected_image_url": row.expected_image_url,
        "actual_image_url": row.actual_image_url,
        "message": (
            (row.error or "Google replaced your cover photo. Replace it again.")
            if row.status == "changed"
            else (row.error or "")
        ),
        "drift_count": row.drift_count or 0,
        "auto_replace": bool(row.auto_replace),
        "auto_replace_count": row.auto_replace_count or 0,
        "max_auto_replaces": MAX_AUTO_REPLACES,
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
    }
