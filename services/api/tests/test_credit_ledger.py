"""Durable AI-credit ledger: holds, settlement, reaper, cutover, reconciler.

These tests replace the Redis-as-source-of-truth assertions. The wallet column
is authoritative; Redis is only a mirror.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.billing import budget, ledger
from app.modules.billing.budget import (
    BudgetExhausted,
    BudgetUnavailable,
    cost_cents,
    get_balance,
)

pytestmark = pytest.mark.asyncio

# In-memory Redis double. Billing correctness must not depend on a live Redis
# in unit tests; the real mirror is exercised by the reconciler path.
_CACHE: dict[str, int] = {}


@pytest.fixture(autouse=True)
def _fake_cache(monkeypatch):
    _CACHE.clear()

    async def _get(uid: str):
        return _CACHE.get(uid)

    async def _set(uid: str, cents: int) -> bool:
        _CACHE[uid] = int(cents)
        return True

    async def _seed(uid: str, cents: int) -> bool:
        _CACHE.setdefault(uid, int(cents))
        return True

    monkeypatch.setattr(budget, "get_cached_balance", _get)
    monkeypatch.setattr(budget, "sync_balance", _set)
    monkeypatch.setattr(budget, "seed_balance", _seed)
    yield
    _CACHE.clear()


async def _clear(uid: str) -> None:
    _CACHE.pop(uid, None)


@pytest_asyncio.fixture
async def wallet_factory(db):
    """Create committed funded tenants and clear their Redis mirrors."""
    created: list[str] = []

    async def _make(cents: int = 100, *, plan: str = "pro") -> str:
        from app.modules.billing.models import BillingEvent
        from app.modules.users.models import User

        uid = f"ledger-{uuid.uuid4()}"
        db.add(User(
            id=uid,
            email=f"{uid}@sayvors.com",
            first_name="L",
            last_name="T",
            password_hash="x",
            onboarded=True,
            plan=plan,
            ai_credit_cents=cents,
        ))
        if cents:
            # Production credit always originates in the ledger. Seeding both
            # keeps the cutover calculation consistent with the column.
            db.add(BillingEvent(
                id=f"seed-grant-{uid}",
                tenant_id=uid,
                kind="plan_grant",
                status="posted",
                amount_cents=cents,
                balance_after_cents=cents,
                created_by="test",
            ))
        await db.commit()
        await _clear(uid)
        created.append(uid)
        return uid

    yield _make
    for uid in created:
        await _clear(uid)


async def _wallet(db, uid: str) -> int:
    from app.modules.users.models import User

    db.expire_all()
    user = await db.get(User, uid)
    assert user is not None
    return int(user.ai_credit_cents or 0)


async def _holds(db, uid: str, status: str | None = None) -> list:
    from app.modules.billing.models import BillingEvent

    db.expire_all()
    query = select(BillingEvent).where(
        BillingEvent.tenant_id == uid,
        BillingEvent.kind == "ai_usage",
    )
    if status is not None:
        query = query.where(BillingEvent.status == status)
    return list((await db.execute(query)).scalars().all())


async def test_reserve_and_settle_write_wallet_and_ledger(db, wallet_factory):
    uid = await wallet_factory(100)

    reservation = await ledger.reserve(
        uid, model_id="groq:oss-120b", purpose="test.ledger"
    )
    assert reservation.tenant_id == uid
    assert reservation.amount_cents == budget.RESERVE_CENTS
    assert await _wallet(db, uid) == 100 - budget.RESERVE_CENTS

    holds = await _holds(db, uid, "pending")
    assert len(holds) == 1
    assert holds[0].id == reservation.id
    assert holds[0].reserved_cents == budget.RESERVE_CENTS
    assert holds[0].amount_cents == 0
    assert holds[0].balance_after_cents == 95
    assert holds[0].model_id == "groq:oss-120b"

    result = await ledger.settle(
        reservation, 1, prompt_tokens=3000, completion_tokens=500
    )
    assert result is not None
    assert result.status == "settled"
    assert await _wallet(db, uid) == 99

    hold = (await _holds(db, uid))[0]
    assert hold.status == "settled"
    assert hold.amount_cents == -1
    assert hold.balance_after_cents == 99
    assert hold.prompt_tokens == 3000
    assert hold.completion_tokens == 500
    assert hold.settled_at is not None
    assert await budget.get_cached_balance(uid) == 99


async def test_empty_wallet_rejects_without_creating_a_hold(db, wallet_factory):
    uid = await wallet_factory(0)

    with pytest.raises(BudgetExhausted):
        await ledger.reserve(uid)

    assert await _wallet(db, uid) == 0
    assert await _holds(db, uid) == []


async def test_settle_is_idempotent(db, wallet_factory):
    uid = await wallet_factory(100)
    reservation = await ledger.reserve(uid)

    first = await ledger.settle(reservation, 3)
    second = await ledger.settle(reservation, 50)  # must not re-charge

    assert first is not None and second is not None
    assert first.status == "settled"
    assert second.status == "settled"
    assert await _wallet(db, uid) == 97
    holds = await _holds(db, uid)
    assert len(holds) == 1
    assert holds[0].amount_cents == -3


async def test_failed_call_releases_the_full_hold(db, wallet_factory):
    uid = await wallet_factory(100)
    reservation = await ledger.reserve(uid)

    result = await ledger.settle(reservation, 0)

    assert result is not None
    assert result.status == "released"
    assert await _wallet(db, uid) == 100
    hold = (await _holds(db, uid))[0]
    assert hold.status == "released"
    assert hold.amount_cents == 0
    assert hold.balance_after_cents == 100


async def test_reaper_refunds_an_expired_hold_and_late_settle_charges(
    db, wallet_factory
):
    from app.modules.billing.models import BillingEvent

    uid = await wallet_factory(100)
    reservation = await ledger.reserve(uid)

    db.expire_all()
    hold = (await db.execute(
        select(BillingEvent).where(BillingEvent.id == reservation.id)
    )).scalar_one()
    hold.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()

    expired = await ledger.expire_stale_holds()
    assert expired == 1
    assert await _wallet(db, uid) == 100
    hold = (await _holds(db, uid))[0]
    assert hold.status == "expired"
    assert hold.amount_cents == 0

    # The process was only slow, not gone: the real cost is still charged.
    await ledger.settle(reservation, 2)
    assert await _wallet(db, uid) == 98
    hold = (await _holds(db, uid))[0]
    assert hold.status == "settled"
    assert hold.amount_cents == -2


async def test_deleting_redis_does_not_change_the_true_balance(db, wallet_factory):
    from app.modules.billing import service

    uid = await wallet_factory(100)
    reservation = await ledger.reserve(uid)
    await ledger.settle(reservation, 1)

    await _clear(uid)
    assert await budget.get_cached_balance(uid) is None
    assert await get_balance(uid) == 99

    db.expire_all()
    out = await service.get_budget(uid, db)
    assert out["balance_cents"] == 99
    assert out["balance_dollars"] == 0.99


async def test_topup_adds_to_the_wallet_without_regranting_spend(db, wallet_factory):
    from app.modules.billing import service

    uid = await wallet_factory(100, plan="pro")
    reservation = await ledger.reserve(uid)
    await ledger.settle(reservation, 3)
    assert await _wallet(db, uid) == 97

    out = await service.grant_plan(uid, "pro", 500, "topup", "admin", db)
    assert out["balance_cents"] == 597
    assert await _wallet(db, uid) == 597
    assert await budget.get_cached_balance(uid) == 597


async def test_opening_balance_is_written_once(db, wallet_factory):
    from app.modules.billing.models import BillingEvent
    from app.modules.llm.models import LLMUsageEvent

    uid = await wallet_factory(0)
    now = datetime.now(timezone.utc)
    db.add(BillingEvent(
        id=f"legacy-grant-{uid}",
        tenant_id=uid,
        kind="plan_grant",
        amount_cents=2000,
        balance_after_cents=2000,
        created_at=now - timedelta(days=5),
    ))
    db.add(LLMUsageEvent(
        id=f"legacy-usage-{uid}",
        tenant_id=uid,
        provider="groq",
        model_id="groq:oss-120b",
        api_model="oss",
        purpose="reply",
        prompt_tokens=3000,
        completion_tokens=500,
        total_tokens=3500,
        status="ok",
        created_at=now - timedelta(days=1),
    ))
    await db.commit()

    first = await ledger.ensure_ledger_initialized(uid, db)
    assert first == 1999
    await db.commit()

    second = await ledger.ensure_ledger_initialized(uid, db)
    assert second == 1999
    await db.commit()

    openings = (await db.execute(
        select(BillingEvent).where(
            BillingEvent.tenant_id == uid,
            BillingEvent.kind == "balance_resync",
        )
    )).scalars().all()
    assert len(openings) == 1
    assert openings[0].balance_after_cents == 1999
    assert openings[0].idempotency_key == f"ledger-opening:{uid}"
    assert await _wallet(db, uid) == 1999


async def test_reconciler_previews_and_repairs_redis_to_db(db, wallet_factory):
    from app.modules.billing.models import BillingEvent

    uid = await wallet_factory(100)
    # Simulate a lost/poisoned cache. The DB remains correct.
    await budget.sync_balance(uid, 0)

    preview = await ledger.reconcile_wallet(uid, db, dry_run=True)
    assert preview["applied"] is False
    assert preview["db_balance_cents"] == 100
    assert preview["redis_balance_cents"] == 0
    assert preview["delta_cents"] == 100

    applied = await ledger.reconcile_wallet(
        uid, db, dry_run=False, created_by="admin", note="test repair"
    )
    assert applied["applied"] is True
    assert applied["redis_synced"] is True
    assert await budget.get_cached_balance(uid) == 100

    audits = (await db.execute(
        select(BillingEvent).where(
            BillingEvent.tenant_id == uid,
            BillingEvent.kind == "balance_reconcile",
        )
    )).scalars().all()
    assert len(audits) == 1
    assert audits[0].balance_after_cents == 100
    assert audits[0].amount_cents == 0

    # A second apply with no drift must not write another audit row.
    again = await ledger.reconcile_wallet(uid, db, dry_run=False)
    assert again["applied"] is True
    audits = (await db.execute(
        select(BillingEvent).where(
            BillingEvent.tenant_id == uid,
            BillingEvent.kind == "balance_reconcile",
        )
    )).scalars().all()
    assert len(audits) == 1


async def test_database_failure_denies_the_budget_gate(monkeypatch, wallet_factory):
    uid = await wallet_factory(100)

    class _BrokenFactory:
        def __call__(self):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr(ledger, "_session_factory", _BrokenFactory())
    with pytest.raises(BudgetUnavailable):
        await ledger.reserve(uid)


async def test_reaper_settles_a_priced_usage_row_instead_of_refunding(db, wallet_factory):
    """A crash after the provider returned must not become free usage."""
    from app.modules.llm.models import LLMUsageEvent

    uid = await wallet_factory(100)
    reservation = await ledger.reserve(uid)
    db.add(LLMUsageEvent(
        id=f"recover-{uid}",
        tenant_id=uid,
        provider="groq",
        model_id="groq:oss-120b",
        api_model="oss",
        purpose="test.recover",
        prompt_tokens=3000,
        completion_tokens=500,
        total_tokens=3500,
        status="ok",
        cost_cents=2,
        ledger_id=reservation.id,
    ))
    await db.commit()

    changed = await ledger.expire_stale_holds()
    assert changed == 1
    assert await _wallet(db, uid) == 98
    hold = (await _holds(db, uid))[0]
    assert hold.status == "settled"
    assert hold.amount_cents == -2


async def test_settle_overage_goes_negative_and_blocks_the_next_call(db, wallet_factory):
    """A real cost above the hold is debt, not a silent cap."""
    uid = await wallet_factory(5)
    reservation = await ledger.reserve(uid)
    assert await _wallet(db, uid) == 0

    await ledger.settle(reservation, 20)
    assert await _wallet(db, uid) == -15
    assert await budget.get_cached_balance(uid) == -15
    with pytest.raises(BudgetExhausted):
        await ledger.reserve(uid)


async def test_usage_row_can_reference_the_ledger_and_cost(
    monkeypatch, db, wallet_factory
):
    import asyncio

    from app.modules.llm.models import LLMUsageEvent
    from app.modules.llm.providers.base import LLMRequest, LLMResponse
    from app.modules.llm import usage as usage_module

    uid = await wallet_factory(100)
    reservation = await ledger.reserve(uid)
    result = await ledger.settle(reservation, 2)
    assert result is not None

    # The test session factory is installed by conftest; schedule and await it.
    req = LLMRequest(
        model="api-x",
        model_id="groq:oss-120b",
        tenant_id=uid,
        purpose="test.ledger",
    )
    task = usage_module.record_usage_event(
        req,
        LLMResponse(content="hi", provider="groq", model="api-x"),
        10,
        cost_cents=2,
        ledger_id=reservation.id,
    )
    assert task is not None
    await asyncio.gather(task)

    db.expire_all()
    event = (await db.execute(
        select(LLMUsageEvent).where(LLMUsageEvent.tenant_id == uid)
    )).scalar_one()
    assert event.cost_cents == 2
    assert event.ledger_id == reservation.id
    assert cost_cents("groq:oss-120b", 3000, 500) == 1
