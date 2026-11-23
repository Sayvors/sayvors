"""Google cover-photo drift monitoring.

``record_publish`` is called when a "Promotion" (banner) publish succeeds. Every
check compares the cover Google currently reports for that location with the
media item we uploaded. A different name means Google replaced it; the row
becomes ``changed`` and the UI can offer "Replace again".

The GBP API cannot tell us which photo Google publicly displays, so this is a
check of the *designated* cover — the closest honest signal the API exposes.
"""
from __future__ import annotations

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
            "Google replaced your cover photo. Replace it again."
            if row.status == "changed"
            else (row.error or "")
        ),
        "drift_count": row.drift_count or 0,
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
    }
