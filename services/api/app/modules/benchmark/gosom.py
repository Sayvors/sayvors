"""gosom Google Maps scraper client for competitor benchmarking.

Talks to a gosom sidecar's embedded web API (no auth). Exposes the same
interface as ``places`` and ``outscraper`` so the benchmark worker can swap
providers without changes in downstream consumers.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

MAX_REVIEWS = 500
REQUEST_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 3.0
JOB_TIMEOUT_SECONDS = 600.0
MIN_MAX_TIME_SECONDS = 180
CSV_TEXT_LIMIT = 4000
CSV_AUTHOR_LIMIT = 255
MAX_SEARCH_RESULTS = 20


class GosomError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def configured() -> bool:
    return bool(str(getattr(settings, "GOSOM_SCRAPER_URL", "") or "").strip())


def _base_url() -> str:
    raw = getattr(settings, "GOSOM_SCRAPER_URL", "http://gosom:8080")
    return str(raw or "http://gosom:8080").strip().rstrip("/")


def _proxies() -> list[str]:
    raw = getattr(settings, "GOSOM_PROXIES", "") or ""
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _rfc3339_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Relative phrases ("2 months ago") are not timestamps.
    if "ago" in text.lower():
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _parse_csv(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    try:
        reader = csv.DictReader(io.StringIO(text))
        return [row for row in reader if row is not None]
    except Exception:  # pragma: no cover - defensive
        logger.exception("gosom CSV parse failed")
        return []


def _parse_reviews(row: dict[str, Any]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for column in ("user_reviews", "user_reviews_extended"):
        raw = row.get(column)
        if not raw:
            continue
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("gosom column %s contained invalid JSON", column)
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            review_id = item.get("review_id")
            if review_id is not None and review_id in seen:
                continue
            if review_id is not None:
                seen.add(review_id)
            reviews.append({
                "rating": item.get("rating"),
                "text": str(item.get("description") or "")[:CSV_TEXT_LIMIT],
                "publish_time": _rfc3339_or_none(item.get("published_at")),
                "author": str(item.get("name") or "")[:CSV_AUTHOR_LIMIT] or None,
                "author_photo": str(item.get("profile_picture") or "")[:1024] or None,
                "owner_answer": str(item.get("reply_text") or "")[:CSV_TEXT_LIMIT] or None,
                "owner_answer_time": _rfc3339_or_none(item.get("reply_published_at")),
            })
            if len(reviews) >= MAX_REVIEWS:
                break
        if len(reviews) >= MAX_REVIEWS:
            break
    return reviews[:MAX_REVIEWS]


def _map_place(row: dict[str, Any]) -> dict[str, Any]:
    place_id = str(
        row.get("place_id") or row.get("cid") or row.get("data_id") or ""
    ).strip()[:255]
    category = str(row.get("category") or "").strip()
    reviews_per_score = row.get("reviews_per_rating")
    if isinstance(reviews_per_score, str) and reviews_per_score.strip():
        try:
            reviews_per_score = json.loads(reviews_per_score)
        except (json.JSONDecodeError, ValueError):
            logger.warning("gosom reviews_per_rating contained invalid JSON")
            reviews_per_score = None
    return {
        "place_id": place_id,
        "name": str(row.get("title") or "")[:255] or None,
        "address": str(row.get("address") or "")[:500] or None,
        "rating": _to_float(row.get("review_rating")),
        "review_count": _to_int(row.get("review_count")),
        "latitude": _to_float(row.get("latitude")),
        "longitude": _to_float(row.get("longitude")),
        "types": [category] if category else [],
        "reviews": _parse_reviews(row),
        "photos": [],
        "reviews_per_score": reviews_per_score,
        "source": "gosom",
    }


async def _create_job(client: httpx.AsyncClient, query: str) -> str:
    url = f"{_base_url()}/api/v1/jobs"
    body = {
        "name": str(query or "")[:255],
        "keywords": [str(query)],
        "lang": "en",
        "zoom": 15,
        "lat": 0.0,
        "lon": 0.0,
        "fast_mode": False,
        "radius": 10000,
        "depth": 1,
        "email": False,
        "extra_reviews": True,
        "max_time": max(MIN_MAX_TIME_SECONDS, 600),
        "proxies": _proxies(),
    }
    try:
        resp = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        logger.error("gosom create job transport failed: %s", type(exc).__name__, exc_info=True)
        raise GosomError("gosom scraper is temporarily unavailable") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("gosom create job failed status=%s", resp.status_code)
        raise GosomError("gosom scraper is temporarily unavailable", resp.status_code)
    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("gosom create job returned invalid JSON")
        raise GosomError("gosom scraper returned an invalid response") from exc
    if not isinstance(data, dict):
        raise GosomError("gosom scraper returned an invalid response")
    job_id = data.get("id") or data.get("job_id") or data.get("jobId")
    if not job_id:
        raise GosomError("gosom scraper returned an invalid response")
    return str(job_id)


async def _poll_job(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    url = f"{_base_url()}/api/v1/jobs/{job_id}"
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("gosom poll transport failed: %s", type(exc).__name__, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        if resp.status_code == 404:
            raise GosomError("gosom job not found", 404)
        if resp.status_code < 200 or resp.status_code >= 300:
            logger.error("gosom poll failed status=%s", resp.status_code)
            raise GosomError("gosom scraper is temporarily unavailable", resp.status_code)
        try:
            job = resp.json()
        except (ValueError, json.JSONDecodeError):
            logger.warning("gosom poll returned invalid JSON")
            continue
        if not isinstance(job, dict):
            continue
        status = str(job.get("status") or "").lower()
        if status == "ok":
            return job
        if status == "failed":
            error = job.get("error") or job.get("message") or "job failed"
            raise GosomError(str(error)[:500])
        # pending / working: keep polling
    raise GosomError("gosom job timed out", 504)


async def _download_csv(client: httpx.AsyncClient, job_id: str) -> str:
    url = f"{_base_url()}/api/v1/jobs/{job_id}/download"
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.error("gosom download transport failed: %s", type(exc).__name__, exc_info=True)
        raise GosomError("gosom scraper is temporarily unavailable") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("gosom download failed status=%s", resp.status_code)
        raise GosomError("gosom scraper is temporarily unavailable", resp.status_code)
    return resp.text


async def _delete_job(client: httpx.AsyncClient, job_id: str) -> None:
    url = f"{_base_url()}/api/v1/jobs/{job_id}"
    try:
        await client.delete(url)
    except Exception as exc:  # best-effort
        logger.debug("gosom delete job failed: %s", type(exc).__name__, exc_info=True)


async def get_place(
    place_id: str,
    *,
    reviews_limit: int = 500,
    cutoff: Any = None,
    maps_url: str | None = None,
) -> dict[str, Any]:
    pid = str(place_id or "").strip()[:255]
    if not pid:
        raise GosomError("Unknown place", 400)
    if not configured():
        raise GosomError("gosom scraper is not configured", 503)
    query = maps_url if maps_url else place_id
    query = str(query or "").strip()
    if not query:
        raise GosomError("Unknown place", 400)

    try:
        limit = max(0, min(int(reviews_limit), MAX_REVIEWS))
    except (TypeError, ValueError):
        limit = MAX_REVIEWS

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        job_id = await _create_job(client, query)
        try:
            await _poll_job(client, job_id)
            csv_text = await _download_csv(client, job_id)
        finally:
            await _delete_job(client, job_id)

    rows = _parse_csv(csv_text)
    if not rows:
        raise GosomError("Place not found", 404)
    place = _map_place(rows[0])
    if not place.get("place_id"):
        place["place_id"] = pid or str(place_id or "").strip()[:255]
    if limit >= 0:
        place["reviews"] = (place.get("reviews") or [])[:limit]
    # cutoff accepted for signature parity; gosom returns full history.
    _ = cutoff
    return place


async def search_places(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    if not configured():
        return []
    q = str(query or "").strip()[:255]
    if not q:
        return []
    try:
        cap = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        cap = MAX_SEARCH_RESULTS

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        job_id = await _create_job(client, q)
        try:
            await _poll_job(client, job_id)
            csv_text = await _download_csv(client, job_id)
        finally:
            await _delete_job(client, job_id)

    rows = _parse_csv(csv_text)
    places = [_map_place(row) for row in rows]
    return places[:cap]