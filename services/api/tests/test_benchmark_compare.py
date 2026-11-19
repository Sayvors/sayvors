"""Two-sided comparison facts: scoping, normalization and honest empty states."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.benchmark import compare

pytestmark = pytest.mark.asyncio

TENANT = "tenant-compare"


async def test_parse_subject():
    assert compare.parse_subject("saved:ChIJ123") == ("saved", "ChIJ123")
    assert compare.parse_subject("own:channel-1") == ("own", "channel-1")
    for bad in ("", "saved:", "unknown:abc", "saved", "own:", "places:abc"):
        with pytest.raises(compare.CompareError):
            compare.parse_subject(bad)


async def test_scan_reviews_counts_windows_stars_and_text():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=2)).isoformat()
    old = (now - timedelta(days=40)).isoformat()
    reviews = [
        {"rating": 5, "text": "The staff are hard working, great parking", "publish_time": recent},
        {"rating": 1, "text": "No parking and expensive menu prices", "publish_time": old},
        {"rating": 4, "text": "Lovely food", "publish_time": recent},
    ]
    scan = compare._scan_reviews(reviews)
    assert scan["windows"]["reviews_last_week"] == 2
    assert scan["windows"]["reviews_last_month"] == 2
    assert scan["windows"]["reviews_last_year"] == 3
    assert scan["stars"][5] == 1 and scan["stars"][1] == 1
    assert scan["text_counts"]["employee_mentions"] == 1
    assert scan["text_counts"]["working_hard_mentions"] == 1
    assert scan["text_counts"]["parking_praised"] == 1
    assert scan["text_counts"]["parking_criticised"] == 1
    assert scan["text_counts"]["menu_price_mentions"] == 1


async def test_saved_subject_uses_places_and_flags_hidden_facts(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(db, TENANT, place_id="cmp-1", label="Rival Cafe")

    async def _fake_get_place(place_id):
        assert place_id == "cmp-1"
        now = datetime.now(timezone.utc)
        return {
            "place_id": "cmp-1",
            "name": "Rival Cafe",
            "address": "Riyadh",
            "rating": 4.4,
            "review_count": 900,
            "types": ["cafe", "coffee_shop"],
            "reviews": [
                {"rating": 5, "text": "helpful staff", "publish_time": (now - timedelta(days=1)).isoformat()},
                {"rating": 2, "text": "bad parking", "publish_time": (now - timedelta(days=1)).isoformat()},
            ],
        }

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    result = (await compare.compare_subjects(db, TENANT, ["saved:cmp-1"]))[0]

    assert result["available"] is True
    assert result["name"] == "Rival Cafe"
    assert result["metrics"]["total_reviews"] == 900
    assert result["metrics"]["avg_rating"] == 4.4
    assert result["metrics"]["reviews_last_week"] == 2
    assert result["metrics"]["five_star"] == 1 and result["metrics"]["one_star"] == 0
    assert result["metrics"]["impressions"] is None  # owner-only fact
    assert result["metrics"]["calls"] is None
    assert result["facts"]["services"] == ["Cafe", "Coffee shop"]
    assert "only available to the listing owner" in result["notes"][-1]


async def test_saved_subject_not_on_bench_is_unavailable(db):
    result = (await compare.compare_subjects(db, TENANT, ["saved:not-mine"]))[0]
    assert result["available"] is False
    assert "not on your bench" in result["reason"]


async def test_own_subject_uses_analytics(db, channel_id, user_id):
    result = (await compare.compare_subjects(db, user_id, [f"own:{channel_id}"]))[0]
    assert result["available"] is True
    assert result["data_source"] == "sayvors_analytics"
    assert result["name"] == "Test Burgers"
    assert result["metrics"]["total_reviews"] == 0
    assert result["metrics"]["reviews_last_day"] == 0
    assert result["metrics"]["impressions"] == 0
    assert result["facts"]["branch"] == "Test Burgers"
    assert result["verified"] is False


async def test_own_subject_scoped_to_tenant(db, channel_id, user_id, other_user_id):
    result = (await compare.compare_subjects(db, other_user_id, [f"own:{channel_id}"]))[0]
    assert result["available"] is False
    assert "not connected" in result["reason"]


async def test_two_sides_and_bad_side_do_not_break_each_other(db, channel_id, user_id):
    results = await compare.compare_subjects(
        db, user_id, [f"own:{channel_id}", "garbage"]
    )
    assert len(results) == 2
    assert results[0]["available"] is True
    assert results[1]["available"] is False


async def test_compare_endpoint(client, monkeypatch):
    from app.modules.benchmark import places as places_module

    created = client.post(
        "/api/v1/benchmark/places", json={"place_id": "http-1", "label": "HTTP Rival"}
    )
    assert created.status_code == 201, created.text

    async def _fake_get_place(place_id):
        return {
            "place_id": "http-1", "name": "HTTP Rival", "address": None,
            "rating": 4.2, "review_count": 42, "types": [], "reviews": [],
        }

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    res = client.get("/api/v1/benchmark/compare?subjects=saved%3Ahttp-1")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["subjects"]) == 1
    assert body["subjects"][0]["name"] == "HTTP Rival"
    assert body["subjects"][0]["metrics"]["total_reviews"] == 42
