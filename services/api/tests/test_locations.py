"""Locations profile CRUD (no network â€” Google push is monkeypatched)."""
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.google_reviews import GoogleReviewsError
from app.modules.channels.models import Channel
from app.modules.channels.service import encrypt_token
from app.modules.locations import service as locations


async def _google_account_connection(db, user_id):
    db.add(Channel(
        id="ch-account",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="acc-1",
        display_name="Existing Place",
        access_token=encrypt_token("at"),
        refresh_token=encrypt_token("rt"),
        status="active",
        listing_key="loc-existing",
        metadata_json=json.dumps({"location_id": "loc-existing", "account_name": "Sayvors"}),
    ))
    await db.commit()


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
    assert out["google_pushed"] == ["description"]
    assert "description" in out["google_synced"]


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
    assert out["google_pushed"] == ["name", "phone", "website"]
    assert {"name", "phone", "website"} <= set(out["google_synced"])


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
    assert out["google_pushed"] == []


@pytest.mark.asyncio
async def test_failed_section_is_retried_on_unchanged_save(monkeypatch, db, user_id):
    """A section Google rejected is retried on the next save even when the
    local value is unchanged — otherwise the merchant can never recover."""
    await _connection(db, user_id)
    from app.modules.channels.service import encrypt_token

    channel = await locations.channel_for_listing(db, user_id, "loc-1")
    channel.access_token = encrypt_token("at")
    channel.refresh_token = encrypt_token("rt")
    meta = locations.channel_meta(channel)
    meta["google_failed"] = {"phone": "rejected earlier"}
    channel.metadata_json = json.dumps(meta)
    await db.commit()

    pushed_seen: dict = {}

    async def _fake_push(self, location_id, **kw):
        pushed_seen.update(kw)
        return {"pushed": ["phone"], "skipped": {}}

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.push_profile",
        _fake_push,
    )
    out = await locations.update_profile(
        db, user_id, "loc-1", description=None, categories=None, hours=None,
        service_area=None, attributes=None,
        name="Test Place", phone="+966 55 000 0000", website="http://x.test",
    )
    assert out["google_pushed"] == ["phone"]
    assert pushed_seen.get("phone") == "+966 55 000 0000"


def test_parse_edit_status_maps_google_fields_to_sections():
    """Google's extendedFieldData keys become Sayvors sections + status."""
    from app.modules.channels.google_business import parse_edit_status

    extended = {
        "extendedFieldData": {
            "title": {
                "lastEditLifecycleStage": "EDIT_LIFECYCLE_STAGE_PENDING",
                "updateTime": "2026-11-10T10:00:00Z",
                "source": "SOURCE_API",
            },
            "phone_numbers": {
                "lastEditLifecycleStage": "EDIT_LIFECYCLE_STAGE_REJECTED",
                "rejectionReason": "MISREPRESENTATION",
                "updateTime": "2026-11-09T10:00:00Z",
                "source": "SOURCE_API",
            },
            "regular_hours": {
                "lastEditLifecycleStage": "EDIT_LIFECYCLE_STAGE_ACCEPTED",
                "updateTime": "2026-11-08T10:00:00Z",
                "source": "SOURCE_API",
            },
        }
    }
    status = parse_edit_status(extended)
    assert status["name"]["stage"] == "pending"
    assert status["phone"]["stage"] == "rejected"
    assert status["phone"]["rejection_reason"] == "MISREPRESENTATION"
    assert status["hours.regular"]["stage"] == "accepted"
    assert status["name"]["update_time"] == "2026-11-10T10:00:00Z"


def test_parse_edit_status_handles_empty_and_unknown():
    from app.modules.channels.google_business import parse_edit_status

    assert parse_edit_status({}) == {}
    assert parse_edit_status({"extendedFieldData": None}) == {}
    # Unknown field names are ignored.
    out = parse_edit_status({"extendedFieldData": {"mystery_field": {}}})
    assert out == {}


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


@pytest.mark.asyncio
async def test_location_create_requires_google_connection(client):
    body = {
        "name": "New Place", "category": "Software company",
        "street": "1 Test Road", "city": "Riyadh", "country": "SA",
        "phone": "+966500000000",
    }
    assert client.post("/api/v1/locations/search", json=body).status_code == 400
    assert client.post("/api/v1/locations", json=body).status_code == 400


@pytest.mark.asyncio
async def test_search_google_locations_maps_matches(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)

    async def fake_search(self, **kwargs):
        assert kwargs["location"]["title"] == "New Place"
        return [{
            "requestAdminRightsUrl": "https://google.test/claim",
            "location": {
                "name": "locations/existing",
                "title": "Existing New Place",
                "storefrontAddress": {
                    "addressLines": ["1 Test Road"],
                    "locality": "Riyadh",
                    "regionCode": "SA",
                },
            },
        }]

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.search_google_locations",
        fake_search,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )
    rows = await locations.search_google_locations(
        db, user_id, {
            "name": "New Place", "category": "Software company",
            "street": "1 Test Road", "city": "Riyadh", "postal_code": None,
            "country": "SA", "phone": "+966500000000", "website": None,
        },
    )
    assert rows[0]["name"] == "Existing New Place"
    assert rows[0]["request_admin_rights_url"] == "https://google.test/claim"
    assert "Riyadh" in rows[0]["address"]


@pytest.mark.asyncio
async def test_create_google_location_persists_a_native_channel(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)
    captured = {}

    async def fake_resolve(self, name, region_code="US"):
        assert name == "Software company"
        return "gcid:software_company"

    async def fake_create(self, account_id, location, *, request_id, validate_only=False):
        captured["account_id"] = account_id
        captured["body"] = location
        captured.setdefault("request_ids", []).append(request_id)
        captured.setdefault("validate_only", []).append(validate_only)
        return {
            "name": "locations/loc-new",
            "title": location["title"],
            "phoneNumbers": location["phoneNumbers"],
            "websiteUri": location.get("websiteUri"),
            "storefrontAddress": location["storefrontAddress"],
            "categories": {"primaryCategory": {"displayName": "Software company"}},
            "metadata": {
                "placeId": "ChIJtest",
                "mapsUri": "https://maps.google.com/?cid=123",
            },
        }

    async def fake_list(self, account_id):
        return []

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.list_locations",
        fake_list,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.create_location",
        fake_create,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    out = await locations.create_google_location(
        db, user_id, {
            "name": "New Place", "category": "Software company",
            "street": "1 Test Road", "city": "Riyadh", "postal_code": "12213",
            "country": "sa", "phone": "+966500000000",
            "website": "https://new.test", "request_id": "req-123",
        },
    )
    assert out["created"] is True
    assert out["listing_id"] == "loc-new"
    assert captured["validate_only"] == [True, False]
    assert captured["account_id"] == "acc-1"
    # validateOnly and the real create are separate requests: a shared
    # requestId can make Google replay the validation response.
    assert len(captured["request_ids"]) == 2
    assert captured["request_ids"][0] != captured["request_ids"][1]
    assert captured["request_ids"][1] == "req-123"
    assert captured["body"]["categories"]["primaryCategory"]["name"] == "gcid:software_company"
    assert captured["body"]["storefrontAddress"]["regionCode"] == "SA"

    channel = await locations.channel_for_listing(db, user_id, "loc-new")
    assert channel is not None
    assert channel.display_name == "New Place"
    assert channel.platform_user_id == "acc-1"
    meta = locations.channel_meta(channel)
    assert meta["location_id"] == "loc-new"
    # v1 returns mapsUri, not mapsUrl.
    assert meta["maps_url"] == "https://maps.google.com/?cid=123"
    assert meta["place_id"] == "ChIJtest"


@pytest.mark.asyncio
async def test_create_google_location_blocks_a_managed_duplicate(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)

    async def fake_list(self, account_id):
        return [{
            "name": "locations/existing",
            "title": "New Place",
            "phoneNumbers": {"primaryPhone": "053 564 3335"},
            "storefrontAddress": {
                "addressLines": ["1 Test Road"],
                "locality": "Riyadh",
                "regionCode": "SA",
            },
        }]

    async def fake_resolve(self, name, region_code="US"):
        return "gcid:software_company"

    async def fake_create(self, *args, **kwargs):
        raise AssertionError("create must not run for an existing managed location")

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.list_locations",
        fake_list,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.create_location",
        fake_create,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    with pytest.raises(ValueError, match="already exists"):
        await locations.create_google_location(
            db, user_id, {
                "name": "New Place", "category": "Software company",
                "street": "1 Test Road", "city": "Riyadh", "postal_code": None,
                "country": "SA", "phone": "+966500000000", "website": None,
                "request_id": "req-dup",
            },
        )


@pytest.mark.asyncio
async def test_create_retries_without_readonly_state(monkeypatch, db, user_id):
    """Pakistan rejects a client-provided administrativeArea with 400.

    The create must drop it and retry instead of showing the raw Google JSON
    to the merchant.
    """
    await _google_account_connection(db, user_id)
    captured: list[dict] = []

    async def fake_resolve(self, name, region_code="US"):
        return "categories/gcid:software_company"

    async def fake_create(self, account_id, location, *, request_id, validate_only=False):
        captured.append(json.loads(json.dumps(location)))
        if validate_only and (location.get("storefrontAddress") or {}).get("administrativeArea"):
            raise GoogleReviewsError(
                'accounts.locations.create failed (400): {"error":{"code":400,'
                '"message":"Request contains an invalid argument.","status":"INVALID_ARGUMENT",'
                '"details":[{"reason":"READ_ONLY_ADDRESS_COMPONENTS","metadata":'
                '{"field_mask":"storefront_address.administrative_area"}}]}}',
                400,
            )
        return {"name": "locations/loc-pk", "title": location["title"]}

    async def fake_list(self, account_id):
        return []

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.list_locations",
        fake_list,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.create_location",
        fake_create,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    out = await locations.create_google_location(
        db, user_id, {
            "name": "Peshawar Branch", "category": "Software company",
            "street": "2F6G+J36 Peshawar, Pakistan, abad", "city": "Peshawar",
            "state": "Peshawar", "postal_code": "24550", "country": "PK",
            "phone": "+92 346 0561173", "request_id": "req-pk",
        },
    )

    assert out["listing_id"] == "loc-pk"
    assert captured[0]["storefrontAddress"]["administrativeArea"] == "Peshawar"
    assert captured[-1]["storefrontAddress"].get("administrativeArea") is None


@pytest.mark.asyncio
async def test_create_error_is_friendly_and_hides_raw_google_json(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)

    async def fake_resolve(self, name, region_code="US"):
        return "categories/gcid:software_company"

    async def fake_create(self, *args, **kwargs):
        raise GoogleReviewsError(
            'accounts.locations.create failed (400): {"error":{"code":400,'
            '"message":"Request contains an invalid argument.","status":"INVALID_ARGUMENT",'
            '"details":[{"reason":"INVALID_ARGUMENT","metadata":'
            '{"field_mask":"storefront_address"}}]}}',
            400,
        )

    async def fake_list(self, account_id):
        return []

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.list_locations",
        fake_list,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.create_location",
        fake_create,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    with pytest.raises(ValueError) as exc:
        await locations.create_google_location(
            db, user_id, {
                "name": "Peshawar Branch", "category": "Software company",
                "street": "1 Test Road", "city": "Peshawar",
                "country": "PK", "phone": "+92 346 0561173",
                "request_id": "req-friendly",
            },
        )

    message = str(exc.value)
    assert "Google could not accept this address" in message
    assert "{" not in message
    assert "INVALID_ARGUMENT" not in message


@pytest.mark.asyncio
async def test_create_service_area_location_uses_place_ids(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)
    captured: dict = {}

    async def fake_resolve_places(names, *, language_code="en", region_code="SA"):
        assert names == ["Riyadh", "Jeddah"]
        return [{"placeId": "place-riyadh", "placeName": "Riyadh"}]

    async def fake_resolve_category(self, name, region_code="US"):
        return "gcid:software_company"

    async def fake_create(self, account_id, location, *, request_id, validate_only=False):
        captured.setdefault("payloads", []).append(location)
        return {"name": "locations/loc-service", "title": location["title"]}

    async def fake_list(self, account_id):
        return []

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.locations.places.resolve_service_area", fake_resolve_places
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.list_locations",
        fake_list,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve_category,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.create_location",
        fake_create,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    out = await locations.create_google_location(
        db, user_id, {
            "name": "Service Co", "category": "Software company",
            "has_storefront": False, "street": None, "city": None,
            "country": "sa", "phone": "+966500000000", "website": None,
            "service_area": ["Riyadh", "Jeddah"], "request_id": "req-sa",
        },
    )

    assert out["listing_id"] == "loc-service"
    payload = captured["payloads"][-1]
    assert "storefrontAddress" not in payload
    assert payload["serviceArea"]["businessType"] == "CUSTOMER_LOCATION_ONLY"
    assert payload["serviceArea"]["regionCode"] == "SA"
    assert payload["serviceArea"]["places"]["placeInfos"] == [
        {"placeId": "place-riyadh", "placeName": "Riyadh"}
    ]


@pytest.mark.asyncio
async def test_create_sends_description_state_language_and_pin(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)
    captured: dict = {}

    async def fake_resolve_category(self, name, region_code="US"):
        return "gcid:software_company"

    async def fake_create(self, account_id, location, *, request_id, validate_only=False):
        captured.setdefault("payloads", []).append(location)
        return {"name": "locations/loc-rich", "title": location["title"]}

    async def fake_list(self, account_id):
        return []

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.list_locations",
        fake_list,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve_category,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.create_location",
        fake_create,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    await locations.create_google_location(
        db, user_id, {
            "name": "Rich Place", "category": "Software company",
            "has_storefront": True, "street": "1 Test Road", "city": "Riyadh",
            "state": "Riyadh Province", "postal_code": "12213", "country": "SA",
            "phone": "+966500000000", "website": "https://rich.test",
            "description": "We build support software.",
            "language_code": "ar", "latitude": 24.7136, "longitude": 46.6753,
            "request_id": "req-rich",
        },
    )

    payload = captured["payloads"][-1]
    assert payload["languageCode"] == "ar"
    assert payload["profile"]["description"] == "We build support software."
    assert payload["storefrontAddress"]["administrativeArea"] == "Riyadh Province"
    assert payload["latlng"] == {"latitude": 24.7136, "longitude": 46.6753}


@pytest.mark.asyncio
async def test_category_search_puts_exact_match_first(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)

    async def fake_search(self, query, *, region_code="US", language_code="en", page_size=50):
        return [
            {"name": "categories/gcid:computer_software_store", "displayName": "Computer software store"},
            {"name": "categories/gcid:software_company", "displayName": "Software company"},
        ]

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.search_categories",
        fake_search,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    rows = await locations.list_google_categories(
        db, user_id, "Software company", "SA", exact=True
    )

    assert rows[0] == {
        "name": "categories/gcid:software_company",
        "display_name": "Software company",
    }


@pytest.mark.asyncio
async def test_category_exact_resolve_when_search_page_misses_it(monkeypatch, db, user_id):
    await _google_account_connection(db, user_id)

    async def fake_search(self, query, *, region_code="US", language_code="en", page_size=50):
        return [{"name": "categories/gcid:computer_software_store", "displayName": "Computer software store"}]

    async def fake_resolve(self, name, region_code="US", language_code="en"):
        assert name == "Software company"
        return "categories/gcid:software_company"

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.search_categories",
        fake_search,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.resolve_category_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.modules.channels.google_business.GoogleBusinessClient.close",
        fake_close,
    )

    rows = await locations.list_google_categories(
        db, user_id, "Software company", "SA", exact=True
    )

    assert rows[0] == {
        "name": "categories/gcid:software_company",
        "display_name": "Software company",
    }
