"""Localith background auto-sync worker.

Every connected listing is re-synced on LOCALITH_SYNC_INTERVAL_SECONDS:
profile snapshot, all review items (into the ReviewInsight pipeline) and
both metrics summaries. Manual "Sync now" (POST /sync) still works and
just runs the same pass for one user on demand.

Safety notes:
- One failure never kills the pass: each connection is synced in its own
  try/except and counted in totals.
- Every uvicorn worker runs this loop, so passes overlap by design. Each
  branch takes its per-listing advisory lock with try-lock semantics: the
  loser SKIPS instead of queueing (counted as skipped), so N workers never
  duplicate work or twin rows. Channel identity additionally rests on the
  unique index (user_id, platform, listing_key) — see channels.service.
"""
import asyncio
import logging
import random

from sqlalchemy import select

from ...config import settings
from ..users.models import User
from . import service as localith_service
from .models import LocalithConnection

logger = logging.getLogger(__name__)


async def sync_all_once(session_factory=None) -> dict:
    """One auto-sync pass over every saved Localith connection."""
    from ...database import async_session

    totals = {"connections": 0, "fetched": 0, "new_reviews": 0, "errors": 0, "skipped": 0}
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
            # Single-flight: another worker (or a manual sync) is on this
            # branch — skip instead of piling on.
            held = await localith_service._try_acquire_sync_lock(db, listing_id)
            if not held:
                totals["skipped"] += 1
                continue
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
            finally:
                await localith_service._release_sync_lock(db, listing_id)
    return totals


async def run_localith_sync_worker() -> None:
    """Background loop started from app lifespan."""
    interval = max(60, settings.LOCALITH_SYNC_INTERVAL_SECONDS)
    # Startup jitter: fresh deploys start every worker at once — spread the
    # loops so they don't fire in lockstep on day one.
    await asyncio.sleep(random.uniform(0, min(15, interval)))
    while True:
        try:
            totals = await sync_all_once()
            if totals["connections"] or totals["errors"]:
                logger.info("Localith auto-sync: %s", totals)
        except Exception as e:
            logger.error("Localith auto-sync pass failed: %s", e)
        await asyncio.sleep(interval)
