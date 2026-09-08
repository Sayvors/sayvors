"""Localith reviews adapter (SPIKE — embedsocial branch only).

Localith is an authorized Google Business Profile partner that exposes a
read-first REST API for reviews, listings, metrics, and posts. We use it
as a middleware today so we can read GBP data without a per-tenant
Google approval; once native Google API access lands, the same shape
goes to the Google adapter.

Endpoint map (from the public Localith n8n community node source):
    https://raw.githubusercontent.com/localithai/n8n-nodes-localith/main/nodes/Localith/Localith.node.ts
    baseURL: https://embedsocial.com/app/api
    items:            /rest/v1/items           (individual reviews)
    listings:         /rest/v1/listings        (connected locations)
    listing_metrics:  /rest/v1/listing_metrics (needs query params)
    item_metrics:     /rest/v1/listing_item_metrics
    publish_media:    /rest/v1/content_publishing_media (POST only)

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
import urllib.request
from dataclasses import dataclass, field


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


def _get(path: str, params: dict | None = None, timeout: int = 30) -> dict | list:
    base, key, _ = _config()
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "sayvors-spike/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def fetch_items(limit: int = 50, listing_id: str | None = None) -> list[dict]:
    """Pull synced review items. Returns raw items as returned by Localith."""
    _base, _key, items_path = _config()
    params: dict = {"limit": limit, "page": 1}
    if listing_id:
        params["listing_id"] = listing_id
    payload = _get(items_path, params)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for envelope in ("data", "items", "results", "reviews"):
            if isinstance(payload.get(envelope), list):
                return payload[envelope]
        return []
    return []


def fetch_listings() -> list[dict]:
    """Pull connected locations / listings."""
    base, key, _ = _config()
    payload = _get("rest/v1/listings", {})
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []


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
            or reviewer.get("full_name")
        )
    else:
        reviewer_name = reviewer or None

    return InternalReview(
        external_id=str(
            item.get("id") or item.get("review_id") or item.get("uid") or ""
        ),
        platform=str(
            item.get("source") or item.get("platform") or "google_reviews"
        ).lower(),
        rating=_to_int_rating(item.get("rating") or item.get("stars") or 5),
        text=item.get("text") or item.get("comment") or item.get("message"),
        reviewer=reviewer_name,
        published_at=item.get("created_at") or item.get("date") or item.get("timestamp"),
        source_name=item.get("location") or item.get("page") or item.get("account"),
        raw=item,
    )
