"""External peer set for Benchmark (Pro feature).

Provider abstraction: today the only implemented source is Google Places API
(New). A licensed crawler/aggregator can implement the same ``fetch_peers``
contract later without changing the benchmark endpoint or the snapshots table.

Design rules:
- The key lives in the environment and is never returned to the client.
- If the key is missing, the feature is dormant: the API says
  ``configured: false`` and the UI shows "not connected" rather than a
  fabricated peer set.
- Every row carries source, query radius, and fetched_at so the UI can
  disclose provenance and age.
- Network failures are logged and surfaced as an empty refresh, never as a
  silent fake success.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from .models import CompetitorSnapshot, CompetitorSnapshotHistory

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.userRatingCount,places.primaryTypeDisplayName"
)
PLACES_TIMEOUT_SECONDS = 10.0
# Deltas are most useful over a month; that is also the benchmark copy's
# "this month" claim. History older than this is retained only for audit.
DELTA_WINDOW_DAYS = 30
HISTORY_QUERY_LIMIT = 2000


def places_configured() -> bool:
    return bool(settings.GOOGLE_PLACES_API_KEY.strip())


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2


async def _search_text(query: str, max_results: int) -> list[dict]:
    """Places API (New) text search. Raises on transport/HTTP errors."""
    async with httpx.AsyncClient(timeout=PLACES_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            PLACES_TEXT_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": PLACES_FIELD_MASK,
            },
            json={
                "textQuery": query,
                "maxResultCount": max(1, min(max_results, 20)),
                "languageCode": "en",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    out: list[dict] = []
    for place in data.get("places") or []:
        place_id = place.get("id")
        name = ((place.get("displayName") or {}).get("text") or "").strip()
        if not place_id or not name:
            continue
        out.append({
            "place_id": place_id,
            "name": name[:255],
            "category": ((place.get("primaryTypeDisplayName") or {}).get("text") or None),
            "address": (place.get("formattedAddress") or None),
            "rating": _num(place.get("rating")),
            "review_count": int(place.get("userRatingCount") or 0),
        })
    return out


async def refresh_external_peers(
    db: AsyncSession,
    user_id: str,
    *,
    name: str | None,
    address: str | None,
    category: str | None,
) -> dict:
    """Fetch and upsert nearby competitors for one tenant.

    Idempotent: rows are upserted by (user_id, place_id, source); rows that
    disappear from the new result set are pruned so a closed business does not
    linger in the peer set forever.
    """
    if not places_configured():
        return {"configured": False, "inserted": 0, "reason": "GOOGLE_PLACES_API_KEY is not set"}

    subject = name or "business"
    where = address or category or subject
    query = f"{category + ' near ' if category else 'businesses near '}{where}".strip()
    try:
        found = await _search_text(query, settings.BENCHMARK_PEER_MAX_RESULTS)
    except Exception as e:
        logger.warning("Places peer refresh failed for %s: %s", user_id, e)
        return {"configured": True, "inserted": 0, "reason": "Places request failed"}

    now = datetime.now(timezone.utc)
    existing = {
        row.place_id: row
        for row in (
            await db.execute(
                select(CompetitorSnapshot).where(
                    CompetitorSnapshot.user_id == user_id,
                    CompetitorSnapshot.source == "google_places",
                )
            )
        ).scalars().all()
    }
    seen: set[str] = set()
    for item in found:
        seen.add(item["place_id"])
        row = existing.get(item["place_id"])
        if row is None:
            row = CompetitorSnapshot(
                user_id=user_id,
                place_id=item["place_id"],
                source="google_places",
            )
            db.add(row)
        row.name = item["name"]
        row.category = item["category"]
        row.address = item["address"]
        row.rating = item["rating"]
        row.review_count = item["review_count"]
        row.query_radius_m = settings.BENCHMARK_PEER_RADIUS_METERS
        row.query_category = category
        row.fetched_at = now
        # Keep every cycle: this is the only source of the delta and velocity
        # facts the benchmark now renders.
        db.add(CompetitorSnapshotHistory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            place_id=item["place_id"],
            name=item["name"],
            category=item["category"],
            address=item["address"],
            rating=item["rating"],
            review_count=item["review_count"],
            source="google_places",
            query_radius_m=settings.BENCHMARK_PEER_RADIUS_METERS,
            query_category=category,
            fetched_at=now,
        ))
    if existing:
        stale_ids = [pid for pid in existing if pid not in seen]
        if stale_ids:
            await db.execute(
                delete(CompetitorSnapshot).where(
                    CompetitorSnapshot.user_id == user_id,
                    CompetitorSnapshot.source == "google_places",
                    CompetitorSnapshot.place_id.in_(stale_ids),
                )
            )
    await db.commit()
    return {"configured": True, "inserted": len(found), "reason": None}


async def get_external_peer_set(db: AsyncSession, user_id: str) -> dict:
    """Read the stored external peer set with provenance, medians and deltas."""
    if not places_configured():
        return {"configured": False, "available": False, "count": 0, "peers": []}

    rows = (
        await db.execute(
            select(CompetitorSnapshot)
            .where(
                CompetitorSnapshot.user_id == user_id,
                CompetitorSnapshot.source == "google_places",
            )
            .order_by(CompetitorSnapshot.rating.desc().nullslast(), CompetitorSnapshot.review_count.desc())
        )
    ).scalars().all()
    if not rows:
        return {"configured": True, "available": False, "count": 0, "peers": []}

    fetched_at = max((r.fetched_at for r in rows if r.fetched_at is not None), default=None)
    stale = False
    if fetched_at is not None:
        stamp = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
        stale = datetime.now(timezone.utc) - stamp > timedelta(hours=settings.BENCHMARK_SNAPSHOT_TTL_HOURS)

    ratings = [r.rating for r in rows if r.rating is not None]
    reviews = [r.review_count for r in rows]

    # Deltas are computed against the last capture at/older than the 30-day
    # window (or the earliest capture when the history is younger). This is
    # why the history table exists: the snapshot row was overwritten each
    # refresh and the before-value was lost.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DELTA_WINDOW_DAYS)
    history = (
        await db.execute(
            select(CompetitorSnapshotHistory)
            .where(
                CompetitorSnapshotHistory.user_id == user_id,
                CompetitorSnapshotHistory.source == "google_places",
            )
            .order_by(CompetitorSnapshotHistory.fetched_at.desc())
            .limit(HISTORY_QUERY_LIMIT)
        )
    ).scalars().all()
    series: dict[str, list[CompetitorSnapshotHistory]] = {}
    for row in history:
        series.setdefault(row.place_id, []).append(row)

    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    peer_deltas: list[dict] = []
    rating_deltas: list[float] = []
    review_deltas: list[int] = []
    velocities: list[float] = []
    for r in rows[:20]:
        points = series.get(r.place_id) or []
        baseline = None
        for point in points:
            stamp = _aware(point.fetched_at)
            if stamp is None or stamp > cutoff:
                continue
            if baseline is None or stamp > (_aware(baseline.fetched_at) or cutoff):
                baseline = point
        if baseline is None and points:
            baseline = min(points, key=lambda p: _aware(p.fetched_at) or now)
        base_at = _aware(baseline.fetched_at) if baseline is not None else None
        current_at = _aware(r.fetched_at) or now
        days = max(1, int((current_at - base_at).days)) if base_at else None
        rating_delta = None
        if baseline is not None and r.rating is not None and baseline.rating is not None:
            rating_delta = round(r.rating - baseline.rating, 2)
            rating_deltas.append(rating_delta)
        review_delta = None
        velocity = None
        if baseline is not None:
            review_delta = int(r.review_count - baseline.review_count)
            review_deltas.append(review_delta)
            if days:
                velocity = round(review_delta * 30 / days, 1)
                velocities.append(velocity)
        peer_deltas.append({
            "place_id": r.place_id,
            "name": r.name,
            "category": r.category,
            "rating": r.rating,
            "review_count": r.review_count,
            "rating_delta": rating_delta,
            "reviews_delta": review_delta,
            "velocity_per_month": velocity,
            "baseline_at": base_at,
            "baseline_days": days,
        })

    return {
        "configured": True,
        "available": len(rows) >= 3,
        "count": len(rows),
        "source": "google_places",
        "radius_m": rows[0].query_radius_m,
        "category": rows[0].query_category,
        "fetched_at": fetched_at,
        "stale": stale,
        "median_rating": round(_median(ratings), 2) if ratings else None,
        "median_reviews": int(_median([float(v) for v in reviews]) or 0) if reviews else None,
        "delta_window_days": DELTA_WINDOW_DAYS,
        "median_rating_delta": round(_median(rating_deltas), 2) if rating_deltas else None,
        "median_reviews_delta": int(_median([float(v) for v in review_deltas]) or 0) if review_deltas else None,
        "median_velocity_per_month": round(_median(velocities), 1) if velocities else None,
        "peers": peer_deltas,
    }
