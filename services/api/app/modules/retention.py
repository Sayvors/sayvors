"""Retention cleanup for unbounded tables.

Runs as part of the outbox worker's hourly cleanup cycle. Each function
deletes rows older than the configured retention period and returns the
count deleted. Failures are logged but never break the cleanup loop.
"""
import logging
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..database import async_session
from ..channels.meta.models import MetaWebhookEvent
from ..channels.models import ChannelMessage
from ..llm.models import LLMUsageEvent
from ..notifications.models import Notification

logger = logging.getLogger(__name__)

# Retention periods (days). Configurable via env if needed.
WEBHOOK_EVENT_RETENTION_DAYS = 30
NOTIFICATION_RETENTION_DAYS = 90
USAGE_EVENT_RETENTION_DAYS = 90
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


async def cleanup_all() -> dict[str, int]:
    """Run all retention cleanup jobs. Returns counts deleted."""
    counts = {}
    for name, fn in [
        ("webhook_events", cleanup_webhook_events),
        ("notifications", cleanup_notifications),
        ("usage_events", cleanup_usage_events),
    ]:
        try:
            counts[name] = await fn()
        except Exception as e:
            logger.warning("Retention cleanup failed for %s: %s", name, e)
            counts[name] = -1
    return counts