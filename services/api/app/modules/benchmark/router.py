"""Benchmark API: search Places and manage the tenant's saved bench."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..redis.service import cache_get, cache_set
from ..team.context import TenantContext, require_perm, tenant_id_of
from . import ai, boq, compare, mapsearch, outscraper, places, service, theme_service
from .summary import distribution as metric_distribution, north_star

router = APIRouter(prefix="/api/v1/benchmark", tags=["benchmark"])

MAX_COMPARE_SUBJECTS = 6
# AI summaries are stable over slowly-moving numbers; 10 min also rate-limits
# the one paid LLM call per comparison set without an extra throttle layer.
AI_SUMMARY_CACHE_TTL = 600
# A synchronous refresh after Save stays short: ~100 reviews is enough to make
# the card ready immediately; the worker deepens the 30-day set later.
REFRESH_REVIEWS_LIMIT = 100
# Search results are stable for a few minutes; cache misses make a slow first
# attempt look like "no matches" on retry.
SEARCH_CACHE_TTL_SECONDS = 300


class SavePlaceIn(BaseModel):
    place_id: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    # Canonical Google Maps URL from mapsearch or Places. It carries the
    # feature id the free place-detail and review endpoints key on.
    maps_url: str | None = Field(default=None, max_length=1024)
    # Google-hosted photo for the saved card. Validated in service.save_place.
    thumbnail: str | None = Field(default=None, max_length=1024)


def _norm(s: str | None) -> str:
    return " ".join(str(s or "").lower().split())


# Google's public endpoint accepts a two-letter market code. A full country name
# in metadata is still useful for filtering, but it is not a valid ``gl`` value.
def _country_code(value: str | None) -> str | None:
    value = str(value or "").strip().upper()
    return value.lower() if len(value) == 2 and value.isalpha() else None


def _country_aliases(loc: dict) -> set[str]:
    """Names a Google address may use for the tenant's country."""
    aliases: set[str] = set()
    raw_country = str(loc.get("country") or "").strip()
    if raw_country:
        aliases.add(_norm(raw_country))
    code = _country_code(loc.get("country_code") or raw_country)
    if code:
        try:
            from babel import Locale

            name = Locale("en").territories.get(code.upper())
            if name:
                aliases.add(_norm(name))
        except Exception:  # pragma: no cover - babel is a declared dependency
            pass
    # Two-letter codes are market parameters, not address text. Matching them
    # by substring made "SA" claim "Sandton" and "South Africa".
    return {alias for alias in aliases if len(alias) > 2}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _country_names() -> set[str]:
    """Normalized English country names used to read an address' last token."""
    try:
        from babel import Locale

        return {
            _norm(name)
            for name in Locale("en").territories.values()
            if isinstance(name, str) and name
        }
    except Exception:  # pragma: no cover - babel is a declared dependency
        return set()


def _address_country(address: str | None) -> str | None:
    names = _country_names()
    if not names:
        return None
    for part in reversed(str(address or "").split(",")):
        candidate = _norm(part)
        if candidate in names:
            return candidate
    return None


# A business is "nearby" only when it is genuinely in the tenant's market. A
# two-letter country code is never compared by substring: "SA" must not match
# "Sandton" or "South Africa".
NEARBY_RADIUS_KM = 50.0


def _is_nearby(place: dict, loc: dict) -> bool:
    addr = _norm(place.get("address"))
    city = _norm(loc.get("city"))
    if city and city in addr:
        return True

    place_lat = place.get("latitude")
    place_lng = place.get("longitude")
    loc_lat = loc.get("latitude")
    loc_lng = loc.get("longitude")
    try:
        if None not in (place_lat, place_lng, loc_lat, loc_lng):
            return _haversine_km(float(loc_lat), float(loc_lng), float(place_lat), float(place_lng)) <= NEARBY_RADIUS_KM
    except (TypeError, ValueError):
        pass

    country_aliases = _country_aliases(loc)
    place_country = _address_country(addr)
    if place_country:
        return place_country in country_aliases
    # Google often omits the country from local addresses. The provider request
    # is already localized with gl=<country> and the country in the query, so a
    # result without an explicit foreign country belongs to that market.
    if country_aliases:
        return True
    # With no market context at all, every result is effectively "other".
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
    has_explicit_location = "," in raw_q or " in " in raw_q.lower() or " near " in raw_q.lower()
    # An explicit location in the query wins: do not re-bias it to the tenant's
    # home market or label those results with the wrong country.
    if has_explicit_location:
        loc = {}
    search_q = raw_q
    loc_hint = ", ".join([p for p in [loc.get("city"), loc.get("country")] if p])
    if loc_hint and not has_explicit_location and loc_hint.lower() not in raw_q.lower():
        search_q = f"{raw_q}, {loc_hint}"

    config = await service.get_config(db)
    # The free map-search RPC does the listings-only job in one request. Places
    # is used only when explicitly configured; otherwise search never depends
    # on a browser, a sidecar, or a paid key.
    use_places = bool(places.configured()) and config.source == "google_places"
    provider_name = "places" if use_places else "mapsearch"

    # Cache results: a repeat query — or a retry after the client gave up on a
    # slow first attempt — is served instantly instead of paying for a second
    # scrape. Keyed on the resolved (location-biased) query, provider and limit.
    location_signature = "|".join(
        str(loc.get(key) or "") for key in ("city", "country", "country_code", "latitude", "longitude")
    )
    cache_key = f"bm:search:{provider_name}:{limit}:{search_q.lower()}:{location_signature.lower()}"
    cached = None
    try:
        raw_cached = await cache_get(cache_key)
        if raw_cached:
            cached = json.loads(raw_cached)
    except Exception:
        cached = None
    if isinstance(cached, dict) and ("nearby" in cached or "other" in cached):
        return {**cached, "query": raw_q}

    if use_places:
        try:
            results = await places.search_places(search_q)
        except places.PlacesError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
    else:
        try:
            results = await mapsearch.search_places(
                search_q,
                limit=limit,
                latitude=loc.get("latitude"),
                longitude=loc.get("longitude"),
                country_code=loc.get("country_code"),
            )
        except mapsearch.MapSearchError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail="Search is temporarily unavailable."
            )

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

    # If we have no location context, or the user named a location, keep the
    # results together instead of inventing a Nearby/Other split.
    if not loc_hint or has_explicit_location:
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


class ThemeSubjectsIn(BaseModel):
    subjects: list[SubjectKey] = Field(min_length=1, max_length=MAX_COMPARE_SUBJECTS)
    main: SubjectKey | None = None


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


@router.get("/themes", response_model=dict)
async def benchmark_themes(
    subjects: list[SubjectKey] = Query(..., min_length=1, max_length=MAX_COMPARE_SUBJECTS),
    main: SubjectKey | None = Query(None),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Read cached theme results and durably enqueue missing/stale samples.

    This endpoint never calls an LLM. Workers do the paid work, so a page load
    can only create one bounded job per subject and remains safe without workers.
    """
    try:
        return await theme_service.theme_response(
            db, tenant_id_of(ctx.user), subjects, main_key=main
        )
    except compare.CompareError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/themes/retry", response_model=dict)
async def retry_benchmark_themes(
    body: ThemeSubjectsIn,
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Retry failed/stale analyses, bounded by the service cooldown."""
    try:
        return await theme_service.theme_response(
            db, tenant_id_of(ctx.user), body.subjects, retry=True, main_key=body.main
        )
    except compare.CompareError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
            maps_url=body.maps_url, thumbnail=body.thumbnail,
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
    """Fetch one place now so its card is ready without waiting for the worker.

    The free provider gets a bounded 100-review sample here; the scheduled
    collector later fills the full 30-day set (up to 500 reviews).
    """
    import time as _time

    saved = await service.get_saved(db, tenant_id_of(ctx.user), place_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved place not found")
    config = await service.get_config(db)
    # Release the read transaction before the network call. A paged scrape must
    # never leave an idle Postgres connection open.
    await db.commit()
    source = str(config.source or "").strip()
    if source not in compare.CACHE_ONLY_SOURCES and not compare.can_fetch_live(source):
        source = "boq"
    now_ts = int(_time.time())
    cutoff_ts = now_ts - 7 * 24 * 3600
    try:
        details = await compare._provider_details(
            source, saved.place_id,
            reviews_limit=REFRESH_REVIEWS_LIMIT, maps_url=saved.maps_url, cutoff=cutoff_ts,
        )
    except (places.PlacesError, boq.BoqError, outscraper.OutscraperError) as exc:
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
    # Cache-only for the free provider (paging is not a page-load operation),
    # and for any paid provider whose credentials are absent. This keeps saved
    # details at 200 on staging instead of returning a dead 503.
    if not compare.can_fetch_live(config.source):
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
            "source": config.source,
        }
        return {**details, "saved_id": saved.id, "label": saved.label}
    await db.commit()
    now_ts = int(_time.time())
    cutoff_ts = now_ts - 7 * 24 * 3600
    try:
        details = await compare._provider_details(
            config.source, saved.place_id,
            reviews_limit=10, maps_url=saved.maps_url, cutoff=cutoff_ts,
        )
    except (places.PlacesError, boq.BoqError, outscraper.OutscraperError) as exc:
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
