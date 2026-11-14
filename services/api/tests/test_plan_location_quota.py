"""Plan location quota (§34): max_locations gates location creation.

A location is stored as a `google_reviews` channel row. Both the locations
router and the Google OAuth callback create them directly, so the cap is
enforced at the `POST /api/v1/locations` write path (the callback counts
the same channel rows).
"""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.entitlements import get_entitlements
from app.modules.billing.models import Plan
from app.modules.channels.models import Channel

pytestmark = pytest.mark.asyncio


async def _set_free_trial_locations(db, max_locations: int) -> Plan:
    """Tune the seeded free-trial plan (conftest) to a known cap."""
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    plan.max_locations = max_locations
    await db.flush()
    return plan


async def _add_location(db, user_id: str, listing_id: str = "loc-1") -> None:
    db.add(Channel(
        id=f"ch-{listing_id}", user_id=user_id, platform="google_reviews",
        platform_user_id=listing_id, display_name="Place", status="active",
        listing_key=listing_id,
        metadata_json=json.dumps({"location_id": listing_id}),
    ))
    await db.commit()


async def test_entitlements_expose_max_locations(db, user_id):
    """The cap comes through get_entitlements with a working helper."""
    await _set_free_trial_locations(db, 3)
    ent = await get_entitlements(user_id, db)
    assert ent.max_locations == 3
    assert ent.location_quota_ok(0) is True
    assert ent.location_quota_ok(2) is True
    assert ent.location_quota_ok(3) is False


async def test_location_create_blocked_at_cap(client, db, user_id):
    """At the cap, POST /locations is denied with the entitlement header."""
    await _set_free_trial_locations(db, 1)
    await _add_location(db, user_id)

    resp = client.post("/api/v1/locations", json={
        "name": "New Place", "category": "Software company",
        "street": "1 Test Road", "city": "Riyadh", "country": "SA",
        "phone": "+966500000000",
    })
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "quota"


async def test_location_create_allowed_under_cap(client, db, user_id):
    """Under the cap the gate passes: the request proceeds into the service
    layer (which 400s without a Google connection) instead of 403."""
    await _set_free_trial_locations(db, 5)
    await _add_location(db, user_id)

    resp = client.post("/api/v1/locations", json={
        "name": "New Place", "category": "Software company",
        "street": "1 Test Road", "city": "Riyadh", "country": "SA",
        "phone": "+966500000000",
    })
    assert resp.status_code == 400
