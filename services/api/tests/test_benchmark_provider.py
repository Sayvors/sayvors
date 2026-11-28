"""Provider strategy: official Places facts, BOQ deep reviews, BOQ fallback."""
import pytest

from app.modules.benchmark import boq, places, provider

FTID = "0x3e2eff0029e37d6d:0xf18199ab22d80c09"
MAPS_URL = (
    "https://www.google.com/maps/place/X/data=!4m6!3m5"
    f"!1s{FTID}!8m2!3d24.8!4d46.6"
)


def _places_payload() -> dict:
    return {
        "place_id": "places/1",
        "name": "Official Cafe",
        "address": "Riyadh",
        "types": ["cafe"],
        "rating": 4.4,
        "review_count": 100,
        "reviews": [{"rating": 5, "text": "official"}],
        "photos": [],
    }


def _boq_payload() -> dict:
    return {
        "place_id": "places/1",
        "name": "Free Cafe",
        "rating": 4.1,
        "review_count": 99,
        "reviews": [{"rating": i % 5 + 1, "text": f"deep-{i}"} for i in range(250)],
        "thumbnail": "https://lh3.googleusercontent.com/cover",
        "maps_url": MAPS_URL,
    }


@pytest.fixture(autouse=True)
def _configured_places(monkeypatch):
    monkeypatch.setattr(places, "configured", lambda: True)


async def test_places_facts_keep_boq_deep_reviews(monkeypatch):
    called = {}

    async def places_get(place_id, **kwargs):
        called["places"] = kwargs
        return _places_payload()

    async def boq_get(place_id, **kwargs):
        called["boq"] = kwargs
        return _boq_payload()

    monkeypatch.setattr(places, "get_place", places_get)
    monkeypatch.setattr(boq, "get_place", boq_get)

    result = await provider.get_details(
        "google_places", "places/1", reviews_limit=250, maps_url=MAPS_URL
    )

    assert called["places"]["reviews_limit"] == 10
    assert called["boq"]["reviews_limit"] == 250
    assert called["boq"]["maps_url"] == MAPS_URL
    assert result["rating"] == 4.4
    assert result["review_count"] == 100
    assert len(result["reviews"]) == 250
    assert result["thumbnail"] == "https://lh3.googleusercontent.com/cover"
    assert result["reviews_source"] == "boq"


async def test_places_failure_falls_back_to_boq(monkeypatch):
    async def places_get(place_id, **kwargs):
        raise places.PlacesError("quota exceeded", 429)

    async def boq_get(place_id, **kwargs):
        return _boq_payload()

    monkeypatch.setattr(places, "get_place", places_get)
    monkeypatch.setattr(boq, "get_place", boq_get)

    result = await provider.get_details(
        "google_places", "places/1", reviews_limit=250, maps_url=MAPS_URL
    )

    assert result["name"] == "Free Cafe"
    assert result["rating"] == 4.1
    assert result["reviews_source"] == "boq"


async def test_unconfigured_places_uses_boq_without_calling_places(monkeypatch):
    monkeypatch.setattr(places, "configured", lambda: False)

    async def places_get(place_id, **kwargs):
        raise AssertionError("Places must not be called without a key")

    async def boq_get(place_id, **kwargs):
        return _boq_payload()

    monkeypatch.setattr(places, "get_place", places_get)
    monkeypatch.setattr(boq, "get_place", boq_get)

    result = await provider.get_details(
        "google_places", "places/1", reviews_limit=250, maps_url=MAPS_URL
    )

    assert result["name"] == "Free Cafe"


async def test_places_without_feature_id_skips_boq_deep_reviews(monkeypatch):
    async def places_get(place_id, **kwargs):
        return _places_payload()

    async def boq_get(place_id, **kwargs):
        raise AssertionError("BOQ must not be called without a feature id")

    monkeypatch.setattr(places, "get_place", places_get)
    monkeypatch.setattr(boq, "get_place", boq_get)

    result = await provider.get_details(
        "google_places", "places/1", reviews_limit=250, maps_url=None
    )

    assert result["rating"] == 4.4
    assert len(result["reviews"]) == 1
    assert "reviews_source" not in result
