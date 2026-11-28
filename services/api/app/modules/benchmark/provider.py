"""Production provider order for benchmark place facts and reviews.

Google Places (New) is authoritative for facts when its key is configured.
BOQ supplies deep review history from the canonical Maps feature ID and acts as
the complete fallback when Places is unavailable. BOQ is cache-only in read
handlers; the bounded worker owns the paged call.

Proxy routing is optional and lives in :mod:`benchmark.net`: with no
``GOOGLE_SCRAPER_PROXIES`` the request goes direct, otherwise one sticky route
is kept for the whole BOQ paging sequence and a blocked route is rested.
"""
from __future__ import annotations

import logging
from typing import Any

from . import boq, outscraper, places

logger = logging.getLogger(__name__)

# Official Places returns at most 10 reviews per place. Deeper history comes
# from BOQ, never from an unbounded Places paginator.
PLACES_REVIEW_LIMIT = 10


def _wants_deep(reviews_limit: int) -> bool:
    try:
        return int(reviews_limit) > PLACES_REVIEW_LIMIT
    except (TypeError, ValueError):
        return False


async def _deep_reviews(
    place_id: str, *, reviews_limit: int, maps_url: str | None,
    review_days: int | None,
) -> dict | None:
    """Paged BOQ reviews, only when a canonical feature ID is available."""
    if not boq.feature_id(maps_url) or not _wants_deep(reviews_limit):
        return None
    return await boq.get_place(
        place_id, reviews_limit=reviews_limit, maps_url=maps_url, days=review_days
    )


def _merge_official_with_deep(official: dict, deep: dict, maps_url: str | None) -> dict:
    merged = {**official}
    merged["reviews"] = deep.get("reviews") or official.get("reviews") or []
    if not merged.get("thumbnail") and deep.get("thumbnail"):
        merged["thumbnail"] = deep["thumbnail"]
    if not merged.get("maps_url") and maps_url:
        merged["maps_url"] = maps_url
    if not merged.get("reviews_per_score") and deep.get("reviews_per_score"):
        merged["reviews_per_score"] = deep["reviews_per_score"]
    merged["reviews_source"] = "boq"
    merged["facts_source"] = "google_places"
    return merged


async def _official_then_boq(
    place_id: str, *, reviews_limit: int, maps_url: str | None,
    cutoff: int | None, review_days: int | None,
) -> dict:
    official: dict | None = None
    places_error: Exception | None = None
    if places.configured():
        try:
            official = await places.get_place(
                place_id, reviews_limit=min(reviews_limit, PLACES_REVIEW_LIMIT),
                cutoff=cutoff,
            )
        except places.PlacesError as exc:
            places_error = exc
            logger.warning("Places details failed for %s: %s", place_id, exc)

    deep: dict | None = None
    deep_error: Exception | None = None
    if _wants_deep(reviews_limit):
        try:
            deep = await _deep_reviews(
                place_id, reviews_limit=reviews_limit,
                maps_url=maps_url, review_days=review_days,
            )
        except boq.BoqError as exc:
            deep_error = exc
            logger.warning("BOQ deep reviews failed for %s: %s", place_id, exc)

    if official is not None:
        if deep is not None:
            return _merge_official_with_deep(official, deep, maps_url)
        return {**official, "facts_source": "google_places"}
    if deep is not None:
        return {**deep, "reviews_source": "boq", "facts_source": "boq"}
    if places_error is not None:
        raise places_error
    if deep_error is not None:
        raise deep_error
    raise places.PlacesError("Place details are unavailable", 503)


async def get_details(
    source: str,
    place_id: str,
    *,
    reviews_limit: int,
    maps_url: str | None = None,
    cutoff: int | None = None,
    review_days: int | None = None,
) -> dict:
    """Provider-routed details with official-first order and BOQ fallback."""
    source = str(source or "").strip()
    if source in {"boq", "gosom"}:
        return await boq.get_place(
            place_id, reviews_limit=reviews_limit, maps_url=maps_url, days=review_days
        )
    if source == "outscraper":
        try:
            return await outscraper.get_place(
                place_id, reviews_limit=10, cutoff=cutoff
            )
        except outscraper.OutscraperError as exc:
            if not places.configured():
                raise
            logger.warning("Outscraper details failed for %s: %s", place_id, exc)
            return await places.get_place(place_id, reviews_limit=10, cutoff=cutoff)
    return await _official_then_boq(
        place_id, reviews_limit=reviews_limit, maps_url=maps_url,
        cutoff=cutoff, review_days=review_days,
    )
