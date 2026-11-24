"""Free place-detail adapter: rating/count/address/category/photo by feature id.

Pins the payload slots the parser depends on. Google's response is
undocumented; if a slot moves the parser must raise rather than store a
plausible-looking zero.
"""
import json
from urllib.parse import quote

import pytest

from app.modules.benchmark import placedetail

FTID = "0x3e2eff0029e37d6d:0xf18199ab22d80c09"
COVER = "https://lh3.googleusercontent.com/grass-cs/AABkmLeIMBj_cover"
GALLERY = "https://lh3.googleusercontent.com/grass-cs/AABkmLdAbrp_gallery"


def _darray(*, cover: str | None = COVER, gallery: str | None = GALLERY) -> list:
    da = [None] * 260
    da[4] = [None, None, None, [None, "6,633 reviews"], None, None, None, 4.4, 6633]
    da[9] = [None, None, 24.8152487, 46.7774083]
    da[11] = "Wahmy Burger"
    da[13] = ["Hamburger restaurant"]
    da[14] = "Al Yarmuk"
    da[18] = "PM2W+XPR Wahmy, Al Yarmuk, Riyadh 13251"
    da[39] = "Dammam Branch Rd, Al Yarmuk, Riyadh 13251, Saudi Arabia"
    da[78] = "ChIJbX3jKQD_Lj4RCQzYIquZgfE"
    # da[37] is the cover block: jd[6][37][0][0][6][0] holds the photo URL.
    da[37] = [[[[None, None, None, None, None, None, [cover] if cover else None]]]]
    # da[51] is the gallery: jd[6][51][0][i][6][0].
    da[51] = [[[[[None] * 6 + [[gallery] if gallery else None]]]]]
    return da


def _body(da: list) -> str:
    top = [None] * 44
    top[6] = da
    return ")]}'\n" + json.dumps(top)


class _Response:
    def __init__(self, status: int = 200, text: str = ""):
        self.status_code = status
        self.text = text


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response

    async def aclose(self):
        return None


# ── Identity ───────────────────────────────────────────────────────────────


def test_feature_id_read_from_maps_url():
    url = "https://www.google.com/maps/place/X/@24.8,46.7,17z/data=!3m1!4b1!4m6!3m5!1s" + FTID + "!8m2!3d24.8!4d46.7"
    assert placedetail.feature_id(url) == FTID


def test_feature_id_absent_for_bare_place_id_url():
    assert placedetail.feature_id("https://www.google.com/maps/place/?q=place_id:ChIJabc") is None
    assert placedetail.feature_id(None) is None


# ── Parsing ────────────────────────────────────────────────────────────────


def test_parse_maps_rating_count_address_and_category():
    place = placedetail.parse(_body(_darray()))

    assert place["name"] == "Wahmy Burger"
    assert place["rating"] == pytest.approx(4.4)
    assert place["review_count"] == 6633
    assert place["address"] == "Dammam Branch Rd, Al Yarmuk, Riyadh 13251, Saudi Arabia"
    assert place["types"] == ["Hamburger restaurant"]
    assert place["latitude"] == pytest.approx(24.8152487)
    assert place["longitude"] == pytest.approx(46.7774083)
    assert place["place_id"] == "ChIJbX3jKQD_Lj4RCQzYIquZgfE"


def test_parse_uses_the_cover_photo_for_the_card():
    assert placedetail.parse(_body(_darray()))["thumbnail"] == COVER


def test_parse_falls_back_to_the_gallery_when_there_is_no_cover():
    place = placedetail.parse(_body(_darray(cover=None)))

    assert place["thumbnail"] == GALLERY


def test_parse_keeps_a_photo_url_with_a_size_suffix():
    assert placedetail.parse(_body(_darray(cover=COVER + "=s256")))["thumbnail"] == COVER + "=s256"


def test_parse_leaves_thumbnail_empty_when_the_place_has_no_photos():
    assert placedetail.parse(_body(_darray(cover=None, gallery=None)))["thumbnail"] is None


def test_parse_never_takes_a_non_google_image_url():
    da = _darray(cover="https://evil.example.com/track.jpg")
    da[51] = None

    assert placedetail.parse(_body(da))["thumbnail"] is None


def test_parse_rejects_an_empty_body():
    """An empty body is a block, not a place with no data."""
    with pytest.raises(placedetail.PlaceDetailError):
        placedetail.parse("")


def test_parse_rejects_a_changed_layout():
    with pytest.raises(placedetail.PlaceDetailError):
        placedetail.parse(")]}'\n" + json.dumps([None, [], None, None, [], None]))


def test_parse_rejects_a_payload_without_a_title():
    da = _darray()
    da[11] = None
    with pytest.raises(placedetail.PlaceDetailError):
        placedetail.parse(_body(da))


# ── Fetch ──────────────────────────────────────────────────────────────────


async def test_get_place_requests_the_feature_and_returns_the_place():
    client = _Client(_Response(200, _body(_darray())))

    place = await placedetail.get_place(
        FTID, client=client, session={"NID": "abc"},
    )

    assert place["name"] == "Wahmy Burger"
    assert place["source"] == "placedetail"
    call = client.calls[0]
    assert quote(FTID, safe="") in call["url"]
    assert call["cookies"] == {"NID": "abc"}


async def test_get_place_requires_a_feature_id():
    with pytest.raises(placedetail.PlaceDetailError) as exc:
        await placedetail.get_place("", client=_Client(_Response(200, "")), session={})
    assert exc.value.status_code == 422


async def test_get_place_maps_rate_limiting_to_503():
    client = _Client(_Response(429, ""))

    with pytest.raises(placedetail.PlaceDetailError) as exc:
        await placedetail.get_place(FTID, client=client, session={})

    assert exc.value.status_code == 503
