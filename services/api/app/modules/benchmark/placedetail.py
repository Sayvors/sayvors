"""Free place metadata by Google feature id (``/maps/preview/place``).

This is the call Google's own Maps page makes when it opens a business, so it
answers with the same public facts a visitor sees: rating, review count, full
address, category, coordinates and photos. It needs no API key, login or
browser, and replaces the browser-driven scraper for everything that is not
review text (``boq`` handles reviews).

The response is an undocumented positional array. Each slot the parser reads is
named here once, and a missing or moved slot raises instead of storing a
plausible zero — a wrong rating silently shown to a merchant is worse than an
error they can retry.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from . import net

logger = logging.getLogger(__name__)

PLACE_URL = "https://www.google.com/maps/preview/place"
# A plain GET here hands out the anonymous session cookies Google wants before
# it serves the full place payload.
SESSION_URL = "https://www.google.com/maps?hl=en"
REQUEST_TIMEOUT_SECONDS = 30.0

NAME_LIMIT = 255
ADDRESS_LIMIT = 500
MAX_TYPES = 5
# How deep to search the photo blocks for the first image URL.
PHOTO_SEARCH_DEPTH = 6

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/maps/",
}

_FTID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
# Business photos are served from googleusercontent. Anything else (avatars,
# third-party images) must never become the merchant's card image.
_PHOTO_RE = re.compile(
    r"^https://lh[3-5]\.googleusercontent\.com/[A-Za-z0-9_\-/?%=&.]+$"
)
_BODY_PREFIX = ")]}'"
_BLOCK_STATUS = frozenset({403, 429})

# Field selector the Maps web app sends for a place page, with the feature id
# as its only variable. It asks for the facts above and nothing that needs a
# signed-in account.
_PLACE_PB = (
    "!1m13!1s{fid}"
    "!3m8!1m3!1d5000!2d0!3d0!3m2!1i1024!2i768!4f13.1"
    "!4m2!3d0!4d0"
    "!12m4!2m3!1i360!2i120!4i8"
    "!13m57!2m2!1i203!2i100!3m2!2i4!5b1"
    "!6m6!1m2!1i86!2i86!1m2!1i408!2i240"
    "!7m33!1m3!1e1!2b0!3e3!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3"
    "!1m3!1e8!2b0!3e3!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2"
    "!1m3!1e10!2b0!3e4!1m3!1e9!2b1!3e2!2b1!9b0"
    "!15m8!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20"
    "!14m3!1s0ahUKEwixxxxxxxxxxxxxxxxxxxxxxxxx!7e81!15i10112"
    "!15m108!1m26!13m9!2b1!3b1!4b1!6i1!8b1!9b1!14b1!20b1!25b1"
    "!18m15!3b1!4b1!5b1!6b1!13b1!14b1!17b1!21b1!22b1!30b1!32b1!33m1!1b1!34b1!36e2"
    "!10m1!8e3!11m1!3e1!17b1!20m2!1e3!1e6!24b1!25b1!26b1!27b1!29b1"
    "!30m1!2b1!36b1!37b1!39m3!2m2!2i1!3i1!43b1!52b1!54m1!1b1!55b1!56m1!1b1"
    "!61m2!1m1!1e1!65m5!3m4!1m3!1m2!1i224!2i298"
    "!72m22!1m8!2b1!5b1!7b1!12m4!1b1!2b1!4m1!1e1!4b1"
    "!8m10!1m6!4m1!1e1!4m1!1e3!4m1!1e4"
    "!3sother_user_google_review_posts__and__hotel_and_vr_partner_review_posts"
    "!6m1!1e1!9b1!89b1!90m2!1m1!1e2!98m3!1b1!2b1!3b1!103b1!113b1"
    "!114m3!1b1!2m1!1b1!117b1!122m1!1b1!126b1!127b1!128m1!1b0"
    "!21m0!22m1!1e81!30m8!3b1!6m2!1b1!2b1!7m2!1e3!2b1!9b1"
    "!34m5!7b1!10b1!14b1!15m1!1b0!37i785"
)


class PlaceDetailError(Exception):
    """Place facts could not be read; carries an HTTP-like status."""

    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def feature_id(maps_url: str | None) -> str | None:
    """The ``0x…:0x…`` feature id BOQ and this endpoint both key on."""
    match = _FTID_RE.search(str(maps_url or ""))
    return match.group(1) if match else None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def _at(node: Any, index: int) -> Any:
    return node[index] if isinstance(node, list) and len(node) > index else None


def _first_photo(node: Any, depth: int = 0) -> str | None:
    """First business photo URL inside a photo block (cover, then gallery)."""
    if depth > PHOTO_SEARCH_DEPTH:
        return None
    if isinstance(node, str):
        return node if _PHOTO_RE.match(node) else None
    if isinstance(node, list):
        for child in node:
            found = _first_photo(child, depth + 1)
            if found:
                return found
    return None


def parse(body: str) -> dict[str, Any]:
    """Normalize one place payload to the benchmark place shape."""
    text = body.split(_BODY_PREFIX, 1)[1] if _BODY_PREFIX in body else body
    text = text.strip()
    if not text:
        raise PlaceDetailError("Place details returned an empty body")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PlaceDetailError("Place details returned an invalid response") from exc

    place = _at(data, 6)
    if not isinstance(place, list) or len(place) < 40:
        raise PlaceDetailError("Place details response layout changed")

    name = str(_at(place, 11) or "").strip()[:NAME_LIMIT]
    if not name:
        raise PlaceDetailError("Place details response has no title")

    stats = _at(place, 4)
    rating = _to_float(_at(stats, 7))
    if rating is not None and not 1.0 <= rating <= 5.0:
        rating = None
    coords = _at(place, 9)
    categories = _at(place, 13)
    address = str(_at(place, 39) or _at(place, 18) or "").strip()[:ADDRESS_LIMIT]

    return {
        "place_id": str(_at(place, 78) or "").strip()[:255] or None,
        "name": name,
        "address": address or None,
        "rating": rating,
        "review_count": _to_int(_at(stats, 8)),
        "latitude": _to_float(_at(coords, 2)),
        "longitude": _to_float(_at(coords, 3)),
        "types": [
            item[:80] for item in (categories if isinstance(categories, list) else [])
            if isinstance(item, str) and item.strip()
        ][:MAX_TYPES],
        "reviews": [],
        "photos": [],
        "reviews_per_score": None,
        "maps_url": None,
        "thumbnail": _first_photo(_at(place, 37)) or _first_photo(_at(place, 51)),
        "source": "placedetail",
    }


def _looks_like_consent_wall(text: str) -> bool:
    head = text[:4000].lower()
    return any(
        marker in head
        for marker in (
            "consent.google.com", "accounts.google.com/servicelogin",
            "before you continue to google", "unusual traffic",
        )
    )


async def _fetch(feature: str, client: Any, cookies: dict | None, *, warm_up: bool) -> dict[str, Any]:
    if warm_up:
        try:
            # Only to collect anonymous session cookies; a failure here is not
            # fatal because the place call is tried regardless.
            await client.get(SESSION_URL, headers=_HEADERS)
        except httpx.HTTPError:
            logger.debug("Google session warm-up failed", exc_info=True)
    url = PLACE_URL + "?authuser=0&hl=en&gl=us&pb=" + quote(
        _PLACE_PB.format(fid=feature), safe="!"
    )
    try:
        response = await client.get(url, headers=_HEADERS, cookies=cookies)
    except httpx.HTTPError as exc:
        raise net.Blocked("Google place details are unreachable") from exc
    if response.status_code in _BLOCK_STATUS:
        raise net.Blocked(
            f"Google rate-limited place details (HTTP {response.status_code})"
        )
    if response.status_code != 200:
        raise PlaceDetailError(
            f"Place details returned HTTP {response.status_code}", 502
        )
    if not response.text.strip():
        # A valid feature id with an empty body is Google refusing, not a
        # business with no facts.
        raise net.Blocked("Google returned an empty place response")
    if _looks_like_consent_wall(response.text):
        raise net.Blocked("Google served a consent page instead of place details")
    return parse(response.text)


async def get_place(
    feature: str,
    *,
    client: Any | None = None,
    session: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch one place's public facts by feature id.

    ``client``/``session`` are injectable for tests and for a caller that
    already holds a route. Otherwise each configured proxy is tried in turn and
    a refused route is rested (see ``net``).
    """
    key = str(feature or "").strip()
    if not key:
        raise PlaceDetailError("Place has no Google feature id", 422)
    if client is not None:
        try:
            return await _fetch(key, client, session, warm_up=False)
        except net.Blocked as exc:
            raise PlaceDetailError(str(exc), exc.status_code) from exc

    last_error: net.Blocked | None = None
    for route in net.routes_for(f"place:{key}"):
        async with net.client_for(route, timeout=REQUEST_TIMEOUT_SECONDS) as owned:
            try:
                place = await _fetch(key, owned, None, warm_up=True)
            except net.Blocked as exc:
                net.note_result(route, ok=False)
                last_error = exc
                logger.warning("Place details blocked on a route for %s: %s", key, exc)
                continue
            net.note_result(route, ok=True)
            return place
    raise PlaceDetailError(str(last_error or "Place details are unavailable"), 503)
