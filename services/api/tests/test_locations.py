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
async def test_create_group_keeps_members_and_position(db, user_id):
    first = await locations.create_group(db, user_id, "North Riyadh", ["loc-1", "loc-2", "loc-1"])
    second = await locations.create_group(db, user_id, "South", ["loc-3"])
    # Duplicates collapse so a double-ticked checkbox can't double-apply.
    assert first["listing_ids"] == ["loc-1", "loc-2"]
    assert first["position"] == 0
    assert second["position"] == 1
    listed = await locations.list_groups(db, user_id)
    assert [g["name"] for g in listed] == ["North Riyadh", "South"]


@pytest.mark.asyncio
async def test_group_rejects_duplicate_name_and_empty_members(db, user_id):
    await locations.create_group(db, user_id, "North Riyadh", ["loc-1"])
    with pytest.raises(ValueError, match="already have a group"):
        await locations.create_group(db, user_id, "  north riyadh  ", ["loc-2"])
    with pytest.raises(ValueError, match="at least one"):
        await locations.create_group(db, user_id, "Empty", [])


@pytest.mark.asyncio
async def test_update_group_renames_and_replaces_members(db, user_id):
    created = await locations.create_group(db, user_id, "North", ["loc-1", "loc-2"])
    out = await locations.update_group(db, user_id, created["id"], "North Riyadh", ["loc-2", "loc-3"])
    assert out["name"] == "North Riyadh"
    assert out["listing_ids"] == ["loc-2", "loc-3"]
    with pytest.raises(ValueError, match="at least one"):
        await locations.update_group(db, user_id, created["id"], None, [])
    # Name-only edit leaves members alone.
    renamed = await locations.update_group(db, user_id, created["id"], "North 2", None)
    assert renamed["listing_ids"] == ["loc-2", "loc-3"]


@pytest.mark.asyncio
async def test_delete_group_and_missing_group_is_none(db, user_id):
    created = await locations.create_group(db, user_id, "Temp", ["loc-1"])
    assert await locations.delete_group(db, user_id, created["id"]) is True
    assert await locations.list_groups(db, user_id) == []
    # Deleting twice is a no-op, not an error, so a stale UI can't 500.
    assert await locations.delete_group(db, user_id, created["id"]) is False
    assert await locations.update_group(db, user_id, created["id"], "x", None) is None


def test_groups_routes_round_trip(client):
    """Router level: the /groups routes must not be swallowed by /{listing_id}."""
    created = client.post(
        "/api/v1/locations/groups",
        json={"name": "North Riyadh", "listing_ids": ["loc-1", "loc-2"]},
    )
    assert created.status_code == 201, created.text
    gid = created.json()["id"]

    listed = client.get("/api/v1/locations/groups")
    assert listed.status_code == 200, listed.text
    assert [g["name"] for g in listed.json()] == ["North Riyadh"]

    # "groups" is declared before /{listing_id}, so GET /locations/groups is
    # the list route rather than a profile lookup for a listing called "groups"
    # (which is what the earlier 200 assertion above proves).
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/locations/groups" in paths
    assert "/api/v1/locations/groups/{group_id}" in paths

    patched = client.patch(
        f"/api/v1/locations/groups/{gid}", json={"name": "North Riyadh 2"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "North Riyadh 2"
    # Members untouched by a name-only patch.
    assert patched.json()["listing_ids"] == ["loc-1", "loc-2"]

    assert client.post(
        "/api/v1/locations/groups", json={"name": "Empty", "listing_ids": []}
    ).status_code == 400
    # Duplicate name, different case and surrounding space, is rejected too.
    assert client.post(
        "/api/v1/locations/groups",
        json={"name": "  north riyadh 2 ", "listing_ids": ["a"]},
    ).status_code == 400

    assert client.delete(f"/api/v1/locations/groups/{gid}").status_code == 204
    assert client.get("/api/v1/locations/groups").json() == []
    assert client.delete(f"/api/v1/locations/groups/{gid}").status_code == 404
    assert client.patch(
        f"/api/v1/locations/groups/{gid}", json={"name": "gone"}
    ).status_code == 404


@pytest.mark.asyncio
async def test_groups_are_scoped_per_user(db, user_id, other_user_id):
    await locations.create_group(db, user_id, "Mine", ["loc-1"])
    assert await locations.list_groups(db, other_user_id) == []


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
