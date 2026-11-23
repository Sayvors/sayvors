"""Free tbm=map search adapter: payload mapping, dedupe, bounds, errors."""
import json

import pytest

from app.modules.benchmark import mapsearch

FTID = "0x3e2f030074314241:0x1a77a4b3c8dcc379"
PLACE_ID = "ChIJQUIxdAADLz4RecPcyLOkdxo"


def _place_darray(index: int = 1, *, name: str = "Wahmy", place_id: str = PLACE_ID) -> list:
    da = [None] * 100
    da[4] = [None, None, None, [None, "12,665 reviews"], None, None, None, 4.5, 12665]
    da[9] = [None, None, 24.7028865, 46.6979563]
    da[10] = FTID
    da[11] = name
    da[14] = "As Sulimaniyah"
    da[18] = "PM2W+XPR Wahmy, As Sulimaniyah, Riyadh 12242"
    da[78] = place_id
    return da


def _body(*places: list) -> str:
    entries = [[None] * 14 + [p] for p in places]
    return ")]}'\n" + json.dumps([["query", entries]])


class _Response:
    def __init__(self, status: int = 200, text: str = ""):
        self.status_code = status
        self.text = text


class _Client:
    def __init__(self, body: str, status: int = 200):
        self.body = body
        self.status = status
        self.requests = []

    async def get(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return _Response(self.status, self.body)

    async def aclose(self):
        return None


def test_search_maps_every_place_field():
    places = mapsearch._parse(_body(_place_darray()))
    assert len(places) == 1
    p = places[0]

    assert p["place_id"] == PLACE_ID
    assert p["name"] == "Wahmy"
    assert p["rating"] == 4.5
    assert p["review_count"] == 12665
    assert p["latitude"] == pytest.approx(24.7028865)
    assert p["longitude"] == pytest.approx(46.6979563)
    assert "Riyadh" in p["address"]
    # The canonical URL must carry the feature id BOQ needs later.
    assert mapsearch_module_feature(p["maps_url"]) == FTID
    assert p["reviews"] == []
    assert p["source"] == "mapsearch"


def mapsearch_module_feature(url: str) -> str:
    from app.modules.benchmark import boq

    return boq.feature_id(url)


def test_search_dedupes_by_place_id():
    places = mapsearch._parse(
        _body(_place_darray(), _place_darray(place_id=PLACE_ID))
    )
    assert len(places) == 1


def test_search_skips_metadata_entries_without_a_place_array():
    places = mapsearch._parse(_body([None] * 20, _place_darray()))
    assert len(places) == 1


def test_search_rejects_invalid_body():
    with pytest.raises(mapsearch.MapSearchError):
        mapsearch._parse("not json")


def test_search_rejects_changed_layout():
    with pytest.raises(mapsearch.MapSearchError):
        mapsearch._parse(")]}'\n" + '{"changed": true}')


async def test_search_returns_at_most_limit():
    places = [
        _place_darray(place_id=f"ChIJplace{i}") for i in range(6)
    ]
    client = _Client(_body(*places))

    result = await mapsearch.search_places("cafe", limit=3, client=client)

    assert len(result) == 3
    assert client.requests[0]["params"]["tbm"] == "map"
    assert client.requests[0]["params"]["q"] == "cafe"


async def test_search_empty_query_makes_no_request():
    client = _Client(_body())
    assert await mapsearch.search_places("  ", client=client) == []
    assert client.requests == []


async def test_search_rate_limit_maps_to_503():
    client = _Client("", status=429)
    with pytest.raises(mapsearch.MapSearchError) as exc:
        await mapsearch.search_places("cafe", client=client)
    assert exc.value.status_code == 503
