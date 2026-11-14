"""Admin financials: month rows, rollups, admin patch."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.admin.service import (
    ensure_finance_rows,
    list_financials,
    patch_finance,
)
from app.modules.billing.models import Plan, TenantFinanceMonth, TenantSubscription
from app.modules.llm.models import LLMUsageEvent
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

MONTH = "2026-11"


async def _seed(db, user_id: str) -> None:
    db.add(User(id=user_id, email="fin@example.com", first_name="Fin", last_name="Tenant", password_hash="x"))
    plan = (await db.execute(select(Plan).where(Plan.slug == "pro"))).scalar_one()
    db.add(TenantSubscription(tenant_id=user_id, plan_id=plan.id, status="active"))
    db.add(LLMUsageEvent(
        tenant_id=user_id,
        provider="openai",
        model_id="openai:gpt-4o-mini",
        api_model="gpt-4o-mini",
        purpose="review_engine.generate",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=10,
        status="ok",
        cost_cents=3,
        provider_cost_micro_usd=25000,
        infrastructure_cost_micro_usd=500,
        delivery_cost_micro_usd=25500,
        created_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    ))
    await db.commit()


async def test_ensure_creates_row_and_rollup(db, user_id):
    await _seed(db, user_id)
    n = await ensure_finance_rows(db, MONTH)
    assert n >= 1

    result = await list_financials(db, MONTH)
    assert result["month"] == MONTH
    assert result["totals"]["infra_cost_micro"] >= 25500
    row = next(i for i in result["items"] if i["tenant_id"] == user_id)
    assert row["plan_slug"] == "pro"
    assert row["plan_price_cents"] > 0
    assert row["credits_used_cents"] == 3
    assert row["status"] == "unpaid"


async def test_patch_sets_status_collected_and_adjustments(db, user_id):
    await _seed(db, user_id)
    await ensure_finance_rows(db, MONTH)

    patched = await patch_finance(
        db, user_id, MONTH,
        status="paid",
        collected_cents=100000,
        adjustments={"extra_cost_cents": 1000},
        note="Paid manually in November.",
    )
    assert patched["status"] == "paid"
    assert patched["collected_cents"] == 100000
    assert patched["adjustments"] == {"extra_cost_cents": 1000}

    result = await list_financials(db, MONTH)
    row = next(i for i in result["items"] if i["tenant_id"] == user_id)
    assert row["collected_cents"] == 100000
    assert row["billed_cents"] == row["plan_price_cents"] + 1000
