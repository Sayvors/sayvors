"""Leads API over HTTP.

The capture loop writes these rows; today's contract is what the
dashboard's Leads tab needs — tenant-scoped listing with platform/stage
filters, stage moves, and the follow-up settings GET/PATCH (clamped by
the engine before storing). Ownership is the rule under test: a lead
from another tenant is invisible and unpatchable.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.models import Channel, Lead


async def _seed(db, user_id, *, channel_id="chan-leads", platform="instagram"):
    db.add(Channel(
        id=channel_id, user_id=user_id, platform=platform,
        platform_user_id="asset-1", display_name="Business", status="active",
    ))
    await db.commit()
    return channel_id


async def _lead(db, tenant_id, channel_id, *, contact_id="igs-1", platform="instagram",
                stage="new", summary=None, username=None, hours_ago=0):
    row = Lead(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        channel_id=channel_id,
        platform=platform,
        contact_id=contact_id,
        contact_name="Sara",
        contact_username=username,
        summary=summary,
        stage=stage,
        thread_key=contact_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_list_is_tenant_scoped(client, db, user_id, other_user_id):
    await _seed(db, user_id)
    await _lead(db, user_id, "chan-leads", contact_id="igs-mine")
    await _seed(db, other_user_id, channel_id="chan-theirs")
    await _lead(db, other_user_id, "chan-theirs", contact_id="igs-theirs")

    r = client.get("/api/v1/leads")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert [lead["contact_id"] for lead in body["leads"]] == ["igs-mine"]


@pytest.mark.asyncio
async def test_list_filters_by_platform_and_stage(client, db, user_id):
    await _seed(db, user_id)
    await _seed(db, user_id, channel_id="chan-wa", platform="whatsapp")
    await _lead(db, user_id, "chan-leads", contact_id="igs-new")
    await _lead(db, user_id, "chan-leads", contact_id="igs-lost", stage="lost")
    await _lead(db, user_id, "chan-wa", contact_id="wa-new", platform="whatsapp")

    r = client.get("/api/v1/leads", params={"platform": "instagram", "stage": "new"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["leads"][0]["contact_id"] == "igs-new"
    assert body["leads"][0]["stage"] == "new"
    assert body["leads"][0]["thread_key"] == "igs-new"


@pytest.mark.asyncio
async def test_list_rejects_bad_stage(client, db):
    r = client.get("/api/v1/leads", params={"stage": "junk"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_patch_moves_lead_to_converted(client, db, user_id):
    await _seed(db, user_id)
    lead = await _lead(db, user_id, "chan-leads", contact_id="igs-1", summary="wants a website")

    r = client.patch(f"/api/v1/leads/{lead.id}", json={"stage": "converted"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "converted"
    assert body["summary"] == "wants a website"


@pytest.mark.asyncio
async def test_patch_foreign_lead_is_404(client, db, user_id, other_user_id):
    await _seed(db, other_user_id, channel_id="chan-theirs")
    theirs = await _lead(db, other_user_id, "chan-theirs", contact_id="igs-theirs")

    r = client.patch(f"/api/v1/leads/{theirs.id}", json={"stage": "converted"})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_patch_rejects_bad_stage(client, db, user_id):
    await _seed(db, user_id)
    lead = await _lead(db, user_id, "chan-leads")

    r = client.patch(f"/api/v1/leads/{lead.id}", json={"stage": "junk"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_patch_unknown_lead_is_404(client, db):
    r = client.patch("/api/v1/leads/nope", json={"stage": "converted"})
    assert r.status_code == 404, r.text


# ── follow-up settings ───────────────────────────────────────────────


async def _seed_settings_user(db, user_id):
    from app.modules.users.models import User

    db.add(User(
        id=user_id, first_name="S", last_name="T",
        email=f"{user_id}@example.com", password_hash="x",
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_settings_defaults_when_unset(client, db, user_id):
    r = client.get("/api/v1/leads/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["max_attempts"] == 3
    assert 5 <= body["first_nudge_minutes"] <= 15  # the brief's window
    assert body["second_followup_hours"] == 24
    assert body["final_followup_hours"] == 72


@pytest.mark.asyncio
async def test_settings_patch_clamps_out_of_range(client, db, user_id):
    await _seed_settings_user(db, user_id)
    r = client.patch("/api/v1/leads/settings", json={
        "first_nudge_minutes": 1,       # below the 5-minute floor
        "max_attempts": 99,             # above the 4-attempt ceiling
        "quiet_start_hour": 22,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first_nudge_minutes"] == 5
    assert body["max_attempts"] == 4
    assert body["quiet_start_hour"] == 22

    # Persisted: a second read shows the clamped values, not the raw ones.
    r2 = client.get("/api/v1/leads/settings")
    assert r2.json()["max_attempts"] == 4


@pytest.mark.asyncio
async def test_settings_patch_rejects_junk_timezone(client, db, user_id):
    await _seed_settings_user(db, user_id)
    r = client.patch("/api/v1/leads/settings", json={"timezone": "Not/AZone"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "UTC"
