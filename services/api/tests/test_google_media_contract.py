"""Contract tests: the Google Business Profile media API wire format.

These tests pin the exact URLs, query parameters and request bodies that
the Google Business Profile API expects, so a typo can never reach Google
again (a wrong method gave a 405, a wrong query parameter gave
``INVALID_ARGUMENT``).

The contract, per Google's own documentation:

Upload from a URL
    POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/media
    {"mediaFormat": "PHOTO", "locationAssociation": {"category": "INTERIOR"},
     "sourceUrl": "https://example.com/images/interior-shot.jpg"}

Upload from bytes
    1. POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/media:startUpload
       -> {"resourceName": "GoogleProvidedValue"}
    2. POST https://mybusiness.googleapis.com/upload/v1/media/{resourceName}?upload_type=media
       (the binary is the request body)
    3. POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/media
       {"mediaFormat": "PHOTO", "locationAssociation": {"category": "EXTERIOR"},
        "dataRef": {"resourceName": "GoogleProvidedValue"}}

Run only this file:  pytest services/api/tests/test_google_media_contract.py
"""
import json

import httpx
import pytest

from app.modules.channels.google_reviews import GoogleReviewsClient


class _RecordingTransport:
    """Records every request and answers with a scripted response."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        status, headers, body = self.script.pop(0)
        return httpx.Response(status, headers=headers, content=body)


def _client(script):
    client = GoogleReviewsClient("access-token", "refresh-token")
    client._http = httpx.AsyncClient(transport=_RecordingTransport(script))
    return client


ACCOUNT = "117767562410497296372"
LOCATION = "8411302920254759403"
MEDIA_PATH = f"/v4/accounts/{ACCOUNT}/locations/{LOCATION}/media"


def _body(request) -> dict:
    return json.loads(request.content.decode())


# -- upload from a URL ------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_from_url_matches_the_documented_request():
    script = [(200, {}, b'{"name":"accounts/a/locations/l/media/m1",'
                       b'"mediaFormat":"PHOTO",'
                       b'"locationAssociation":{"category":"INTERIOR"}}')]
    client = _client(script)

    await client.create_location_media(
        ACCOUNT,
        LOCATION,
        category="INTERIOR",
        source_url="https://example.com/images/interior-shot.jpg",
    )

    req = client._http._transport.requests[0]
    assert req.method == "POST"
    assert req.url.host == "mybusiness.googleapis.com"
    assert req.url.path == MEDIA_PATH
    assert req.url.query == b""
    assert _body(req) == {
        "mediaFormat": "PHOTO",
        "locationAssociation": {"category": "INTERIOR"},
        "sourceUrl": "https://example.com/images/interior-shot.jpg",
    }


# -- upload from bytes ------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_from_bytes_matches_the_documented_three_steps():
    script = [
        (200, {}, b'{"resourceName":"GoogleProvidedValue"}'),  # step 1
        (200, {}, b""),                                        # step 2
        (200, {}, b'{"name":"accounts/a/locations/l/media/m2",'
                   b'"mediaFormat":"PHOTO",'
                   b'"locationAssociation":{"category":"EXTERIOR"}}'),  # step 3
    ]
    client = _client(script)

    # Step 1: request the upload token.
    ref = await client.start_media_upload(ACCOUNT, LOCATION)
    assert ref == "GoogleProvidedValue"

    # Step 2: upload the binary.
    await client.upload_media_bytes(ref, b"\xff\xd8\xff binary", "image/jpeg")

    # Step 3: create the media item from the uploaded bytes.
    await client.create_location_media(
        ACCOUNT, LOCATION, category="EXTERIOR", data_ref=ref
    )

    requests = client._http._transport.requests
    assert len(requests) == 3

    # Step 1 - startUpload, no body, no query parameters.
    step1 = requests[0]
    assert step1.method == "POST"
    assert step1.url.host == "mybusiness.googleapis.com"
    assert step1.url.path == f"{MEDIA_PATH}:startUpload"
    assert step1.url.query == b""

    # Step 2 - the binary on the upload endpoint, with the documented
    # `upload_type=media` query parameter.
    step2 = requests[1]
    assert step2.method == "POST"
    assert step2.url.host == "mybusiness.googleapis.com"
    assert step2.url.path == "/upload/v1/media/GoogleProvidedValue"
    assert step2.url.query == b"upload_type=media"
    assert step2.content == b"\xff\xd8\xff binary"
    assert step2.headers["content-type"] == "image/jpeg"

    # Step 3 - the create call, referencing the uploaded resource name.
    step3 = requests[2]
    assert step3.method == "POST"
    assert step3.url.host == "mybusiness.googleapis.com"
    assert step3.url.path == MEDIA_PATH
    assert step3.url.query == b""
    assert _body(step3) == {
        "mediaFormat": "PHOTO",
        "locationAssociation": {"category": "EXTERIOR"},
        "dataRef": {"resourceName": "GoogleProvidedValue"},
    }


@pytest.mark.asyncio
async def test_start_upload_accepts_the_data_ref_envelope():
    """Google returns the token under dataRef on some responses."""
    script = [(200, {}, b'{"dataRef":{"resourceName":"GoogleProvidedValue"}}')]
    client = _client(script)

    assert await client.start_media_upload(ACCOUNT, LOCATION) == "GoogleProvidedValue"


# -- listing ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_media_uses_the_documented_path_and_query_parameters():
    script = [(200, {}, b'{"mediaItems":[],"totalMediaItemCount":0}')]
    client = _client(script)

    await client.list_media(ACCOUNT, LOCATION, page_size=50, page_token="tok")

    req = client._http._transport.requests[0]
    assert req.method == "GET"
    assert req.url.host == "mybusiness.googleapis.com"
    assert req.url.path == MEDIA_PATH
    # Only the two documented query parameters are ever sent.
    assert set(req.url.params.keys()) <= {"pageSize", "pageToken"}
