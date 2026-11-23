"""Benchmark API: search Places and manage the tenant's saved bench."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..redis.service import cache_get, cache_set
from ..team.context import TenantContext, require_perm, tenant_id_of
from . import ai, compare, gosom, outscraper, places, service
from .summary import distribution as metric_distribution, north_star

router = APIRouter(prefix="/api/v1/benchmark", tags=["benchmark"])

MAX_COMPARE_SUBJECTS = 6
# AI summaries are stable over slowly-moving numbers; 10 min also rate-limits
# the one paid LLM call per comparison set without an extra throttle layer.
AI_SUMMARY_CACHE_TTL = 600


class SavePlaceIn(BaseModel):
    place_id: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    # Canonical Google Maps URL from the search result (gosom) or Places
    # details. Used as the scrape target so gosom hits the exact listing.
    maps_url: str | None = Field(default=None, max_length=1024)


def _norm(s: str | None) -> str:
    return " ".join(str(s or "").lower().split())


def _is_nearby(place: dict, loc: dict) -> bool:
    addr = _norm(place.get("address"))
    city = _norm(loc.get("city"))
    country = _norm(loc.get("country"))
    if city and city in addr:
        return True
    if country and country in addr:
        # Same country counts as nearby-ish when we have no city; city match is stronger.
        return bool(city) or True
    return False


def _popularity(place: dict) -> tuple:
    rating = place.get("rating") or 0
    reviews = place.get("review_count") or 0
    return (int(reviews), float(rating))


@router.get("/search", response_model=dict)
async def search_places(
    q: str = Query(..., min_length=2, max_length=255),
    limit: int = Query(20, ge=1, le=20),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Search businesses for benchmarking. Nearby results first, then others."""
    tenant_id = tenant_id_of(ctx.user)
    loc = await service.tenant_location_context(db, tenant_id)
    raw_q = str(q or "").strip()[:255]
    search_q = raw_q
    loc_hint = ", ".join([p for p in [loc.get("city"), loc.get("country")] if p])
    # Bias keyword/category searches to the tenant location, but don't fight an
    # explicit location the user already typed.
    has_explicit_location = "," in raw_q or " in " in raw_q.lower() or " near " in raw_q.lower()
    if loc_hint and not has_explicit_location and loc_hint.lower() not in raw_q.lower():
        search_q = f"{raw_q}, {loc_hint}"

    config = await service.get_config(db)
    use_gosom = config.source == "gosom" or not places.configured()

    # gosom search drives a real browser (~60s), so cache results: a repeat
    # query — or a retry after the client gave up on a slow first attempt — is
    # served instantly instead of paying for a second scrape. Keyed on the
    # resolved (location-biased) query, provider and limit.
    cache_key = (
        "bm:search:" + ("gosom" if use_gosom else "places")
        + f":{limit}:{search_q.lower()}"
    )
    cached = None
    try:
        raw_cached = await cache_get(cache_key)
        if raw_cached:
            cached = json.loads(raw_cached)
    except Exception:
        cached = None
    if isinstance(cached, dict) and ("nearby" in cached or "other" in cached):
        return {**cached, "query": raw_q}

    if use_gosom:
        if not gosom.configured():
            raise HTTPException(status_code=503, detail="Search is not configured.")
        try:
            results = await gosom.search_places(search_q, limit=limit)
        except gosom.GosomError as exc:
            raise HTTPException(status_code=exc.status_code, detail="Search is temporarily unavailable.")
    else:
        try:
            results = await places.search_places(search_q)
        except places.PlacesError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    # De-dupe by place_id preserving order.
    seen = set()
    deduped = []
    for p in results:
        pid = str(p.get("place_id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        deduped.append(p)

    nearby, other = [], []
    for p in deduped:
        (nearby if _is_nearby(p, loc) else other).append(p)

    # If we have no location context, treat all as nearby to avoid a confusing split.
    if not loc_hint:
        nearby, other = deduped, []

    nearby.sort(key=_popularity, reverse=True)
    other.sort(key=_popularity, reverse=True)
    nearby = nearby[: max(1, min(limit, 20))]
    remaining = max(0, min(limit, 20) - len(nearby))
    other = other[:remaining]
    payload = {
        "query": raw_q,
        "location": {"city": loc.get("city"), "country": loc.get("country")},
        "nearby": nearby,
        "other": other,
    }
    # Only cache non-empty results: a transient empty (Google throttled the
    # anonymous scrape) must not stick for the whole TTL and look like "no
    # matches" on the next attempt.
    if nearby or other:
        try:
            await cache_set(cache_key, json.dumps(payload, default=str), ttl=SEARCH_CACHE_TTL_SECONDS)
        except Exception:
            pass
    return payload


@router.get("/heatmap", response_model=dict)
async def get_heatmap(
    weeks: int = Query(12, ge=1, le=52),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    return await service.heatmap_matrix(db, tenant_id_of(ctx.user), weeks=weeks)


@router.get("/compare", response_model=dict)
async def compare_places(
    subjects: list[str] = Query(..., min_length=1, max_length=MAX_COMPARE_SUBJECTS),
    period: Literal["live", "30d", "90d", "365d"] = Query("live", alias="range"),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Normalized facts for up to six comparison subjects.

    A subject is ``saved:<place_id>`` (a place on this tenant's bench) or
    ``own:<channel_id>`` (one of the tenant's Google locations). Each side is
    scoped to the tenant; an inaccessible side comes back as an unavailable
    record rather than failing the whole request.

    ``range`` selects the period table: ``live`` leaves the period facts null,
    the others ask for a window that saved places compute from snapshot history
    and own locations compute from their review and performance rows.
    """
    tenant_id = tenant_id_of(ctx.user)
    key = "bm:compare:" + hashlib.sha1(
        json.dumps({"t": tenant_id, "s": sorted(subjects), "r": period}, sort_keys=True).encode()
    ).hexdigest()
    try:
        cached = await cache_get(key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    days = compare.RANGES[period]
    subject_records = await compare.compare_subjects(
        db, tenant_id, subjects, days=days
    )
    # Query params may carry stray spaces; match own keys on the stripped form.
    own_keys = [s.strip() for s in subjects if s.strip().startswith("own:")]
    payload = {
        "range": period,
        "days": days,
        "subjects": subject_records,
        "distribution": metric_distribution(subject_records),
        "summary": north_star(subject_records, own_keys),
    }
    try:
        await cache_set(key, json.dumps(payload, default=str), ttl=60)
    except Exception:
        pass
    return payload


# One subject key ("own:<channel_id>" / "saved:<place_id>"): bounded per item
# so an oversized string cannot ride in as a cache-key or LLM-payload
# amplifier; the list itself stays 1–6 via the model below.
SubjectKey = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class AiSummaryIn(BaseModel):
    subjects: list[SubjectKey] = Field(min_length=1, max_length=MAX_COMPARE_SUBJECTS)


@router.post("/ai-summary", response_model=dict)
async def post_ai_summary(
    body: AiSummaryIn,
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """One-to-two sentence takeaway over the comparison numbers.

    Subjects parse exactly like ``/compare`` (saved:<place_id> / own:<channel_id>,
    max 6); unknown sides come back through ``compare_subjects`` as unavailable
    records instead of failing the request. The LLM only ever sees the numeric
    aggregate (rank, gaps, distribution), never review text.

    Fail-open by design: any LLM failure, timeout or missing model returns the
    rule-based template with HTTP 200 and ``source: "template"`` — the compare
    page always has a summary, so a broken provider must not surface as 5xx.
    Cached 10 min per tenant + subject set, which doubles as the cost cap.
    """
    tenant_id = tenant_id_of(ctx.user)
    key = "bm:ai-summary:" + tenant_id + ":" + hashlib.sha1(
        json.dumps(sorted(body.subjects)).encode()
    ).hexdigest()
    try:
        cached = await cache_get(key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    result = await ai.ai_summary(db, tenant_id, body.subjects)
    try:
        await cache_set(key, json.dumps(result), ttl=AI_SUMMARY_CACHE_TTL)
    except Exception:
        pass
    return result


@router.get("/history", response_model=dict)
async def benchmark_history(
    subjects: list[str] = Query(..., min_length=1, max_length=MAX_COMPARE_SUBJECTS),
    days: int = Query(90, ge=1, le=3650),
    points: int = Query(12, ge=2, le=compare.MAX_HISTORY_POINTS),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Dated history behind the period filter.

    Saved places return their scraped snapshots; own locations return cumulative
    review counts and average ratings sampled across the window. Each series is
    bounded to `points` rows and always tenant-scoped.
    """
    return await compare.subject_history(
        db, tenant_id_of(ctx.user), subjects, days=days, points=points
    )


@router.get("/reviews", response_model=dict)
async def benchmark_reviews(
    subjects: list[str] = Query(..., min_length=1, max_length=MAX_COMPARE_SUBJECTS),
    limit: int = Query(10, ge=1, le=50),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Newest review samples per subject, for the paginated reviews table.

    Saved places return their cached review sample (up to 50 rows); own
    locations return their newest `ReviewInsight` rows, newest first.
    """
    return await compare.reviews_for(
        db, tenant_id_of(ctx.user), subjects, limit=limit
    )


@router.get("/places", response_model=list[dict])
async def list_saved(
    limit: int = Query(50, ge=1, le=100),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_saved(db, tenant_id_of(ctx.user), limit=limit)


@router.post("/places", response_model=dict, status_code=201)
async def save_place(
    body: SavePlaceIn,
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    import time as _time
    try:
        row = await service.save_place(
            db, tenant_id_of(ctx.user),
            place_id=body.place_id, label=body.label, notes=body.notes,
            latitude=body.latitude, longitude=body.longitude,
            rating=body.rating, review_count=body.review_count,
            maps_url=body.maps_url,
        )
    except service.BenchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return service.serialize(row)


@router.post("/places/{place_id}/heatmap", response_model=dict)
async def set_heatmap(
    place_id: str,
    enabled: bool | None = Query(default=None),
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await service.toggle_heatmap(
        db, tenant_id_of(ctx.user), place_id, enabled=enabled
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Saved place not found")
    return service.serialize(row)


@router.post("/places/{place_id}/bench-set", response_model=dict)
async def set_bench_set(
    place_id: str,
    enabled: bool | None = Query(default=None),
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await service.set_bench_set(
            db, tenant_id_of(ctx.user), place_id, enabled=enabled
        )
    except service.BenchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.BenchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.serialize(row)


@router.post("/places/{place_id}/refresh", response_model=dict)
async def refresh_place(
    place_id: str,
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Fetch last-week details for one saved place (cost-capped, 10 reviews max)."""
    import time as _time

    saved = await service.get_saved(db, tenant_id_of(ctx.user), place_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved place not found")
    config = await service.get_config(db)
    now_ts = int(_time.time())
    cutoff_ts = now_ts - 7 * 24 * 3600
    try:
        details = await compare._provider_details(
            config.source, saved.place_id,
            reviews_limit=10, maps_url=saved.maps_url, cutoff=cutoff_ts,
        )
    except (places.PlacesError, gosom.GosomError, outscraper.OutscraperError) as exc:
        saved.last_scrape_error = str(exc)[:500]
        await db.commit()
        await db.refresh(saved)
        raise HTTPException(
            status_code=getattr(exc, "status_code", 502), detail=str(exc)
        )
    await service.store_place_details(db, saved, details, append_snapshot=True)
    await db.refresh(saved)
    return service.serialize(saved)


@router.get("/places/{place_id}/details", response_model=dict)
async def place_details(
    place_id: str,
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Live details for a place on this tenant's bench (for the heatmap modal).

    The saved row is checked first: a place nobody on this tenant saved cannot
    be used as a free Places lookup proxy.
    """
    import time as _time

    saved = await service.get_saved(db, tenant_id_of(ctx.user), place_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved place not found")
    config = await service.get_config(db)
    # gosom scraping drives a real browser (~60s+) and must NEVER run inside an
    # HTTP read handler: it held the request 120s+ and killed the DB session on
    # close. For gosom, serve the cached row the worker / explicit refresh
    # filled. Places/outscraper keep their live path (fast).
    if config.source == "gosom":
        details = {
            "place_id": saved.place_id,
            "name": saved.name,
            "address": saved.address,
            "types": saved.types,
            "rating": saved.rating,
            "review_count": saved.review_count,
            "reviews": saved.reviews or [],
            "photos": saved.photos or [],
            "thumbnail": saved.thumbnail,
            "source": "gosom",
        }
        return {**details, "saved_id": saved.id, "label": saved.label}
    now_ts = int(_time.time())
    cutoff_ts = now_ts - 7 * 24 * 3600
    try:
        details = await compare._provider_details(
            config.source, saved.place_id,
            reviews_limit=10, maps_url=saved.maps_url, cutoff=cutoff_ts,
        )
    except (places.PlacesError, gosom.GosomError, outscraper.OutscraperError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 502), detail=str(exc)
        )
    return {**details, "saved_id": saved.id, "label": saved.label}


@router.delete("/places/{place_id}", response_model=dict)
async def delete_saved(
    place_id: str,
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    removed = await service.delete_saved(db, tenant_id_of(ctx.user), place_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Saved place not found")
    return {"deleted": True, "place_id": place_id}


@router.get("/config", response_model=dict)
async def get_config(
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    config = await service.get_config(db)
    return {
        "place_cache_enabled": config.place_cache_enabled,
        "retention_days": config.retention_days,
        "refresh_hours": config.refresh_hours,
        "max_saved_places": config.max_saved_places,
        "source": config.source,
    }
