"""Google Business Profile local-post publisher (no network — HTTP mocked).

Google offers three kinds of post on a business profile, and each one is a
different ``topicType`` on the localPosts endpoint. The composer exposes
them as three separate formats, so the mapping from a format to a
``topicType`` is pinned here — along with the fields Google refuses a
post without (an event needs a date, an offer needs terms).
"""
import json

import pytest

from app.modules.channels.google_reviews import GoogleReviewsError
from app.modules.channels.meta.providers.google_publish import GoogleBusinessPublisher


class _Resp:
    """Minimal stand-in for the httpx response the client returns."""

    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


async def _publish(method: str, **overrides) -> dict:
    """Publish one post with the HTTP call captured, and return the body."""
    captured: dict = {}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def _fake_authed_request(http_method: str, url: str, **kwargs):
        captured["method"] = http_method
        captured["url"] = url
        captured["body"] = kwargs.get("json") or {}
        return _Resp(
            {
                "name": "accounts/1/locations/2/localPosts/3",
                "topicType": captured["body"].get("topicType"),
                "state": "PUBLISHED",
            },
            status_code=200,
        )

    publisher._client._authed_request = _fake_authed_request
    kwargs = {
        "token": "token",
        "asset_id": "locations/2",
        "method": method,
        "media_url": "https://cdn.example/p.jpg",
        "media_type": "image",
        "caption": "Grand opening",
        "description": "Come say hello",
        "scheduled_at": None,
        "account_id": "accounts/1",
    }
    kwargs.update(overrides)
    result = await publisher.publish_post(**kwargs)
    captured["result"] = result
    return captured


@pytest.mark.asyncio
async def test_update_maps_to_the_standard_topic():
    """Google's "What's New" is a STANDARD post."""
    captured = await _publish("update")
    assert captured["body"]["topicType"] == "STANDARD"
    assert captured["body"]["summary"] == "Grand opening"
    assert "event" not in captured["body"]
    assert "offer" not in captured["body"]


@pytest.mark.asyncio
async def test_legacy_post_method_still_publishes():
    """Jobs created before the format split used "post" — it must keep
    working rather than fail on an unknown method."""
    captured = await _publish("post")
    assert captured["body"]["topicType"] == "STANDARD"


@pytest.mark.asyncio
async def test_event_carries_the_date_google_requires():
    """Google rejects an EVENT post with no event object."""
    captured = await _publish("event")
    body = captured["body"]
    assert body["topicType"] == "EVENT"
    assert body["event"]["title"] == "Grand opening"
    assert body["event"]["startDate"]
    assert body["event"]["endDate"]


@pytest.mark.asyncio
async def test_offer_carries_terms_google_requires():
    """An OFFER post needs at least one of the offer fields."""
    captured = await _publish("offer")
    body = captured["body"]
    assert body["topicType"] == "OFFER"
    assert body["offer"]["description"] == "Grand opening"
    assert body["offer"]["termsConditions"] == "Come say hello"


@pytest.mark.asyncio
async def test_unsupported_method_is_refused():
    """A format Google has no topic type for must fail loudly, not post a
    STANDARD post the tenant did not ask for."""
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def _never(url, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the request must not be sent")

    publisher._client._authed_request = _never
    with pytest.raises(GoogleReviewsError):
        await publisher.publish_post(
            token="token",
            asset_id="locations/2",
            method="reel",
            media_url="https://cdn.example/p.jpg",
            media_type="image",
            caption="x",
            description="",
            scheduled_at=None,
            account_id="accounts/1",
        )


@pytest.mark.asyncio
async def test_media_is_attached_as_a_photo():
    captured = await _publish("update")
    assert captured["body"]["media"] == [
        {"mediaFormat": "PHOTO", "sourceUrl": "https://cdn.example/p.jpg"}
    ]


@pytest.mark.asyncio
async def test_scheduled_time_is_sent_as_rfc3339():
    captured = await _publish("update", scheduled_at="2026-12-01T09:30:00+00:00")
    assert captured["body"]["scheduledPublishTime"] == "2026-12-01T09:30:00Z"


# ── location images (profile picture / cover) ──────────────────────────


async def _set_location_image(method: str) -> dict:
    """Set a location image with the HTTP call captured."""
    captured: dict = {}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def _fake_authed_request(http_method: str, url: str, **kwargs):
        captured["method"] = http_method
        captured["url"] = url
        captured["body"] = kwargs.get("json") or {}
        return _Resp(
            {
                "name": "accounts/1/locations/2/media/profile",
                "locationAssociation": {"category": captured["body"]
                                        .get("locationAssociation", {})
                                        .get("category")},
                "googleUrl": "https://lh3.googleusercontent.com/x",
            },
            status_code=200,
        )

    publisher._client._authed_request = _fake_authed_request
    result = await publisher.set_location_image(
        token="token",
        asset_id="locations/2",
        method=method,
        media_url="https://cdn.example/avatar.jpg",
        account_id="accounts/1",
    )
    captured["result"] = result
    return captured


@pytest.mark.asyncio
async def test_profile_picture_is_a_profile_category_media_item():
    """Google files the profile picture under the PROFILE category."""
    captured = await _set_location_image("profile")
    assert captured["body"]["locationAssociation"] == {"category": "PROFILE"}
    assert captured["body"]["mediaFormat"] == "PHOTO"
    assert captured["body"]["sourceUrl"] == "https://cdn.example/avatar.jpg"


@pytest.mark.asyncio
async def test_banner_is_a_cover_category_media_item():
    """Google files the cover image under the COVER category."""
    captured = await _set_location_image("banner")
    assert captured["body"]["locationAssociation"] == {"category": "COVER"}


@pytest.mark.asyncio
async def test_location_image_uses_the_v4_media_endpoint():
    """Location photos live in the v4.9 API — v1 has no media resource."""
    captured = await _set_location_image("profile")
    assert captured["url"] == (
        "https://mybusiness.googleapis.com/v4/accounts/1/locations/2/media"
    )


@pytest.mark.asyncio
async def test_location_image_refuses_a_method_it_has_no_category_for():
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def _never(url, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the request must not be sent")

    publisher._client._authed_request = _never
    with pytest.raises(GoogleReviewsError):
        await publisher.set_location_image(
            token="token",
            asset_id="locations/2",
            method="update",
            media_url="https://cdn.example/avatar.jpg",
            account_id="accounts/1",
        )
