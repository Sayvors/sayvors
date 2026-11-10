"""Google Business Profile (GBP) local-post publisher.

GBP does not have a "feed post" in the Meta sense. The equivalent is a
``localPost`` created via:

    POST /v1/accounts/{accountId}/locations/{locationId}/localPosts

A STANDARD local post carries a summary (caption) and optionally a photo
and a call-to-action. A future ``scheduledTime`` makes Google hold the post in
SCHEDULED and publish it at that moment. The field rules live in
``google_post_fields``; this module only sends and reads them.

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
from .google_post_fields import (
    build_post_fields,
    parse_instant,
    scheduled_time_rfc3339,
    topic_type_for,
)

logger = logging.getLogger(__name__)

GBP_LOCAL_POSTS_API = "https://mybusiness.googleapis.com/v4"

# Listing a location's posts is how a "gone" post is confirmed: Google's
# localPosts.get answers 500 INTERNAL (not 404) for a post it no longer holds.
LOCAL_POST_LIST_PAGE_SIZE = 100
# A location with more posts than this is not worth paging through to prove a
# deletion; the caller reports the original failure instead of guessing.
LOCAL_POST_LIST_MAX_PAGES = 50

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


def _require_post_name(post_name: str) -> None:
    if not post_name or "/localPosts/" not in post_name:
        raise GoogleReviewsError(
            "post name must be a full localPost resource name", 400
        )


def _post_summary(data: dict) -> dict:
    """What Sayvors keeps about a local post, from Google's LocalPost JSON."""
    return {
        "id": data.get("name", ""),
        "name": data.get("name", ""),
        "topicType": data.get("topicType"),
        "state": data.get("state"),
        "searchUrl": data.get("searchUrl"),
        "summary": data.get("summary"),
        "event": data.get("event"),
        "offer": data.get("offer"),
        "callToAction": data.get("callToAction"),
        "mediaCount": len(data.get("media") or []),
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

        ``scheduled_at`` is sent as ``scheduledTime``: Google holds the post in
        SCHEDULED and publishes it at that moment. A time already past is
        published now.

        Returns the post summary plus the resolved event ``window`` and the
        ``scheduledTime`` that was sent. Raises ``GoogleReviewsError`` on failure.
        """
        try:
            topic_type = topic_type_for(method)
        except ValueError as e:
            raise GoogleReviewsError(str(e), 400) from e

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

        now = datetime.now(timezone.utc)
        try:
            built = build_post_fields(
                topic=topic_type,
                caption=caption,
                description=description,
                cta_type=cta_type,
                cta_url=cta_url,
                start=parse_instant(start_date),
                end=parse_instant(end_date),
                coupon_code=coupon_code,
                terms=terms_conditions,
                now=now,
            )
            scheduled_time = scheduled_time_rfc3339(scheduled_at, now)
        except ValueError as e:
            raise GoogleReviewsError(str(e), 400) from e

        body: dict[str, Any] = {
            "topicType": topic_type,
            "languageCode": "en",
            **{k: v for k, v in built.fields.items() if v is not None},
        }
        if scheduled_time:
            body["scheduledTime"] = scheduled_time

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
        window = None
        if built.window:
            window = {
                "start": built.window[0].isoformat(),
                "end": built.window[1].isoformat(),
            }
        return {
            **_post_summary(resp.json()),
            "window": window,
            "scheduledTime": scheduled_time,
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

    async def get_post(self, post_name: str) -> dict:
        """Read a local post as Google holds it now (``localPosts.get``).

        A post Google no longer has raises ``GoogleReviewsError`` with status
        404, which callers record as gone rather than as a failure.
        """
        _require_post_name(post_name)
        url = f"{GBP_LOCAL_POSTS_API}/{post_name}"
        resp = await self._client._authed_request("GET", url)
        if resp.status_code != 200:
            status = await self._missing_status(resp.status_code, post_name)
            raise GoogleReviewsError(
                f"get_local_post failed ({resp.status_code}): {resp.text[:300]}",
                status,
            )
        return _post_summary(resp.json())

    async def post_exists(self, post_name: str) -> bool:
        """Whether the location's post list still holds this post.

        Google answers a get for a post it no longer holds with 500 INTERNAL
        rather than 404, so a 5xx alone cannot be read as "deleted". The list
        is authoritative. A list failure propagates: an outage must never be
        mistaken for a deletion.
        """
        _require_post_name(post_name)
        parent = post_name.rsplit("/localPosts/", 1)[0]
        url = f"{GBP_LOCAL_POSTS_API}/{parent}/localPosts"
        page_token = ""
        for _ in range(LOCAL_POST_LIST_MAX_PAGES):
            params: dict[str, Any] = {"pageSize": LOCAL_POST_LIST_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            resp = await self._client._authed_request("GET", url, params=params)
            if resp.status_code != 200:
                raise GoogleReviewsError(
                    f"list_local_posts failed ({resp.status_code}): {resp.text[:300]}",
                    resp.status_code,
                )
            data = resp.json() or {}
            for item in data.get("localPosts") or []:
                if item.get("name") == post_name:
                    return True
            page_token = str(data.get("nextPageToken") or "").strip()
            if not page_token:
                return False
        # More pages than the cap: neither existence nor absence is proven.
        raise GoogleReviewsError(
            "could not confirm whether the local post still exists", 500
        )

    async def _missing_status(self, status_code: int, post_name: str) -> int:
        """The status to report for a failed read: 404 only if the post is gone.

        Only a 5xx is ambiguous (Google uses 500 for "no such post"); anything
        else keeps its own status. A failed list check keeps the 5xx.
        """
        if status_code < 500:
            return status_code
        try:
            exists = await self.post_exists(post_name)
        except GoogleReviewsError:
            return status_code
        return status_code if exists else 404

    async def update_post(self, post_name: str, fields: dict[str, Any]) -> dict:
        """Change fields of a local post in place (``localPosts.patch``).

        Google requires the updateMask to name every field being changed, so
        the mask is built from the keys of ``fields``. A ``None`` value is sent
        as JSON null, which clears that field (used to remove a button).
        """
        _require_post_name(post_name)
        if not fields:
            raise GoogleReviewsError("nothing to change on the local post", 400)
        mask = ",".join(sorted(fields))
        url = f"{GBP_LOCAL_POSTS_API}/{post_name}?updateMask={mask}"
        resp = await self._client._authed_request("PATCH", url, json=fields)
        if resp.status_code not in (200, 201):
            detail = resp.text[:2000]
            logger.warning(
                "update_local_post failed (%s): %s | mask=%s",
                resp.status_code, detail, mask,
            )
            raise GoogleReviewsError(
                f"update_local_post failed ({resp.status_code}): {detail}",
                resp.status_code,
            )
        return _post_summary(resp.json())

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
            # A post that is already gone is the state the caller wanted.
            # Google reports it as 500 INTERNAL, not 404, so the list decides.
            if await self._missing_status(resp.status_code, post_id) == 404:
                return {
                    "deleted": True,
                    "already_gone": True,
                    "platform": "google_reviews",
                    "post_id": post_id,
                }
            raise GoogleReviewsError(
                f"delete_local_post failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return {"deleted": True, "platform": "google_reviews", "post_id": post_id}
