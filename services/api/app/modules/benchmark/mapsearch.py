"""Free Google Maps place search via the public ``tbm=map`` endpoint.

Calls the same map-search RPC the Maps UI uses, gets structured JSON in one
HTTP GET, and needs no browser, API key, login or payment. Place facts are
refreshed by ``placedetail`` and review history by ``boq``.

The response is XSSI-guarded JSON. Results live at ``data[0][1]``; each entry's
place array is at ``entry[14]`` and carries the fields we need at fixed slots:
``[10]`` feature id, ``[11]`` name, ``[4][7]`` rating, ``[4][8]`` review count,
``[9][2:4]`` coordinates, ``[18]`` address, ``[78]`` place id.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

from . import net

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.google.com/search"
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RESULTS = 20
MAX_MAPS_URL_LEN = 1024

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_XSSI = ")]}'"

# Google's own map-search field selector. The bare tbm=map page silently
# switches between several payload shapes for the same query (a name lookup can
# return zero results while a longer query returns a place), so we send the
# selector the Maps UI sends. It pins the result shape at data[0][1][i][14]
# and asks for 20 places with a whole-earth viewport; results are localized
# from the query text, which the router already biases to the tenant's city.
_SEARCH_PB = (
    "!4m12!1m3!1d{diameter}!2d{lng}!3d{lat}"
    "!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1"
    "!7i{per_page}!8i{offset}!10b1"
    "!12m6!1m1!18b1!2m1!20e3!6m1!114b1"
    "!17m1!3e1"
    "!20m57!2m2!1i203!2i100!3m2!2i4!5b1"
    "!6m6!1m2!1i86!2i86!1m2!1i408!2i240"
    "!7m33!1m3!1e1!2b0!3e3!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3"
    "!1m3!1e8!2b0!3e3!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2"
    "!1m3!1e10!2b0!3e4!1m3!1e9!2b1!3e2!2b1!9b0"
    "!15m8!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20"
)
_EARTH_DIAMETER_METERS = 25_000_000.0


class MapSearchError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def configured() -> bool:
    """No credentials required: the endpoint is public."""
    return True


def _maps_url(feature: str, name: str, lat: Any, lng: Any) -> str:
    """Canonical Maps URL carrying the feature id BOQ needs for deep reviews."""
    slug = quote(name[:120], safe="")
    try:
        coords = f"@{float(lat):.7f},{float(lng):.7f},17z/"
    except (TypeError, ValueError):
        coords = ""
    return (
        f"https://www.google.com/maps/place/{slug}/{coords}"
        f"data=!3m1!4b1!4m6!3m5!1s{feature}!8m2"
    )[:MAX_MAPS_URL_LEN]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").split()[0])
        except (ValueError, IndexError):
            return None
    return None


def _parse(body: str) -> list[dict[str, Any]]:
    """Parse the lite search payload into the bench's place shape."""
    text = body.split(_XSSI, 1)[1] if _XSSI in body else body
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise MapSearchError("Map search returned an invalid response") from exc

    block = None
    try:
        block = data[0][1]
    except (IndexError, KeyError, TypeError):
        pass
    if not isinstance(block, list):
        raise MapSearchError("Map search response layout changed")

    places: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in block:
        place = entry[14] if isinstance(entry, list) and len(entry) > 14 else None
        if not isinstance(place, list) or len(place) < 79:
            continue
        feature = str(place[10] or "").strip()
        place_id = str(place[78] or "").strip()
        if not feature or not place_id or place_id in seen:
            continue
        seen.add(place_id)

        stats = place[4] if isinstance(place[4], list) else []
        coords = place[9] if isinstance(place[9], list) else []
        name = str(place[11] or "").strip()[:255]
        rating = _number(stats[7] if len(stats) > 7 else None)
        count = _number(stats[8] if len(stats) > 8 else None)
        places.append({
            "place_id": place_id,
            "name": name or None,
            "address": str(place[18] or place[14] or "").strip()[:500] or None,
            "rating": rating,
            "review_count": int(count) if count is not None else None,
            "latitude": _number(coords[2] if len(coords) > 2 else None),
            "longitude": _number(coords[3] if len(coords) > 3 else None),
            "types": [],
            "reviews": [],
            "photos": [],
            "reviews_per_score": None,
            "maps_url": _maps_url(feature, name, coords[2] if len(coords) > 2 else None,
                                  coords[3] if len(coords) > 3 else None),
            # Feature id is carried so the BOQ adapter can use it for deep
            # reviews immediately after the place is saved.
            "feature_id": feature,
            "thumbnail": None,
            "source": "mapsearch",
        })
    return places


async def _search_on_client(
    q: str, cap: int, session: Any
) -> list[dict[str, Any]]:
    pb = _SEARCH_PB.format(
        diameter=_EARTH_DIAMETER_METERS,
        lat=0.0,
        lng=0.0,
        per_page=MAX_RESULTS,
        offset=0,
    )
    try:
        response = await session.get(
            SEARCH_URL,
            params={
                "tbm": "map", "authuser": "0", "hl": "en", "gl": "us",
                "q": q, "pb": pb,
            },
            headers=_HEADERS,
        )
    except httpx.HTTPError as exc:
        raise net.Blocked("Map search is unreachable") from exc
    if response.status_code in (403, 429):
        raise net.Blocked(f"Map search rate-limited the route (HTTP {response.status_code})")
    if response.status_code != 200:
        raise MapSearchError(f"Map search returned HTTP {response.status_code}", 502)
    if not response.text.strip():
        raise net.Blocked("Map search returned an empty body")
    if any(marker in response.text[:4000].lower() for marker in (
        "consent.google.com", "accounts.google.com", "before you continue",
        "unusual traffic",
    )):
        raise net.Blocked("Map search served a consent page")
    return _parse(response.text)[:cap]


async def search_places(
    query: str, *, limit: int = MAX_RESULTS, client: Any | None = None
) -> list[dict[str, Any]]:
    """Find places for ``query``; listings only, no reviews and no browser.

    ``client`` is injectable for tests; production tries one route per place,
    keeping each search on one IP and moving off a refused route automatically.
    """
    q = str(query or "").strip()[:255]
    if not q:
        return []
    try:
        cap = max(1, min(int(limit), MAX_RESULTS))
    except (TypeError, ValueError):
        cap = MAX_RESULTS
    if client is not None:
        try:
            return await _search_on_client(q, cap, client)
        except net.Blocked as exc:
            raise MapSearchError(str(exc), exc.status_code) from exc

    last_error: net.Blocked | None = None
    for route in net.routes_for(f"search:{q.lower()}"):
        async with net.client_for(route, timeout=REQUEST_TIMEOUT_SECONDS) as session:
            try:
                places = await _search_on_client(q, cap, session)
            except net.Blocked as exc:
                net.note_result(route, ok=False)
                last_error = exc
                logger.warning("Map search blocked on a route for %r: %s", q, exc)
                continue
            net.note_result(route, ok=True)
            return places
    raise MapSearchError(str(last_error or "Map search is unavailable"), 503)
