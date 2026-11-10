"""Reading and changing a live Google local post (localPosts.get / patch).

HTTP is mocked: these pin the request shape Google requires, not the network.
"""

import json

import pytest

from app.modules.channels.google_reviews import GoogleReviewsError
from app.modules.channels.meta.providers.google_publish import GoogleBusinessPublisher

POST = "accounts/1/locations/2/localPosts/3"


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _publisher(fake) -> GoogleBusinessPublisher:
    publisher = GoogleBusinessPublisher("token", "refresh")
    publisher._client._authed_request = fake
    return publisher


@pytest.mark.asyncio
async def test_update_sends_only_the_changed_fields_with_a_matching_mask():
    calls = []

    async def fake(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return _Resp({"name": POST, "topicType": "STANDARD", "state": "LIVE", "summary": "New text"})

    result = await _publisher(fake).update_post(POST, {"summary": "New text", "callToAction": None})
    method, url, body = calls[0]
    assert method == "PATCH"
    assert url == f"https://mybusiness.googleapis.com/v4/{POST}?updateMask=callToAction,summary"
    assert body == {"summary": "New text", "callToAction": None}
    assert result["summary"] == "New text"
    assert result["state"] == "LIVE"


@pytest.mark.asyncio
async def test_an_empty_change_is_refused_before_any_request():
    with pytest.raises(GoogleReviewsError):
        await _publisher(None).update_post(POST, {})


@pytest.mark.asyncio
async def test_a_bare_post_id_is_refused_before_any_request():
    with pytest.raises(GoogleReviewsError):
        await _publisher(None).update_post("3", {"summary": "x"})
    with pytest.raises(GoogleReviewsError):
        await _publisher(None).get_post("3")


@pytest.mark.asyncio
async def test_google_refusal_keeps_its_status_and_reason():
    async def fake(method, url, **kwargs):
        return _Resp({"error": {"message": "Unknown name"}}, status_code=400)

    with pytest.raises(GoogleReviewsError) as err:
        await _publisher(fake).update_post(POST, {"summary": "x"})
    assert err.value.status_code == 400
    assert "Unknown name" in str(err.value)


@pytest.mark.asyncio
async def test_get_reports_a_missing_post_as_404():
    async def fake(method, url, **kwargs):
        assert method == "GET"
        return _Resp({"error": {"message": "not found"}}, status_code=404)

    with pytest.raises(GoogleReviewsError) as err:
        await _publisher(fake).get_post(POST)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_get_returns_the_state_google_holds_now():
    async def fake(method, url, **kwargs):
        return _Resp(
            {
                "name": POST,
                "topicType": "EVENT",
                "state": "SCHEDULED",
                "media": [{"sourceUrl": "https://cdn.example/p.jpg"}],
            }
        )

    result = await _publisher(fake).get_post(POST)
    assert result["state"] == "SCHEDULED"
    assert result["topicType"] == "EVENT"
    assert result["mediaCount"] == 1


@pytest.mark.asyncio
async def test_get_500_is_gone_when_the_location_list_lacks_the_post():
    """Google answers 500 INTERNAL — never 404 — for a deleted local post.

    The list is what decides: the same status with the post still listed is a
    real Google failure and must stay one.
    """
    async def fake(method, url, **kwargs):
        if url.endswith("/localPosts"):
            return _Resp({"localPosts": [{"name": "accounts/1/locations/2/localPosts/999"}]})
        return _Resp({"error": {"message": "Internal error encountered."}}, status_code=500)

    with pytest.raises(GoogleReviewsError) as err:
        await _publisher(fake).get_post(POST)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_get_500_stays_a_failure_while_the_post_is_still_listed():
    async def fake(method, url, **kwargs):
        if url.endswith("/localPosts"):
            return _Resp({"localPosts": [{"name": POST}]})
        return _Resp({"error": {"message": "Internal error encountered."}}, status_code=500)

    with pytest.raises(GoogleReviewsError) as err:
        await _publisher(fake).get_post(POST)
    assert err.value.status_code == 500


@pytest.mark.asyncio
async def test_a_failed_list_check_keeps_the_original_failure():
    async def fake(method, url, **kwargs):
        if url.endswith("/localPosts"):
            return _Resp({"error": {"message": "backend error"}}, status_code=503)
        return _Resp({"error": {"message": "Internal error encountered."}}, status_code=500)

    with pytest.raises(GoogleReviewsError) as err:
        await _publisher(fake).get_post(POST)
    assert err.value.status_code == 500


@pytest.mark.asyncio
async def test_delete_of_an_already_gone_post_reports_success():
    """A removal job that runs after the post was deleted must not retry: the
    desired state (gone) is already true."""
    async def fake(method, url, **kwargs):
        if url.endswith("/localPosts"):
            return _Resp({"localPosts": []})
        return _Resp({"error": {"message": "Internal error encountered."}}, status_code=500)

    result = await _publisher(fake).delete_post("token", POST)
    assert result["deleted"] is True
    assert result["already_gone"] is True
