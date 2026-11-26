"""Bounded retention for grounded research evidence."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from .models import AiVisibilityAttempt, AiVisibilityQuerySet, AiVisibilityQuestion, AiVisibilityRun

logger = logging.getLogger(__name__)
RUN_RETENTION_DAYS = 365
TERMINAL_FAILURE_RETENTION_DAYS = 30
CLEANUP_BATCH = 500
CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def _cleanup_query_sets(
    db: AsyncSession, cutoff: datetime, failure_cutoff: datetime
) -> int:
    ids = (
        await db.execute(
            select(AiVisibilityQuerySet.id)
            .where(
                or_(
                    and_(
                        AiVisibilityQuerySet.status == "completed",
                        AiVisibilityQuerySet.completed_at < cutoff,
                    ),
                    and_(
                        AiVisibilityQuerySet.status.in_(("failed", "partial")),
                        AiVisibilityQuerySet.completed_at < failure_cutoff,
                    ),
                ),
                AiVisibilityQuerySet.completed_at.is_not(None),
            )
            .order_by(AiVisibilityQuerySet.completed_at)
            .limit(CLEANUP_BATCH)
        )
    ).scalars().all()
    if not ids:
        return 0
    # Explicit child deletion keeps behavior identical on SQLite test engines
    # where foreign-key enforcement can be disabled.
    await db.execute(
        delete(AiVisibilityQuestion).where(
            AiVisibilityQuestion.query_set_id.in_(ids)
        )
    )
    await db.execute(delete(AiVisibilityQuerySet).where(AiVisibilityQuerySet.id.in_(ids)))
    await db.commit()
    return len(ids)


async def cleanup_once(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RUN_RETENTION_DAYS)
    failure_cutoff = datetime.now(timezone.utc) - timedelta(
        days=TERMINAL_FAILURE_RETENTION_DAYS
    )
    query_sets_deleted = await _cleanup_query_sets(db, cutoff, failure_cutoff)
    ids = (
        await db.execute(
            select(AiVisibilityRun.id)
            .where(
                or_(
                    and_(
                        AiVisibilityRun.status == "completed",
                        AiVisibilityRun.completed_at < cutoff,
                    ),
                    and_(
                        AiVisibilityRun.status.in_(
                            ("failed", "insufficient_evidence", "ambiguous")
                        ),
                        AiVisibilityRun.completed_at < failure_cutoff,
                    ),
                ),
                AiVisibilityRun.completed_at.is_not(None),
            )
            .order_by(AiVisibilityRun.completed_at)
            .limit(CLEANUP_BATCH)
        )
    ).scalars().all()
    if not ids:
        attempt_ids = (
            await db.execute(
                select(AiVisibilityAttempt.id)
                .where(AiVisibilityAttempt.attempted_at < failure_cutoff)
                .order_by(AiVisibilityAttempt.attempted_at)
                .limit(CLEANUP_BATCH)
            )
        ).scalars().all()
        if attempt_ids:
            await db.execute(
                delete(AiVisibilityAttempt).where(
                    AiVisibilityAttempt.id.in_(attempt_ids)
                )
            )
            await db.commit()
        return len(attempt_ids) + query_sets_deleted
    await db.execute(delete(AiVisibilityRun).where(AiVisibilityRun.id.in_(ids)))
    attempt_ids = (
        await db.execute(
            select(AiVisibilityAttempt.id)
            .where(AiVisibilityAttempt.attempted_at < failure_cutoff)
            .order_by(AiVisibilityAttempt.attempted_at)
            .limit(CLEANUP_BATCH)
        )
    ).scalars().all()
    if attempt_ids:
        await db.execute(
            delete(AiVisibilityAttempt).where(
                AiVisibilityAttempt.id.in_(attempt_ids)
            )
        )
    await db.commit()
    return len(ids) + len(attempt_ids) + query_sets_deleted


async def run_cleanup_worker() -> None:
    while True:
        try:
            async with async_session() as db:
                deleted = await cleanup_once(db)
                if deleted:
                    logger.info(
                        "ai_visibility_retention_deleted",
                        extra={"count": deleted},
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ai_visibility_retention_failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
