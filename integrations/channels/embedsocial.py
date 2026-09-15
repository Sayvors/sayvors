"""Localith reviews adapter (SPIKE — embedsocial branch only).

Localith is an authorized Google Business Profile partner that exposes a
read-first REST API for reviews, listings, metrics, and posts. We use it
as a middleware today so we can read GBP data without a per-tenant
Google approval; once native Google API access lands, the same shape
goes to the Google adapter.

Endpoint map (from the public Localith n8n community node source
    and https://app.localith.ai/app/api/documentation):
    https://github.com/localithai/n8n-nodes-localith (nodes/Localith/Localith.node.ts)
    baseURL: https://embedsocial.com/app/api
    items:            GET   /rest/v1/items           (individual reviews)
                      query: page, pageSize (max 100), sourceId, sort (+field/-field)
    reply:            POST  /rest/v1/items/{id}/replies  (write — publishes to Google)
    listings:         GET   /rest/v1/listings        (connected locations)
                      query: address, name, page, pageSize, sort
    listing detail:   GET   /rest/v1/listings/{listingId}
    listing update:   PATCH /rest/v1/listings/{listingId}  (write — not used by sync)
    listing_metrics:  GET   /rest/v1/listing_metrics (REQUIRES startDate & endDate DD-MM-YYYY)
                      query: startDate*, endDate*, sourceId, page, pageSize
    item_metrics:     GET   /rest/v1/listing_item_metrics (same required dates)
    publish_media:    POST  /rest/v1/content_publishing_media (write — not used by sync)

Auth is a single bearer token (Account > API key in the Localith dashboard).

Env vars (never committed)::
  LOCALITH_API_KEY       required
  LOCALITH_BASE_URL      default https://embedsocial.com/app/api
  LOCALITH_ITEMS_PATH    default rest/v1/items
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field

import httpx


@dataclass
class InternalReview:
    """Sayvors' unified review shape (source-agnostic downstream)."""

    source: str = "localith"
    external_id: str = ""
    platform: str = "google_reviews"
    rating: int = 5
    text: str | None = None
    reviewer: str | None = None
    published_at: str | None = None
    source_name: str | None = None
    review_url: str | None = None
    has_replies: bool = False
    raw: dict = field(default_factory=dict)


def _config() -> tuple[str, str, str]:
    key = os.environ.get("LOCALITH_API_KEY", "")
    base = os.environ.get("LOCALITH_BASE_URL", "")
    items_path = os.environ.get("LOCALITH_ITEMS_PATH", "")
    if not key or not base or not items_path:
        try:
            from app.config import settings

            key = key or settings.LOCALITH_API_KEY
            base = base or settings.LOCALITH_BASE_URL
            items_path = items_path or settings.LOCALITH_ITEMS_PATH
        except ImportError:
            pass
    if not key:
        raise RuntimeError("Set LOCALITH_API_KEY (Localith Account > API key).")
    return (base or "https://embedsocial.com/app/api").rstrip("/"), key, items_path or "rest/v1/items"


_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "sayvors-spike/1.0",
}


def _http_url(url: str) -> str:
    """Fail fast on misconfigured base URLs. httpx only speaks http(s),
    so file://-style exfiltration is impossible by construction."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Localith base URL must be http(s), got: {url[:60]!r}")
    return url


def _get(path: str, params: dict | None = None, timeout: int = 30) -> dict | list:
    base, key, _ = _config()
    url = _http_url(f"{base}/{path.lstrip('/')}")
    resp = httpx.get(
        url,
        params=params or {},
        headers={**_HEADERS, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def post_item_reply(item_id: str, text: str, timeout: int = 30) -> dict:
    """Create a reply for a review item: POST /rest/v1/items/{id}/replies.

    Localith is a Google Business Profile partner, so this reply goes
    live on the connected listing. Body contract (confirmed live against
    the API and per the official docs): {"comment": "<reply text>"}.
    Returns the created reply: {id, comment, updateTime}.
    """
    base, key, _ = _config()
    url = _http_url(f"{base}/rest/v1/items/{urllib.parse.quote(str(item_id), safe='')}/replies")
    headers = {**_HEADERS, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    resp = httpx.post(url, content=json.dumps({"comment": text}).encode("utf-8"), headers=headers, timeout=timeout)
    if resp.status_code < 300:
        try:
            return resp.json()
        except ValueError:
            return {}
    if resp.status_code in (400, 422):
        # Their validation detail (e.g. {"errors": {"comment": ...}}) is
        # the most useful thing we can surface to the merchant. A 400 on
        # approve almost always means the review is unreachable on
        # Google: it either already has a reply (one per review) or it
        # was deleted/removed since the sync — both are unfixable here.
        hint = (
            " (the review either already has a reply on Google, or it"
            " was deleted/removed since the sync — in both cases it"
            " cannot be replied to)"
            if resp.status_code == 400
            else ""
        )
        detail = resp.text[:300].replace("\n", " ")
        raise RuntimeError(f"Localith reply rejected (HTTP {resp.status_code}){hint}: {detail}")
    resp.raise_for_status()
    return {}


def fetch_items(limit: int = 50, listing_id: str | None = None) -> list[dict]:
    """Pull synced review items. Returns raw items as returned by Localith.

    Uses the official query params (page/pageSize/sourceId/sort). ``limit``
    is split across pages of at most 100.
    """
    _base, _key, items_path = _config()
    out: list[dict] = []
    page = 1
    remaining = max(1, limit)
    while remaining > 0:
        params: dict = {
            "page": page,
            "pageSize": min(100, remaining),
            "sort": "-originalCreatedOn",
        }
        if listing_id:
            params["sourceId"] = listing_id
        payload = _get(items_path, params)
        batch = _unwrap_list(payload)
        if not batch:
            break
        out.extend(batch)
        remaining -= len(batch)
        if len(batch) < min(100, remaining + len(batch)):
            break
        page += 1
        if page > 50:  # safety cap: 50 pages x 100
            break
    return out


def fetch_all_items(listing_id: str | None = None, max_pages: int = 50) -> list[dict]:
    """Pull every review item, following pages until a short/empty page."""
    _base, _key, items_path = _config()
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params: dict = {"page": page, "pageSize": 100, "sort": "-originalCreatedOn"}
        if listing_id:
            params["sourceId"] = listing_id
        batch = _unwrap_list(_get(items_path, params))
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def _unwrap_list(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for envelope in ("data", "items", "results", "reviews"):
            if isinstance(payload.get(envelope), list):
                return payload[envelope]
    return []


def _post(path: str, body: dict, timeout: int = 60) -> dict | list:
    base, key, _ = _config()
    url = _http_url(f"{base}/{path.lstrip('/')}")
    resp = httpx.post(
        url,
        json=body,
        headers={**_HEADERS, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def publish_media_post(
    listing_id: str,
    *,
    post_type: str = "update",
    title: str | None = None,
    caption: str = "",
    image_urls: list | None = None,
    cta_type: str | None = None,
    cta_url: str | None = None,
    scheduled_on: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Publish (or schedule) a Google post through Localith.

    Body shape per the official n8n node: type (update/event/offer),
    sourceIds, captionText, title, imageUrls, ctaType, ctaUrl,
    scheduledOn, startDate/endDate, voucherCode. Only http(s) image URLs
    are accepted — local filenames must be filtered by the caller.
    """
    if post_type not in ("update", "event", "offer"):
        raise ValueError(f"Unsupported post type: {post_type}")
    body: dict = {
        "type": post_type,
        "sourceIds": [listing_id],
        "captionText": caption,
    }
    if title:
        body["title"] = title
    urls = [u for u in (image_urls or []) if isinstance(u, str) and u.startswith("http")]
    if urls:
        body["imageUrls"] = urls
    if cta_type:
        body["ctaType"] = cta_type
    if cta_url:
        body["ctaUrl"] = cta_url
    if scheduled_on:
        body["scheduledOn"] = scheduled_on
    if extra:
        body.update(extra)
    payload = _post("rest/v1/content_publishing_media", body)
    return payload if isinstance(payload, dict) else {"result": payload}


def _patch(path: str, body: dict, timeout: int = 30) -> dict | list:
    base, key, _ = _config()
    url = _http_url(f"{base}/{path.lstrip('/')}")
    resp = httpx.patch(
        url,
        json=body,
        headers={**_HEADERS, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# Fields the PATCH /rest/v1/listings/{id} endpoint accepts, mapped from
# our snake_case names to the API's body properties.
UPDATABLE_FIELDS = {
    "name": "name",
    "description": "description",
    "phone_number": "phoneNumber",
    "website_url": "websiteUrl",
    "city": "address.city",
    "country": "address.country",
    "street": "address.streetLines[0]",
}


def build_update_body(fields: dict) -> dict:
    """Map snake_case editable fields to the Localith PATCH body shape."""
    body: dict = {}
    for key, value in fields.items():
        prop = UPDATABLE_FIELDS.get(key)
        if prop is None or value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        body[prop] = value.strip() if isinstance(value, str) else value
    return body


def update_listing(listing_id: str, fields: dict) -> dict:
    """Update a listing's editable profile fields. Returns the API response."""
    body = build_update_body(fields)
    if not body:
        raise ValueError("No updatable fields provided.")
    payload = _patch(
        f"rest/v1/listings/{urllib.parse.quote(listing_id, safe='')}", body
    )
    return payload if isinstance(payload, dict) else {}


def fetch_listings() -> list[dict]:
    """Pull connected locations / listings."""
    base, key, _ = _config()
    payload = _get("rest/v1/listings", {})
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []


def fetch_listing_detail(listing_id: str) -> dict:
    """Pull one listing with the full profile snapshot.

    Live shape (2026-09): id, googleId, name, storeCode, url, isVerified,
    isDisabled, isSuspended, phoneNumber, address, websiteUrl, totalReviews,
    averageRating, lastReviewOn, lastReplyOn.
    """
    payload = _get(f"rest/v1/listings/{urllib.parse.quote(listing_id, safe='')}", {})
    if isinstance(payload, dict):
        return payload
    return {}


def normalize_listing(raw: dict) -> dict:
    """Map a raw listing payload to Sayvors' snake_case snapshot shape.

    Tolerates camelCase (googleId) and snake_case (google_id) variants.
    Unknown extra keys are kept inside ``raw`` by the caller, not here.
    """
    return {
        "listing_id": str(raw.get("id") or raw.get("listing_id") or ""),
        "google_id": raw.get("googleId") or raw.get("google_id"),
        "name": raw.get("name"),
        "store_code": raw.get("storeCode") or raw.get("store_code"),
        "maps_url": raw.get("url"),
        "is_verified": raw.get("isVerified", raw.get("is_verified")),
        "is_disabled": raw.get("isDisabled", raw.get("is_disabled")),
        "is_suspended": raw.get("isSuspended", raw.get("is_suspended")),
        "phone_number": raw.get("phoneNumber") or raw.get("phone_number"),
        "address": raw.get("address"),
        "website_url": raw.get("websiteUrl") or raw.get("website_url"),
        "total_reviews": raw.get("totalReviews", raw.get("total_reviews", 0)),
        "average_rating": raw.get("averageRating", raw.get("average_rating", 0.0)),
        "last_review_on": raw.get("lastReviewOn") or raw.get("last_review_on"),
        "last_reply_on": raw.get("lastReplyOn") or raw.get("last_reply_on"),
    }


def _ddmmyyyy(value) -> str:
    """Format a date/datetime/ISO string as DD-MM-YYYY for the metrics endpoints."""
    import datetime as _dt

    if isinstance(value, (_dt.datetime, _dt.date)):
        d = value
    else:
        d = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if isinstance(d, _dt.datetime):
            d = d.date()
    return d.strftime("%d-%m-%Y")


def fetch_listing_metrics(
    start,
    end,
    listing_id: str | None = None,
    page_size: int = 100,
) -> dict:
    """Daily performance metrics summarized over [start, end].

    Returns ``{"dateRange": {...}, "listings": [...]}`` where each listing row
    carries googleMapsDesktop/Mobile, googleSearchDesktop/Mobile, messages,
    directions, callClicks, websiteClicks, bookings, foodOrders,
    foodMenuClicks, numPublishedPosts, avgPostingTime, avgReviewResponseTime,
    reviewResponsePercentage.
    """
    params: dict = {
        "startDate": _ddmmyyyy(start),
        "endDate": _ddmmyyyy(end),
        "pageSize": page_size,
    }
    if listing_id:
        params["sourceId"] = listing_id
    payload = _get("rest/v1/listing_metrics", params)
    return payload if isinstance(payload, dict) else {}


def fetch_item_metrics(
    start,
    end,
    listing_id: str | None = None,
    page_size: int = 100,
) -> dict:
    """Review metrics summarized over [start, end].

    Each listing row carries numberOfReviews, averageRating, per-star counts,
    numberReplies, latestReviewOn, positive/neutral/negative splits and
    yesterday/week/month/year counts.
    """
    params: dict = {
        "startDate": _ddmmyyyy(start),
        "endDate": _ddmmyyyy(end),
        "pageSize": page_size,
    }
    if listing_id:
        params["sourceId"] = listing_id
    payload = _get("rest/v1/listing_item_metrics", params)
    return payload if isinstance(payload, dict) else {}


# Back-compat name used by the spike runner
def fetch_reviews(limit: int = 50) -> list[dict]:
    return fetch_items(limit=limit)


def _to_int_rating(value) -> int:
    try:
        rating = int(float(value))
    except (TypeError, ValueError):
        return 5
    return max(1, min(5, rating))


def to_internal_review(item: dict) -> InternalReview:
    """Map one Localith review item to our unified shape.

    Field names fall back through common variants so the spike prints
    something useful on first run; once we have a sample response we
    tighten the picks.
    """
    reviewer = item.get("reviewer") or item.get("author") or {}
    if isinstance(reviewer, dict):
        reviewer_name = (
            reviewer.get("name")
            or reviewer.get("displayName")
            or reviewer.get("display_name")
            or reviewer.get("full_name")
            or reviewer.get("author_name")
        )
    else:
        reviewer_name = reviewer or None
    if not reviewer_name:
        reviewer_name = (
            item.get("reviewer_name")
            or item.get("reviewerName")
            or item.get("author_name")
            or item.get("authorName")
        )

    published_at = (
        item.get("created_at")
        or item.get("originalCreatedOn")
        or item.get("createdOn")
        or item.get("publishedOn")
        or item.get("reviewCreatedOn")
        or item.get("date")
        or item.get("timestamp")
    )

    return InternalReview(
        external_id=str(
            item.get("id") or item.get("review_id") or item.get("uid") or ""
        ),
        platform=str(
            item.get("source") or item.get("platform") or "google_reviews"
        ).lower(),
        rating=_to_int_rating(
            item.get("rating") or item.get("stars") or item.get("starRating") or 5
        ),
        text=(
            item.get("text")
            or item.get("captionText")
            or item.get("caption")
            or item.get("comment")
            or item.get("message")
            or item.get("review_text")
            or item.get("reviewText")
            or item.get("body")
            or item.get("content")
        ),
        reviewer=reviewer_name,
        published_at=published_at,
        source_name=item.get("location") or item.get("page") or item.get("account"),
        review_url=(
            item.get("reviewLink")
            or item.get("review_url")
            or item.get("reviewUrl")
            or item.get("url")
        ),
        has_replies=bool(item.get("replies")),
        raw=item,
    )
