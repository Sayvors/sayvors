"""Scheduled-media worker: publish due photos, delete expired rows.

Same contract as the posts worker: per-item try-locks (a photo must never
publish twice on Google), retry-then-park on failures, startup jitter so
fresh deploys don't fire every worker in lockstep.
"""
import asyncio
import logging
import random

from ...config import settings
from ...database import async_session
from . import service as media_service

logger = logging.getLogger(__name__)


async def run_media_publish_worker() -> None:
    """Background loop started from app lifespan."""
    interval = max(60, settings.MEDIA_PUBLISH_INTERVAL_SECONDS)
    await asyncio.sleep(random.uniform(0, min(15, interval)))
    while True:
        try:
            async with async_session() as db:
                totals = await media_service.publish_due(db)
                gone = await media_service.delete_due(db)
                totals["deleted"] = gone["deleted"]
            if totals["checked"] or gone["checked"]:
                logger.info("Scheduled media sync: %s", totals)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduled media sync pass failed: %s", e)
        await asyncio.sleep(interval)
