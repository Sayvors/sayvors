"""Contract tests: the Google Business Profile local-post wire format.

Pins the exact URL and request body that ``accounts.locations.localPosts``
expects, per Google's own documentation, so a typo cannot reach Google:

    POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/localPosts

    {
      "languageCode": "en-US",
      "summary": "Join us for our Grand Opening Celebration!",
      "topicType": "EVENT",
      "event": {
        "title": "Grand Opening Party",
        "schedule": {
          "startDate": {"year": 2024, "month": 12, "day": 15},
          "startTime": {"hours": 10, "minutes": 0, "seconds": 0, "nanos": 0},
          "endDate":   {"year": 2024, "month": 12, "day": 15},
          "endTime":   {"hours": 18, "minutes": 0, "seconds": 0, "nanos": 0}
        }
      },
      "media": [{"mediaFormat": "PHOTO", "sourceUrl": "https://example.com/flyer.jpg"}],
      "callToAction": {"actionType": "LEARN_MORE", "url": "https://example.com/details"}
    }

A post's photo must be a public ``sourceUrl`` - unlike location media, a
local post cannot take raw bytes.

Run only this file:  pytest services/api/tests/test_google_local_post_contract.py
"""
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.modules.channels.meta.providers.google_publish import GoogleBusinessPublisher


class _RecordingTransport:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        status, headers, body = self.script.pop(0)
        return httpx.Response(status, headers=headers, content=body)


def _publisher(script):
    publisher = GoogleBusinessPublisher("token", "refresh")
    publisher._client._http = httpx.AsyncClient(transport=_RecordingTransport(script))
    return publisher


ACCOUNT = "117767562410497296372"
LOCATION = "8411302920254759403"


def _body(request) -> dict:
    return json.loads(request.content.decode())


@pytest.mark.asyncio
async def test_event_post_matches_the_documented_body():
    script = [(200, {}, b'{"name":"accounts/a/locations/l/localPosts/1",'
                       b'"topicType":"EVENT","state":"PUBLISHED"}')]
    publisher = _publisher(script)

    await publisher.publish_post(
        token="token",
        asset_id=LOCATION,
        account_id=ACCOUNT,
        method="event",
        media_url="https://example.com/flyer.jpg",
        media_type="image",
        caption="Join us for our Grand Opening Celebration!",
        description="",
        scheduled_at=None,
        cta_type="learn_more",
        cta_url="https://example.com/event-details",
        start_date="2024-12-15T10:00:00+00:00",
        end_date="2024-12-15T18:00:00+00:00",
        language_code="en-US",
    )

    req = publisher._client._http._transport.requests[0]
    assert req.method == "POST"
    assert req.url.host == "mybusiness.googleapis.com"
    assert req.url.path == f"/v4/accounts/{ACCOUNT}/locations/{LOCATION}/localPosts"
    assert req.url.query == b""

    body = _body(req)
    assert body["topicType"] == "EVENT"
    assert body["languageCode"] == "en-US"
    assert body["summary"] == "Join us for our Grand Opening Celebration!"
    assert body["event"]["title"]
    assert body["event"]["schedule"]["startDate"] == {"year": 2024, "month": 12, "day": 15}
    assert body["event"]["schedule"]["endDate"] == {"year": 2024, "month": 12, "day": 15}
    # The time parts carry all four fields Google documents.
    assert body["event"]["schedule"]["startTime"] == {
        "hours": 13, "minutes": 0, "seconds": 0, "nanos": 0,
    }
    assert body["event"]["schedule"]["endTime"] == {
        "hours": 21, "minutes": 0, "seconds": 0, "nanos": 0,
    }
    # A post's photo is a public URL - never raw bytes.
    assert body["media"] == [
        {"mediaFormat": "PHOTO", "sourceUrl": "https://example.com/flyer.jpg"}
    ]
    assert "dataRef" not in json.dumps(body)
    assert body["callToAction"] == {
        "actionType": "LEARN_MORE",
        "url": "https://example.com/event-details",
    }


@pytest.mark.asyncio
async def test_language_code_defaults_to_the_documented_value():
    script = [(200, {}, b'{"name":"accounts/a/locations/l/localPosts/1"}')]
    publisher = _publisher(script)

    await publisher.publish_post(
        token="token",
        asset_id=LOCATION,
        account_id=ACCOUNT,
        method="update",
        media_url=None,
        media_type=None,
        caption="Hello",
        description="",
        scheduled_at=None,
    )

    body = _body(publisher._client._http._transport.requests[0])
    assert body["languageCode"] == "en-US"


@pytest.mark.asyncio
async def test_scheduled_time_is_rfc3339_and_optional():
    script = [(200, {}, b'{"name":"accounts/a/locations/l/localPosts/1"}')]
    publisher = _publisher(script)

    await publisher.publish_post(
        token="token",
        asset_id=LOCATION,
        account_id=ACCOUNT,
        method="update",
        media_url=None,
        media_type=None,
        caption="Later",
        description="",
        scheduled_at="2030-01-02T03:04:05+00:00",
    )

    body = _body(publisher._client._http._transport.requests[0])
    assert body["scheduledTime"] == "2030-01-02T03:04:05Z"


@pytest.mark.asyncio
async def test_call_button_carries_no_url():
    """CALL never carries a URL - Google rejects the field with one."""
    script = [(200, {}, b'{"name":"accounts/a/locations/l/localPosts/1"}')]
    publisher = _publisher(script)

    await publisher.publish_post(
        token="token",
        asset_id=LOCATION,
        account_id=ACCOUNT,
        method="update",
        media_url=None,
        media_type=None,
        caption="Call us",
        description="",
        scheduled_at=None,
        cta_type="call",
        cta_url=None,
    )

    body = _body(publisher._client._http._transport.requests[0])
    assert body["callToAction"] == {"actionType": "CALL"}
