"""Tenant/admin WhatsApp usage and spend APIs enforce scope and funding boundaries."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.deps import get_current_user, require_admin
from app.modules.billing.models import Plan, TenantSubscription
from app.modules.channels.meta.spend_models import WhatsAppMonthlyUsage
from app.modules.channels.meta.spend_store import upsert_spend_result
from app.modules.team.models import TeamMember, TeamMemberChannel, TeamRole
from app.modules.users.models import User


def _point(**changes):
    point = {
        "spend_date": date(2026, 11, 5), "phone": "966500000001",
        "country": "SA", "pricing_category": "UTILITY",
        "pricing_type": "REGULAR", "tier": "0:MAX",
        "volume": 2, "cost": Decimal("10.00"), "cost_status": "available",
    }
    point.update(changes)
    return point


async def _seed(db, uid, *, funding="direct_client", cost=Decimal("10.00")):
    db.add(User(
        id=uid, first_name="Spend", last_name="Test",
        email=f"{uid}@example.com", password_hash="x",
    ))
    plan = Plan(
        id=f"plan-{uid}", slug=f"plan-{uid}", name="Spend Plan",
        max_messages_per_month=5, features={"messaging": True},
    )
    db.add(plan)
    await db.flush()
    db.add(TenantSubscription(tenant_id=uid, plan_id=plan.id, message_bonus=2))
    db.add(WhatsAppMonthlyUsage(
        tenant_id=uid, month=date(2026, 11, 1), used_count=3,
    ))
    await db.flush()
    await upsert_spend_result(db, uid, "waba-1", {
        "points": [_point(cost=cost)], "currency": "SAR",
        "funding_mode": funding, "waba_timezone": "Asia/Riyadh",
        "messaging_account_id": "ma-1",
    })


@pytest.mark.asyncio
async def test_tenant_usage_is_scoped_and_keeps_funding_currencies_separate(client, db, user_id):
    other = "other-spend-tenant"
    await _seed(db, user_id)
    await _seed(db, other, funding="platform_liable", cost=Decimal("99.00"))
    response = client.get("/api/v1/billing/whatsapp-usage", params={"days": 30})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used"] == 3
    assert body["limit"] == 7
    assert body["remaining"] == 4
    assert body["approximate_cost"] == 10.0
    assert body["currency"] == "SAR"
    assert body["funding_mode"] == "direct_client"
    assert body["cost_availability"] == "available"
    assert body["sync_status"] == "synced"
    assert body["last_meta_sync_at"] is not None
    assert body["totals"] == [{
        "currency": "SAR", "funding_mode": "direct_client",
        "approximate_cost": 10.0, "volume": 2,
        "cost_availability": "available",
        "last_meta_sync_at": body["last_meta_sync_at"],
    }]
    assert body["breakdowns"]["by_waba"][0]["waba_id"] == "waba-1"
    assert body["breakdowns"]["by_phone"][0]["phone"] == "966500000001"
    assert body["breakdowns"]["by_category"][0]["category"] == "UTILITY"


async def _seed_member(db, tenant_id: str, permissions: list[str], *, denied_channel: str | None = None):
    uid = f"member-{tenant_id[-8:]}"
    db.add(User(
        id=uid, first_name="Workspace", last_name="Member", tenant_id=tenant_id,
        email=f"{uid}@example.com", password_hash="x",
    ))
    role = TeamRole(tenant_id=tenant_id, name="Spend Viewer", permissions=permissions)
    db.add(role)
    await db.flush()
    member = TeamMember(
        tenant_id=tenant_id, user_id=uid, email=f"{uid}@example.com",
        role_id=role.id, status="active",
    )
    db.add(member)
    await db.flush()
    if denied_channel:
        db.add(TeamMemberChannel(
            member_id=member.id, channel_id=denied_channel, level="none",
        ))
    await db.commit()
    return await db.get(User, uid)


def _auth_member(client, member):
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: member


@pytest.mark.asyncio
async def test_member_without_channels_view_gets_403(client, db):
    tenant_id = "usage-owner-no-permission"
    await _seed(db, tenant_id)
    member = await _seed_member(db, tenant_id, [])
    _auth_member(client, member)
    try:
        response = client.get("/api/v1/billing/whatsapp-usage", params={"days": 30})
    finally:
        from app.main import app
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 403
    assert "channels.view" in response.json()["detail"]


@pytest.mark.asyncio
async def test_authorized_member_receives_tenant_scoped_usage(client, db):
    tenant_id = "usage-owner-authorized"
    await _seed(db, tenant_id)
    await _seed(db, "usage-owner-other", cost=Decimal("99.00"))
    member = await _seed_member(db, tenant_id, ["channels.view"])
    _auth_member(client, member)
    try:
        response = client.get("/api/v1/billing/whatsapp-usage", params={"days": 30})
    finally:
        from app.main import app
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used"] == 3
    assert body["approximate_cost"] == 10.0
    assert body["breakdowns"]["by_phone"][0]["phone"] == "966500000001"


@pytest.mark.asyncio
async def test_channel_deny_override_omits_phone_breakdown(client, db):
    tenant_id = "usage-owner-restricted"
    await _seed(db, tenant_id)
    member = await _seed_member(
        db, tenant_id, ["channels.view"], denied_channel="restricted-channel"
    )
    _auth_member(client, member)
    try:
        response = client.get("/api/v1/billing/whatsapp-usage", params={"days": 30})
    finally:
        from app.main import app
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"][0]["volume"] == 2
    assert body["breakdowns"]["by_phone"] == []


@pytest.mark.asyncio
async def test_admin_requires_admin_and_cogs_excludes_client_direct(client, db, user_id):
    await _seed(db, user_id)
    await _seed(db, "platform-tenant", funding="platform_liable", cost=Decimal("20.00"))
    params = {"days": 30}
    assert client.get("/api/v1/admin/whatsapp-spend", params=params).status_code in (401, 403)

    from app.main import app
    app.dependency_overrides[require_admin] = lambda: {"admin": True}
    try:
        response = client.get("/api/v1/admin/whatsapp-spend", params=params)
    finally:
        app.dependency_overrides.pop(require_admin, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == 30
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert {row["tenant_name"] for row in body["items"]} == {"Spend Test"}
    assert all(row["waba_id"] == "waba-1" for row in body["items"])
    assert {row["funding_mode"] for row in body["totals"]} == {
        "direct_client", "platform_liable",
    }
    filtered = client.get(
        "/api/v1/admin/whatsapp-spend",
        params={**params, "tenant_id": user_id},
    )
    assert filtered.status_code in (401, 403)


@pytest.mark.asyncio
async def test_mixed_currencies_are_never_summed_at_top_level(client, db, user_id):
    await _seed(db, user_id)
    await upsert_spend_result(db, user_id, "waba-1", {
        "points": [_point(phone="966500000002", cost=Decimal("20.00"))],
        "currency": "USD", "funding_mode": "direct_client",
        "messaging_account_id": "ma-1",
    })
    body = client.get(
        "/api/v1/billing/whatsapp-usage", params={"days": 30}
    ).json()
    assert {row["currency"] for row in body["totals"]} == {"SAR", "USD"}
    assert body["approximate_cost"] in (10.0, 20.0)
    assert body["currency"] in ("SAR", "USD")


@pytest.mark.asyncio
async def test_unavailable_cost_is_visible_and_date_range_is_bounded(client, db, user_id):
    await _seed(db, user_id, cost=None)
    response = client.get("/api/v1/billing/whatsapp-usage", params={"days": 30})
    assert response.status_code == 200
    assert response.json()["approximate_cost"] is None
    assert response.json()["cost_availability"] == "unavailable"
    assert response.json()["totals"][0]["approximate_cost"] is None
    assert response.json()["totals"][0]["cost_availability"] == "unavailable"
    assert client.get(
        "/api/v1/billing/whatsapp-usage", params={"days": 31}
    ).status_code == 422
