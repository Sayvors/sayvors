import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
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
# Dead events are the terminal failure record: kept longer than sent rows so
# an operator can still inspect what failed, but not forever. Without this
# window the dispatch log grows for every event that ever exhausted retries.
DEAD_RETENTION_DAYS = 30
# Delete in bounded batches. One unbounded DELETE on a large outbox holds
# locks for the whole statement; the sweep walks it in small transactions.
OUTBOX_DELETE_BATCH = 2000
OUTBOX_MAX_BATCHES = 10


async def enqueue_event(
    event_type: str,
    payload: dict,
    topic: str = "auth-events",
    dedupe_key: str | None = None,
) -> str:
    """Write an event to the outbox. Returns the event ID.

    This is the only call the request path makes. It's a single local
    PostgreSQL INSERT (~1-2ms) — non-blocking, never hangs.

    ``dedupe_key`` is the producer's identity for the event: a retry that
    passes the same key returns the first event instead of writing a second
    one, so the event is dispatched once.
    """
    event_id = str(uuid.uuid4())
    async with async_session() as db:
        if dedupe_key:
            existing = (
                await db.execute(
                    select(EventOutbox).where(EventOutbox.dedupe_key == dedupe_key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
        row = EventOutbox(
            id=event_id,
            event_type=event_type,
            payload=payload,
            topic=topic,
            status="pending",
            attempts=0,
            next_retry_at=datetime.now(timezone.utc),
            dedupe_key=dedupe_key,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # Another writer inserted the same key between the check and the
            # insert. The savepoint rolled back our row; theirs is the one
            # that counts.
            existing = (
                await db.execute(
                    select(EventOutbox).where(EventOutbox.dedupe_key == dedupe_key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
            raise
        await db.commit()
    return event_id


async def enqueue_event_in(
    db: AsyncSession,
    event_type: str,
    payload: dict,
    topic: str = "auth-events",
    dedupe_key: str | None = None,
) -> str:
    """Write an event to the outbox using the caller's session.

    Caller commits once — job row + outbox row are atomic (R2 in design doc).

    With a ``dedupe_key`` the event is written once: a second writer with
    the same key gets the first event's id back and nothing is dispatched
    twice.
    """
    if dedupe_key:
        existing = (
            await db.execute(
                select(EventOutbox).where(EventOutbox.dedupe_key == dedupe_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id
    event_id = str(uuid.uuid4())
    row = EventOutbox(
        id=event_id,
        event_type=event_type,
        payload=payload,
        topic=topic,
        status="pending",
        attempts=0,
        next_retry_at=datetime.now(timezone.utc),
        dedupe_key=dedupe_key,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Lost the race with another writer for the same key.
        existing = (
            await db.execute(
                select(EventOutbox).where(EventOutbox.dedupe_key == dedupe_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id
        raise
    return event_id


async def fetch_pending_events(batch_size: int = 100) -> list[EventOutbox]:
    """Fetch a batch of events ready for delivery with FOR UPDATE SKIP LOCKED.

    Multiple drainers can run concurrently without twin-sending events (S5 in design doc).

    Ownership split: ``meta.*`` rows are EXCLUDED here. They are owned
    exclusively by the meta events worker, which claims them from the same
    table (pending -> processing -> sent/failed/dead). The Kafka publisher
    must never mark them ``sent``: nothing consumes the ``meta-events`` Kafka
    topic since the sequential Kafka consumer was retired, so a published
    meta event is processed by nobody — yet its row reads ``sent`` and the
    meta worker will never pick it up. That race silently drops inbound
    customer messages (accepted 200, stored nowhere, no reply, no log).
    """
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(EventOutbox)
            .where(
                EventOutbox.status.in_(["pending", "failed"]),
                EventOutbox.next_retry_at <= now,
                EventOutbox.attempts < MAX_RETRIES,
                # Meta events belong to the meta events worker (see above).
                ~EventOutbox.event_type.like("meta.%"),
            )
            .order_by(EventOutbox.created_at)
            .with_for_update(skip_locked=True)
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


async def cleanup_outbox_events() -> int:
    """Delete terminal outbox events older than their retention window.

    Sent rows are dispatch history and go after a day; dead rows are the
    failure record and are kept for a month. Pending and failed rows are
    still deliverable work and are never touched. Deletes are batched so a
    large backlog cannot hold row locks for one long statement.
    """
    from sqlalchemy import delete

    now = datetime.now(timezone.utc)
    windows = (
        (["sent"], now - timedelta(hours=SENT_RETENTION_HOURS)),
        (["dead"], now - timedelta(days=DEAD_RETENTION_DAYS)),
    )
    deleted = 0
    async with async_session() as db:
        for statuses, cutoff in windows:
            for _ in range(OUTBOX_MAX_BATCHES):
                batch_ids = (
                    select(EventOutbox.id)
                    .where(
                        EventOutbox.status.in_(statuses),
                        EventOutbox.created_at < cutoff,
                    )
                    .limit(OUTBOX_DELETE_BATCH)
                )
                result = await db.execute(
                    delete(EventOutbox).where(EventOutbox.id.in_(batch_ids))
                )
                await db.commit()
                if not result.rowcount:
                    break
                deleted += result.rowcount
                if result.rowcount < OUTBOX_DELETE_BATCH:
                    break
    return deleted


async def get_outbox_stats() -> dict:
    """Return counts by status for monitoring."""
    async with async_session() as db:
        from sqlalchemy import func

        result = await db.execute(
            select(EventOutbox.status, func.count()).group_by(EventOutbox.status)
        )
        return {row[0]: row[1] for row in result.all()}
