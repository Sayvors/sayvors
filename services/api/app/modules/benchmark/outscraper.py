"""Outscraper Google Maps Reviews client for competitor benchmarking.

Used only for public competitor/place intelligence. The tenant's own connected
Google Business location stays on GBP OAuth. The key is server-side only.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

OUTSCRAPER_BASE = "https://api.outscraper.cloud"
REVIEWS_ENDPOINT = "/google-maps-reviews"
REQUEST_TIMEOUT_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 3.0
POLL_TIMEOUT_SECONDS = 180.0
MAX_SEARCH_RESULTS = 20
# Hard cost cap: never pull more than 10 reviews per place in one call.
MAX_REVIEWS = 10


class OutscraperError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def configured() -> bool:
    return bool((settings.OUTSCRAPER_API_KEY or "").strip())


def _key() -> str:
    key = (settings.OUTSCRAPER_API_KEY or "").strip()
    if not key:
        raise OutscraperError("Outscraper is not configured", 503)
    return key


def _publish_time(review: dict) -> str | None:
    ts = review.get("review_timestamp")
    if ts is not None:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
    raw = str(review.get("review_datetime_utc") or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _map_review(review: dict) -> dict:
    text = review.get("review_text")
    if text is None:
        text = ""
    return {
        "rating": review.get("review_rating"),
        "text": str(text)[:4000],
        "publish_time": _publish_time(review),
        "author": str(review.get("author_title") or "")[:255] or None,
        "author_photo": str(review.get("author_image") or "")[:1024] or None,
        "owner_answer": str(review.get("owner_answer") or "")[:4000] or None,
        "owner_answer_time": _publish_time({"review_timestamp": review.get("owner_answer_timestamp")})
        if review.get("owner_answer_timestamp")
        else None,
    }


def _map_place(place: dict) -> dict:
    reviews = []
    for review in (place.get("reviews_data") or [])[:MAX_REVIEWS]:
        if isinstance(review, dict):
            reviews.append(_map_review(review))
    place_id = str(place.get("place_id") or place.get("google_id") or "")[:255]
    return {
        "place_id": place_id,
        "name": str(place.get("name") or "")[:255] or None,
        "address": str(place.get("full_address") or "")[:500] or None,
        "rating": place.get("rating"),
        "review_count": place.get("reviews"),
        "latitude": None,
        "longitude": None,
        "types": [],
        "reviews": reviews,
        "photos": [],
        "reviews_per_score": place.get("reviews_per_score") or None,
        "source": "outscraper",
    }


async def _request(params: dict[str, Any]) -> list[dict]:
    key = _key()
    headers = {"X-API-KEY": key}
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(f"{OUTSCRAPER_BASE}{REVIEWS_ENDPOINT}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("Outscraper transport failed: %s", type(exc).__name__, exc_info=True)
            raise OutscraperError("Benchmark data source is temporarily unavailable") from exc

        if resp.status_code in (401, 402):
            logger.error("Outscraper auth/billing failed status=%s", resp.status_code)
            raise OutscraperError("Benchmark data source is not available", 503)
        if resp.status_code == 422:
            logger.error("Outscraper rejected request status=422")
            raise OutscraperError("Benchmark request was invalid", 422)
        if resp.status_code not in (200, 202):
            logger.error("Outscraper request failed status=%s", resp.status_code)
            raise OutscraperError("Benchmark data source is temporarily unavailable", resp.status_code)

        try:
            body = resp.json() or {}
        except ValueError as exc:
            raise OutscraperError("Benchmark data source returned an invalid response") from exc

        if resp.status_code == 202:
            request_id = str(body.get("id") or "").strip()
            if not request_id:
                raise OutscraperError("Benchmark data source returned an invalid response")
            body = await _poll(client, headers, request_id)

    status = str(body.get("status") or "").lower()
    if status == "pending":
        raise OutscraperError("Benchmark data is still being prepared", 503)
    if status not in ("success", "ok", ""):
        logger.error("Outscraper request status=%s", status)
        raise OutscraperError("Benchmark data source is temporarily unavailable")

    data = body.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        # Outscraper returns array of places; sometimes nested.
        if data and isinstance(data[0], list):
            # batched query result
            flat = []
            for chunk in data:
                if isinstance(chunk, list):
                    flat.extend([p for p in chunk if isinstance(p, dict)])
            return flat
        return [p for p in data if isinstance(p, dict)]
    return []


async def _poll(client: httpx.AsyncClient, headers: dict[str, str], request_id: str) -> dict:
    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
    url = f"{OUTSCRAPER_BASE}/requests/{request_id}"
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("Outscraper poll transport failed: %s", type(exc).__name__)
            continue
        if resp.status_code not in (200, 202):
            logger.error("Outscraper poll failed status=%s", resp.status_code)
            raise OutscraperError("Benchmark data source is temporarily unavailable", resp.status_code)
        try:
            body = resp.json() or {}
        except ValueError:
            continue
        status = str(body.get("status") or "").lower()
        if status in ("pending", "in_progress", "running"):
            continue
        return body
    raise OutscraperError("Benchmark data took too long to prepare", 504)


async def search_places(query: str, *, limit: int = MAX_SEARCH_RESULTS) -> list[dict]:
    q = str(query or "").strip()[:255]
    if not q:
        return []
    rows = await _request({
        "query": q,
        "limit": max(1, min(int(limit), MAX_SEARCH_RESULTS)),
        # Never 0: Outscraper treats 0 as unlimited and bills per review.
        "reviewsLimit": 1,
        "async": "false",
    })
    return [_map_place(p) for p in rows[:limit]]


async def get_place(
    place_id: str,
    *,
    reviews_limit: int = MAX_REVIEWS,
    start: int | None = None,
    cutoff: int | None = None,
) -> dict:
    pid = str(place_id or "").strip()[:255]
    if not pid:
        raise OutscraperError("Unknown place", 400)
    params: dict[str, Any] = {
        "query": pid,
        "limit": 1,
        # Never 0: Outscraper treats 0 as unlimited and bills per review.
        "reviewsLimit": max(1, min(int(reviews_limit), MAX_REVIEWS)),
        "sort": "newest",
        "async": "false",
    }
    if start is not None:
        params["start"] = int(start)
    if cutoff is not None:
        params["cutoff"] = int(cutoff)
    rows = await _request(params)
    if not rows:
        raise OutscraperError("Place not found", 404)
    place = _map_place(rows[0])
    if not place.get("place_id"):
        place["place_id"] = pid
    return place