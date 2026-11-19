"""Scheduled Google Places scrape that feeds the benchmark history.

Admin owns the cadence. `BenchmarkConfig` carries it:

- `refresh_hours` — how stale a snapshot may get before a place is scraped again.
- `retention_days` — how long snapshots are kept before the pruner removes them.
- `place_cache_enabled` — false pauses scraping entirely without deleting history.

The worker loop wakes on a short fixed tick and scrapes whatever is due, so an
admin changing the interval takes effect on the next tick instead of needing a
restart. One pass is bounded: a fixed number of places, one Places call per
distinct Google place id (a competitor saved by many tenants is fetched once),
and a failure on one place never stops the pass. Every failure is stored on the
row it belongs to, so a silent outage is impossible.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from . import places, service
from .models import BenchmarkPlace, BenchmarkSnapshot

logger = logging.getLogger(__name__)

# How often the loop checks for work. The real cadence is `refresh_hours`;
# this only decides how quickly an admin change is picked up.
TICK_SECONDS = 300
# Places per pass. Google Places bills per request, so a pass is deliberately
# small enough to stay predictable at 1000 tenants with 50 saved places each.
BATCH_LIMIT = 200
# Politeness gap between Google calls; keeps a large pass from bursting.
CALL_PACING_SECONDS = 0.15
MAX_ERROR_LEN = 300


class ScrapeAborted(RuntimeError):
    """The pass cannot continue (Places is not configured). Never retried in-pass."""


async def _record_error(db: AsyncSession, place_pk: str, message: str) -> None:
    row = await db.get(BenchmarkPlace, place_pk)
    if row is not None:
        row.last_scrape_error = message[:MAX_ERROR_LEN]
        await db.commit()


async def _store(
    db: AsyncSession,
    place_pk: str,
    tenant_id: str,
    details: dict[str, Any],
    now: datetime,
) -> None:
    """Update the bench row and append one history point, atomically."""
    row = await db.get(BenchmarkPlace, place_pk)
    if row is None:  # removed while the pass was running
        return
    rating = details.get("rating")
    review_count = details.get("review_count")
    row.name = details.get("name") or row.name
    row.rating = rating if rating is not None else row.rating
    row.review_count = review_count if review_count is not None else row.review_count
    row.reviews = details.get("reviews") or row.reviews
    row.fetched_at = now
    row.last_scrape_error = None
    db.add(
        BenchmarkSnapshot(
            place_id=place_pk,
            tenant_id=tenant_id,
            rating=rating,
            review_count=review_count,
            reviews=details.get("reviews") or None,
            fetched_at=now,
        )
    )
    await db.commit()


async def _due_rows(db: AsyncSession, cutoff: datetime, limit: int) -> list[tuple[str, str, str, str | None]]:
    """Rows whose newest snapshot is missing or older than `cutoff`."""
    newest = (
        select(
            BenchmarkSnapshot.place_id.label("place_id"),
            func.max(BenchmarkSnapshot.fetched_at).label("last_at"),
        )
        .group_by(BenchmarkSnapshot.place_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                BenchmarkPlace.id,
                BenchmarkPlace.place_id,
                BenchmarkPlace.tenant_id,
                newest.c.last_at,
            )
            .outerjoin(newest, newest.c.place_id == BenchmarkPlace.id)
            .where(or_(newest.c.last_at.is_(None), newest.c.last_at <= cutoff))
            .order_by(newest.c.last_at.asc().nullsfirst())
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def _prune(db: AsyncSession, now: datetime, retention_days: int) -> int:
    cutoff = now - timedelta(days=max(1, retention_days))
    result = await db.execute(
        delete(BenchmarkSnapshot).where(BenchmarkSnapshot.fetched_at < cutoff)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def refresh_due_places(
    *, limit: int = BATCH_LIMIT, now: datetime | None = None
) -> dict[str, Any]:
    """Run one bounded scrape pass.

    Returns a counter dict — the worker logs it and tests assert on it. Raises
    `ScrapeAborted` only when Places is not configured at all; every per-place
    failure is isolated and recorded on that row.
    """
    moment = now or datetime.now(timezone.utc)
    async with async_session() as db:
        config = await service.get_config(db)
        if not config.place_cache_enabled:
            return {"scraped": 0, "failed": 0, "pruned": 0, "reason": "scraping disabled"}

        cutoff = moment - timedelta(hours=max(1, config.refresh_hours))
        due = await _due_rows(db, cutoff, limit)
        scraped = failed = 0

        # One Places call per distinct Google place id: the same competitor is
        # often saved by several tenants, and each save still needs its own
        # snapshot row.
        grouped: dict[str, list[tuple[str, str]]] = {}
        for place_pk, google_place_id, tenant_id, _last in due:
            grouped.setdefault(google_place_id, []).append((place_pk, tenant_id))

        for google_place_id, targets in grouped.items():
            try:
                details = await places.get_place(google_place_id)
            except places.PlacesError as exc:
                if exc.status_code == 503:
                    # No API key: every remaining call fails the same way.
                    logger.error("Benchmark scrape aborted: %s", exc)
                    raise ScrapeAborted(str(exc)) from exc
                failed += len(targets)
                logger.warning("Benchmark scrape failed for %s: %s", google_place_id, exc)
                for place_pk, _tenant in targets:
                    await _record_error(db, place_pk, str(exc))
                continue
            except Exception:
                failed += len(targets)
                logger.exception("Benchmark scrape crashed for %s", google_place_id)
                for place_pk, _tenant in targets:
                    await _record_error(db, place_pk, "Scrape failed with an unexpected error.")
                continue

            for place_pk, tenant_id in targets:
                try:
                    await _store(db, place_pk, tenant_id, details, moment)
                    scraped += 1
                except Exception:
                    failed += 1
                    await db.rollback()
                    logger.exception("Benchmark snapshot write failed for %s", place_pk)
                    await _record_error(db, place_pk, "Could not store this snapshot.")

            await asyncio.sleep(CALL_PACING_SECONDS)

        pruned = await _prune(db, moment, config.retention_days)
        return {
            "scraped": scraped,
            "failed": failed,
            "pruned": pruned,
            "due": len(due),
            "refresh_hours": config.refresh_hours,
            "retention_days": config.retention_days,
        }


async def run_benchmark_scraper() -> None:
    """Worker loop. Never exits: a crashed pass is logged and retried."""
    while True:
        try:
            result = await refresh_due_places()
            if result.get("scraped") or result.get("failed") or result.get("reason"):
                logger.info("Benchmark scrape pass: %s", result)
        except ScrapeAborted:
            # Logged where it happened; idle until Places is configured.
            pass
        except Exception:
            logger.exception("Benchmark scrape pass crashed; retrying next tick")
        await asyncio.sleep(TICK_SECONDS)
