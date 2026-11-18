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
from .admin.models import RetentionConfig
from .analytics.models import CompetitorSnapshotHistory
from .channels.meta.models import MetaWebhookEvent
from .jobs.models import Job
from .llm.models import LLMUsageEvent
from .notifications.models import Notification
from .review_engine.models import ReviewResponseLog

logger = logging.getLogger(__name__)

# Retention periods (days). Configurable via env if needed.
WEBHOOK_EVENT_RETENTION_DAYS = 30
# A webhook row that never reached a terminal status is an orphan: an unknown
# asset was parked as unresolved, or an outbox event died before the worker
# could close the row. It carries no operational value after the retry window,
# so it goes sooner than a terminal row.
WEBHOOK_EVENT_ORPHAN_RETENTION_DAYS = 7
NOTIFICATION_RETENTION_DAYS = 90
USAGE_EVENT_RETENTION_DAYS = 90
# Competitor history powers month-over-month deltas; keep two years so the
# benchmark can still show a year-over-year comparison without unbounded growth.
COMPETITOR_HISTORY_RETENTION_DAYS = 730
# The jobs table is the execution record and grows with every AI reply,
# publish, transcription and media job. It needs a retention window like
# every other unbounded table - without one it is the table that eventually
# takes the database down.
JOB_RETENTION_DAYS = 30
# Failed and dead jobs are what an operator reads when something went wrong,
# so they are kept three times longer than the successful ones.
JOB_FAILURE_RETENTION_DAYS = 90
# Retention windows for review logs and connect-import events are admin-owned
# in retention_config (with these values as the migration defaults).
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
    """Delete terminal webhook events, plus stale non-terminal orphans.

    Terminal rows (processed / duplicate / rejected) are history and go after
    the full window. ``received`` / ``unresolved`` rows only appear here when
    no consumer ever closed them — an unknown asset or a lost outbox event —
    and a short window keeps those from becoming the unbounded table this
    sweep exists to prevent.
    """
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        terminal = await _batched_delete(
            db,
            MetaWebhookEvent,
            MetaWebhookEvent.created_at
            < now - timedelta(days=WEBHOOK_EVENT_RETENTION_DAYS),
            MetaWebhookEvent.status.in_(["processed", "duplicate", "rejected"]),
        )
        orphaned = await _batched_delete(
            db,
            MetaWebhookEvent,
            MetaWebhookEvent.created_at
            < now - timedelta(days=WEBHOOK_EVENT_ORPHAN_RETENTION_DAYS),
            MetaWebhookEvent.status.in_(["received", "unresolved"]),
        )
    return terminal + orphaned


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


async def cleanup_competitor_history() -> int:
    """Delete competitor snapshots older than the delta history window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=COMPETITOR_HISTORY_RETENTION_DAYS)
    async with async_session() as db:
        return await _batched_delete(
            db,
            CompetitorSnapshotHistory,
            CompetitorSnapshotHistory.fetched_at < cutoff,
        )


async def get_policy(db=None):
    """Read the single admin-owned policy row, creating it on first use.

    Returns a plain namespace, not the ORM row: the session closes here, and a
    detached row would make later reads depend on expire_on_commit. HTTP
    callers pass their request session so tests and prod share one database.
    """
    from types import SimpleNamespace

    async def _read(session):
        row = (
            await session.execute(
                select(RetentionConfig).where(RetentionConfig.id == "default")
            )
        ).scalar_one_or_none()
        if row is None:
            row = RetentionConfig(id="default")
            session.add(row)
            await session.commit()
        return SimpleNamespace(
            review_log_days=row.review_log_days,
            connect_event_days=row.connect_event_days,
            backup_lead_days=row.backup_lead_days,
            archive_enabled=row.archive_enabled,
            review_log_archived_through=row.review_log_archived_through,
            connect_event_archived_through=row.connect_event_archived_through,
        )

    if db is not None:
        return await _read(db)
    async with async_session() as session:
        return await _read(session)


async def update_policy(db=None, **values) -> None:
    """Admin-only mutation of the policy row. Validated by the API layer."""
    async def _write(session):
        row = (
            await session.execute(
                select(RetentionConfig).where(RetentionConfig.id == "default")
            )
        ).scalar_one_or_none()
        if row is None:
            row = RetentionConfig(id="default")
            session.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        await session.commit()

    if db is not None:
        await _write(db)
        return
    async with async_session() as session:
        await _write(session)


def _s3_put(kind, key, data, content_type):
    from integrations.storage import s3

    return s3.put(kind, key, data, content_type)


async def _archive_before_delete(
    *,
    kind: str,
    model,
    cutoff,
    lead_days: int,
    watermark_field: str,
    watermark,
    trigger: str,
) -> bool:
    """Archive lead-window rows once, advancing a high-water mark.

    Returns False if S3 failed — the caller must then skip deletion entirely.
    """
    from .retention_archive import archive_rows

    archive_until = cutoff + timedelta(days=lead_days)
    async with async_session() as db:
        for _ in range(MAX_BATCHES_PER_RUN):
            stmt = select(model).where(model.created_at < archive_until)
            if watermark is not None:
                stmt = stmt.where(model.created_at >= watermark)
            rows = (
                (await db.execute(stmt.order_by(model.created_at).limit(DELETE_BATCH_SIZE)))
                .scalars().all()
            )
            if not rows:
                return True
            try:
                await archive_rows(
                    db, kind=kind, rows=list(rows), trigger=trigger, s3_put=_s3_put
                )
            except Exception as e:  # noqa: BLE001 - fail closed on deletion
                logger.warning("Retention archive failed for %s: %s", kind, e)
                return False
            watermark = max(r.created_at for r in rows if r.created_at is not None)
            await update_policy(**{watermark_field: watermark})
            if len(rows) < DELETE_BATCH_SIZE:
                return True
    return True


async def cleanup_review_response_logs(*, trigger: str = "scheduled") -> int:
    """Delete per-generation review logs older than the admin-set window."""
    policy = await get_policy()
    cutoff = datetime.now(timezone.utc) - timedelta(days=policy.review_log_days)
    if policy.archive_enabled:
        ok = await _archive_before_delete(
            kind="review_generation", model=ReviewResponseLog, cutoff=cutoff,
            lead_days=policy.backup_lead_days,
            watermark_field="review_log_archived_through",
            watermark=policy.review_log_archived_through, trigger=trigger,
        )
        if not ok:
            return -1
    async with async_session() as db:
        return await _batched_delete(
            db, ReviewResponseLog, ReviewResponseLog.created_at < cutoff
        )


async def cleanup_connect_import_events(*, trigger: str = "scheduled") -> int:
    """Delete old connect-import progress events after archiving them."""
    from .channels.models import ConnectImportEvent

    policy = await get_policy()
    cutoff = datetime.now(timezone.utc) - timedelta(days=policy.connect_event_days)
    if policy.archive_enabled:
        ok = await _archive_before_delete(
            kind="connect_progress", model=ConnectImportEvent, cutoff=cutoff,
            lead_days=policy.backup_lead_days,
            watermark_field="connect_event_archived_through",
            watermark=policy.connect_event_archived_through, trigger=trigger,
        )
        if not ok:
            return -1
    async with async_session() as db:
        return await _batched_delete(
            db, ConnectImportEvent, ConnectImportEvent.created_at < cutoff
        )


async def backup_now(kind: str) -> int:
    """Admin-triggered archive of the lead window, without deleting anything."""
    from .channels.models import ConnectImportEvent

    policy = await get_policy()
    if kind == "review_generation":
        model, mark, field, days = (
            ReviewResponseLog, policy.review_log_archived_through,
            "review_log_archived_through", policy.review_log_days,
        )
    elif kind == "connect_progress":
        model, mark, field, days = (
            ConnectImportEvent, policy.connect_event_archived_through,
            "connect_event_archived_through", policy.connect_event_days,
        )
    else:
        raise ValueError(f"unknown retention kind: {kind}")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ok = await _archive_before_delete(
        kind=kind, model=model, cutoff=cutoff,
        lead_days=policy.backup_lead_days, watermark_field=field,
        watermark=mark, trigger="manual",
    )
    if not ok:
        raise RuntimeError("archive upload failed; nothing was deleted")
    return 1


async def cleanup_all() -> dict[str, int]:
    """Run all retention cleanup jobs. Returns counts deleted."""
    counts = {}
    for name, fn in [
        ("webhook_events", cleanup_webhook_events),
        ("notifications", cleanup_notifications),
        ("usage_events", cleanup_usage_events),
        ("jobs", cleanup_jobs),
        ("competitor_history", cleanup_competitor_history),
        ("review_response_logs", cleanup_review_response_logs),
        ("connect_import_events", cleanup_connect_import_events),
    ]:
        try:
            counts[name] = await fn()
        except Exception as e:
            logger.warning("Retention cleanup failed for %s: %s", name, e)
            counts[name] = -1
    return counts
