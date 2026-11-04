"""Locations profile CRUD (no network — Google push is monkeypatched)."""
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.models import Channel
from app.modules.locations import service as locations


async def _connection(db, user_id, listing_id="loc-1", name="Test Place"):
    db.add(Channel(
        id=f"ch-{listing_id}", user_id=user_id, platform="google_reviews",
        platform_user_id=listing_id, display_name=name, status="active",
        listing_key=listing_id,
        metadata_json=json.dumps({
            "location_id": listing_id,
            "address": "RIYADH",
            "phone": "+966 55 000 0000",
            "website": "http://x.test",
            "maps_url": "https://maps.google.com/?cid=1",
            "description": "Google description",
            "profile_fields_checked": True,
        }),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_locations_endpoint_lists_google_channels(client, db, user_id):
    """Router level: the page's list and profile routes exist and are native."""
    await _connection(db, user_id)

    listed = client.get("/api/v1/locations")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [r["listing_id"] for r in rows] == ["loc-1"]
    assert rows[0]["name"] == "Test Place"
    assert rows[0]["phone"] == "+966 55 000 0000"
    assert rows[0]["source"] == "google"

    profile = client.get("/api/v1/locations/loc-1")
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["phone"] == "+966 55 000 0000"
    assert body["website"] == "http://x.test"


@pytest.mark.asyncio
async def test_get_profile_merges_google_and_local(db, user_id):
    await _connection(db, user_id)
    profile = await locations.get_profile(db, user_id, "loc-1")
    assert profile["name"] == "Test Place"
    assert profile["address"] == "RIYADH"
    assert profile["phone"] == "+966 55 000 0000"
    assert profile["status"] == "active"
    assert profile["description"] == "Google description"
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
    seen = {}

    async def _fake_push(self, location_id, **kw):
        seen["location_id"] = location_id
        seen["kw"] = kw
        return {"pushed": ["description"], "skipped": {}}

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.push_profile",
        _fake_push,
    )
    # Encrypt real tokens so the push path doesn't skip for missing credentials.
    from app.modules.channels.service import encrypt_token

    channel = await locations.channel_for_listing(db, user_id, "loc-1")
    channel.access_token = encrypt_token("at")
    channel.refresh_token = encrypt_token("rt")
    await db.commit()

    out = await locations.update_profile(
        db, user_id, "loc-1", description="We build AI support software.",
        categories=None, hours=None, service_area=None, attributes=None,
    )
    assert seen["location_id"] == "loc-1"
    assert seen["kw"]["description"] == "We build AI support software."
    assert out["description"] == "We build AI support software."
    assert out["google_synced"] == ["description"]


@pytest.mark.asyncio
async def test_google_hours_snapshot_used_until_local_save(db, user_id):
    """Hours come from Google until the merchant saves an override."""
    await _connection(db, user_id)
    channel = await locations.channel_for_listing(db, user_id, "loc-1")
    meta = locations.channel_meta(channel)
    meta["hours"] = {
        "regular": {
            "Monday": {"open": "00:00", "close": "00:00", "closed": False,
                       "all_day": True},
            "Tuesday": {"open": "", "close": "", "closed": True},
        },
        "special": [], "more": [],
    }
    channel.metadata_json = json.dumps(meta)
    await db.commit()

    profile = await locations.get_profile(db, user_id, "loc-1")
    assert profile["hours"]["regular"]["Monday"]["all_day"] is True
    assert profile["hours"]["regular"]["Tuesday"]["closed"] is True

    await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None,
        hours={"regular": {"Monday": {"open": "09:00", "close": "17:00", "closed": False}}},
        service_area=None, attributes=None,
    )
    again = await locations.get_profile(db, user_id, "loc-1")
    assert again["hours"]["regular"]["Monday"]["open"] == "09:00"
    assert "all_day" not in again["hours"]["regular"]["Monday"]


@pytest.mark.asyncio
async def test_identity_fields_save_locally_and_push(monkeypatch, db, user_id):
    await _connection(db, user_id)
    from app.modules.channels.service import encrypt_token

    channel = await locations.channel_for_listing(db, user_id, "loc-1")
    channel.access_token = encrypt_token("at")
    channel.refresh_token = encrypt_token("rt")
    await db.commit()

    async def _fake_push(self, location_id, **kw):
        return {"pushed": ["name", "phone", "website"], "skipped": {}}

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.push_profile",
        _fake_push,
    )
    out = await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None, hours=None,
        service_area=None, attributes=None,
        name="New Name", phone="+966 11 222 3333", website="https://new.test",
    )
    assert out["name"] == "New Name"
    assert out["phone"] == "+966 11 222 3333"
    assert out["website"] == "https://new.test"
    assert out["google_synced"] == ["name", "phone", "website"]


@pytest.mark.asyncio
async def test_unchanged_save_does_not_call_google(monkeypatch, db, user_id):
    """A bulk save sends every column; unchanged values must cost zero calls."""
    await _connection(db, user_id)
    from app.modules.channels.service import encrypt_token

    channel = await locations.channel_for_listing(db, user_id, "loc-1")
    channel.access_token = encrypt_token("at")
    channel.refresh_token = encrypt_token("rt")
    await db.commit()

    async def _must_not_push(self, location_id, **kw):
        raise AssertionError(f"unexpected push: {location_id} {kw}")

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.push_profile",
        _must_not_push,
    )
    out = await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None, hours=None,
        service_area=None, attributes=None,
        name="Test Place", phone="+966 55 000 0000", website="http://x.test",
    )
    assert out["google_synced"] == []


@pytest.mark.asyncio
async def test_expired_channel_is_readable_but_not_writable(db, user_id):
    """A 403 marks a channel expired; the page must still show its data and
    refuse edits with a reconnect message instead of pretending it vanished."""
    await _connection(db, user_id)
    channel = await locations.channel_for_listing(db, user_id, "loc-1")
    channel.status = "expired"
    await db.commit()

    assert await locations.native_channels(db, user_id) == []
    readable = await locations.native_channels(
        db, user_id, statuses=("active", "expired")
    )
    assert [locations.listing_id_of(ch) for ch in readable] == ["loc-1"]

    profile = await locations.get_profile(db, user_id, "loc-1")
    assert profile["name"] == "Test Place"
    assert profile["status"] == "expired"

    with pytest.raises(ValueError, match="reconnect Google"):
        await locations.update_profile(
            db, user_id, "loc-1", description="Nope", categories=None,
            hours=None, service_area=None, attributes=None,
        )


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
async def test_update_without_connection_stores_locally(db, user_id):
    out = await locations.update_profile(
        db, user_id, "nope", description="Local only",
        categories=None, hours=None, service_area=None, attributes=None,
    )
    assert out["description"] == "Local only"
    assert out["google_synced"] == []
    assert out["status"] == "unknown"
