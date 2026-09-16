"""Localith background auto-sync worker.

Every connected listing is re-synced on LOCALITH_SYNC_INTERVAL_SECONDS:
profile snapshot, all review items (into the ReviewInsight pipeline) and
both metrics summaries. Manual "Sync now" (POST /sync) still works and
just runs the same pass for one user on demand.

Safety notes:
- One failure never kills the pass: each connection is synced in its own
  try/except and counted in totals.
- sync_connection is idempotent (reviews upsert on channel+review_id,
  snapshots overwrite), so overlapping runs from two API instances are
  harmless — worst case is a duplicate review event, which the analytics
  consumer handles idempotently.
"""
import asyncio
import logging

from sqlalchemy import select

from ...config import settings
from ..users.models import User
from . import service as localith_service
from .models import LocalithConnection

logger = logging.getLogger(__name__)


async def sync_all_once(session_factory=None) -> dict:
    """One auto-sync pass over every saved Localith connection."""
    from ...database import async_session

    totals = {"connections": 0, "fetched": 0, "new_reviews": 0, "errors": 0}
    if not localith_service._key_present():
        return totals
    factory = session_factory or async_session
    async with factory() as db:
        try:
            connections = (
                await db.execute(select(LocalithConnection))
            ).scalars().all()
        except Exception as e:
            logger.error("Localith auto-sync: could not list connections: %s", e)
            totals["errors"] += 1
            return totals
        for connection in connections:
            listing_id = getattr(connection, "listing_id", None)
            try:
                user = await db.get(User, connection.user_id)
                if user is None:
                    continue
                totals["connections"] += 1
                result = await localith_service.sync_connection(
                    user, db, listing_id=listing_id
                )
                totals["fetched"] += int(result.get("fetched", 0))
                totals["new_reviews"] += int(result.get("new_reviews", 0))
            except Exception as e:
                logger.error(
                    "Localith auto-sync failed for listing %s: %s",
                    listing_id or "?", e,
                )
                totals["errors"] += 1
                try:
                    await db.rollback()
                except Exception:
                    pass
    return totals


async def run_localith_sync_worker() -> None:
    """Background loop started from app lifespan."""
    interval = max(60, settings.LOCALITH_SYNC_INTERVAL_SECONDS)
    while True:
        try:
            totals = await sync_all_once()
            if totals["connections"] or totals["errors"]:
                logger.info("Localith auto-sync: %s", totals)
        except Exception as e:
            logger.error("Localith auto-sync pass failed: %s", e)
        await asyncio.sleep(interval)
