"""Scheduled-post publisher worker.

Every POSTS_PUBLISH_INTERVAL_SECONDS, publishes all due scheduled rows
(scheduled_on <= now) across users. Per-post failures are isolated, marked
failed with the error, and reported in totals — one bad post never blocks
the rest.
"""
import asyncio
import logging

from ...config import settings
from ...database import async_session
from . import service as posts_service

logger = logging.getLogger(__name__)


async def run_post_publish_worker() -> None:
    """Background loop started from app lifespan."""
    interval = max(60, settings.POSTS_PUBLISH_INTERVAL_SECONDS)
    while True:
        try:
            async with async_session() as db:
                totals = await posts_service.publish_due(db)
            if totals["checked"]:
                logger.info("Scheduled posts sync: %s", totals)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduled posts sync pass failed: %s", e)
        await asyncio.sleep(interval)
