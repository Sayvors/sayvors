"""gosom Google Maps scraper client for competitor benchmarking.

Talks to a gosom sidecar's embedded web API (no auth). Exposes the same
interface as ``places`` and ``outscraper`` so the benchmark worker can swap
providers without changes in downstream consumers.

gosom owns discovery and place metadata. Its reviews are only the handful
Google renders for a signed-out browser, so ``get_place`` deepens them with the
free BOQ panel endpoint (see ``boq``) — same business, same window, far more
reviews.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ...config import settings
from . import boq

logger = logging.getLogger(__name__)

MAX_REVIEWS = 500
# Review history we keep per place. Benchmarking cares about recent momentum
# (last 30 days), not a multi-year archive: the aggregate rating/count still
# come through untouched, only the stored review *text* list is windowed.
DEFAULT_REVIEW_WINDOW_DAYS = 30
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


def _first(item: dict[str, Any], *keys: str) -> Any:
    """First non-empty value among possibly-cased JSON keys.

    gosom's Review struct tags only SOME fields (published_at, reply_text are
    lowercase; Name/Rating/Description/ProfilePicture marshal capitalised).
    Reading one case silently blanks the other, which is exactly how reviews
    ended up stored with a date and an owner reply but no author/rating/text.
    """
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


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
            rating = _first(item, "rating", "Rating")
            try:
                rating_int = int(rating) if rating not in (None, "") else None
            except (TypeError, ValueError):
                rating_int = None
            reviews.append({
                # Google star ratings are 1-5; 0 means the parse found none.
                "rating": rating_int if rating_int and 1 <= rating_int <= 5 else None,
                "text": str(_first(item, "description", "Description") or "")[:CSV_TEXT_LIMIT],
                "publish_time": _rfc3339_or_none(_first(item, "published_at", "PublishedAt")),
                "author": str(_first(item, "name", "Name") or "")[:CSV_AUTHOR_LIMIT] or None,
                "author_photo": str(_first(item, "profile_picture", "ProfilePicture") or "")[:1024] or None,
                "owner_answer": str(_first(item, "reply_text", "ReplyText") or "")[:CSV_TEXT_LIMIT] or None,
                "owner_answer_time": _rfc3339_or_none(_first(item, "reply_published_at", "ReplyPublishedAt")),
            })
            if len(reviews) >= MAX_REVIEWS:
                break
        if len(reviews) >= MAX_REVIEWS:
            break
    # Newest first so the reviews table's "Newest" label is true (gosom
    # returns Google's order, which is not date-sorted). Undated last.
    reviews.sort(key=lambda r: r["publish_time"] or "", reverse=True)
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
        # The Maps URL (row["link"]) is the canonical place URL gosom scraped.
        # Storing it at save time lets get_place() target the exact listing
        # without relying on the cid/place_id string alone.
        "maps_url": str(row.get("link") or "")[:1024] or None,
        # Google place photo URL for the card avatar.
        "thumbnail": str(row.get("thumbnail") or "")[:1024] or None,
        "source": "gosom",
    }


async def _create_job(
    client: httpx.AsyncClient, query: str, *, extra_reviews: bool = True
) -> str:
    url = f"{_base_url()}/api/v1/jobs"
    body = {
        "name": str(query or "")[:255],
        "keywords": [str(query)],
        "lang": "en",
        "zoom": 15,
        "lat": "",
        "lon": "",
        "fast_mode": False,
        "radius": 10000,
        "depth": 1,
        "email": False,
        # Search passes False: it only needs place listings (name, address,
        # rating, count), which gosom returns without opening each place's
        # review panel. Only a saved place's scrape sets True — that is the
        # expensive per-place review pagination, and it should run for the
        # few places a user actually saved, never for a whole search page.
        "extra_reviews": extra_reviews,
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
        # gosom's web.Job Go struct has NO json tags, so it marshals with
        # capitalised field names ("Status", "ID", ...). Read both cases so a
        # future gosom that adds tags (lowercase) still works. Reading only
        # lowercase made every real poll miss "ok" and time out at 504 while
        # the job actually completed server-side.
        status = str(job.get("Status") or job.get("status") or "").lower()
        if status == "ok":
            return job
        if status == "failed":
            error = job.get("Error") or job.get("error") or job.get("message") or "job failed"
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


def _filter_recent(
    reviews: list[dict[str, Any]], days: int | None
) -> list[dict[str, Any]]:
    """Keep only reviews published within the last ``days`` days.

    A review with no parseable publish date cannot be proven recent, so it is
    excluded from the window rather than guessed in. ``days=None`` disables the
    filter (returns everything). Ordering is preserved (gosom returns newest
    first).
    """
    if not days or days <= 0:
        return reviews
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[dict[str, Any]] = []
    for review in reviews:
        raw = review.get("publish_time")
        if not raw:
            continue
        try:
            published = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published >= cutoff:
            kept.append(review)
    return kept


async def get_place(
    place_id: str,
    *,
    reviews_limit: int = 500,
    cutoff: Any = None,
    maps_url: str | None = None,
    days: int | None = DEFAULT_REVIEW_WINDOW_DAYS,
) -> dict[str, Any]:
    """Scrape one saved place's details and recent reviews.

    This is the expensive path (one browser render + review pagination) and runs
    only for a place the user actually saved. Reviews are windowed to the last
    ``days`` days (default 30) so the stored text stays focused on recent
    momentum; the aggregate rating and review count are always full.

    ``cutoff`` is accepted for signature parity with ``places.get_place`` but is
    ignored — the window is expressed in ``days`` instead.
    """
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
        job_id = await _create_job(client, query, extra_reviews=True)
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
    reviews = _filter_recent(place.get("reviews") or [], days)
    if limit >= 0:
        reviews = reviews[:limit]
    place["reviews"] = await _deepen_reviews(
        place, reviews, limit=limit, days=days, maps_url=maps_url
    )
    # cutoff accepted for signature parity; the window is `days` above.
    _ = cutoff
    return place


async def _deepen_reviews(
    place: dict[str, Any],
    reviews: list[dict[str, Any]],
    *,
    limit: int,
    days: int | None,
    maps_url: str | None,
) -> list[dict[str, Any]]:
    """Replace gosom's handful of reviews with the full recent set from BOQ.

    gosom sees only the reviews Google serves a signed-out browser (~5 since the
    2026 sign-in wall), which cannot answer "what changed this month". The BOQ
    panel endpoint returns the same public reviews at real depth, for free.

    Metadata (rating, count, address, photos) stays gosom's: the BOQ payload has
    none. A BOQ failure is logged and the shallow reviews are kept, because
    losing depth must never blank a competitor's review column.
    """
    if limit == 0:
        return []
    if not bool(getattr(settings, "BOQ_REVIEWS_ENABLED", True)):
        return reviews
    url = place.get("maps_url") or maps_url
    if not boq.feature_id(url):
        # No canonical Maps URL means no feature id; a guess would scrape a
        # different business than the one the user saved.
        return reviews
    try:
        deep = await boq.reviews_for_place(
            str(place.get("place_id") or ""),
            maps_url=url,
            max_reviews=MAX_REVIEWS if limit < 0 else max(limit, len(reviews)),
            days=days,
        )
    except boq.BoqError as exc:
        logger.warning("BOQ review depth failed for %s: %s", url, exc)
        return reviews
    return deep or reviews


async def search_places(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Find places matching a query — listings only, no reviews.

    This is the fast path: gosom returns name, address, rating, review count,
    coordinates and the Maps URL for each result without opening any review
    panel. Review scraping is deferred to ``get_place`` when the user saves a
    place, so a search never pays the per-place review cost.
    """
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
        job_id = await _create_job(client, q, extra_reviews=False)
        try:
            await _poll_job(client, job_id)
            csv_text = await _download_csv(client, job_id)
        finally:
            await _delete_job(client, job_id)

    rows = _parse_csv(csv_text)
    results: list[dict[str, Any]] = []
    for row in rows:
        place = _map_place(row)
        # Search never carries reviews; keep the field empty and explicit.
        place["reviews"] = []
        results.append(place)
        if len(results) >= cap:
            break
    return results