"""Resolve free-text service areas to Google Place IDs.

The Business Information API accepts service areas only as place IDs (a
region type such as a city, postal code or administrative area), never as
free text. Places API (New) Text Search is the bridge: the merchant types
"Al Malqa, Riyadh", we resolve it to the Google place that represents that
region, then patch `serviceArea.places.placeInfos`.

The key is server-side only (`GOOGLE_PLACES_API_KEY`) and never returned to a
client. A missing key or an unresolved name degrades to a skipped section,
consistent with every other best-effort profile push.
"""
from __future__ import annotations

import logging

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Google accepts region-like places for a service area, not arbitrary
# businesses (a restaurant cannot be "served"). These are the place types the
# Business Profile docs accept for service areas.
SERVICE_AREA_TYPES = frozenset({
    "country",
    "administrative_area_level_1",
    "administrative_area_level_2",
    "administrative_area_level_3",
    "locality",
    "sublocality",
    "sublocality_level_1",
    "postal_code",
    "neighborhood",
})
# Google caps placeInfos at 20; keep the request bounded.
MAX_SERVICE_AREAS = 20
REQUEST_TIMEOUT_SECONDS = 15.0


class PlacesError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def _display_name(place: dict, fallback: str) -> str:
    display = place.get("displayName") or {}
    if isinstance(display, dict):
        text = display.get("text")
        if text:
            return str(text)[:255]
    address = place.get("formattedAddress")
    return str(address or fallback)[:255]


def _region_place(places: list[dict]) -> dict | None:
    """First result whose types describe a region we may serve."""
    for place in places:
        types = {str(t) for t in place.get("types", []) or []}
        if types & SERVICE_AREA_TYPES and place.get("id"):
            return place
    return None


async def resolve_service_area(
    names: list[str], *, language_code: str = "en", region_code: str = "SA"
) -> list[dict]:
    """Resolve each name to `{placeId, placeName}` for locations.patch.

    Raises PlacesError when the key is missing; unresolved individual names
    are returned in the caller's skipped report instead of failing the whole
    save.
    """
    key = (settings.GOOGLE_PLACES_API_KEY or "").strip()
    if not key:
        raise PlacesError("GOOGLE_PLACES_API_KEY not configured", 503)

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            cleaned.append(name[:255])
        if len(cleaned) >= MAX_SERVICE_AREAS:
            break
    if not cleaned:
        return []

    out: list[dict] = []
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.types",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for name in cleaned:
            try:
                resp = await client.post(
                    PLACES_TEXT_SEARCH_URL,
                    headers=headers,
                    json={
                        "textQuery": name,
                        "languageCode": language_code or "en",
                        "regionCode": region_code or "SA",
                        "maxResultCount": 5,
                    },
                )
            except httpx.HTTPError as e:
                raise PlacesError(f"Places Text Search transport failed: {e}") from e
            if resp.status_code != 200:
                raise PlacesError(
                    f"Places Text Search failed ({resp.status_code}): {resp.text[:200]}",
                    resp.status_code,
                )
            place = _region_place((resp.json() or {}).get("places", []) or [])
            if place is None:
                logger.warning("Service area %r did not resolve to a region place", name)
                continue
            place_id = str(place["id"]).removeprefix("places/")
            out.append({
                "placeId": place_id,
                "placeName": _display_name(place, name),
            })
    return out
