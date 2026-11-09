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

GBP_LOCAL_POSTS_API = "https://mybusiness.googleapis.com/v4"

# Location photos live in the v4.9 Business Profile API — v1 has no media
# resource. Both versions are served from the same host and take the same
# OAuth token, so the two are used side by side: v1 for local posts, v4.9
# for the profile picture and cover image.
GBP_MEDIA_API = "https://mybusiness.googleapis.com/v4"

# Direct binary upload endpoint (media.startUpload hands back a resourceName
# that is posted to here). Used instead of a public sourceUrl so location
# media needs no S3/GCS bucket.
GBP_MEDIA_UPLOAD_API = "https://mybusiness.googleapis.com/upload/v1/media"

# The method -> the location media category Google stores it under.
# PROFILE and COVER are the two surfaces that belong to the location
# itself rather than to a post; a location has exactly one of each.
_LOCATION_IMAGE_CATEGORY = {
    "profile": "PROFILE",
    "banner": "COVER",
}


def _parse_google_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
        *,
        media_urls: list[str] | None = None,
        cta_type: str | None = None,
        cta_url: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        coupon_code: str | None = None,
        terms_conditions: str | None = None,
        tenant_id: str | None = None,
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

        urls = [u for u in (media_urls or ([media_url] if media_url else [])) if u]
        original_media = [
            {
                "mediaFormat": "PHOTO" if (media_type or "image") == "image" else "VIDEO",
                "sourceUrl": u,
            }
            for u in urls[:10]
        ]
        used_staging = False
        if urls:
            media_items: list[dict[str, str]] = []
            for original, url in zip(original_media, urls[:10]):
                source = url
                if (
                    settings.GOOGLE_POST_MEDIA_STAGING
                    and (media_type or "image") == "image"
                ):
                    try:
                        # Resolve the stored/external URL back to bytes, then
                        # let Google host them. A Sayvors /media-files URL is
                        # read straight from our own storage (no HTTP fetch).
                        from .....core.storage import media_bytes_from_url

                        data, ctype = media_bytes_from_url(tenant_id, url)
                        hosted, _name = await self.stage_post_image(
                            account, location, data, ctype or "image/jpeg"
                        )
                        source = hosted
                        used_staging = True
                    except Exception as e:  # noqa: BLE001 — staging is best effort
                        logger.warning(
                            "Could not stage post image on Google (%s); "
                            "falling back to sourceUrl %s",
                            e, url[:120],
                        )
                item = dict(original)
                item["sourceUrl"] = source
                media_items.append(item)
            body["media"] = media_items

        # EVENT posts require an event object with a title and a start date.
        if topic_type == "EVENT":
            from datetime import timedelta

            now = datetime.now(timezone.utc)
            start = _parse_google_dt(start_date) or now
            end = _parse_google_dt(end_date) or (start + timedelta(days=7))
            body["event"] = {
                "title": (summary[:60] if summary else "Event"),
                "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDate": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        # OFFER posts carry a coupon / redeem link and terms.
        if topic_type == "OFFER":
            offer: dict[str, Any] = {
                "description": (summary[:300] if summary else ""),
                "termsConditions": (terms_conditions or "Terms apply")[:300],
            }
            if coupon_code:
                offer["couponCode"] = coupon_code[:64]
            if cta_url:
                offer["redeemOnlineUrl"] = cta_url[:1000]
            body["offer"] = offer

        cta_map = {
            "book": "BOOK", "order": "ORDER", "shop": "SHOP",
            "learn_more": "LEARN_MORE", "sign_up": "SIGN_UP", "call": "CALL",
        }
        action = cta_map.get((cta_type or "").strip().lower())
        if action and cta_url and topic_type != "OFFER":
            body["callToAction"] = {"actionType": action, "url": cta_url[:1000]}

        if scheduled_at:
            try:
                dt = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                body["scheduledPublishTime"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                logger.warning("invalid scheduled_at %r - publishing immediately", scheduled_at)

        url = f"{GBP_LOCAL_POSTS_API}/{account}/{location}/localPosts"
        post_body = body
        resp = await self._client._authed_request("POST", url, json=body)
        if resp.status_code not in (200, 201) and used_staging:
            # Google can reject its own googleUrl as a post sourceUrl (a
            # deterministic 500 INTERNAL — staged media is still PENDING).
            # Staging is an optimisation, so retry once with the caller's
            # original URL before giving up.
            logger.warning(
                "create_local_post with staged Google media failed (%s); "
                "retrying once with the original sourceUrl",
                resp.status_code,
            )
            fallback = dict(body)
            fallback["media"] = original_media
            post_body = fallback
            resp = await self._client._authed_request("POST", url, json=fallback)
        if resp.status_code not in (200, 201):
            # Keep the whole ValidationError body: the useful part (which
            # field Google rejected) lives well past 300 chars. Log the body
            # that actually failed, not the first attempt's body.
            detail = resp.text[:2000]
            logger.warning(
                "create_local_post failed (%s): %s | request=%s",
                resp.status_code, detail, str(post_body)[:800],
            )
            raise GoogleReviewsError(
                f"create_local_post failed ({resp.status_code}): {detail}",
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

    async def start_media_upload(self, account_id: str, location_id: str) -> str:
        """`media:startUpload` -> the resourceName used to upload bytes.

        The upload is tied to the location, so the bytes must belong to a
        media item for the same location that `set_location_image` creates.
        """
        account = (account_id or "").strip()
        location = (location_id or "").strip()
        if "/" not in account:
            account = f"accounts/{account}"
        if "/" not in location:
            location = f"locations/{location}"
        url = f"{GBP_MEDIA_API}/{account}/{location}/media:startUpload"
        # The API requires an empty request body; sending `{}` is not the
        # same thing and some versions reject it.
        resp = await self._client._authed_request("POST", url)
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"startUpload failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json() or {}
        # The reference says the body is a bare MediaItemDataRef; some
        # versions wrap it in `dataRef`. Accept both rather than condemning
        # a successful upload.
        ref = (
            data.get("resourceName")
            or (data.get("dataRef") or {}).get("resourceName")
            or ""
        ).strip()
        if not ref:
            raise GoogleReviewsError(
                f"startUpload returned no resourceName: {str(data)[:200]}", 502
            )
        return ref

    async def upload_media_bytes(
        self, resource_name: str, data: bytes, content_type: str
    ) -> None:
        """POST the raw image bytes to Google's media upload endpoint."""
        base = f"{GBP_MEDIA_UPLOAD_API}/{resource_name}"
        headers = {"Content-Type": content_type or "application/octet-stream"}
        # Google's own docs disagree on the parameter spelling (`uploadType`
        # in the reference, `upload_type` in the upload guide). Try both so
        # a doc mismatch cannot break every byte upload.
        last: tuple[int, str] | None = None
        for param in ("uploadType=media", "upload_type=media"):
            resp = await self._client._authed_request(
                "POST", f"{base}?{param}", content=data, extra_headers=headers,
            )
            if resp.status_code in (200, 201):
                return
            last = (resp.status_code, resp.text[:300])
            logger.warning(
                "Google media upload with %s failed (%s): %s",
                param, last[0], last[1],
            )
        raise GoogleReviewsError(
            f"media upload failed ({last[0]}): {last[1]}", last[0]
        )

    async def stage_post_image(
        self, account: str, location: str, data: bytes, content_type: str
    ) -> tuple[str, str]:
        """Upload bytes into Google's own media store for use by a local post.

        Local Posts refuse raw bytes, but they do accept a ``sourceUrl`` that
        Google fetches. Staging puts the bytes into a temporary location-media
        item (category ADDITIONAL) and returns ``(googleUrl, media_name)`` —
        a Google-hosted URL we can hand back as that sourceUrl. Google then
        stores its own copy in the post, so the image survives even if the
        Sayvors copy disappears.

        Note: the temporary item appears in the location's photo gallery. Do
        not delete it immediately — Google may fetch the URL asynchronously,
        and deleting the source before that fetch breaks the post image.
        """
        ref = await self.start_media_upload(account, location)
        await self.upload_media_bytes(ref, data, content_type)
        url = f"{GBP_MEDIA_API}/{account}/{location}/media"
        resp = await self._client._authed_request(
            "POST",
            url,
            json={
                "mediaFormat": "PHOTO",
                "locationAssociation": {"category": "ADDITIONAL"},
                "dataRef": {"resourceName": ref},
            },
        )
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"stage_post_image failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        payload = resp.json() or {}
        hosted = (payload.get("googleUrl") or "").strip()
        if not hosted:
            raise GoogleReviewsError(
                "media.create returned no googleUrl to use as post sourceUrl", 502
            )
        return hosted, (payload.get("name") or "").strip()

    async def set_location_image(
        self,
        token: str,
        asset_id: str,
        method: str,
        media_url: str,
        account_id: str | None = None,
        *,
        category_override: str | None = None,
        media_data: bytes | None = None,
        content_type: str | None = None,
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

        Pass ``media_data`` (the image bytes) to upload straight to Google via
        ``media:startUpload`` and a ``dataRef`` — no public bucket and no
        publicly reachable image URL. ``media_url`` alone falls back to the
        legacy ``sourceUrl`` flow.

        ``asset_id`` is the location id; ``account_id`` is the Google
        account id.
        """
        category = (category_override or _LOCATION_IMAGE_CATEGORY.get(method) or "").upper()
        if category not in {
            "PROFILE", "COVER", "LOGO", "EXTERIOR", "INTERIOR", "PRODUCT",
            "FOOD_AND_DRINK", "MENU", "COMMON_AREA", "ROOMS", "TEAM", "ADDITIONAL",
        }:
            raise GoogleReviewsError(
                f"GBP location media category is invalid: {category or method!r}", 400
            )
        if not media_url and media_data is None:
            raise GoogleReviewsError(
                "a location image needs a media URL or image bytes", 400
            )

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
        }
        if media_data is not None:
            try:
                ref = await self.start_media_upload(account, location)
                await self.upload_media_bytes(
                    ref, media_data, content_type or "image/jpeg"
                )
                body["dataRef"] = {"resourceName": ref}
            except GoogleReviewsError as e:
                if not media_url:
                    raise
                # Byte upload is an optimisation, not a requirement: Google
                # also accepts a public URL. Log the reason and fall back so
                # a doc/API mismatch cannot make the whole publish fail.
                logger.warning(
                    "Google byte upload failed for %s/%s (%s); "
                    "falling back to sourceUrl",
                    account, location, e,
                )
                body["sourceUrl"] = media_url
        else:
            body["sourceUrl"] = media_url
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

        url = f"{GBP_LOCAL_POSTS_API}/{post_id}"
        resp = await self._client._authed_request("DELETE", url)
        if resp.status_code not in (200, 204):
            raise GoogleReviewsError(
                f"delete_local_post failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return {"deleted": True, "platform": "google_reviews", "post_id": post_id}