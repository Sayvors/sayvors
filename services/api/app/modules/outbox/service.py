import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from .models import EventOutbox

logger = logging.getLogger(__name__)

# Max retries before giving up (mark as dead)
MAX_RETRIES = 10
# Base backoff: 2^attempts seconds, capped at 5 minutes
BASE_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 300
# Cleanup: delete sent events older than this
SENT_RETENTION_HOURS = 24


async def enqueue_event(
    event_type: str,
    payload: dict,
    topic: str = "auth-events",
) -> str:
    """Write an event to the outbox. Returns the event ID.

    This is the only call the request path makes. It's a single local
    PostgreSQL INSERT (~1-2ms) — non-blocking, never hangs.
    """
    event_id = str(uuid.uuid4())
    async with async_session() as db:
        row = EventOutbox(
            id=event_id,
            event_type=event_type,
            payload=payload,
            topic=topic,
            status="pending",
            attempts=0,
            next_retry_at=datetime.now(timezone.utc),
        )
        db.add(row)
        await db.commit()
    return event_id


async def fetch_pending_events(batch_size: int = 100) -> list[EventOutbox]:
    """Fetch a batch of events ready for delivery."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(EventOutbox)
            .where(
                EventOutbox.status.in_(["pending", "failed"]),
                EventOutbox.next_retry_at <= now,
                EventOutbox.attempts < MAX_RETRIES,
            )
            .order_by(EventOutbox.created_at)
            .limit(batch_size)
        )
        events = list(result.scalars().all())
        # Detach from session so we can use them outside
        for e in events:
            db.expunge(e)
        return events


async def mark_sent(event_ids: list[str]) -> None:
    """Mark events as successfully delivered."""
    if not event_ids:
        return
    async with async_session() as db:
        await db.execute(
            update(EventOutbox)
            .where(EventOutbox.id.in_(event_ids))
            .values(status="sent")
        )
        await db.commit()


async def mark_failed(event_id: str, error: str) -> None:
    """Mark an event as failed and schedule retry with backoff."""
    async with async_session() as db:
        result = await db.execute(
            select(EventOutbox).where(EventOutbox.id == event_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return

        row.attempts += 1
        row.last_error = error[:500]

        if row.attempts >= MAX_RETRIES:
            row.status = "dead"
            logger.error(
                "Event %s (%s) marked dead after %d attempts: %s",
                event_id, row.event_type, row.attempts, error,
            )
        else:
            row.status = "failed"
            backoff = min(BASE_BACKOFF_SECONDS ** row.attempts, MAX_BACKOFF_SECONDS)
            row.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)

        await db.commit()


async def cleanup_sent_events() -> int:
    """Delete sent events older than retention period. Returns count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SENT_RETENTION_HOURS)
    async with async_session() as db:
        from sqlalchemy import delete
        result = await db.execute(
            delete(EventOutbox).where(
                EventOutbox.status == "sent",
                EventOutbox.created_at < cutoff,
            )
        )
        await db.commit()
        return result.rowcount


async def get_outbox_stats() -> dict:
    """Return counts by status for monitoring."""
    async with async_session() as db:
        from sqlalchemy import func
        result = await db.execute(
            select(EventOutbox.status, func.count())
            .group_by(EventOutbox.status)
        )
        return {row[0]: row[1] for row in result.all()}
