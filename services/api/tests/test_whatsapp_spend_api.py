"""Tenant/admin WhatsApp usage and spend APIs enforce scope and funding boundaries."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.deps import require_admin
from app.modules.billing.models import Plan, TenantSubscription
from app.modules.channels.meta.spend_models import WhatsAppMonthlyUsage
from app.modules.channels.meta.spend_store import upsert_spend_result
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
    response = client.get(
        "/api/v1/billing/whatsapp-usage",
        params={"start": "2026-11-01", "end": "2026-11-29"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used"] == 3
    assert body["limit"] == 7
    assert body["remaining"] == 4
    assert body["totals"] == [{
        "currency": "SAR", "funding_mode": "direct_client",
        "approx_cost": 10.0, "volume": 2, "unavailable_volume": 0,
    }]
    assert all(row["tenant_id"] == user_id for row in body["breakdowns"])


@pytest.mark.asyncio
async def test_admin_requires_admin_and_cogs_excludes_client_direct(client, db, user_id):
    await _seed(db, user_id)
    await _seed(db, "platform-tenant", funding="platform_liable", cost=Decimal("20.00"))
    params = {"start": "2026-11-01", "end": "2026-11-29"}
    assert client.get("/api/v1/admin/whatsapp-spend", params=params).status_code in (401, 403)

    from app.main import app
    app.dependency_overrides[require_admin] = lambda: {"admin": True}
    try:
        response = client.get("/api/v1/admin/whatsapp-spend", params=params)
    finally:
        app.dependency_overrides.pop(require_admin, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert body["cogs"] == [{
        "currency": "SAR", "approx_cost": 20.0, "volume": 2,
    }]
    filtered = client.get(
        "/api/v1/admin/whatsapp-spend",
        params={**params, "tenant_id": user_id},
    )
    assert filtered.status_code in (401, 403)


@pytest.mark.asyncio
async def test_unavailable_cost_is_visible_and_date_range_is_bounded(client, db, user_id):
    await _seed(db, user_id, cost=None)
    response = client.get(
        "/api/v1/billing/whatsapp-usage",
        params={"start": "2026-11-01", "end": "2026-11-29"},
    )
    assert response.status_code == 200
    assert response.json()["totals"][0]["approx_cost"] is None
    assert response.json()["totals"][0]["unavailable_volume"] == 2
    assert client.get(
        "/api/v1/billing/whatsapp-usage",
        params={"start": "2020-01-01", "end": "2026-11-29"},
    ).status_code == 422
