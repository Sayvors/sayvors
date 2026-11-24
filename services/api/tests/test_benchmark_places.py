"""Places client: field mapping, bounded results, generic errors."""
import pytest

from app.config import settings
from app.modules.benchmark import places

pytestmark = pytest.mark.asyncio


async def _async_none(*args, **kwargs):
    return None


class _Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.resp

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.resp


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OUTSCRAPER_API_KEY", "")


async def test_search_maps_fields_and_strips_prefix(monkeypatch, key):
    client = _Client(_Response(payload={"places": [
        {"id": "places/abc123", "displayName": {"text": "Riyadh Cafe"},
         "formattedAddress": "Malaz, Riyadh", "rating": 4.5,
         "userRatingCount": 120, "types": ["cafe"]},
    ]}))
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(places, "_cache_get_json", lambda *a, **k: _async_none())
    monkeypatch.setattr(places, "_cache_set_json", lambda *a, **k: _async_none())

    result = await places.search_places("cafe riyadh")
    assert result == [{
        "place_id": "abc123", "name": "Riyadh Cafe", "address": "Malaz, Riyadh",
        "rating": 4.5, "review_count": 120,
        "latitude": None, "longitude": None,
        "types": ["cafe"],
    }]
    assert client.calls[0][1]["json"]["maxResultCount"] == places.MAX_SEARCH_RESULTS


async def test_search_missing_key_fails_503(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "")
    monkeypatch.setattr(settings, "OUTSCRAPER_API_KEY", "")
    with pytest.raises(places.PlacesError) as exc:
        await places.search_places("cafe")
    assert exc.value.status_code == 503


async def test_search_failure_hides_response_body(monkeypatch, key):
    client = _Client(_Response(status=429))
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kw: client)
    with pytest.raises(places.PlacesError) as exc:
        await places.search_places("cafe")
    assert exc.value.status_code == 429
    assert "429" not in str(exc.value)
    assert "internal-secret" not in str(exc.value)


async def test_details_maps_reviews_and_photos(monkeypatch, key):
    client = _Client(_Response(payload={
        "id": "places/abc", "displayName": {"text": "Cafe"},
        "rating": 4.2, "userRatingCount": 50,
        "reviews": [{"rating": 5, "text": {"text": "Great"}, "publishTime": "2026-01-01T00:00:00Z"}],
        "photos": [{"name": "places/abc/photos/p1", "widthPx": 800}],
    }))
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kw: client)
    result = await places.get_place("places/abc")
    assert result["place_id"] == "abc"
    assert result["reviews"][0]["text"] == "Great"
    assert result["photos"][0]["name"] == "places/abc/photos/p1"


async def test_get_place_caps_reviews_limit(monkeypatch, key):
    client = _Client(_Response(payload={
        "id": "places/abc", "displayName": {"text": "Cafe"},
        "rating": 4.2, "userRatingCount": 50,
        "reviews": [{"rating": i, "text": {"text": f"r{i}"}, "publishTime": "2026-01-01T00:00:00Z"} for i in range(20)],
        "photos": [],
    }))
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(places, "_cache_get_json", lambda *a, **k: _async_none())
    monkeypatch.setattr(places, "_cache_set_json", lambda *a, **k: _async_none())

    result = await places.get_place("places/abc", reviews_limit=999)
    assert result["place_id"] == "abc"
    assert len(result["reviews"]) == 10
