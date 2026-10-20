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
        ``method`` is "post" (only supported method for GBP).

        Returns a dict with at least ``{"id": ..., "name": ...}`` on success.
        Raises ``GoogleReviewsError`` on failure.
        """
        if method not in {"post"}:
            raise GoogleReviewsError(
                f"GBP supports only 'post' method, got {method!r}", 400
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
            "topicType": "STANDARD",
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