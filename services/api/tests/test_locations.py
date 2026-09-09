"""Locations profile CRUD (no network — Google push is monkeypatched)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.locations import service as locations
from app.modules.localith.models import LocalithConnection


async def _connection(db, user_id, listing_id="loc-1", name="Test Place"):
    db.add(LocalithConnection(
        id="conn-loc-1", user_id=user_id, listing_id=listing_id,
        listing_name=name, listing_google_id="g1",
        address="RIYADH", phone_number=None, website_url="http://x.test",
        is_verified=True, total_reviews=3, average_rating=4.5,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_get_profile_merges_google_and_local(db, user_id):
    await _connection(db, user_id)
    profile = await locations.get_profile(db, user_id, "loc-1")
    assert profile["name"] == "Test Place"
    assert profile["address"] == "RIYADH"
    assert profile["status"] == "active"
    assert "description" in profile["google_synced"]
    assert profile["categories"] == {}
    assert profile["service_area"] == []


@pytest.mark.asyncio
async def test_update_categories_round_trip(db, user_id):
    await _connection(db, user_id)
    out = await locations.update_profile(
        db, user_id, "loc-1", description=None,
        categories={"primary": "Software", "additional": ["AI", "SaaS"]},
        hours=None, service_area=None, attributes=None,
    )
    assert out["categories"] == {"primary": "Software", "additional": ["AI", "SaaS"]}
    again = await locations.get_profile(db, user_id, "loc-1")
    assert again["categories"]["primary"] == "Software"


@pytest.mark.asyncio
async def test_partial_hours_update_preserves_slices(db, user_id):
    await _connection(db, user_id)
    await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None,
        hours={"regular": {"Monday": {"open": "09:00", "close": "17:00", "closed": False}},
               "special": [{"date": "2026-12-25", "hours": "closed", "reason": "Holiday"}],
               "more": []},
        service_area=None, attributes=None,
    )
    out = await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None,
        hours={"more": [{"type": "Delivery", "open": "10:00", "close": "22:00"}]},
        service_area=None, attributes=None,
    )
    assert out["hours"]["regular"]["Monday"]["open"] == "09:00"
    assert out["hours"]["special"][0]["reason"] == "Holiday"
    assert out["hours"]["more"][0]["type"] == "Delivery"


@pytest.mark.asyncio
async def test_service_area_and_attributes(db, user_id):
    await _connection(db, user_id)
    out = await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None, hours=None,
        service_area=["Riyadh", "Jeddah"],
        attributes={"parking": "yes", "wifi": "free"},
    )
    assert out["service_area"] == ["Riyadh", "Jeddah"]
    assert out["attributes"] == {"parking": "yes", "wifi": "free"}


@pytest.mark.asyncio
async def test_description_pushes_to_google(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_update(listing_id, fields):
        calls.append((listing_id, fields))
        return {"ok": True}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.update_listing", _fake_update
    )
    # Ensure service module uses the patched attribute.
    import integrations.channels.embedsocial as emb
    monkeypatch.setattr(
        "app.modules.localith.service.embedsocial", emb, raising=False
    )
    out = await locations.update_profile(
        db, user_id, "loc-1", description="We build AI support software.",
        categories=None, hours=None, service_area=None, attributes=None,
    )
    assert calls == [("loc-1", {"description": "We build AI support software."})]
    assert out["description"] == "We build AI support software."


@pytest.mark.asyncio
async def test_update_without_connection_stores_locally(monkeypatch, db, user_id):
    def _boom(*a, **k):
        raise AssertionError("must not call Google without a connection")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.update_listing", _boom
    )
    out = await locations.update_profile(
        db, user_id, "nope", description="Local only",
        categories=None, hours=None, service_area=None, attributes=None,
    )
    assert out["description"] == "Local only"
    assert out["google_synced"] == []
    assert out["status"] == "unknown"
