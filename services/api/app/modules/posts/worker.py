"""Scheduled-post worker: publish due rows, delete expired rows.

Every POSTS_PUBLISH_INTERVAL_SECONDS, one pass over due scheduled posts
(scheduled_on passed, retry backoff elapsed) plus rows whose delete_at has
passed. Per-post advisory locks make overlapping passes (two workers, or a
manual publish at the same instant) safe: publishing twice on Google is the
one outcome that must never happen, so losers SKIP instead of waiting.
Deletes are naturally idempotent and need no locks.
"""
import asyncio
import logging
import random

from ...config import settings
from ...database import async_session
from . import service as posts_service

logger = logging.getLogger(__name__)


async def run_post_publish_worker() -> None:
    """Background loop started from app lifespan."""
    interval = max(60, settings.POSTS_PUBLISH_INTERVAL_SECONDS)
    # Startup jitter so fresh deploys don't fire every worker in lockstep.
    await asyncio.sleep(random.uniform(0, min(15, interval)))
    while True:
        try:
            async with async_session() as db:
                totals = await posts_service.publish_due(db)
                gone = await posts_service.delete_due(db)
                totals["deleted"] = gone["deleted"]
            if totals["checked"] or gone["checked"]:
                logger.info("Scheduled posts sync: %s", totals)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduled posts sync pass failed: %s", e)
        await asyncio.sleep(interval)
