"""Service areas resolve to Google Place IDs, never free text.

The Business Information API only accepts region place IDs. Places API (New)
Text Search is the bridge; a missing key or a non-region result must degrade
to a skipped section, never a fabricated Place ID.
"""
import pytest

from app.modules.locations import places


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_missing_key_raises_places_error(monkeypatch):
    monkeypatch.setattr(places.settings, "GOOGLE_PLACES_API_KEY", "")
    with pytest.raises(places.PlacesError) as err:
        await places.resolve_service_area(["Riyadh"])
    assert err.value.status_code == 503


@pytest.mark.asyncio
async def test_resolve_picks_a_region_and_ignores_business_results(monkeypatch):
    monkeypatch.setattr(places.settings, "GOOGLE_PLACES_API_KEY", "key")
    fake = _FakeClient([
        _Resp(200, {"places": [
            {"id": "places/ChIJbusiness", "types": ["restaurant", "food"],
             "displayName": {"text": "A Restaurant"}},
            {"id": "places/ChIJriyadh", "types": ["locality", "political"],
             "displayName": {"text": "Riyadh"}, "formattedAddress": "Riyadh, Saudi Arabia"},
        ]}),
    ])
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kwargs: fake)

    out = await places.resolve_service_area(["Riyadh"], region_code="SA")
    assert out == [{"placeId": "ChIJriyadh", "placeName": "Riyadh"}]
    assert fake.calls[0]["headers"]["X-Goog-Api-Key"] == "key"
    assert fake.calls[0]["json"]["textQuery"] == "Riyadh"
    assert fake.calls[0]["json"]["regionCode"] == "SA"


@pytest.mark.asyncio
async def test_no_region_result_is_skipped_not_invented(monkeypatch):
    monkeypatch.setattr(places.settings, "GOOGLE_PLACES_API_KEY", "key")
    fake = _FakeClient([
        _Resp(200, {"places": [
            {"id": "places/ChIJbusiness", "types": ["restaurant"],
             "displayName": {"text": "A Restaurant"}},
        ]}),
    ])
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kwargs: fake)
    assert await places.resolve_service_area(["Nowhere"]) == []


@pytest.mark.asyncio
async def test_duplicate_names_are_searched_once(monkeypatch):
    monkeypatch.setattr(places.settings, "GOOGLE_PLACES_API_KEY", "key")
    fake = _FakeClient([
        _Resp(200, {"places": [
            {"id": "places/ChIJriyadh", "types": ["locality"],
             "displayName": {"text": "Riyadh"}},
        ]}),
    ])
    monkeypatch.setattr(places.httpx, "AsyncClient", lambda **kwargs: fake)
    out = await places.resolve_service_area(["Riyadh", "riyadh", " Riyadh "])
    assert out == [{"placeId": "ChIJriyadh", "placeName": "Riyadh"}]
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_push_profile_patches_resolved_service_area(monkeypatch):
    from app.modules.channels.google_business import GoogleBusinessClient

    client = GoogleBusinessClient("access-token")
    calls: list[tuple[dict, str]] = []

    async def _patch(location_id, body, mask):
        calls.append((body, mask))
        return {}

    async def _resolve(names):
        assert names == ["Riyadh", "Jeddah"]
        return [
            {"placeId": "ChIJriyadh", "placeName": "Riyadh"},
            {"placeId": "ChIJjeddah", "placeName": "Jeddah"},
        ]

    client.patch_location = _patch
    monkeypatch.setattr(
        "app.modules.locations.places.resolve_service_area", _resolve
    )
    report = await client.push_profile(
        "123", service_area=["Riyadh", "Jeddah"]
    )
    assert report["pushed"] == ["service_area"]
    assert calls == [(
        {"serviceArea": {"places": {"placeInfos": [
            {"placeId": "ChIJriyadh", "placeName": "Riyadh"},
            {"placeId": "ChIJjeddah", "placeName": "Jeddah"},
        ]}}},
        "serviceArea.places.placeInfos",
    )]
    await client.close()


@pytest.mark.asyncio
async def test_empty_service_area_is_not_patched(monkeypatch):
    from app.modules.channels.google_business import GoogleBusinessClient

    client = GoogleBusinessClient("access-token")
    calls: list[tuple[dict, str]] = []

    async def _patch(location_id, body, mask):
        calls.append((body, mask))
        return {}

    client.patch_location = _patch
    report = await client.push_profile("123", service_area=[])
    assert calls == []
    assert "service_area" in report["skipped"]
    await client.close()
