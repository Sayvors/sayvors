"""Tenant-scoped bench CRUD with hard caps.

A saved place belongs to one tenant's bench. Everything here is scoped by
tenant_id in the query itself, so a cross-tenant read is impossible by
construction rather than by convention.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BenchmarkConfig, BenchmarkPlace, BenchmarkSnapshot

MAX_LABEL = 120
MAX_NOTES = 2000
MAX_LIST = 100
# Canonical Google Maps URL for gosom, bounded to the column width.
MAX_MAPS_URL = 1024


class BenchError(ValueError):
    """A validation or quota failure safe to show to the tenant."""


class BenchNotFound(BenchError):
    """The place is not on this tenant's bench."""


async def get_config(db: AsyncSession) -> BenchmarkConfig:
    """Single config row, created with defaults on first use."""
    row = (
        await db.execute(select(BenchmarkConfig).where(BenchmarkConfig.id == "default"))
    ).scalar_one_or_none()
    if row is None:
        row = BenchmarkConfig(id="default")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def serialize(place: BenchmarkPlace) -> dict:
    return {
        "id": place.id,
        "place_id": place.place_id,
        "label": place.label,
        "notes": place.notes,
        "in_heatmap": place.in_heatmap,
        "in_bench_set": place.in_bench_set,
        "name": place.name,
        "address": getattr(place, "address", None),
        "types": getattr(place, "types", None),
        "rating": place.rating,
        "review_count": place.review_count,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "reviews": place.reviews,
        "photos": place.photos,
        "maps_url": place.maps_url,
        "reviews_per_score": place.reviews_per_score,
        "maps_url": getattr(place, "maps_url", None),
        "thumbnail": getattr(place, "thumbnail", None),
        "fetched_at": place.fetched_at.isoformat() if place.fetched_at else None,
        "last_scrape_error": place.last_scrape_error,
        "created_at": place.created_at.isoformat() if place.created_at else None,
        "updated_at": place.updated_at.isoformat() if place.updated_at else None,
    }


def serialize_config(row: BenchmarkConfig) -> dict:
    return {
        "refresh_hours": row.refresh_hours,
        "retention_days": row.retention_days,
        "place_cache_enabled": row.place_cache_enabled,
        "max_saved_places": row.max_saved_places,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def save_place(
    db: AsyncSession,
    tenant_id: str,
    *,
    place_id: str,
    label: str | None = None,
    notes: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    rating: float | None = None,
    review_count: int | None = None,
    maps_url: str | None = None,
) -> BenchmarkPlace:
    """Save one place to this tenant's bench, idempotent on (tenant, place)."""
    pid = str(place_id or "").strip()[:255]
    if not pid:
        raise BenchError("Choose a place to save.")
    clean_label = (label or "").strip()[:MAX_LABEL] or None
    clean_notes = (notes or "").strip()[:MAX_NOTES] or None
    clean_maps_url = str(maps_url or "").strip()[:MAX_MAPS_URL] or None

    dup = (
        await db.execute(
            select(BenchmarkPlace).where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.place_id == pid,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        if clean_label is not None:
            dup.label = clean_label
        if clean_notes is not None:
            dup.notes = clean_notes
        if latitude is not None and longitude is not None:
            dup.latitude, dup.longitude = latitude, longitude
        if rating is not None:
            dup.rating = rating
        if review_count is not None:
            dup.review_count = review_count
        if clean_maps_url is not None:
            dup.maps_url = clean_maps_url
        await db.commit()
        await db.refresh(dup)
        return dup

    config = await get_config(db)
    used = (
        await db.execute(
            select(func.count(BenchmarkPlace.id)).where(
                BenchmarkPlace.tenant_id == tenant_id
            )
        )
    ).scalar() or 0
    if int(used) >= config.max_saved_places:
        raise BenchError(
            f"Your bench holds {config.max_saved_places} places. Remove one before saving another."
        )

    row = BenchmarkPlace(
        tenant_id=tenant_id, place_id=pid,
        label=clean_label, notes=clean_notes,
        latitude=latitude, longitude=longitude,
        rating=rating, review_count=review_count,
        maps_url=clean_maps_url,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:  # concurrent save of the same place
        await db.rollback()
        existing = (
            await db.execute(
                select(BenchmarkPlace).where(
                    BenchmarkPlace.tenant_id == tenant_id,
                    BenchmarkPlace.place_id == pid,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise BenchError("Could not save this place.") from exc
        return existing
    await db.refresh(row)
    # The first snapshot is the day-one fact for the heatmap: a saved place
    # with no history still has a real cell at "now" rather than an empty row.
    db.add(BenchmarkSnapshot(
        place_id=row.id, tenant_id=tenant_id,
        rating=rating, review_count=review_count,
        fetched_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return row


async def heatmap_matrix(db: AsyncSession, tenant_id: str, *, weeks: int = 12) -> dict:
    """Locations x weeks matrix for the heatmap chart.

    Each cell is the latest review count captured in that ISO week. Weeks are
    always emitted so the chart has a stable axis even with one saved place.
    """
    from datetime import timedelta

    count = max(1, min(int(weeks), 52))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(weeks=count - 1)
    start = start - timedelta(days=start.weekday())
    end = today + timedelta(days=6 - today.weekday())

    places = (
        await db.execute(
            select(BenchmarkPlace)
            .where(BenchmarkPlace.tenant_id == tenant_id, BenchmarkPlace.in_heatmap.is_(True))
            .order_by(BenchmarkPlace.created_at)
        )
    ).scalars().all()
    columns = [(start + timedelta(weeks=i)).isoformat() for i in range(count)]
    if not places:
        return {"weeks": columns, "rows": [], "metric": "reviews"}

    place_ids = [p.id for p in places]
    snapshots = (
        await db.execute(
            select(BenchmarkSnapshot)
            .where(
                BenchmarkSnapshot.tenant_id == tenant_id,
                BenchmarkSnapshot.place_id.in_(place_ids),
                BenchmarkSnapshot.fetched_at >= datetime.combine(start, datetime.min.time()),
                BenchmarkSnapshot.fetched_at <= datetime.combine(end, datetime.min.time()) + timedelta(days=1),
            )
            .order_by(BenchmarkSnapshot.fetched_at)
        )
    ).scalars().all()

    latest: dict[tuple[str, str], int | None] = {}
    for snap in snapshots:
        week = (snap.fetched_at.date() - timedelta(days=snap.fetched_at.date().weekday())).isoformat()
        latest[(snap.place_id, week)] = snap.review_count

    rows = [{
        "place_id": p.id,
        "external_id": p.place_id,
        "name": p.label or p.name or p.place_id,
        "rating": p.rating,
        "cells": [latest.get((p.id, week)) for week in columns],
    } for p in places]
    return {"weeks": columns, "rows": rows, "metric": "reviews"}


async def list_saved(
    db: AsyncSession, tenant_id: str, *, limit: int = MAX_LIST
) -> list[dict]:
    rows = (
        await db.execute(
            select(BenchmarkPlace)
            .where(BenchmarkPlace.tenant_id == tenant_id)
            .order_by(BenchmarkPlace.created_at.desc())
            .limit(max(1, min(int(limit), MAX_LIST)))
        )
    ).scalars().all()
    return [serialize(row) for row in rows]


async def get_saved(db: AsyncSession, tenant_id: str, place_id: str) -> BenchmarkPlace | None:
    """Fetch one saved place, scoped to this tenant. None means not on their bench."""
    return (
        await db.execute(
            select(BenchmarkPlace).where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.place_id == str(place_id or "")[:255],
            )
        )
    ).scalar_one_or_none()


async def toggle_heatmap(
    db: AsyncSession, tenant_id: str, place_id: str, *, enabled: bool | None = None
) -> BenchmarkPlace | None:
    """Include or exclude a saved place from the heatmap (tenant-scoped)."""
    row = await get_saved(db, tenant_id, place_id)
    if row is None:
        return None
    row.in_heatmap = (not row.in_heatmap) if enabled is None else bool(enabled)
    await db.commit()
    await db.refresh(row)
    return row


BENCH_SET_MAX = 5


async def set_bench_set(
    db: AsyncSession, tenant_id: str, place_id: str, *, enabled: bool | None = None
) -> BenchmarkPlace:
    """Toggle a saved place's membership in the tenant's benchmark set.

    The cap is enforced under a row lock on ALL of the tenant's saved rows,
    not just current members: a members-only lock anchors zero rows on an
    empty set, so N concurrent first-enables would all pass the count check
    (AGENTS.md: real concurrency). Enabling an already-enabled member is a
    no-op that must not trip the cap. SQLite ignores FOR UPDATE, so the
    tests exercise the count logic, not the locking itself.
    """
    row = await get_saved(db, tenant_id, place_id)
    if row is None:
        raise BenchNotFound("Saved place not found")
    new_value = (not row.in_bench_set) if enabled is None else bool(enabled)
    if new_value is False or row.in_bench_set is True:
        row.in_bench_set = new_value
        await db.commit()
        await db.refresh(row)
        return row
    members = (
        await db.execute(
            select(BenchmarkPlace)
            .where(BenchmarkPlace.tenant_id == tenant_id)
            .with_for_update()
        )
    ).scalars().all()
    if len([m for m in members if m.in_bench_set]) >= BENCH_SET_MAX:
        raise BenchError(
            f"Benchmark set is full ({BENCH_SET_MAX} places). "
            "Remove one before adding another."
        )
    row.in_bench_set = True
    await db.commit()
    await db.refresh(row)
    return row


async def delete_saved(db: AsyncSession, tenant_id: str, place_id: str) -> bool:
    row = (
        await db.execute(
            select(BenchmarkPlace).where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.place_id == str(place_id or "")[:255],
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


# Admin-editable settings. Bounds are deliberately wide but finite: an interval
# of 0 would scrape on every tick, and a retention of 0 would delete the
# history the comparison page reads.
CONFIG_BOUNDS: dict[str, tuple[int, int]] = {
    "refresh_hours": (1, 168),
    "retention_days": (7, 3650),
    "max_saved_places": (1, 500),
}


async def update_config(db: AsyncSession, **values: object) -> BenchmarkConfig:
    """Apply admin changes to the single benchmark config row.

    Unknown keys are rejected rather than ignored: a typo'd field must not look
    like it saved. `place_cache_enabled` doubles as the scraper switch.
    """
    row = await get_config(db)
    for key, value in values.items():
        if key == "place_cache_enabled":
            row.place_cache_enabled = bool(value)
            continue
        if key not in CONFIG_BOUNDS:
            raise BenchError(f"Unknown benchmark setting: {key}")
        if value is None:
            continue
        low, high = CONFIG_BOUNDS[key]
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise BenchError(f"{key} must be a whole number.") from exc
        if not low <= number <= high:
            raise BenchError(f"{key} must be between {low} and {high}.")
        setattr(row, key, number)
    await db.commit()
    await db.refresh(row)
    return row


async def has_recent_snapshot(
    db: AsyncSession, place_pk: str, *, hours: int, now: datetime
) -> bool:
    """True when this place already has a snapshot inside the freshness window.

    Used to keep history sparse: a live read doubles as the periodic scrape, so
    it must not append a row on every page view.
    """
    cutoff = now - timedelta(hours=max(1, hours))
    return (
        await db.execute(
            select(func.count())
            .select_from(BenchmarkSnapshot)
            .where(
                BenchmarkSnapshot.place_id == place_pk,
                BenchmarkSnapshot.fetched_at >= cutoff,
            )
        )
    ).scalar() > 0


async def store_place_details(
    db: AsyncSession,
    place: BenchmarkPlace,
    details: dict,
    *,
    now: datetime | None = None,
    append_snapshot: bool = False,
) -> None:
    """Write a provider payload into the cached bench row.

    `append_snapshot` also records one history point. Callers decide when that
    is due (see `has_recent_snapshot`), so a cached read never floods history.
    """
    moment = now or datetime.now(timezone.utc)
    place.name = details.get("name") or place.name
    place.address = details.get("address") or place.address
    place.types = details.get("types") or place.types
    rating = details.get("rating")
    review_count = details.get("review_count")
    place.rating = rating if rating is not None else place.rating
    place.review_count = review_count if review_count is not None else place.review_count
    place.reviews = details.get("reviews") or place.reviews
    place.reviews_per_score = details.get("reviews_per_score") or place.reviews_per_score
    place.maps_url = details.get("maps_url") or place.maps_url
    place.thumbnail = details.get("thumbnail") or place.thumbnail
    place.fetched_at = moment
    place.last_scrape_error = None
    if append_snapshot:
        db.add(
            BenchmarkSnapshot(
                place_id=place.id,
                tenant_id=place.tenant_id,
                rating=rating,
                review_count=review_count,
                reviews=details.get("reviews") or None,
                fetched_at=moment,
            )
        )
    await db.commit()


async def history_points(
    db: AsyncSession,
    tenant_id: str,
    place: BenchmarkPlace,
    *,
    days: int,
    points: int,
) -> list[dict]:
    """Snapshot history for one saved place, oldest first, downsampled.

    Only the selected window is returned: history from before it belongs to a
    different range and must not appear here. Reading every snapshot of a year
    would put hundreds of rows into a table nobody can read, so the caller asks
    for at most `points` evenly spaced rows and the scan is bounded before that.
    """
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    points = max(points, 1)
    rows = (
        await db.execute(
            select(
                BenchmarkSnapshot.fetched_at,
                BenchmarkSnapshot.rating,
                BenchmarkSnapshot.review_count,
            )
            .where(
                BenchmarkSnapshot.tenant_id == tenant_id,
                BenchmarkSnapshot.place_id == place.id,
                BenchmarkSnapshot.fetched_at >= since,
            )
            .order_by(BenchmarkSnapshot.fetched_at.desc())
            .limit(points * 4)
        )
    ).all()
    if not rows:
        return []
    if len(rows) <= points:
        selected = rows
    else:
        step = len(rows) / float(points)
        selected = [rows[min(len(rows) - 1, int(index * step))] for index in range(points)]
    # Oldest first: a history table reads top-to-bottom in time order.
    return [
        {
            "at": row[0].isoformat() if row[0] else None,
            "rating": row[1],
            "reviews": row[2],
        }
        for row in reversed(selected)
    ]

async def tenant_location_context(db: AsyncSession, tenant_id: str) -> dict:
    """Best-effort location context for nearby-first benchmark search.

    Uses the tenant's active Google location metadata. No guessing: if fields
    are missing, we return only what we know.
    """
    from ..channels.models import Channel

    rows = (
        await db.execute(
            select(Channel)
            .where(Channel.user_id == tenant_id, Channel.platform == "google_reviews", Channel.status == "active")
            .order_by(Channel.created_at.desc())
        )
    ).scalars().all()
    for ch in rows:
        try:
            meta = json.loads(ch.metadata_json or "{}")
        except Exception:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        addr = str(meta.get("address") or meta.get("formatted_address") or "").strip()
        country = str(meta.get("country") or "").strip()
        city = str(meta.get("city") or meta.get("locality") or "").strip()
        lat = meta.get("latitude") or meta.get("lat")
        lng = meta.get("longitude") or meta.get("lng")
        try:
            lat = float(lat) if lat is not None else None
            lng = float(lng) if lng is not None else None
        except Exception:
            lat = lng = None
        if not country and addr:
            parts = [p.strip() for p in addr.split(",") if p.strip()]
            if parts:
                country = parts[-1][:80]
                if len(parts) >= 2 and not city:
                    city = parts[-2][:80]
        if not (addr or city or country or (lat is not None and lng is not None)):
            continue
        return {
            "name": ch.display_name,
            "address": addr or None,
            "city": city or None,
            "country": country or None,
            "latitude": lat,
            "longitude": lng,
        }
    return {}

