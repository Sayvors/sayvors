"""Billing requests: creation, duplicate suppression and approval effects."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.billing.entitlements import get_entitlements
from app.modules.billing.models import BillingEvent, Plan, TenantSubscription
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


# -- REQ-1: the denormalised plan must follow an approval -----------------


async def test_plan_approval_syncs_user_plan(db, user_id):
    """The subscription moved but users.plan still said free-trial.

    That column is read by the admin tenant list, campaign targeting and the
    effective-plan fallback, so an approved upgrade was only half applied.
    """
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="plan", plan_slug="enterprise"
    )
    await decide_request(db, request.id, approve=True, operator="operator-a")

    user = await db.get(User, user_id)
    assert user.plan == "enterprise"


async def test_message_approval_does_not_change_user_plan(db, user_id):
    """Only a plan decision changes the tier; a top-up must not touch it."""
    await _seed(db, user_id)
    user = await db.get(User, user_id)
    user.plan = "pro"
    await db.commit()
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    await decide_request(db, request.id, approve=True, operator="operator-a")

    await db.refresh(user)
    assert user.plan == "pro"


# -- REQ-4: every approval leaves a dated ledger row ----------------------


async def test_non_credit_approval_writes_a_ledger_audit_row(db, user_id):
    """Message/channel/plan approvals used to bypass the wallet entirely."""
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    await decide_request(db, request.id, approve=True, operator="operator-a")

    events = (
        await db.execute(
            select(BillingEvent).where(
                BillingEvent.tenant_id == user_id,
                BillingEvent.idempotency_key == f"billing-request-decision:{request.id}",
            )
        )
    ).scalars().all()
    assert len(events) == 1
    row = events[0]
    assert row.kind == "billing_request"
    assert row.status == "posted"
    assert row.amount_cents == 0  # audit snapshot, never a balance movement
    assert row.balance_after_cents == 0
    assert row.created_by == "operator-a"
    assert "messages" in row.note


async def test_plan_approval_writes_a_ledger_audit_row(db, user_id):
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="plan", plan_slug="enterprise"
    )
    await decide_request(db, request.id, approve=True, operator="operator-a")

    row = (
        await db.execute(
            select(BillingEvent).where(
                BillingEvent.idempotency_key == f"billing-request-decision:{request.id}"
            )
        )
    ).scalar_one()
    assert row.note.endswith("Plan switched to Enterprise.") or "enterprise" in row.note


async def test_rejection_writes_no_ledger_audit_row(db, user_id):
    await _seed(db, user_id)
    request, _ = await create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    await decide_request(db, request.id, approve=False, operator="operator-a")

    row = (
        await db.execute(
            select(BillingEvent).where(
                BillingEvent.idempotency_key == f"billing-request-decision:{request.id}"
            )
        )
    ).scalar_one_or_none()
    assert row is None


# -- REQ-2: bounded operator queue and submission rate --------------------


async def test_pending_queue_is_capped(db, user_id):
    await _seed(db, user_id)
    from app.modules.billing.requests import MAX_PENDING_PER_TENANT

    for amount in range(1, MAX_PENDING_PER_TENANT + 1):
        _, duplicate = await create_request(
            db, tenant_id=user_id, created_by=user_id, kind="messages", amount=amount
        )
        assert duplicate is False

    with pytest.raises(RequestError, match="waiting for review"):
        await create_request(
            db, tenant_id=user_id, created_by=user_id, kind="messages", amount=999
        )
    assert len(await list_for_tenant(db, user_id)) == MAX_PENDING_PER_TENANT


async def test_request_endpoint_rate_limits(client, db, user_id, monkeypatch):
    await _seed(db, user_id)
    from app.modules.billing import router as billing_router

    monkeypatch.setattr(billing_router.settings, "TESTING", False)

    async def _denied(*args, **kwargs):
        return False

    monkeypatch.setattr(billing_router, "rate_limit", _denied)
    res = client.post(
        "/api/v1/billing/requests", json={"kind": "messages", "amount": 100}
    )
    assert res.status_code == 429
    assert "Too many requests" in res.json()["detail"]


# -- REQ-3: the database arbitrates a concurrent duplicate ----------------


async def test_unique_index_settles_a_submission_race(db, user_id, monkeypatch):
    """Two submissions that both pass the pre-check must yield one row.

    The pre-check is deliberately forced to miss the second time, which is
    what two concurrent requests would see. The partial unique index is the
    arbiter, and the losing insert is reported as an ordinary duplicate.
    """
    await _seed(db, user_id)
    from app.modules.billing import requests as billing_requests

    first, duplicate = await billing_requests.create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    assert duplicate is False

    real_lookup = billing_requests._pending_duplicate
    calls = 0
    skip_next = True

    async def _lookup_skipping_the_precheck(*args, **kwargs):
        nonlocal calls, skip_next
        calls += 1
        if skip_next:
            skip_next = False
            return None
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(billing_requests, "_pending_duplicate", _lookup_skipping_the_precheck)

    second, duplicate_again = await billing_requests.create_request(
        db, tenant_id=user_id, created_by=user_id, kind="messages", amount=500
    )
    assert duplicate_again is True
    assert second.id == first.id
    assert len(await list_for_tenant(db, user_id)) == 1
    # One forced miss from the pre-check, then the conflict handler's real
    # lookup — never swallow an unrelated constraint failure as a duplicate.
    assert calls == 2
