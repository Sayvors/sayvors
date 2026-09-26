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
    reviewer_photo: str | None = None
    published_at: str | None = None
    source_name: str | None = None
    review_url: str | None = None
    has_replies: bool = False
    # The business's live reply, as the provider reports it. Localith/EmbedSocial
    # returns the full reply array on every review payload; we used to collapse
    # it to `has_replies` and throw the text away, which left every review
    # answered outside Sayvors with no editable response on file.
    reply_text: str | None = None
    reply_external_id: str | None = None
    reply_published_at: str | None = None
    # Photos the reviewer attached, when the provider supplies them. Localith's
    # /rest/v1/items payload carries no media today (verified against the live
    # API: no media field, and /items/{id}/media 404s), so this stays empty on
    # this provider. Parsed defensively so a future payload change is picked up
    # without another adapter change.
    media: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _photo_http_url(value) -> str | None:
    if isinstance(value, str) and value.startswith("http"):
        return value
    return None


def _config(key_override: str | None = None) -> tuple[str, str, str]:
    # key_override: per-connection key (decrypted) — wins over env/settings.
    key = key_override or os.environ.get("LOCALITH_API_KEY", "")
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


def _get(path: str, params: dict | None = None, timeout: int = 30, api_key: str | None = None) -> dict | list:
    base, key, _ = _config(api_key)
    url = _http_url(f"{base}/{path.lstrip('/')}")
    resp = httpx.get(
        url,
        params=params or {},
        headers={**_HEADERS, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def post_item_reply(item_id: str, text: str, timeout: int = 30, api_key: str | None = None) -> dict:
    """Create a reply for a review item: POST /rest/v1/items/{id}/replies.

    Localith is a Google Business Profile partner, so this reply goes
    live on the connected listing. Body contract (confirmed live against
    the API and per the official docs): {"comment": "<reply text>"}.
    Returns the created reply: {id, comment, updateTime}.
    """
    base, key, _ = _config(api_key)
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


def fetch_items(limit: int = 50, listing_id: str | None = None, api_key: str | None = None) -> list[dict]:
    """Pull synced review items. Returns raw items as returned by Localith.

    Uses the official query params (page/pageSize/sourceId/sort). ``limit``
    is split across pages of at most 100.
    """
    _base, _key, items_path = _config(api_key)
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


def fetch_all_items(listing_id: str | None = None, max_pages: int = 50, api_key: str | None = None) -> list[dict]:
    """Pull every review item, following pages until a short/empty page."""
    _base, _key, items_path = _config(api_key)
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


def _post(path: str, body: dict, timeout: int = 60, api_key: str | None = None) -> dict | list:
    base, key, _ = _config(api_key)
    url = _http_url(f"{base}/{path.lstrip('/')}")
    resp = httpx.post(
        url,
        json=body,
        headers={**_HEADERS, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    try:
        resp.raise_for_status()
    except Exception as e:
        # Localith returns the useful part (which field, what limit) in
        # the body — never swallow it into a bare status code, or every
        # publish failure becomes undebuggable.
        detail = (resp.text or "").strip().replace("\n", " ")[:500]
        raise RuntimeError(
            f"Localith rejected {path} (HTTP {resp.status_code})"
            + (f": {detail}" if detail else "")
        ) from e
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
    start_date: str | None = None,
    end_date: str | None = None,
    voucher_code: str | None = None,
    extra: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """Publish (or schedule) a Google post through Localith.

    Body shape per the official n8n node: type (update/event/offer),
    sourceIds, captionText, title, imageUrls, ctaType, ctaUrl,
    scheduledOn, startDate/endDate, voucherCode. Only http(s) image URLs
    are accepted — local filenames must be filtered by the caller.
    start_date/end_date drive the event/offer lifecycle on Google: Google
    takes ended posts down by itself, which is the only Google-side
    removal lever available (Localith exposes no post delete).
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
    if start_date:
        body["startDate"] = start_date
    if end_date:
        body["endDate"] = end_date
    if voucher_code:
        body["voucherCode"] = voucher_code
    if extra:
        body.update(extra)
    payload = _post("rest/v1/content_publishing_media", body, api_key=api_key)
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


def fetch_listings(api_key: str | None = None) -> list[dict]:
    """Pull connected locations / listings."""
    base, key, _ = _config(api_key)
    payload = _get("rest/v1/listings", {}, api_key=api_key)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []


def fetch_listing_detail(listing_id: str, api_key: str | None = None) -> dict:
    """Pull one listing with the full profile snapshot.

    Live shape (2026-09): id, googleId, name, storeCode, url, isVerified,
    isDisabled, isSuspended, phoneNumber, address, websiteUrl, totalReviews,
    averageRating, lastReviewOn, lastReplyOn.
    """
    payload = _get(f"rest/v1/listings/{urllib.parse.quote(listing_id, safe='')}", {}, api_key=api_key)
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


def fetch_listing_metrics_for_day(listing_id: str, day) -> dict:
    """Single-day performance numbers for one listing.

    Calls listing_metrics with startDate == endDate == day and parses the
    first listing row into daily ints. Returns zeros on any shape surprise
    (missing listing, empty payload) — the caller treats zeros as "no data"
    for that day, never as failure, so one odd day can't break a backfill.
    """
    try:
        payload = fetch_listing_metrics(day, day, listing_id)
    except Exception:
        return _empty_day()
    rows = payload.get("listings") if isinstance(payload, dict) else None
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}

    def _int(*keys: str) -> int:
        total = 0
        for key in keys:
            try:
                total += int(row.get(key) or 0)
            except (TypeError, ValueError):
                pass
        return total

    return {
        "impressions_maps_desktop": _int("googleMapsDesktop"),
        "impressions_maps_mobile": _int("googleMapsMobile"),
        "impressions_search": _int("googleSearchDesktop", "googleSearchMobile"),
        "website_clicks": _int("websiteClicks"),
        "call_clicks": _int("callClicks"),
        "direction_requests": _int("directions"),
        "messages": _int("messages"),
        "bookings": _int("bookings"),
    }


def _empty_day() -> dict:
    return {
        "impressions_maps_desktop": 0,
        "impressions_maps_mobile": 0,
        "impressions_search": 0,
        "website_clicks": 0,
        "call_clicks": 0,
        "direction_requests": 0,
        "messages": 0,
        "bookings": 0,
    }


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


def _latest_reply(item: dict) -> dict | None:
    """Pick the newest reply the provider reports for a review.

    Localith returns `replies: [{id, text, createdOn}]`. A review can carry more
    than one (owner + other users), so the most recent `createdOn` wins — that
    is the reply currently live on the listing. Entries may also be bare
    strings in older payloads.
    """
    replies = item.get("replies") or item.get("repliesList") or []
    if not isinstance(replies, (list, tuple)):
        return None

    def _sort_key(entry):
        if not isinstance(entry, dict):
            return ("", 0)
        return (
            str(
                entry.get("createdOn")
                or entry.get("created_on")
                or entry.get("publishedOn")
                or entry.get("updatedOn")
                or ""
            ),
            # Undated entries: the provider appends in order, so the later
            # element is the newer reply. Without this, max() would keep the
            # first one and we'd show the oldest reply as current.
            replies.index(entry),
        )

    if not replies:
        return None
    return max(replies, key=_sort_key)


def _reply_field(entry, *keys, bare_string: bool = False) -> str | None:
    """Read the first non-empty key off a reply entry.

    `bare_string` allows legacy payloads where a reply is just a string. It is
    opt-in per call so a bare string can never be mistaken for an id or date.
    """
    if isinstance(entry, str):
        return entry.strip() or None if bare_string else None
    if not isinstance(entry, dict):
        return None
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_item_media(item: dict) -> list[dict]:
    """Pull reviewer-attached photos off a review payload, if any.

    Localith returns none today, so this yields [] in practice. Kept
    defensive (every field optional, never raises) so that if they start
    shipping photos the sync picks them up instead of silently dropping them
    again — which is exactly how the reply text was lost.
    """
    out: list[dict] = []
    for key in ("media", "mediaItems", "photos", "images", "reviewMediaItems"):
        raw = item.get(key)
        if not isinstance(raw, (list, tuple)):
            continue
        for entry in raw:
            if isinstance(entry, str) and entry.strip():
                out.append({
                    "thumbnail_url": entry.strip(),
                    "video_url": None,
                    "label": None,
                    "kind": "image",
                })
            elif isinstance(entry, dict):
                thumb = (
                    entry.get("thumbnailUrl") or entry.get("url")
                    or entry.get("imageUrl") or entry.get("src")
                )
                video = entry.get("videoUrl") or entry.get("video_url")
                if not thumb and not video:
                    continue
                out.append({
                    "thumbnail_url": thumb,
                    "video_url": video,
                    "label": entry.get("thumbnailLabel") or entry.get("label"),
                    "kind": "video" if video else "image",
                })
        if out:
            break
    return out


def to_internal_review(item: dict) -> InternalReview:
    """Map one Localith review item to our unified shape.

    Field names fall back through common variants so the spike prints
    something useful on first run; once we have a sample response we
    tighten the picks.
    """
    reviewer = item.get("reviewer") or item.get("author") or {}
    reviewer_photo = None
    if isinstance(reviewer, dict):
        reviewer_name = (
            reviewer.get("name")
            or reviewer.get("displayName")
            or reviewer.get("display_name")
            or reviewer.get("full_name")
            or reviewer.get("author_name")
        )
        # Localith reviewer photos (when the upstream payload carries one).
        for key in ("photo", "photoUrl", "photo_url", "avatar",
                    "avatarUrl", "avatar_url", "profilePhoto",
                    "profile_photo", "profilePhotoUrl",
                    "profile_photo_url"):
            reviewer_photo = _photo_http_url(reviewer.get(key))
            if reviewer_photo:
                break
    else:
        reviewer_name = reviewer or None
    if not reviewer_name:
        reviewer_name = (
            item.get("reviewer_name")
            or item.get("reviewerName")
            or item.get("author_name")
            or item.get("authorName")
        )
    if reviewer_photo is None:
        for key in ("reviewer_photo", "reviewerPhoto", "author_photo",
                    "authorPhoto"):
            reviewer_photo = _photo_http_url(item.get(key))
            if reviewer_photo:
                break

    published_at = (
        item.get("created_at")
        or item.get("originalCreatedOn")
        or item.get("createdOn")
        or item.get("publishedOn")
        or item.get("reviewCreatedOn")
        or item.get("date")
        or item.get("timestamp")
    )

    latest_reply = _latest_reply(item)

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
        reviewer_photo=reviewer_photo,
        published_at=published_at,
        source_name=item.get("location") or item.get("page") or item.get("account"),
        review_url=(
            item.get("reviewLink")
            or item.get("review_url")
            or item.get("reviewUrl")
            or item.get("url")
        ),
        has_replies=bool(latest_reply),
        reply_text=_reply_field(
            latest_reply, "text", "body", "content", "message", "comment",
            bare_string=True,
        ),
        reply_external_id=_reply_field(
            latest_reply, "id", "replyId", "reply_id",
        ),
        reply_published_at=_reply_field(
            latest_reply, "createdOn", "created_on", "publishedOn", "updatedOn",
        ),
        media=_parse_item_media(item),
        raw=item,
    )
