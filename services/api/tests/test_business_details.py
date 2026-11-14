"""Databank business-details overrides: Google vs merchant, saved wins."""
import json

import pytest

import app.modules.locations.models  # noqa: F401
from app.modules.channels.service import encrypt_token
from app.modules.locations.models import LocationProfile


async def _seed(db, user_id, listing_id="loc-bd"):
    from app.modules.channels.models import Channel
    from app.modules.users.models import User

    db.add(User(
        id=user_id, email=f"{user_id}@test.dev", first_name="Test", last_name="User",
        password_hash="x", onboarded=True,
    ))
    db.add(Channel(
        id="ch-bd", user_id=user_id, platform="google_reviews",
        platform_user_id="acct-bd", display_name="Test Place", status="active",
        listing_key=listing_id, access_token=encrypt_token("at"),
        refresh_token=encrypt_token("rt"),
        metadata_json=json.dumps({
            "location_id": listing_id,
            "address": "King Fahd Rd, Riyadh",
            "website": "https://example.com",
        }),
    ))
    db.add(LocationProfile(
        id="lp-bd", user_id=user_id, listing_id=listing_id,
        categories={"category": "Restaurant", "subcategories": ["Café"]},
        hours={"regular": {"Monday": {"open": "08:00", "close": "22:00", "closed": False}}},
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_business_details_list_prefilled_from_google(client, db, user_id):
    await _seed(db, user_id)
    r = client.get("/api/v1/profile/business-details")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert item["listing_id"] == "loc-bd"
    assert item["google"]["name"] == "Test Place"
    assert item["google"]["address"] == "King Fahd Rd, Riyadh"
    assert item["google"]["categories"]["category"] == "Restaurant"
    assert item["google"]["hours"]["regular"]["Monday"]["open"] == "08:00"
    assert item["user"] is None


@pytest.mark.asyncio
async def test_business_details_save_and_compare(client, db, user_id):
    await _seed(db, user_id)

    r = client.put(
        "/api/v1/profile/business-details/loc-bd",
        json={
            "name": "Test Place (Edited)",
            "categories": {"category": "Restaurant", "subcategories": ["Bakery"], "sub_subcategories": ["Desserts"]},
            "services": ["Catering", "Home delivery"],
            "hours": {"regular": {"Monday": {"open": "07:00", "close": "23:00", "closed": False}}},
            "special_hours": [{"date": "2026-12-25", "closed": True}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["google"]["name"] == "Test Place"
    assert body["user"]["name"] == "Test Place (Edited)"
    assert body["user"]["source"] == "edited"
    assert body["user"]["services"] == ["Catering", "Home delivery"]

    items = client.get("/api/v1/profile/business-details").json()
    assert items[0]["user"]["hours"]["regular"]["Monday"]["close"] == "23:00"

    from sqlalchemy import select

    from app.modules.profile.models import TenantFacts

    row = (await db.execute(select(TenantFacts).where(TenantFacts.tenant_id == user_id))).scalar_one_or_none()
    assert row is not None
    loc = next(l for l in row.facts["locations"] if l["listing_id"] == "loc-bd")
    assert loc["name"] == "Test Place (Edited)"
    assert loc["schedule"]
    assert loc.get("categories", {}).get("subcategories") == ["Bakery"]
    assert loc.get("services") == ["Catering", "Home delivery"]
    assert loc.get("special_hours") == [{"date": "2026-12-25", "closed": True}]


@pytest.mark.asyncio
async def test_business_details_unknown_listing_rejected(client, db, user_id):
    await _seed(db, user_id)
    r = client.put(
        "/api/v1/profile/business-details/not-mine",
        json={"name": "X"},
    )
    assert r.status_code == 400
