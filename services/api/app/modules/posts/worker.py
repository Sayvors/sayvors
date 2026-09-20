"""Scheduled publishing worker: posts + media, one loop.

Every interval, one pass over due scheduled posts AND due scheduled photos
(scheduled_on passed, retry backoff elapsed), plus rows whose delete_at has
passed. One loop for both — never a loop per content type. Per-item advisory
locks make overlapping passes (two workers, or a manual publish at the same
instant) safe: publishing twice on Google is the one outcome that must never
happen, so losers SKIP instead of waiting. Deletes are naturally idempotent
and need no locks.
"""
import asyncio
import logging
import random

from ...config import settings
from ...database import async_session
from ..media import service as media_service
from . import service as posts_service

logger = logging.getLogger(__name__)


async def run_post_publish_worker() -> None:
    """Background loop started from app lifespan."""
    media_interval = max(60, settings.MEDIA_PUBLISH_INTERVAL_SECONDS)
    interval = min(max(60, settings.POSTS_PUBLISH_INTERVAL_SECONDS), media_interval)
    # Startup jitter so fresh deploys don't fire every worker in lockstep.
    await asyncio.sleep(random.uniform(0, min(15, interval)))
    while True:
        try:
            async with async_session() as db:
                totals = await posts_service.publish_due(db)
                gone = await posts_service.delete_due(db)
                totals["deleted"] = gone["deleted"]
                media = await media_service.publish_due(db)
                media_gone = await media_service.delete_due(db)
            if totals["checked"] or gone["checked"] or media["checked"] or media_gone["checked"]:
                logger.info("Scheduled posts sync: %s | media: %s", totals, {
                    **media, "deleted": media_gone["deleted"],
                })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduled posts sync pass failed: %s", e)
        await asyncio.sleep(interval)
