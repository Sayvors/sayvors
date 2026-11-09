"""Billing requests: creation, duplicate suppression and approval effects."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.billing.entitlements import get_entitlements
from app.modules.billing.models import Plan, TenantSubscription
from app.modules.billing.requests import (
    RequestError,
    create_request,
    decide_request,
    list_for_tenant,
)
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed(db, user_id: str) -> None:
    db.add(User(
        id=user_id,
        email="requests@example.com",
        first_name="Request",
        last_name="Tenant",
        password_hash="x",
    ))
    existing = {
        row.slug
        for row in (await db.execute(select(Plan))).scalars().all()
    }
    if "free-trial" not in existing:
        db.add(Plan(
            id="plan-free-trial-0000000000000001",
            slug="free-trial",
            name="Free Trial",
            max_messages_per_month=500,
            max_channels=1,
            features={"messaging": True},
            is_active=True,
            sort_order=1,
        ))
    if "enterprise" not in existing:
        db.add(Plan(
            id="plan-enterprise-00000000000000001",
            slug="enterprise",
            name="Enterprise",
            max_messages_per_month=None,
            max_channels=None,
            features={"messaging": True},
            is_active=True,
            sort_order=2,
        ))
    await db.commit()


async def test_message_request_is_created_and_deduplicated(db, user_id):
    await _seed(db, user_id)

    first, duplicate = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    second, duplicate_again = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )

    assert duplicate is False
    assert duplicate_again is True
    assert first.id == second.id
    assert first.status == "pending"

    rows = await list_for_tenant(db, user_id)
    assert len(rows) == 1


async def test_validation_rejects_bad_amounts(db, user_id):
    await _seed(db, user_id)

    with pytest.raises(RequestError):
        await create_request(db, tenant_id=user_id, created_by=user_id, kind="messages", amount=0)
    with pytest.raises(RequestError):
        await create_request(db, tenant_id=user_id, created_by=user_id, kind="ai_credit", amount=10)
    with pytest.raises(RequestError):
        await create_request(db, tenant_id=user_id, created_by=user_id, kind="plan", plan_slug="nope")


async def test_approving_a_message_pack_raises_the_effective_limit(db, user_id):
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )

    decided = await decide_request(
        db, request.id, approve=True, operator="operator-a", note="paid offline"
    )

    assert decided.status == "approved"
    sub = (
        await db.execute(TenantSubscription.__table__.select().where(
            TenantSubscription.tenant_id == user_id
        ))
    ).first()
    assert sub is not None
    # The pack is stored as a bonus, not an absolute limit, so the plan stays
    # authoritative for the base.
    assert sub.message_bonus == 500
    assert sub.message_limit_override is None


async def test_plan_change_keeps_the_bonus_and_uses_the_new_base(db, user_id):
    """A bought pack must survive a plan change instead of pinning the limit."""
    await _seed(db, user_id)
    pack, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    await decide_request(db, pack.id, approve=True, operator="operator-a")

    upgrade, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="plan", plan_slug="pro"
    )
    await decide_request(db, upgrade.id, approve=True, operator="operator-a")

    ent = await get_entitlements(user_id, db)
    assert ent.plan_slug == "pro"
    assert ent.max_messages_per_month == 25_500


async def test_approving_a_plan_switches_the_subscription(db, user_id):
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="plan", plan_slug="enterprise"
    )

    decided = await decide_request(db, request.id, approve=True, operator="operator-a")

    assert decided.status == "approved"
    sub = (
        await db.execute(
            TenantSubscription.__table__.select().where(TenantSubscription.tenant_id == user_id)
        )
    ).first()
    enterprise = (
        await db.execute(select(Plan).where(Plan.slug == "enterprise"))
    ).scalar_one()
    assert sub.plan_id == enterprise.id


async def test_reject_does_not_apply_anything(db, user_id):
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )

    decided = await decide_request(
        db, request.id, approve=False, operator="operator-a", note="out of policy"
    )

    assert decided.status == "rejected"
    remaining = (
        await db.execute(
            TenantSubscription.__table__.select().where(TenantSubscription.tenant_id == user_id)
        )
    ).first()
    assert remaining is None or not remaining.message_bonus
