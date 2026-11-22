"""Google Places (New) client for benchmark search and details.

Server-side key only (`GOOGLE_PLACES_API_KEY`), field-masked to what the UI
renders. Every provider failure is logged with context and returned as a
generic error — raw response bodies never reach a client.
"""
from __future__ import annotations

import json
import logging

import httpx

from ...config import settings
from ..redis.service import cache_get, cache_set
from . import outscraper

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL_SECONDS = 600
DETAILS_CACHE_TTL_SECONDS = 1800


async def _cache_get_json(key: str) -> dict | list | None:
    try:
        raw = await cache_get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def _cache_set_json(key: str, value: dict | list, ttl: int) -> None:
    try:
        await cache_set(key, json.dumps(value, separators=(",", ":"), default=str), ttl=ttl)
    except Exception:
        logger.debug("Benchmark cache write failed for %s", key, exc_info=True)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
MAX_SEARCH_RESULTS = 20
# Hard cost cap: never pull/return more than 10 reviews per place.
MAX_REVIEWS = 10
MAX_PHOTOS = 30
REQUEST_TIMEOUT_SECONDS = 15.0

SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.rating,places.userRatingCount,places.types,places.location"
)
DETAILS_FIELD_MASK = (
    "id,displayName,formattedAddress,rating,userRatingCount,"
    "reviews,photos,types,location"
)


class PlacesError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def _key() -> str:
    key = (settings.GOOGLE_PLACES_API_KEY or "").strip()
    if not key:
        raise PlacesError("Place search is not configured", 503)
    return key


def _place_id(raw: str) -> str:
    return str(raw or "").removeprefix("places/")[:255]


def _text(value: object) -> str | None:
    if isinstance(value, dict):
        text = value.get("text")
        return str(text)[:255] if text else None
    return str(value)[:255] if value else None


def _coordinates(place: dict) -> tuple[float | None, float | None]:
    location = place.get("location") or {}
    if not isinstance(location, dict):
        return None, None
    lat, lng = location.get("latitude"), location.get("longitude")
    try:
        return (float(lat) if lat is not None else None,
                float(lng) if lng is not None else None)
    except (TypeError, ValueError):
        return None, None


def _map_search(place: dict) -> dict:
    lat, lng = _coordinates(place)
    return {
        "place_id": _place_id(str(place.get("id") or "")),
        "name": _text(place.get("displayName")),
        "address": str(place.get("formattedAddress") or "")[:500] or None,
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "latitude": lat,
        "longitude": lng,
        "types": [str(t) for t in (place.get("types") or [])][:10],
    }


def _map_details(place: dict, *, reviews_limit: int = MAX_REVIEWS) -> dict:
    base = _map_search(place)
    reviews = []
    limit = max(1, min(int(reviews_limit), MAX_REVIEWS))
    for review in (place.get("reviews") or [])[:limit]:
        if not isinstance(review, dict):
            continue
        text_value = review.get("text")
        if isinstance(text_value, dict):
            text_value = text_value.get("text")
        attribution = review.get("authorAttribution") or {}
        if isinstance(attribution, dict):
            author_name = _text(attribution.get("displayName"))
            author_photo = str(attribution.get("photoUri") or "")[:1024] or None
        else:
            author_name = _text(attribution)
            author_photo = None
        reviews.append({
            "rating": review.get("rating"),
            "text": str(text_value or "")[:4000],
            "publish_time": review.get("publishTime"),
            "author": author_name,
            "author_photo": author_photo,
        })
    photos = []
    for photo in (place.get("photos") or [])[:MAX_PHOTOS]:
        if isinstance(photo, dict) and photo.get("name"):
            photos.append({
                "name": str(photo["name"])[:255],
                "width": photo.get("widthPx"),
                "height": photo.get("heightPx"),
            })
    return {**base, "reviews": reviews, "photos": photos}


async def search_places(
    query: str, *, language: str = "en", region: str = "SA"
) -> list[dict]:
    """Free-text business search, bounded to 20 results."""
    text = str(query or "").strip()[:255]
    if not text:
        return []
    cache_key = f"bm:search:{outscraper.configured()}:{language or 'en'}:{region or 'SA'}:{text.lower()}"
    cached = await _cache_get_json(cache_key)
    if isinstance(cached, list):
        return cached

    if outscraper.configured():
        try:
            result = await outscraper.search_places(text, limit=MAX_SEARCH_RESULTS)
        except outscraper.OutscraperError as exc:
            raise PlacesError(str(exc), exc.status_code) from exc
        await _cache_set_json(cache_key, result, SEARCH_CACHE_TTL_SECONDS)
        return result

    key = _key()
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": SEARCH_FIELD_MASK}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                PLACES_TEXT_SEARCH_URL,
                headers=headers,
                json={
                    "textQuery": text,
                    "languageCode": language or "en",
                    "regionCode": region or "SA",
                    "maxResultCount": MAX_SEARCH_RESULTS,
                },
            )
    except httpx.HTTPError as exc:
        logger.error("Places search transport failed: %s", type(exc).__name__, exc_info=True)
        raise PlacesError("Place search is temporarily unavailable") from exc
    if resp.status_code != 200:
        logger.error("Places search failed status=%s", resp.status_code)
        raise PlacesError("Place search is temporarily unavailable", resp.status_code)
    try:
        places = (resp.json() or {}).get("places") or []
    except ValueError:
        logger.error("Places search returned invalid JSON")
        raise PlacesError("Place search returned an invalid response")
    result = [_map_search(p) for p in places[:MAX_SEARCH_RESULTS] if isinstance(p, dict)]
    await _cache_set_json(cache_key, result, SEARCH_CACHE_TTL_SECONDS)
    return result


async def get_place(
    place_id: str, *, language: str = "en", reviews_limit: int = 10, start: int | None = None, cutoff: int | None = None
) -> dict:
    """Details for one place."""
    pid = _place_id(place_id)
    if not pid:
        raise PlacesError("Unknown place")
    reviews_limit = max(1, min(int(reviews_limit), 10))
    cache_key = f"bm:place:{outscraper.configured()}:{language or 'en'}:{pid}:{reviews_limit}:{start or 0}:{cutoff or 0}"
    cached = await _cache_get_json(cache_key)
    if isinstance(cached, dict) and cached.get("place_id"):
        return cached

    if outscraper.configured():
        try:
            result = await outscraper.get_place(pid, reviews_limit=reviews_limit, start=start, cutoff=cutoff)
        except outscraper.OutscraperError as exc:
            raise PlacesError(str(exc), exc.status_code) from exc
        await _cache_set_json(cache_key, result, DETAILS_CACHE_TTL_SECONDS)
        return result

    key = _key()
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": DETAILS_FIELD_MASK}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                PLACES_DETAILS_URL.format(place_id=pid),
                headers=headers,
                params={"languageCode": language or "en"},
            )
    except httpx.HTTPError as exc:
        logger.error("Places details transport failed: %s", type(exc).__name__, exc_info=True)
        raise PlacesError("Place details are temporarily unavailable") from exc
    if resp.status_code != 200:
        logger.error("Places details failed status=%s", resp.status_code)
        raise PlacesError("Place details are temporarily unavailable", resp.status_code)
    try:
        result = _map_details(resp.json() or {}, reviews_limit=reviews_limit)
    except ValueError:
        raise PlacesError("Place details returned an invalid response")
    await _cache_set_json(cache_key, result, DETAILS_CACHE_TTL_SECONDS)
    return result
