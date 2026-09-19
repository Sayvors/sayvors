"""Emit user-facing notifications.

Called from sync paths, approve flow, and (later) edit detection.
Failures never break the caller — a notification must not take down
a sync or a publish.
"""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Notification

logger = logging.getLogger(__name__)

# Per-sync cap so a big backfill can't flood the feed.
MAX_PER_SYNC = 20


async def notify(
    db: AsyncSession,
    user_id: str,
    type: str,
    title: str,
    body: str | None = None,
    data: dict | None = None,
    href: str | None = None,
) -> str | None:
    """Persist one notification row. Returns its id (None on failure)."""
    try:
        nid = str(uuid.uuid4())
        db.add(Notification(
            id=nid,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=data or {},
            href=href,
        ))
        await db.flush()
        return nid
    except Exception as e:
        logger.warning("notify failed (%s): %s", type, e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None
