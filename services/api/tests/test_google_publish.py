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


@pytest.fixture(autouse=True)
def _staging_off_by_default(monkeypatch):
    """Most tests pin the localPosts request shape, not the staging handshake.
    Staging has its own dedicated tests below."""
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_POST_MEDIA_STAGING", False)


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
    # localPosts exists on v4; v1 returns Google's HTML 404.
    assert "/v4/accounts/1/locations/2/localPosts" in captured["url"]


@pytest.mark.asyncio
async def test_legacy_post_method_still_publishes():
    """Jobs created before the format split used "post" — it must keep
    working rather than fail on an unknown method."""
    captured = await _publish("post")
    assert captured["body"]["topicType"] == "STANDARD"


@pytest.mark.asyncio
async def test_event_carries_the_date_google_requires():
    """Google rejects an EVENT post with no event object, and its
    LocalPostEvent is {title, schedule:{startDate, startTime, ...}} with
    Date/TimeOfDay objects — not ISO strings."""
    captured = await _publish(
        "event",
        start_date="2026-11-09T09:00:00+00:00",
        end_date="2026-11-10T09:00:00+00:00",
    )
    body = captured["body"]
    assert body["topicType"] == "EVENT"
    assert body["event"]["title"] == "Grand opening"
    schedule = body["event"]["schedule"]
    assert schedule["startDate"] == {"year": 2026, "month": 11, "day": 9}
    assert schedule["endDate"] == {"year": 2026, "month": 11, "day": 10}
    assert schedule["startTime"]["hours"] == 9
    assert schedule["endTime"]["minutes"] == 0


@pytest.mark.asyncio
async def test_call_to_action_maps_to_google_action_type():
    captured = await _publish(
        "update", cta_type="shop", cta_url="https://shop.example.com"
    )
    assert captured["body"]["callToAction"] == {
        "actionType": "SHOP",
        "url": "https://shop.example.com",
    }


@pytest.mark.asyncio
async def test_offer_only_uses_fields_google_accepts():
    """LocalPostOffer accepts only couponCode / redeemOnlineUrl /
    termsConditions. A "description" key is rejected with
    'Unknown name "description" at local_post.offer'."""
    captured = await _publish("offer", terms_conditions="Come say hello")
    body = captured["body"]
    assert body["topicType"] == "OFFER"
    assert body["offer"]["termsConditions"] == "Come say hello"
    assert set(body["offer"]) <= {"couponCode", "redeemOnlineUrl", "termsConditions"}


@pytest.mark.asyncio
async def test_standard_post_carries_a_call_to_action():
    """Google renders a button from callToAction {actionType, url}."""
    captured = await _publish(
        "update", cta_type="learn_more", cta_url="https://sayvors.com"
    )
    assert captured["body"]["callToAction"] == {
        "actionType": "LEARN_MORE",
        "url": "https://sayvors.com",
    }


@pytest.mark.asyncio
async def test_call_action_never_carries_a_url():
    """CALL is the phone number, not a link — a URL is rejected."""
    captured = await _publish("update", cta_type="call", cta_url="https://sayvors.com")
    assert captured["body"]["callToAction"] == {"actionType": "CALL"}


@pytest.mark.asyncio
async def test_action_without_a_url_is_refused():
    """A button type with no link would silently do nothing — fail loudly."""
    with pytest.raises(GoogleReviewsError):
        await _publish("update", cta_type="book", cta_url="")


@pytest.mark.asyncio
async def test_offer_link_goes_to_redeem_url_not_a_button():
    """callToAction is ignored for OFFER posts; the offer carries the link."""
    captured = await _publish(
        "offer", cta_type="shop", cta_url="https://sayvors.com/redeem"
    )
    body = captured["body"]
    assert "callToAction" not in body
    assert body["offer"]["redeemOnlineUrl"] == "https://sayvors.com/redeem"
    assert "description" not in body["offer"]


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


async def _upload_location_image(method: str) -> dict:
    """Set a location image from raw bytes, capturing every HTTP call."""
    captured: dict = {"calls": []}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def _fake_authed_request(http_method: str, url: str, **kwargs):
        captured["calls"].append({
            "method": http_method,
            "url": url,
            "json": kwargs.get("json") or {},
            "content": kwargs.get("content"),
            "extra_headers": kwargs.get("extra_headers"),
        })
        if url.endswith(":startUpload"):
            return _Resp({"resourceName": "accounts/1/locations/2/media/up-1"})
        if "/upload/v1/media/" in url:
            return _Resp({})
        return _Resp({
            "name": "accounts/1/locations/2/media/profile",
            "locationAssociation": {"category": "PROFILE"},
            "googleUrl": "https://lh3.googleusercontent.com/x",
        })

    publisher._client._authed_request = _fake_authed_request
    await publisher.set_location_image(
        token="token",
        asset_id="locations/2",
        method=method,
        media_url="",
        account_id="accounts/1",
        media_data=b"jpeg-bytes",
        content_type="image/jpeg",
    )
    return captured


@pytest.mark.asyncio
async def test_location_image_bytes_are_uploaded_directly():
    """No public bucket: startUpload -> byte upload -> create with dataRef."""
    calls = (await _upload_location_image("profile"))["calls"]

    assert calls[0]["url"] == (
        "https://mybusiness.googleapis.com/v4/accounts/1/locations/2/media:startUpload"
    )
    assert calls[0]["json"] == {}

    assert calls[1]["url"] == (
        "https://mybusiness.googleapis.com/upload/v1/media"
        "/accounts/1/locations/2/media/up-1?uploadType=media"
    )
    assert calls[1]["content"] == b"jpeg-bytes"
    assert calls[1]["extra_headers"]["Content-Type"] == "image/jpeg"

    create = calls[2]
    assert create["url"] == (
        "https://mybusiness.googleapis.com/v4/accounts/1/locations/2/media"
    )
    assert create["json"]["dataRef"] == {
        "resourceName": "accounts/1/locations/2/media/up-1"
    }
    assert "sourceUrl" not in create["json"]


@pytest.mark.asyncio
async def test_location_image_falls_back_to_source_url_on_upload_failure():
    """A failed byte upload must not sink the whole publish."""
    captured: dict = {"calls": []}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def _fake_authed_request(http_method: str, url: str, **kwargs):
        captured["calls"].append({"url": url, "json": kwargs.get("json") or {}})
        if url.endswith(":startUpload"):
            return _Resp({"resourceName": "accounts/1/locations/2/media/up-1"})
        if "/upload/v1/media/" in url:
            return _Resp({"error": "upload rejected"}, status_code=400)
        return _Resp({
            "name": "accounts/1/locations/2/media/profile",
            "locationAssociation": {"category": "PROFILE"},
        })

    publisher._client._authed_request = _fake_authed_request
    res = await publisher.set_location_image(
        token="token",
        asset_id="locations/2",
        method="profile",
        media_url="https://cdn.example/avatar.jpg",
        account_id="accounts/1",
        media_data=b"jpeg-bytes",
        content_type="image/jpeg",
    )
    assert res["name"]
    create = captured["calls"][-1]
    assert create["json"]["sourceUrl"] == "https://cdn.example/avatar.jpg"
    assert "dataRef" not in create["json"]


@pytest.mark.asyncio
async def test_post_image_is_staged_on_google(monkeypatch):
    """Bytes go to Google's own media store; the post uses Google's URL."""
    from app.config import settings
    from app.core import storage

    monkeypatch.setattr(settings, "GOOGLE_POST_MEDIA_STAGING", True)
    monkeypatch.setattr(
        storage, "media_bytes_from_url",
        lambda user_id, url: (b"image-bytes", "image/jpeg"),
    )

    captured: dict = {"calls": []}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def fake(method, url, **kwargs):
        captured["calls"].append({
            "url": url,
            "json": kwargs.get("json") or {},
            "content": kwargs.get("content"),
        })
        if url.endswith(":startUpload"):
            return _Resp({"resourceName": "ref-1"})
        if "/upload/v1/media/" in url:
            return _Resp({})
        if url.endswith("/media"):
            return _Resp({
                "name": "accounts/1/locations/2/media/staged",
                "googleUrl": "https://lh3.googleusercontent.com/staged",
            })
        return _Resp({
            "name": "accounts/1/locations/2/localPosts/3",
            "topicType": "STANDARD",
        })

    publisher._client._authed_request = fake
    await publisher.publish_post(
        token="token",
        asset_id="locations/2",
        method="update",
        media_url="https://api.example.com/media-files/u1/p.jpg",
        media_type="image",
        caption="Grand opening",
        description="Come say hello",
        scheduled_at=None,
        account_id="accounts/1",
        tenant_id="u1",
    )

    urls = [c["url"] for c in captured["calls"]]
    assert urls[0].endswith("/media:startUpload")
    assert "/upload/v1/media/" in urls[1]
    assert captured["calls"][1]["content"] == b"image-bytes"
    assert urls[2].endswith("/media")
    staged = captured["calls"][2]["json"]
    assert staged["locationAssociation"] == {"category": "ADDITIONAL"}
    assert staged["dataRef"] == {"resourceName": "ref-1"}

    post = captured["calls"][-1]["json"]
    assert post["media"] == [
        {"mediaFormat": "PHOTO", "sourceUrl": "https://lh3.googleusercontent.com/staged"}
    ]


@pytest.mark.asyncio
async def test_post_image_falls_back_when_staging_fails(monkeypatch):
    """A staging failure must not sink the publish."""
    from app.config import settings
    from app.core import storage

    monkeypatch.setattr(settings, "GOOGLE_POST_MEDIA_STAGING", True)
    monkeypatch.setattr(
        storage, "media_bytes_from_url",
        lambda user_id, url: (b"image-bytes", "image/jpeg"),
    )

    captured: dict = {"calls": []}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def fake(method, url, **kwargs):
        captured["calls"].append({"url": url, "json": kwargs.get("json") or {}})
        if url.endswith(":startUpload"):
            return _Resp({"error": "quota"}, status_code=429)
        return _Resp({"name": "accounts/1/locations/2/localPosts/3"})

    publisher._client._authed_request = fake
    await publisher.publish_post(
        token="token",
        asset_id="locations/2",
        method="update",
        media_url="https://cdn.example/p.jpg",
        media_type="image",
        caption="Hi",
        description="Hi",
        scheduled_at=None,
        account_id="accounts/1",
    )
    post = captured["calls"][-1]["json"]
    assert post["media"] == [
        {"mediaFormat": "PHOTO", "sourceUrl": "https://cdn.example/p.jpg"}
    ]


@pytest.mark.asyncio
async def test_post_retries_with_original_url_when_google_rejects_staged(monkeypatch):
    """Google returned a deterministic 500 INTERNAL on its own googleUrl.
    Staging must not sink the publish: retry once with the caller's URL."""
    from app.config import settings
    from app.core import storage

    monkeypatch.setattr(settings, "GOOGLE_POST_MEDIA_STAGING", True)
    monkeypatch.setattr(
        storage, "media_bytes_from_url",
        lambda user_id, url: (b"image-bytes", "image/jpeg"),
    )

    captured: dict = {"calls": []}
    publisher = GoogleBusinessPublisher("token", "refresh")

    async def fake(method, url, **kwargs):
        captured["calls"].append({"url": url, "json": kwargs.get("json") or {}})
        if url.endswith(":startUpload"):
            return _Resp({"resourceName": "ref-1"})
        if "/upload/v1/media/" in url:
            return _Resp({})
        if url.endswith("/media"):
            return _Resp({
                "name": "accounts/1/locations/2/media/staged",
                "googleUrl": "https://lh3.googleusercontent.com/staged",
            })
        n_posts = sum(
            1 for c in captured["calls"] if c["url"].endswith("/localPosts")
        )
        if n_posts == 1:
            return _Resp(
                {"error": {"code": 500, "message": "Internal error encountered."}},
                status_code=500,
            )
        return _Resp({"name": "accounts/1/locations/2/localPosts/3"})

    publisher._client._authed_request = fake
    res = await publisher.publish_post(
        token="token",
        asset_id="locations/2",
        method="update",
        media_url="https://api.example.com/media-files/u1/p.jpg",
        media_type="image",
        caption="Hi",
        description="Hi",
        scheduled_at=None,
        account_id="accounts/1",
        tenant_id="u1",
    )
    assert res["name"] == "accounts/1/locations/2/localPosts/3"
    posts = [
        c["json"] for c in captured["calls"] if c["url"].endswith("/localPosts")
    ]
    assert len(posts) == 2
    assert posts[0]["media"][0]["sourceUrl"] == "https://lh3.googleusercontent.com/staged"
    assert posts[1]["media"][0]["sourceUrl"] == "https://api.example.com/media-files/u1/p.jpg"


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
