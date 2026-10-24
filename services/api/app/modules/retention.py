"""Retention cleanup for unbounded tables.

Runs as part of the outbox worker's hourly cleanup cycle. Each sweep deletes
rows older than the configured retention period and returns the count
deleted. Failures are logged but never break the cleanup loop.

Every delete is batched. One unbounded ``DELETE`` on a table with millions of
rows holds row locks for the whole statement, bloats the WAL, and can stall
writes for minutes — exactly when a big backlog exists and cleanup matters
most. The sweep walks the table in bounded chunks instead and gives up after
a fixed number of chunks so one run cannot monopolise the worker; the next
hourly run continues where this one stopped.

Only terminal rows are ever touched. A queued, running or retrying job, an
unread notification, or a webhook event still being processed is live data,
not history.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from ..database import async_session
from .channels.meta.models import MetaWebhookEvent
from .jobs.models import Job
from .llm.models import LLMUsageEvent
from .notifications.models import Notification

logger = logging.getLogger(__name__)

# Retention periods (days). Configurable via env if needed.
WEBHOOK_EVENT_RETENTION_DAYS = 30
NOTIFICATION_RETENTION_DAYS = 90
USAGE_EVENT_RETENTION_DAYS = 90
# The jobs table is the execution record and grows with every AI reply,
# publish, transcription and media job. It needs a retention window like
# every other unbounded table - without one it is the table that eventually
# takes the database down.
JOB_RETENTION_DAYS = 30
# Failed and dead jobs are what an operator reads when something went wrong,
# so they are kept three times longer than the successful ones.
JOB_FAILURE_RETENTION_DAYS = 90
# Rows deleted per statement. A batch small enough to keep each transaction
# short and its lock footprint tiny.
DELETE_BATCH_SIZE = 2000
# Upper bound on batches per table per run, so a huge backlog is worked
# through over several runs instead of one long transaction.
MAX_BATCHES_PER_RUN = 20


async def _batched_delete(db, model, *conditions) -> int:
    """Delete ``model`` rows matching ``conditions`` in bounded batches.

    Uses ``DELETE ... WHERE id IN (SELECT id ... LIMIT n)`` rather than an
    unbounded ``DELETE`` so each statement only locks the rows it removes.
    Returns the number of rows deleted in this run.
    """
    deleted = 0
    for _ in range(MAX_BATCHES_PER_RUN):
        batch_ids = select(model.id).where(*conditions).limit(DELETE_BATCH_SIZE)
        result = await db.execute(delete(model).where(model.id.in_(batch_ids)))
        await db.commit()
        if not result.rowcount:
            break
        deleted += result.rowcount
        # A short batch means the backlog is drained; no point paying for
        # another round trip just to discover the next SELECT is empty.
        if result.rowcount < DELETE_BATCH_SIZE:
            break
    return deleted


async def cleanup_webhook_events() -> int:
    """Delete processed/rejected webhook events older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=WEBHOOK_EVENT_RETENTION_DAYS)
    async with async_session() as db:
        return await _batched_delete(
            db,
            MetaWebhookEvent,
            MetaWebhookEvent.created_at < cutoff,
            MetaWebhookEvent.status.in_(["processed", "duplicate", "rejected"]),
        )


async def cleanup_notifications() -> int:
    """Delete read notifications older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    async with async_session() as db:
        return await _batched_delete(
            db,
            Notification,
            Notification.created_at < cutoff,
            Notification.read_at.is_not(None),
        )


async def cleanup_usage_events() -> int:
    """Delete usage events older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=USAGE_EVENT_RETENTION_DAYS)
    async with async_session() as db:
        return await _batched_delete(
            db,
            LLMUsageEvent,
            LLMUsageEvent.created_at < cutoff,
        )


async def cleanup_jobs() -> int:
    """Delete terminal job rows older than their retention window.

    Succeeded and cancelled jobs are the bulk and go first; failed and dead
    jobs stay longer because they are the evidence an operator reads. A job
    that is still queued, running, retrying or blocked is never touched -
    only terminal rows are history.
    """
    now = datetime.now(timezone.utc)
    windows = (
        (["succeeded", "cancelled"], now - timedelta(days=JOB_RETENTION_DAYS)),
        (["failed", "dead"], now - timedelta(days=JOB_FAILURE_RETENTION_DAYS)),
    )
    deleted = 0
    async with async_session() as db:
        for statuses, cutoff in windows:
            deleted += await _batched_delete(
                db,
                Job,
                Job.status.in_(statuses),
                Job.created_at < cutoff,
            )
    return deleted


async def cleanup_all() -> dict[str, int]:
    """Run all retention cleanup jobs. Returns counts deleted."""
    counts = {}
    for name, fn in [
        ("webhook_events", cleanup_webhook_events),
        ("notifications", cleanup_notifications),
        ("usage_events", cleanup_usage_events),
        ("jobs", cleanup_jobs),
    ]:
        try:
            counts[name] = await fn()
        except Exception as e:
            logger.warning("Retention cleanup failed for %s: %s", name, e)
            counts[name] = -1
    return counts
