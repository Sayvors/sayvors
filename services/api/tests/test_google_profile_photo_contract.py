"""Contract tests: the Google Business Profile profile picture / cover image.

Pins the exact wire format Google documents for the two location surfaces
that are not gallery photos, so a typo cannot reach Google:

Upload from a URL
    POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/media
    {"mediaFormat": "PHOTO",
     "locationAssociation": {"category": "PROFILE"},
     "sourceUrl": "https://example.com/images/business-profile-logo.jpg"}

Upload from bytes
    1. POST .../media:startUpload            -> {"resourceName": "..."}
    2. POST https://mybusiness.googleapis.com/upload/v1/media/{resourceName}?upload_type=media
    3. POST .../media  {"mediaFormat": "PHOTO",
                        "locationAssociation": {"category": "PROFILE"},
                        "dataRef": {"resourceName": "..."}}

Two documented behaviours these tests protect:
- A location has only one profile photo, filed under the fixed resource name
  ``.../locations/{id}/media/profile``; creating it again replaces the old
  one. No delete-then-create, which would leave the listing with no avatar
  whenever the upload fails half way.
- Google returns the Unix epoch as a profile photo's ``createTime`` and
  leaves its dimensions empty, so neither can be used as upload metadata.

Run only this file:  pytest services/api/tests/test_google_profile_photo_contract.py
"""
import io
import json
import random

import httpx
import pytest

# Pillow is a live-path dependency (the publisher validates image dimensions
# with it) but not a CI test dependency; skip the whole module when absent.
pytest.importorskip("PIL")

from PIL import Image

from app.modules.channels.google_reviews import GoogleReviewsClient
from app.modules.channels.meta.providers.google_publish import GoogleBusinessPublisher


class _RecordingTransport:
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
PROFILE_NAME = f"accounts/{ACCOUNT}/locations/{LOCATION}/media/profile"


def _body(request) -> dict:
    return json.loads(request.content.decode())


def _profile_png(size: int = 400) -> bytes:
    """A real square PNG above Google's 10 KB floor."""
    img = Image.new("RGB", (size, size), (20, 90, 160))
    rnd = random.Random(size)
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (
                (px[x, y][0] + rnd.randint(0, 60)) % 256,
                (px[x, y][1] + rnd.randint(0, 60)) % 256,
                (px[x, y][2] + rnd.randint(0, 60)) % 256,
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert len(buf.getvalue()) > 10 * 1024
    return buf.getvalue()


# -- profile picture from a URL --------------------------------------------

@pytest.mark.asyncio
async def test_profile_photo_from_url_matches_the_documented_body():
    script = [(200, {}, json.dumps({
        "name": PROFILE_NAME,
        "mediaFormat": "PHOTO",
        "locationAssociation": {"category": "PROFILE"},
        "googleUrl": "https://lh3.googleusercontent.com/a-/profile",
        "createTime": "1970-01-01T00:00:00Z",
    }).encode())]
    client = _client(script)

    await client.create_location_media(
        ACCOUNT,
        LOCATION,
        category="PROFILE",
        source_url="https://example.com/images/business-profile-logo.jpg",
    )

    req = client._http._transport.requests[0]
    assert req.method == "POST"
    assert req.url.host == "mybusiness.googleapis.com"
    assert req.url.path == MEDIA_PATH
    assert req.url.query == b""
    assert _body(req) == {
        "mediaFormat": "PHOTO",
        "locationAssociation": {"category": "PROFILE"},
        "sourceUrl": "https://example.com/images/business-profile-logo.jpg",
    }


# -- profile picture from bytes --------------------------------------------

@pytest.mark.asyncio
async def test_profile_photo_from_bytes_uses_start_upload_then_data_ref():
    png = _profile_png()
    script = [
        (200, {}, b'{"resourceName":"GoogleProvidedValue"}'),
        (200, {}, b""),
        (200, {}, json.dumps({
            "name": PROFILE_NAME,
            "mediaFormat": "PHOTO",
            "locationAssociation": {"category": "PROFILE"},
        }).encode()),
    ]
    client = _client(script)

    ref = await client.start_media_upload(ACCOUNT, LOCATION)
    await client.upload_media_bytes(ref, png, "image/png")
    created = await client.create_location_media(
        ACCOUNT, LOCATION, category="PROFILE", data_ref=ref
    )

    start, upload, create = client._http._transport.requests

    assert start.method == "POST"
    assert start.url.path == f"{MEDIA_PATH}:startUpload"

    # The upload endpoint is the root-level /upload/v1 host path, not /v4.
    assert upload.method == "POST"
    assert upload.url.host == "mybusiness.googleapis.com"
    assert upload.url.path == "/upload/v1/media/GoogleProvidedValue"
    assert upload.url.query == b"upload_type=media"
    assert upload.content == png
    assert upload.headers["content-type"] == "image/png"

    assert create.method == "POST"
    assert create.url.path == MEDIA_PATH
    assert _body(create) == {
        "mediaFormat": "PHOTO",
        "locationAssociation": {"category": "PROFILE"},
        "dataRef": {"resourceName": "GoogleProvidedValue"},
    }

    # The profile photo lives at a fixed resource name, which is what makes
    # a re-upload a replacement rather than a second avatar.
    assert created["name"] == PROFILE_NAME


@pytest.mark.asyncio
async def test_profile_photo_is_never_refiled_under_additional():
    """A refused PROFILE tag must fail, not land in the public gallery."""
    script = [(400, {}, json.dumps({
        "error": {
            "code": 400,
            "status": "INVALID_ARGUMENT",
            "message": "Request contains an invalid argument.",
            "details": [{
                "@type": "type.googleapis.com/google.rpc.BadRequest",
                "fieldViolations": [{
                    "field": "media.location_association.category",
                    "description": "Photo tag 'profile' does not apply to this location",
                }],
            }],
        }
    }).encode())]
    client = _client(script)

    with pytest.raises(Exception):
        await client.create_location_media(
            ACCOUNT, LOCATION, category="PROFILE",
            source_url="https://example.com/logo.png",
        )

    # Exactly one call: there is no second request filed as ADDITIONAL.
    assert len(client._http._transport.requests) == 1


# -- cover image -----------------------------------------------------------

@pytest.mark.asyncio
async def test_cover_upload_carries_no_description():
    """Google: a description can be set on new media that is not a cover."""
    script = [
        (200, {}, b'{"name":"accounts/a/locations/l/media/c1"}'),
        (200, {}, b'{"name":"accounts/a/locations/l/media/p1"}'),
    ]
    client = _client(script)

    await client.create_location_media(
        ACCOUNT, LOCATION, category="COVER",
        source_url="https://example.com/cover.jpg", description="Front of shop",
    )
    await client.create_location_media(
        ACCOUNT, LOCATION, category="PROFILE",
        source_url="https://example.com/logo.png", description="Our logo",
    )

    cover, profile = client._http._transport.requests
    assert "description" not in _body(cover)
    assert _body(cover)["locationAssociation"] == {"category": "COVER"}
    assert _body(profile)["description"] == "Our logo"


# -- the composer's path ---------------------------------------------------

@pytest.mark.asyncio
async def test_publisher_profile_picture_uses_the_media_endpoint():
    """The compose flow must produce the same request as the media API."""
    png = _profile_png()
    script = [
        (200, {}, b'{"resourceName":"Ref-1"}'),
        (200, {}, b""),
        (200, {}, json.dumps({
            "name": PROFILE_NAME,
            "mediaFormat": "PHOTO",
            "locationAssociation": {"category": "PROFILE"},
        }).encode()),
    ]
    publisher = GoogleBusinessPublisher("token", "refresh")
    publisher._client._http = httpx.AsyncClient(
        transport=_RecordingTransport(script)
    )

    result = await publisher.set_location_image(
        token="token",
        asset_id=LOCATION,
        account_id=ACCOUNT,
        method="profile",
        media_url="https://sayvors.com/media-files/t/logo.png",
        media_data=png,
        content_type="image/png",
    )

    create = publisher._client._http._transport.requests[-1]
    assert create.url.path == MEDIA_PATH
    body = _body(create)
    assert body["locationAssociation"] == {"category": "PROFILE"}
    assert body["dataRef"] == {"resourceName": "Ref-1"}
    assert "sourceUrl" not in body
    assert result["category"] == "PROFILE"
