"""Contract tests: the Google Business Profile OFFER (promotion) post.

Pins the OFFER body against Google's LocalPost reference:

- ``topicType`` is ``OFFER``.
- ``event`` is **required** for topic types EVENT *and* OFFER, and carries the
  schedule (title + startDate/startTime/endDate/endTime).
- ``offer`` holds exactly the three documented fields: ``couponCode``,
  ``redeemOnlineUrl`` and ``termsConditions``. It has no schedule of its own.
- ``callToAction`` is **ignored** for topic type OFFER, so the link belongs
  in ``offer.redeemOnlineUrl``.

Run only this file:  pytest services/api/tests/test_google_offer_contract.py
"""
import json

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


def _body(publisher) -> dict:
    return json.loads(publisher._client._http._transport.requests[0].content.decode())


@pytest.mark.asyncio
async def test_offer_post_matches_the_documented_body():
    script = [(200, {}, b'{"name":"accounts/a/locations/l/localPosts/1",'
                       b'"topicType":"OFFER","state":"PROCESSING"}')]
    publisher = _publisher(script)

    await publisher.publish_post(
        token="token",
        asset_id="8411302920254759403",
        account_id="117767562410497296372",
        method="offer",
        media_url="https://example.com/promo-banner.jpg",
        media_type="image",
        caption="Get 20% off all services this week!",
        description="",
        scheduled_at=None,
        cta_type="shop",
        cta_url="https://example.com/shop-now",
        start_date="2024-11-20T00:00:00+00:00",
        end_date="2024-11-27T00:00:00+00:00",
        coupon_code="SAVE20",
        terms_conditions="Offer valid for new customers only.",
        language_code="en-US",
    )

    body = _body(publisher)

    assert body["topicType"] == "OFFER"
    assert body["languageCode"] == "en-US"
    assert body["summary"] == "Get 20% off all services this week!"

    # The schedule lives on the event block: Google requires `event` for
    # OFFER posts and `offer` has no schedule field of its own.
    assert body["event"]["schedule"]["startDate"] == {"year": 2024, "month": 11, "day": 20}
    assert body["event"]["schedule"]["endDate"] == {"year": 2024, "month": 11, "day": 27}
    assert set(body["event"]["schedule"]) == {
        "startDate", "startTime", "endDate", "endTime",
    }

    # The offer block carries exactly the three documented fields.
    assert body["offer"]["couponCode"] == "SAVE20"
    assert body["offer"]["redeemOnlineUrl"] == "https://example.com/shop-now"
    assert body["offer"]["termsConditions"] == "Offer valid for new customers only."
    assert set(body["offer"]) <= {"couponCode", "redeemOnlineUrl", "termsConditions"}
    assert "schedule" not in body["offer"]

    # Google ignores callToAction for OFFER, so the link is the redeem URL.
    assert "callToAction" not in body

    # The photo is a public URL.
    assert body["media"] == [
        {"mediaFormat": "PHOTO", "sourceUrl": "https://example.com/promo-banner.jpg"}
    ]


@pytest.mark.asyncio
async def test_offer_without_a_coupon_still_sends_the_documented_fields():
    script = [(200, {}, b'{"name":"accounts/a/locations/l/localPosts/1"}')]
    publisher = _publisher(script)

    await publisher.publish_post(
        token="token",
        asset_id="8411302920254759403",
        account_id="117767562410497296372",
        method="offer",
        media_url=None,
        media_type=None,
        caption="Discount on Sayvors",
        description="",
        scheduled_at=None,
        cta_type="shop",
        cta_url="https://example.com/shop-now",
    )

    offer = _body(publisher)["offer"]
    assert "couponCode" not in offer          # optional, not invented
    assert offer["redeemOnlineUrl"] == "https://example.com/shop-now"
    assert offer["termsConditions"]           # a default, never empty
