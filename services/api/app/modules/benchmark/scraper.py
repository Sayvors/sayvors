"""Scheduled benchmark collector: official Places facts, BOQ deep reviews.

Search uses ``mapsearch`` (the canonical Maps URL/feature ID). Place facts and
a bounded review sample use Google Places (New) when a key is configured;
``boq`` supplies deep recent reviews and is the complete fallback when Places
is unavailable. ``benchmark/provider.py`` owns that order, so the worker and
read handlers cannot drift.

Admin owns the cadence. `BenchmarkConfig` carries it:

- `refresh_hours` — how stale a snapshot may get before a place is scraped again.
- `retention_days` — how long snapshots are kept before the pruner removes them.
- `place_cache_enabled` — false pauses scraping entirely without deleting history.

One pass is bounded: a fixed number of places, one provider call per distinct
Google place id (a competitor saved by many tenants is fetched once), and a
failure on one place never stops the pass. Every failure is stored on the row
it belongs to, so a silent outage is impossible.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from . import boq, outscraper, places, provider, service
from .models import BenchmarkPlace, BenchmarkSnapshot

logger = logging.getLogger(__name__)

# How often the loop checks for work. The real cadence is `refresh_hours`;
# this only decides how quickly an admin change is picked up.
TICK_SECONDS = 300
# Hard cost cap: small batch, bounded provider work.
BATCH_LIMIT = 10
# Politeness gap between provider calls; keeps a pass from bursting.
CALL_PACING_SECONDS = 0.25
MAX_ERROR_LEN = 300
TICKS_PER_HOUR = 3600 // TICK_SECONDS

# The worker asks for deep history; provider.get_details caps the official
# Places call at 10 and sources the remainder from BOQ. Outscraper stays bounded
# because it bills per review.
PROVIDER_REVIEWS_LIMIT = {
    "google_places": 500,
    "boq": 500,
    "outscraper": 10,
}


def _resolve_provider(config: Any) -> Any:
    """Pick the provider; legacy ``gosom`` rows now use the free endpoints."""
    source = str(getattr(config, "source", "") or "").strip()
    if source in {"boq", "gosom"}:
        return boq
    if source == "outscraper":
        return outscraper
    return places


def capacity_warning(config: Any) -> str | None:
    """Warn when the saved-place cap exceeds one cadence's scrape capacity."""
    capacity = BATCH_LIMIT * TICKS_PER_HOUR * max(1, int(config.refresh_hours))
    if int(config.max_saved_places) <= capacity:
        return None
    return (
        f"At the current cadence the collector can refresh about {capacity} places "
        f"per cycle, but the saved-place cap is {config.max_saved_places}. "
        "Lower the cap or shorten refresh_hours."
    )


class ScrapeAborted(RuntimeError):
    """The pass cannot continue (the selected provider is not configured).

    Never retried in-pass; the worker idles until an admin configures it.
    """


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
    # A fresh snapshot exists by definition of "due"; storing unconditionally
    # matches `has_recent_snapshot` elsewhere and keeps the pass simple.
    await service.store_place_details(
        db, row, details, now=now, append_snapshot=True
    )


async def _due_rows(
    db: AsyncSession, cutoff: datetime, limit: int
) -> list[tuple[str, str, str, str | None, str | None]]:
    """Rows whose newest snapshot is missing or older than `cutoff`.

    Returns `(place_pk, place_id, tenant_id, last_at, maps_url)`; `maps_url` is
    the canonical Maps URL captured at save time and carries the feature id the
    free endpoints key on.
    """
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
                BenchmarkPlace.maps_url,
            )
            .outerjoin(newest, newest.c.place_id == BenchmarkPlace.id)
            .where(or_(newest.c.last_at.is_(None), newest.c.last_at <= cutoff))
            .order_by(newest.c.last_at.asc().nullsfirst())
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]


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

    Returns a counter dict — the worker logs it and tests assert on it. A 503
    from a configured provider aborts the pass (quota/block); every other
    per-place failure is isolated and recorded on that row.
    """
    moment = now or datetime.now(timezone.utc)
    async with async_session() as db:
        config = await service.get_config(db)
        if not config.place_cache_enabled:
            return {"scraped": 0, "failed": 0, "pruned": 0, "reason": "scraping disabled"}

        source = str(getattr(config, "source", "") or "").strip()
        reviews_limit = PROVIDER_REVIEWS_LIMIT.get(source, 500)
        # Official Places supplies facts; BOQ supplies deep reviews and is the
        # complete fallback. A row without a canonical Maps feature id can only
        # be refreshed when a non-BOQ primary can answer on its own.
        boq_only = source in {"boq", "gosom"} or (
            source == "google_places" and not places.configured()
        )
        cutoff = moment - timedelta(hours=max(1, config.refresh_hours))
        due = await _due_rows(db, cutoff, limit)
        skipped = 0
        if boq_only:
            refreshable = [row for row in due if boq.feature_id(row[4])]
            skipped = len(due) - len(refreshable)
            due = refreshable
            if skipped:
                logger.debug("Skipped %d benchmark rows without a Maps feature id", skipped)
        scraped = failed = 0

        # One provider call per distinct Google place id: the same competitor is
        # often saved by several tenants, and each save still needs its own
        # snapshot row. The group's maps_url is identical by construction.
        grouped: dict[str, list[tuple[str, str]]] = {}
        group_maps_url: dict[str, str | None] = {}
        for place_pk, google_place_id, tenant_id, _last, maps_url in due:
            grouped.setdefault(google_place_id, []).append((place_pk, tenant_id))
            group_maps_url.setdefault(google_place_id, maps_url)

        cutoff_ts = int((moment - timedelta(days=7)).timestamp())
        for google_place_id, targets in grouped.items():
            maps_url = group_maps_url.get(google_place_id)
            try:
                details = await provider.get_details(
                    source,
                    google_place_id,
                    reviews_limit=reviews_limit,
                    maps_url=maps_url,
                    cutoff=cutoff_ts,
                )
            except (places.PlacesError, boq.BoqError, outscraper.OutscraperError) as exc:
                if getattr(exc, "status_code", None) == 503:
                    # No API key / not configured: every remaining call fails the same way.
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
            "due": len(due) + skipped,
            "skipped": skipped,
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
            # Logged where it happened; idle until the provider recovers.
            pass
        except Exception:
            logger.exception("Benchmark scrape pass crashed; retrying next tick")
        await asyncio.sleep(TICK_SECONDS)
