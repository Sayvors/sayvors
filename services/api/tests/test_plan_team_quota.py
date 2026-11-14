"""Plan team-member quota (§34 item 2): max_team_members gates invites.

Seats = every team_members row (invited + active + suspended); a pending
invite holds its slot until revoked or accepted. Enforcement is at
`POST /api/v1/team/invites` — the only path that creates a new seat.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.entitlements import get_entitlements
from app.modules.billing.models import Plan
from app.modules.team import service
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

OWNER_ID = "test-user-0000-0000-0000-000000000001"
TENANT = OWNER_ID


@pytest.fixture
def no_email(monkeypatch):
    """Capture invite emails instead of hitting the real sender."""
    sent = []

    async def _fake(to, inviter, business, role, url):
        sent.append({"to": to, "inviter": inviter, "business": business, "role": role, "url": url})

    import app.modules.email.service as email_service
    monkeypatch.setattr(email_service, "send_team_invite_email", _fake)
    return sent


async def _set_free_trial_team_cap(db, cap: int) -> Plan:
    """Tune the seeded free-trial plan (conftest) to a known seat cap."""
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    plan.max_team_members = cap
    await db.flush()
    return plan


async def _seed_one_active_member(db) -> None:
    """Owner + system roles + one active member (a full seat)."""
    existing = (await db.execute(select(User).where(User.id == OWNER_ID))).scalar_one_or_none()
    if existing is None:
        db.add(User(
            id=OWNER_ID, email="owner@acme.com", first_name="Ola", last_name="Owner",
            password_hash="x", business_name="Acme", onboarded=True,
        ))
        await db.commit()
    roles = await service.ensure_system_roles(db, TENANT)
    role = next(r for r in roles if r.name == "Agent")
    mu = User(email="sara@acme.com", first_name="Sara", last_name="S", password_hash="x", tenant_id=TENANT)
    db.add(mu)
    await db.commit()
    member, _raw = await service.invite_member(db, TENANT, OWNER_ID, mu.email, role)
    await db.commit()
    await service.join_existing_user(db, member, mu)
    await db.commit()


async def _agent_role_id(client) -> str:
    roles = client.get("/api/v1/team/roles").json()["roles"]
    return next(r for r in roles if r["name"] == "Agent")["id"]


async def test_entitlements_expose_team_member_cap(db, user_id):
    await _set_free_trial_team_cap(db, 3)
    ent = await get_entitlements(user_id, db)
    assert ent.max_team_members == 3
    assert ent.team_member_quota_ok(0) is True
    assert ent.team_member_quota_ok(2) is True
    assert ent.team_member_quota_ok(3) is False


async def test_invite_blocked_at_seat_cap(client, db, no_email):
    await _set_free_trial_team_cap(db, 1)
    await _seed_one_active_member(db)
    agent = await _agent_role_id(client)

    resp = client.post("/api/v1/team/invites", json={
        "email": "new@acme.com", "role_id": agent,
    })
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "quota"


async def test_invite_allowed_under_seat_cap(client, db, no_email):
    await _set_free_trial_team_cap(db, 5)
    await _seed_one_active_member(db)
    agent = await _agent_role_id(client)

    resp = client.post("/api/v1/team/invites", json={
        "email": "new@acme.com", "role_id": agent,
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "invited"


async def test_pending_invite_counts_as_a_seat(client, db, no_email):
    """Two pending invites fill a cap of 2; the third is rejected."""
    await _set_free_trial_team_cap(db, 2)
    agent = await _agent_role_id(client)

    first = client.post("/api/v1/team/invites", json={
        "email": "a@acme.com", "role_id": agent,
    })
    assert first.status_code == 201
    second = client.post("/api/v1/team/invites", json={
        "email": "b@acme.com", "role_id": agent,
    })
    assert second.status_code == 201

    third = client.post("/api/v1/team/invites", json={
        "email": "c@acme.com", "role_id": agent,
    })
    assert third.status_code == 403
    assert third.headers.get("X-Entitlement-Denied") == "quota"
