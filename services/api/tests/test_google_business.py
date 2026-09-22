"""Native Google Business Information push (no network — HTTP mocked).

Covers the mapping builders (hours/special/more/attributes/categories),
per-section failure containment, the provider seam, and the opening-date
round trip. Live-API verification happens when GBP access lands; until
then every external shape is asserted exactly as coded.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.google_business import (
    build_attributes,
    build_more_hours,
    build_regular_periods,
    parse_special_entry,
)


def test_regular_periods_normal_and_closed():
    periods = build_regular_periods({
        "Monday": {"open": "09:00", "close": "17:00", "closed": False},
        "Tuesday": {"open": "", "close": "", "closed": True},
    })
    assert periods == [{
        "openDay": "MONDAY", "openTime": "09:00",
        "closeDay": "MONDAY", "closeTime": "17:00",
    }]


def test_regular_periods_overnight_rolls_close_day():
    periods = build_regular_periods({
        "Friday": {"open": "20:00", "close": "02:00", "closed": False},
    })
    assert periods[0]["openDay"] == "FRIDAY"
    assert periods[0]["closeDay"] == "SATURDAY"


def test_regular_periods_garbage_skipped():
    assert build_regular_periods({
        "Monday": {"open": "nine", "close": "17:00", "closed": False},
    }) == []
    assert build_regular_periods({}) == []


def test_special_entry_range_and_closed():
    parsed = parse_special_entry(
        {"date": "2026-12-25", "hours": "09:00 - 13:00", "reason": "Xmas"})
    assert parsed["startDate"] == {"year": 2026, "month": 12, "day": 25}
    assert parsed["openTime"] == "09:00"
    assert parsed["closeTime"] == "13:00"
    assert parse_special_entry(
        {"date": "2026-01-01", "hours": "closed", "reason": ""}) == {
        "startDate": {"year": 2026, "month": 1, "day": 1}, "closed": True}
    assert parse_special_entry(
        {"date": "2026-01-01", "hours": "whenever", "reason": ""}) is None
    assert parse_special_entry(
        {"date": "not-a-date", "hours": "09:00 - 10:00", "reason": ""}) is None


def test_more_hours_mapping_and_unknown_skip():
    built, skipped = build_more_hours([
        {"type": "Delivery", "open": "10:00", "close": "22:00"},
        {"type": "Happy Hour", "open": "17:00", "close": "19:00"},
        {"type": "Moonlight", "open": "00:00", "close": "01:00"},
    ])
    assert [b["hoursTypeId"] for b in built] == ["DELIVERY", "HAPPY_HOUR"]
    assert skipped == ["Moonlight"]


def test_attributes_curated_bools_only():
    entries, skipped = build_attributes({
        "wheelchair accessible entrance": "yes",
        "free wifi": "no",
        "mystery perk": "yes",
        "open late": "sometimes",
    })
    by_id = {e["attributeId"]: e["values"] for e in entries}
    assert by_id["wheelchair_accessible_entrance"] == [{"boolValue": True}]
    assert by_id["has_wifi"] == [{"boolValue": False}]
    assert sorted(skipped) == ["mystery perk", "open late"]


@pytest.mark.asyncio
async def test_resolve_category_id_matches_and_misses(monkeypatch):
    from app.modules.channels.google_business import GoogleBusinessClient

    pages = [
        {"categories": [{"name": "categories/gcid:restaurant",
                         "displayName": "Restaurant"}]},
        {"categories": [{"name": "categories/gcid:software_company",
                         "displayName": "Software company"}]},
    ]
    calls = {"n": 0}

    async def _list(self, page_token=None, page_size=100):
        calls["n"] += 1
        idx = 0 if page_token is None else 1
        out = dict(pages[idx])
        if idx == 0:
            out["nextPageToken"] = "p2"
        return out

    monkeypatch.setattr(GoogleBusinessClient, "list_categories", _list)
    client = GoogleBusinessClient("tok", None)
    try:
        assert await client.resolve_category_id("software COMPANY") == \
            "categories/gcid:software_company"
        assert calls["n"] == 2  # paginated past page one
        assert await client.resolve_category_id("Moonlight Emporium") is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_push_profile_per_section_containment(monkeypatch):
    """One rejected section never fails the others; report is exact."""
    from app.modules.channels.google_business import GoogleBusinessClient
    from app.modules.channels.google_reviews import GoogleReviewsError

    calls = []

    async def _patch(self, location_id, body, mask):
        calls.append(mask)
        if mask == "regularHours":
            raise GoogleReviewsError("regularHours rejected", 400)
        return {}

    async def _attrs(self, location_id, entries):
        calls.append("attributes")
        return {}

    async def _resolve(self, name, max_pages=10):
        return "categories/gcid:software_company"

    monkeypatch.setattr(GoogleBusinessClient, "patch_location", _patch)
    monkeypatch.setattr(GoogleBusinessClient, "update_attributes", _attrs)
    monkeypatch.setattr(GoogleBusinessClient, "resolve_category_id", _resolve)
    client = GoogleBusinessClient("tok", None)
    try:
        report = await client.push_profile(
            "loc-1",
            description="Hi",
            categories={"primary": "Software company"},
            hours={"regular": {"Monday": {"open": "09:00", "close": "17:00",
                                          "closed": False}}},
            attributes={"free wifi": "yes"},
        )
    finally:
        await client.close()
    assert "description" in report["pushed"]
    assert "categories" in report["pushed"]
    assert "attributes" in report["pushed"]
    assert "hours.regular" not in report["pushed"]
    assert "hours.regular" in report["skipped"]


def _native_channel(db, user_id, listing_id="loc-google-1"):
    import json as _json

    from app.modules.channels.models import Channel
    from app.modules.channels.service import encrypt_token

    db.add(Channel(
        id="ch-native-1", user_id=user_id, platform="google_reviews",
        platform_user_id=listing_id, display_name="Native",
        access_token=encrypt_token("at"), refresh_token=encrypt_token("rt"),
        status="active",
        metadata_json=_json.dumps({"location_id": listing_id}),
    ))


@pytest.mark.asyncio
async def test_seam_google_no_channel_saves_locally(db, user_id, monkeypatch):
    """No native channel: local save lands, google_synced stays empty."""
    from app.modules.locations import service as locations

    monkeypatch.setenv("LOCATIONS_WRITE_PROVIDER", "google")
    out = await locations.update_profile(
        db, user_id, "loc-1", description="Hello",
        categories=None, hours=None, service_area=None, attributes=None,
    )
    assert out["description"] == "Hello"
    assert out["google_synced"] == []


@pytest.mark.asyncio
async def test_seam_google_pushes_via_native_client(monkeypatch, db, user_id):
    from app.modules.channels import google_business as gb
    from app.modules.locations import service as locations

    _native_channel(db, user_id)
    await db.commit()
    seen = {}

    async def _push(self, location_id, **kw):
        seen["location_id"] = location_id
        seen["kw"] = kw
        return {"pushed": ["description", "categories"], "skipped": {}}

    monkeypatch.setattr(gb.GoogleBusinessClient, "push_profile", _push)
    monkeypatch.setenv("LOCATIONS_WRITE_PROVIDER", "google")
    out = await locations.update_profile(
        db, user_id, "loc-google-1", description="Hello",
        categories={"primary": "Software company"}, hours=None,
        service_area=None, attributes=None,
    )
    assert seen["location_id"] == "loc-google-1"
    assert seen["kw"]["description"] == "Hello"
    assert out["google_synced"] == ["description", "categories"]


@pytest.mark.asyncio
async def test_opening_date_round_trip(db, user_id):
    from app.modules.locations import service as locations

    out = await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None, hours=None,
        service_area=None, attributes=None, opening_date="2020-05-17",
    )
    assert out["opening_date"] == "2020-05-17"
    again = await locations.get_profile(db, user_id, "loc-1")
    assert again["opening_date"] == "2020-05-17"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await locations.update_profile(
            db, user_id, "loc-1", description=None, categories=None,
            hours=None, service_area=None, attributes=None,
            opening_date="17-05-2020",
        )
