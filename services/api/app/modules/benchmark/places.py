"""Google Places (New) client for benchmark search and details.

Server-side key only (`GOOGLE_PLACES_API_KEY`), field-masked to what the UI
renders. Every provider failure is logged with context and returned as a
generic error — raw response bodies never reach a client.
"""
from __future__ import annotations

import logging

import httpx

from ...config import settings
from . import outscraper

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
MAX_SEARCH_RESULTS = 20
MAX_REVIEWS = 500
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


def _map_details(place: dict) -> dict:
    base = _map_search(place)
    reviews = []
    for review in (place.get("reviews") or [])[:MAX_REVIEWS]:
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
    if outscraper.configured():
        try:
            return await outscraper.search_places(text, limit=MAX_SEARCH_RESULTS)
        except outscraper.OutscraperError as exc:
            raise PlacesError(str(exc), exc.status_code) from exc
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
    return [_map_search(p) for p in places[:MAX_SEARCH_RESULTS] if isinstance(p, dict)]


async def get_place(place_id: str, *, language: str = "en") -> dict:
    """Details for one place."""
    pid = _place_id(place_id)
    if not pid:
        raise PlacesError("Unknown place")
    if outscraper.configured():
        try:
            return await outscraper.get_place(pid)
        except outscraper.OutscraperError as exc:
            raise PlacesError(str(exc), exc.status_code) from exc
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
        return _map_details(resp.json() or {})
    except ValueError:
        raise PlacesError("Place details returned an invalid response")
