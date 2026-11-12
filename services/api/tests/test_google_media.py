"""Google Business Profile location media (gallery) behaviour.

Covers the three failure modes that broke gallery publishing in the wild:

- Google refuses a photo tag that does not apply to the location's business
  type ("Photo tag 'product' does not apply to this location"). The photo must
  still reach the listing, filed under ADDITIONAL, and the caller must be told.
- A tag that names a specific slot (PROFILE/COVER/LOGO) must NOT fall back:
  filing an avatar in the gallery would be wrong, so the error must surface.
- ``media.list`` only accepts pageSize/pageToken; the category filter is
  applied to the returned items, and every page is followed.

These tests mock the HTTP layer (httpx.MockTransport), so they run in
milliseconds with no network and no live Google credentials.
Run only this file:  pytest services/api/tests/test_google_media.py
"""
import httpx
import pytest

from app.modules.channels.google_reviews import (
    GoogleReviewsClient,
    GoogleReviewsError,
    google_error_details,
    is_category_not_applicable,
)


class _FakeTransport:
    """httpx.MockTransport-alike built from a scripted list of responses."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        if not self.script:
            raise AssertionError("no more scripted responses")
        status, headers, body = self.script.pop(0)
        return httpx.Response(status, headers=headers, content=body)


def _make_client(script):
    client = GoogleReviewsClient("access-token", "refresh-token")
    client._http = httpx.AsyncClient(transport=_FakeTransport(script))
    return client


_TAG_NOT_APPLICABLE = (
    b'{"error":{"code":400,"message":"Request contains an invalid argument.",'
    b'"status":"INVALID_ARGUMENT","details":[{"@type":"type.googleapis.com/'
    b'google.mybusiness.v4.ValidationError","errorDetails":[{"code":3,'
    b'"message":"Photo tag \'product\' does not apply to this location",'
    b'"value":"product"}]}]}}'
)


# -- category fallback ------------------------------------------------------

@pytest.mark.asyncio
async def test_rejected_tag_falls_back_to_additional():
    """A tag Google refuses for this location still publishes, as ADDITIONAL."""
    script = [
        (400, {}, _TAG_NOT_APPLICABLE),
        (200, {}, b'{"name":"accounts/a/locations/l/media/m1",'
                   b'"mediaFormat":"PHOTO",'
                   b'"locationAssociation":{"category":"ADDITIONAL"},'
                   b'"googleUrl":"https://lh3.googleusercontent.com/x"}'),
    ]
    client = _make_client(script)

    created = await client.create_location_media(
        "a", "l", category="PRODUCT", data_ref="ref-1"
    )

    assert created["locationAssociation"]["category"] == "ADDITIONAL"
    fallback = created["categoryFallback"]
    assert fallback["requested"] == "PRODUCT"
    assert fallback["used"] == "ADDITIONAL"
    # The first attempt asked for PRODUCT, the retry for ADDITIONAL.
    bodies = [
        __import__("json").loads(r.content.decode())["locationAssociation"]["category"]
        for r in client._http._transport.requests
    ]
    assert bodies == ["PRODUCT", "ADDITIONAL"]


@pytest.mark.asyncio
async def test_fallback_reuploads_bytes_when_the_first_ref_is_consumed():
    """A retry that Google refuses again re-uploads the bytes once."""
    script = [
        (400, {}, _TAG_NOT_APPLICABLE),   # PRODUCT refused
        (400, {}, _TAG_NOT_APPLICABLE),   # ADDITIONAL refused, ref consumed
        (200, {}, b'{"name":"accounts/a/locations/l/media/m2",'
                   b'"locationAssociation":{"category":"ADDITIONAL"}}'),
    ]
    client = _make_client(script)

    uploads = []

    async def fresh_ref():
        uploads.append("ref-2")
        return "ref-2"

    created = await client.create_location_media(
        "a", "l", category="PRODUCT", data_ref="ref-1", fresh_data_ref=fresh_ref
    )

    assert created["locationAssociation"]["category"] == "ADDITIONAL"
    assert uploads == ["ref-2"]
    bodies = [
        __import__("json").loads(r.content.decode()) for r in client._http._transport.requests
    ]
    assert bodies[0]["locationAssociation"]["category"] == "PRODUCT"
    assert bodies[1]["locationAssociation"]["category"] == "ADDITIONAL"
    assert bodies[2]["dataRef"]["resourceName"] == "ref-2"


@pytest.mark.asyncio
async def test_profile_tag_is_never_filed_under_additional():
    """PROFILE names a specific slot: falling back would put it in the gallery."""
    script = [(400, {}, _TAG_NOT_APPLICABLE)]
    client = _make_client(script)

    with pytest.raises(GoogleReviewsError) as exc:
        await client.create_location_media(
            "a", "l", category="PROFILE", data_ref="ref-1"
        )

    assert exc.value.status_code == 400
    # Exactly one request: no fallback attempt was made.
    assert len(client._http._transport.requests) == 1


@pytest.mark.asyncio
async def test_other_google_errors_are_not_retried_as_additional():
    """A quota error must surface, not be masked by an ADDITIONAL retry."""
    script = [(403, {}, b'{"error":{"code":403,"message":"Insufficient permissions."}}')]
    client = _make_client(script)

    with pytest.raises(GoogleReviewsError):
        await client.create_location_media("a", "l", category="PRODUCT", data_ref="ref-1")

    assert len(client._http._transport.requests) == 1


# -- error parsing ----------------------------------------------------------

def test_google_error_details_extracts_the_human_reason():
    status_message, details = google_error_details(_TAG_NOT_APPLICABLE.decode())
    assert status_message == "Request contains an invalid argument."
    assert details == ["Photo tag 'product' does not apply to this location"]


def test_is_category_not_applicable_detects_the_tag_refusal():
    assert is_category_not_applicable(_TAG_NOT_APPLICABLE.decode()) is True
    assert is_category_not_applicable('{"error":{"code":403,"message":"Nope."}}') is False
    assert is_category_not_applicable(None) is False


def test_google_error_details_tolerates_a_non_google_body():
    assert google_error_details("not json at all") == (None, [])
    assert google_error_details(None) == (None, [])


# -- listing ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_media_filters_by_category_without_a_query_param():
    """Google rejects an unknown query parameter, so the filter is local."""
    script = [
        (
            200,
            {},
            b'{"mediaItems":['
            b'{"name":"m1","locationAssociation":{"category":"EXTERIOR"}},'
            b'{"name":"m2","locationAssociation":{"category":"ADDITIONAL"}}'
            b'],"totalMediaItemCount":2}',
        ),
    ]
    client = _make_client(script)

    data = await client.list_media("a", "l", category="EXTERIOR")

    assert [m["name"] for m in data["mediaItems"]] == ["m1"]
    # No `filter` query parameter was sent to Google.
    url = str(client._http._transport.requests[0].url)
    assert "filter" not in url


@pytest.mark.asyncio
async def test_list_media_follows_pagination():
    """Google caps a page below the requested size; every page is followed."""
    script = [
        (
            200,
            {},
            b'{"mediaItems":[{"name":"m1","locationAssociation":{"category":"EXTERIOR"}}],'
            b'"totalMediaItemCount":2,"nextPageToken":"t2"}',
        ),
        (
            200,
            {},
            b'{"mediaItems":[{"name":"m2","locationAssociation":{"category":"EXTERIOR"}}],'
            b'"totalMediaItemCount":2}',
        ),
    ]
    client = _make_client(script)

    data = await client.list_media("a", "l")

    assert [m["name"] for m in data["mediaItems"]] == ["m1", "m2"]
    assert data["totalMediaItemCount"] == 2
    assert "nextPageToken" not in data
    assert len(client._http._transport.requests) == 2
