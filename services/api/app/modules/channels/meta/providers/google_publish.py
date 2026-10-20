"""Google Business Profile (GBP) local-post publisher.

GBP does not have a "feed post" in the Meta sense. The equivalent is a
``localPost`` created via:

    POST /v1/accounts/{accountId}/locations/{locationId}/localPosts

A STANDARD local post carries a summary (caption) and optionally a photo
and a call-to-action. Scheduled publishing is done by setting
``scheduledPublishTime`` in the payload (RFC3339 timestamp).

This adapter mirrors the shape of the Meta adapters so the job runner can
treat every destination uniformly: one ``publish_post`` call per
(destination, method) job.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .....config import settings
from ...google_reviews import GoogleReviewsClient, GoogleReviewsError

logger = logging.getLogger(__name__)

GBP_LOCAL_POSTS_API = "https://mybusiness.googleapis.com/v1"

# Location photos live in the v4.9 Business Profile API — v1 has no media
# resource. Both versions are served from the same host and take the same
# OAuth token, so the two are used side by side: v1 for local posts, v4.9
# for the profile picture and cover image.
GBP_MEDIA_API = "https://mybusiness.googleapis.com/v4"

# The method -> the location media category Google stores it under.
# PROFILE and COVER are the two surfaces that belong to the location
# itself rather than to a post; a location has exactly one of each.
_LOCATION_IMAGE_CATEGORY = {
    "profile": "PROFILE",
    "banner": "COVER",
}


class GoogleBusinessPublisher:
    """Publish a post to a Google Business Profile location.

    Wraps ``GoogleReviewsClient`` for OAuth + token refresh, but calls the
    Business Information API's localPosts endpoint directly.
    """

    provider = "google_reviews"

    def __init__(self, access_token: str, refresh_token: str | None = None):
        self._client = GoogleReviewsClient(access_token, refresh_token)

    def set_token_persister(self, persister) -> None:
        self._client.set_token_persister(persister)

    def set_known_expiry(self, expires_at) -> None:
        self._client.set_known_expiry(expires_at)

    async def close(self) -> None:
        await self._client.close()

    async def publish_post(
        self,
        token: str,
        asset_id: str,
        method: str,
        media_url: str | None,
        media_type: str | None,
        caption: str,
        description: str,
        scheduled_at: str | None,
        account_id: str | None = None,
    ) -> dict:
        """Publish one post to one GBP location.

        ``asset_id`` is the location_id (e.g. "locations/123" or bare "123").
        ``account_id`` is the Google account id (e.g. "accounts/456").
        ``method`` maps to a Google topicType:
            "update" → STANDARD (What's New)
            "event"  → EVENT
            "offer"  → OFFER

        Returns a dict with at least ``{"id": ..., "name": ...}`` on success.
        Raises ``GoogleReviewsError`` on failure.
        """
        _METHOD_TO_TOPIC = {
            "update": "STANDARD",
            "event": "EVENT",
            "offer": "OFFER",
            # "post" is the legacy alias for What's New, kept so jobs
            # created before the method split still publish.
            "post": "STANDARD",
        }
        topic_type = _METHOD_TO_TOPIC.get(method)
        if topic_type is None:
            raise GoogleReviewsError(
                f"GBP supports 'update', 'event' or 'offer', got {method!r}", 400
            )

        account = (account_id or "").strip()
        location = (asset_id or "").strip()
        if not account:
            raise GoogleReviewsError("account_id is required for GBP publish", 400)
        if not location:
            raise GoogleReviewsError("location_id is required for GBP publish", 400)

        # Normalise to full resource names.
        if "/" not in account:
            account = f"accounts/{account}"
        if "/" not in location:
            location = f"locations/{location}"

        body: dict[str, Any] = {
            "topicType": topic_type,
            "languageCode": "en",
        }
        summary = (caption or description or "").strip()
        if summary:
            body["summary"] = summary[:1500]

        if media_url:
            body["media"] = [
                {
                    "mediaFormat": "PHOTO" if (media_type or "image") == "image" else "VIDEO",
                    "sourceUrl": media_url,
                }
            ]

        # EVENT posts require an event object with a title and a start
        # date. The composer does not collect dates yet, so default to a
        # 7-day window from now — Google rejects a bare STANDARD payload
        # with topicType EVENT.
        if topic_type == "EVENT":
            from datetime import timedelta

            now = datetime.now(timezone.utc)
            end = now + timedelta(days=7)
            body["event"] = {
                "title": (summary[:60] if summary else "Event"),
                "startDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDate": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        # OFFER posts require at least one of couponCode, redeemOnlineUrl,
        # termsConditions, or description. Send description + terms so the
        # offer renders even without a coupon code.
        if topic_type == "OFFER":
            body["offer"] = {
                "description": (summary[:300] if summary else ""),
                "termsConditions": (description or "Terms apply")[:300],
            }

        if scheduled_at:
            try:
                dt = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                body["scheduledPublishTime"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                logger.warning("invalid scheduled_at %r - publishing immediately", scheduled_at)

        url = (
            f"https://mybusiness.googleapis.com/v1/"
            f"{account}/{location}/localPosts"
        )
        resp = await self._client._authed_request("POST", url, json=body)
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"create_local_post failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return {
            "id": data.get("name", ""),
            "name": data.get("name", ""),
            "topicType": data.get("topicType"),
            "state": data.get("state"),
            "searchUrl": data.get("searchUrl"),
        }

    async def set_location_image(
        self,
        token: str,
        asset_id: str,
        method: str,
        media_url: str,
        account_id: str | None = None,
    ) -> dict:
        """Replace a location's profile picture or cover image.

        Google stores both as location media:
        ``POST /v4/{parent=accounts/*/locations/*}/media`` with
        ``locationAssociation.category`` set to ``PROFILE`` or ``COVER``.
        A location has exactly one of each, and the profile picture is
        filed under a fixed resource name
        (``.../locations/{id}/media/profile``), so creating the media
        item replaces what was there — no separate delete first, which
        would leave the location with no picture if the upload failed.

        ``asset_id`` is the location id; ``account_id`` is the Google
        account id.
        """
        category = _LOCATION_IMAGE_CATEGORY.get(method)
        if category is None:
            raise GoogleReviewsError(
                f"GBP location images are 'profile' or 'banner', got {method!r}", 400
            )
        if not media_url:
            raise GoogleReviewsError("a location image needs a media URL", 400)

        account = (account_id or "").strip()
        location = (asset_id or "").strip()
        if not account:
            raise GoogleReviewsError("account_id is required for GBP publish", 400)
        if not location:
            raise GoogleReviewsError("location_id is required for GBP publish", 400)
        if "/" not in account:
            account = f"accounts/{account}"
        if "/" not in location:
            location = f"locations/{location}"

        body: dict[str, Any] = {
            "mediaFormat": "PHOTO",
            "locationAssociation": {"category": category},
            "sourceUrl": media_url,
        }
        url = f"{GBP_MEDIA_API}/{account}/{location}/media"
        resp = await self._client._authed_request("POST", url, json=body)
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"create_location_media failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return {
            "id": data.get("name", ""),
            "name": data.get("name", ""),
            "category": (data.get("locationAssociation") or {}).get("category"),
            "googleUrl": data.get("googleUrl", ""),
        }

    async def delete_post(self, token: str, post_id: str) -> dict:
        """Delete a Google Business Profile local post.

        ``post_id`` is the full resource name returned by publish_post
        (e.g. "accounts/123/locations/456/localPosts/789").
        """
        if not post_id:
            raise GoogleReviewsError("post_id is required for delete", 400)

        # Accept both full resource names and bare ids.
        if "/" not in post_id:
            raise GoogleReviewsError(
                "post_id must be the full localPost resource name", 400
            )

        url = f"https://mybusiness.googleapis.com/v1/{post_id}"
        resp = await self._client._authed_request("DELETE", url)
        if resp.status_code not in (200, 204):
            raise GoogleReviewsError(
                f"delete_local_post failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return {"deleted": True, "platform": "google_reviews", "post_id": post_id}