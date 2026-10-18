"""EmbedSocial API integration (stub).

This module provides the EmbedSocial / Localith integration surface that the
app expects. Without a real EmbedSocial account these functions raise
informative errors instead of silently failing — the tenant must configure
LOCALITH_API_KEY and reachable EmbedSocial endpoints before any Localith
flow can succeed.

All functions are synchronous; callers wrap them in asyncio.to_thread.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

EMBEDSOCIAL_BASE_URL = "https://embedsocial.com/app/api"


class EmbedSocialError(RuntimeError):
    """Raised when the EmbedSocial API is misconfigured or unreachable."""


def _require_api_key(api_key: str | None) -> str:
    if not api_key:
        raise EmbedSocialError(
            "EmbedSocial integration is not configured: set LOCALITH_API_KEY in .env "
            "and pass a per-connection API key."
        )
    return api_key


# ── Listings ─────────────────────────────────────────────────────────

def fetch_listings(api_key: str | None = None) -> list[dict]:
    """List Localith listings for the configured account."""
    _require_api_key(api_key)
    raise EmbedSocialError("EmbedSocial fetch_listings not implemented without a live account.")


def fetch_items(limit: int = 50, listing_id: str | None = None, api_key: str | None = None) -> list[dict]:
    """List Localith review items for one listing."""
    _require_api_key(api_key)
    raise EmbedSocialError("EmbedSocial fetch_items not implemented without a live account.")


def fetch_listing_detail(listing_id: str, api_key: str | None = None) -> dict:
    """Fetch the full profile snapshot for one listing."""
    _require_api_key(api_key)
    raise EmbedSocialError("EmbedSocial fetch_listing_detail not implemented without a live account.")


# ── Reviews ──────────────────────────────────────────────────────────

def post_item_reply(
    item_id: str, text: str, timeout: int = 30, api_key: str | None = None
) -> dict:
    """Publish a reply to a review item through Localith."""
    _require_api_key(api_key)
    raise EmbedSocialError("EmbedSocial post_item_reply not implemented without a live account.")


def to_internal_review(item: dict) -> dict:
    """Normalize a raw EmbedSocial review item into the app's internal shape."""
    return {
        "id": item.get("id") or item.get("review_id"),
        "listing_id": item.get("listing_id"),
        "rating": item.get("rating"),
        "text": item.get("text") or item.get("review_text"),
        "reviewer": item.get("reviewer") or item.get("author"),
        "reviewer_avatar": item.get("reviewer_avatar"),
        "created_at": item.get("created_at") or item.get("date"),
        "platform": item.get("platform", "google"),
        "replied": bool(item.get("replied")),
        "reply_text": item.get("reply_text"),
        "source": "embedsocial",
    }


# ── Listing metadata ─────────────────────────────────────────────────

def normalize_listing(raw: dict) -> dict:
    """Normalize a raw EmbedSocial listing detail into the app's field names."""
    return {
        "name": raw.get("name") or raw.get("title"),
        "google_id": raw.get("google_id") or raw.get("place_id"),
        "address": raw.get("address"),
        "phone_number": raw.get("phone_number") or raw.get("phone"),
        "website_url": raw.get("website_url") or raw.get("website"),
        "maps_url": raw.get("maps_url"),
        "store_code": raw.get("store_code"),
        "is_verified": raw.get("is_verified"),
        "is_disabled": raw.get("is_disabled"),
        "is_suspended": raw.get("is_suspended"),
        "total_reviews": raw.get("total_reviews", 0),
        "average_rating": raw.get("average_rating", 0.0),
        "last_review_on": raw.get("last_review_on"),
        "last_reply_on": raw.get("last_reply_on"),
    }


def update_listing(listing_id: str, fields: dict) -> dict:
    """Update listing fields on EmbedSocial."""
    raise EmbedSocialError("EmbedSocial update_listing not implemented without a live account.")


def fetch_all_items(listing_id: str, limit: int = 50, api_key: str | None = None) -> list[dict]:
    """Fetch all review items for a listing (paginated internally)."""
    _require_api_key(api_key)
    raise EmbedSocialError("EmbedSocial fetch_all_items not implemented without a live account.")


# ── Publishing ───────────────────────────────────────────────────────

def publish_media_post(
    listing_id: str,
    *,
    post_type: str = "update",
    title: str | None = None,
    caption: str | None = None,
    image_urls: list[str] | None = None,
    cta_type: str | None = None,
    cta_url: str | None = None,
    scheduled_on: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    voucher_code: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Publish a post (with optional media) to a Localith-managed Google Profile."""
    _require_api_key(api_key)
    raise EmbedSocialError("EmbedSocial publish_media_post not implemented without a live account.")


# ── Metrics ──────────────────────────────────────────────────────────

def fetch_listing_metrics(start, end, listing_id: str) -> dict:
    """Fetch aggregate metrics for a listing over a date range."""
    raise EmbedSocialError("EmbedSocial fetch_listing_metrics not implemented without a live account.")


def fetch_item_metrics(start, end, listing_id: str) -> dict:
    """Fetch per-item metrics for a listing over a date range."""
    raise EmbedSocialError("EmbedSocial fetch_item_metrics not implemented without a live account.")


def fetch_listing_metrics_for_day(listing_id: str, day: date | str) -> dict:
    """Fetch metrics for a single listing on a single day."""
    raise EmbedSocialError("EmbedSocial fetch_listing_metrics_for_day not implemented without a live account.")
