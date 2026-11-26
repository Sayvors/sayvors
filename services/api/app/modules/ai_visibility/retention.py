"""Bounded retention for grounded research evidence."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from .models import AiVisibilityAttempt, AiVisibilityRun

logger = logging.getLogger(__name__)
RUN_RETENTION_DAYS = 365
TERMINAL_FAILURE_RETENTION_DAYS = 30
CLEANUP_BATCH = 500
CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def cleanup_once(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RUN_RETENTION_DAYS)
    failure_cutoff = datetime.now(timezone.utc) - timedelta(
        days=TERMINAL_FAILURE_RETENTION_DAYS
    )
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
        return len(attempt_ids)
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
    return len(ids) + len(attempt_ids)


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
