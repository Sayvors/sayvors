"""Retention cleanup for unbounded tables.

Runs as part of the outbox worker's hourly cleanup cycle. Each function
deletes rows older than the configured retention period and returns the
count deleted. Failures are logged but never break the cleanup loop.
"""
import logging
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..database import async_session
from .channels.meta.models import MetaWebhookEvent
from .channels.models import ChannelMessage
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
# Rows deleted per statement. One unbounded DELETE on a large table holds a
# lock for a long time, so the sweep walks in batches.
JOB_DELETE_BATCH = 2000
# Upper bound on batches per window per run, so a huge backlog is worked
# through over several runs instead of one long transaction.
JOB_MAX_BATCHES = 20
# channel_messages: keep all (conversation history). Prune only if needed.


async def cleanup_webhook_events() -> int:
    """Delete processed/rejected webhook events older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=WEBHOOK_EVENT_RETENTION_DAYS)
    async with async_session() as db:
        from sqlalchemy import delete

        result = await db.execute(
            delete(MetaWebhookEvent).where(
                MetaWebhookEvent.created_at < cutoff,
                MetaWebhookEvent.status.in_(["processed", "duplicate", "rejected"]),
            )
        )
        await db.commit()
        return result.rowcount


async def cleanup_notifications() -> int:
    """Delete read notifications older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    async with async_session() as db:
        from sqlalchemy import delete

        result = await db.execute(
            delete(Notification).where(
                Notification.created_at < cutoff,
                Notification.read_at.is_not(None),
            )
        )
        await db.commit()
        return result.rowcount


async def cleanup_usage_events() -> int:
    """Delete usage events older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=USAGE_EVENT_RETENTION_DAYS)
    async with async_session() as db:
        from sqlalchemy import delete

        result = await db.execute(
            delete(LLMUsageEvent).where(
                LLMUsageEvent.created_at < cutoff,
            )
        )
        await db.commit()
        return result.rowcount


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
        from sqlalchemy import delete, select

        for statuses, cutoff in windows:
            for _ in range(JOB_MAX_BATCHES):
                result = await db.execute(
                    delete(Job).where(
                        Job.id.in_(
                            select(Job.id)
                            .where(
                                Job.status.in_(statuses),
                                Job.created_at < cutoff,
                            )
                            .limit(JOB_DELETE_BATCH)
                        )
                    )
                )
                await db.commit()
                if not result.rowcount:
                    break
                deleted += result.rowcount
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