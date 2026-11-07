"""AI credit budget — pricing, durable reserve/settle, provider gate, grants."""
import pytest
from sqlalchemy import select

from app.modules.billing import budget
from app.modules.billing.budget import (
    BudgetExhausted,
    cost_cents,
    get_balance,
    reserve,
    settle,
)

_TENANT = "budget-test-tenant-0001"

# In-memory Redis double. The durable tests must pass with no Redis server.
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


async def _seed_live_wallet(db, uid: str, cents: int = 0) -> None:
    """Create a tenant that already has a ledger opening row.

    The wallet column is authoritative once the opening row exists, so tests
    can set the balance directly without replaying historical usage.
    """
    from app.modules.billing.models import BillingEvent
    from app.modules.users.models import User

    db.add(User(
        id=uid, email=f"{uid}@sayvors.com", first_name="B",
        last_name="T", password_hash="x", onboarded=True,
        plan="pro", ai_credit_cents=cents,
    ))
    db.add(BillingEvent(
        id=f"opening-{uid}", tenant_id=uid, kind="balance_resync",
        status="posted", amount_cents=0, balance_after_cents=cents,
        idempotency_key=f"ledger-opening:{uid}", created_by="test",
    ))
    await db.commit()


async def _set_wallet(db, uid: str, cents: int) -> None:
    from app.modules.users.models import User

    db.expire_all()
    user = await db.get(User, uid)
    assert user is not None
    user.ai_credit_cents = cents
    await db.commit()


@pytest.fixture
def _allow_admin_auth(monkeypatch):
    """Billing tests run without Redis; the auth blacklist fails closed."""
    from app.modules.auth import rate_limit

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(rate_limit, "is_token_blacklisted", _not_revoked)


def test_cost_cents_math():
    assert cost_cents("groq:oss-120b", 3000, 500) == 1  # ceil(0.045 + 0.03)
    assert cost_cents("mock:anything", 1_000_000, 1_000_000) == 0
    assert cost_cents("openai:gpt-4o", 0, 0) == 0
    assert cost_cents(None, 100, 100) == 0
    assert cost_cents("weirdmodel", 2_000_000, 0) == 0  # unknown family → free
    # OpenRouter resells other families; it must not fall through to "free".
    assert cost_cents("openrouter:openai/gpt-4o-mini", 1_000_000, 0) == 375


@pytest.mark.asyncio
async def test_reserve_settle_roundtrip(db):
    await _seed_live_wallet(db, _TENANT, 100)
    assert await get_balance(_TENANT) == 100
    reservation = await reserve(_TENANT)
    assert reservation.amount_cents == budget.RESERVE_CENTS
    assert await get_balance(_TENANT) == 100 - budget.RESERVE_CENTS
    await settle(reservation, 1)
    assert await get_balance(_TENANT) == 99


@pytest.mark.asyncio
async def test_reserve_empty_wallet_raises_and_refunds(db):
    await _seed_live_wallet(db, _TENANT, 0)
    with pytest.raises(BudgetExhausted):
        await reserve(_TENANT)
    assert await get_balance(_TENANT) == 0  # never negative


@pytest.mark.asyncio
async def test_provider_complete_gated(monkeypatch, db):
    """Zero balance → 402 before _complete; funded → called + settled."""
    from app.modules.llm.providers.base import (
        LLMProvider,
        LLMRequest,
        LLMResponse,
        LLMUsage,
        ProviderError,
    )

    monkeypatch.setattr("app.modules.llm.usage.record_usage_event",
                        lambda *a, **k: None)

    class _P(LLMProvider):
        def __init__(self):
            self.calls = 0

        async def _complete(self, req):
            self.calls += 1
            return LLMResponse(content="hi", provider="t", model="m",
                               usage=LLMUsage(prompt_tokens=3000, completion_tokens=500))

        async def stream(self, req):
            yield "hi"

        def name(self):
            return "t"

    p = _P()
    req = LLMRequest(model="m", model_id="groq:oss-120b", tenant_id=_TENANT)

    await _seed_live_wallet(db, _TENANT, 0)
    with pytest.raises(ProviderError) as exc:
        await p.complete(req)
    assert exc.value.status_code == 402
    assert p.calls == 0

    await _set_wallet(db, _TENANT, 10_000)
    resp = await p.complete(req)
    assert resp.content == "hi"
    assert p.calls == 1
    expected = 10_000 - cost_cents("groq:oss-120b", 3000, 500)
    assert await get_balance(_TENANT) == expected


@pytest.mark.asyncio
async def test_provider_complete_untracked_without_tenant(monkeypatch):
    """System calls (tenant_id=None) are never gated."""
    from app.modules.llm.providers.base import (
        LLMProvider,
        LLMRequest,
        LLMResponse,
    )

    monkeypatch.setattr("app.modules.llm.usage.record_usage_event",
                        lambda *a, **k: None)

    class _P(LLMProvider):
        async def _complete(self, req):
            return LLMResponse(content="sys", provider="t", model="m")

        async def stream(self, req):
            yield "sys"

        def name(self):
            return "t"

    resp = await _P().complete(LLMRequest(model="m"))
    assert resp.content == "sys"


@pytest.mark.asyncio
async def test_gateway_stream_reserves_meters_and_settles(monkeypatch, db):
    """A streamed call is budgeted and metered even without provider usage."""
    from app.modules.llm import gateway
    from app.modules.llm.providers import registry
    from app.modules.llm.providers.base import LLMMessage

    captured = {}

    class _P:
        async def stream(self, req):
            yield "hello "
            yield "world"

    monkeypatch.setattr(registry, "get_provider_for_model", lambda model: _P())
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model", lambda model: ("api-x", "groq")
    )
    monkeypatch.setattr(
        "app.modules.llm.gateway.record_usage_event",
        lambda req, resp, latency_ms, **kw: captured.update(resp=resp, **kw),
    )

    await _seed_live_wallet(db, _TENANT, 100)
    chunks = [
        c async for c in gateway.stream(
            model="groq:oss-120b",
            messages=[LLMMessage(role="user", content="hi there")],
            purpose="test.stream",
            system_prompt="be nice",
            tenant_id=_TENANT,
        )
    ]

    assert "".join(chunks) == "hello world"
    # prompt = (8 + 7) // 4 = 3 tokens; completion = 11 // 4 = 2 tokens.
    assert captured["resp"].usage.prompt_tokens == 3
    assert captured["resp"].usage.completion_tokens == 2
    assert captured["status"] == "ok"
    assert await get_balance(_TENANT) == 100 - cost_cents("groq:oss-120b", 3, 2)


@pytest.mark.asyncio
async def test_gateway_stream_refunds_the_reservation_on_provider_failure(
    monkeypatch, db
):
    from app.modules.llm import gateway
    from app.modules.llm.providers import registry
    from app.modules.llm.providers.base import LLMMessage

    captured = {}

    class _P:
        async def stream(self, req):
            yield "partial"
            raise RuntimeError("upstream died")

    monkeypatch.setattr(registry, "get_provider_for_model", lambda model: _P())
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model", lambda model: ("api-x", "groq")
    )
    monkeypatch.setattr(
        "app.modules.llm.gateway.record_usage_event",
        lambda req, resp, latency_ms, **kw: captured.update(resp=resp, **kw),
    )

    await _seed_live_wallet(db, _TENANT, 100)
    with pytest.raises(RuntimeError, match="upstream died"):
        async for _ in gateway.stream(
            model="groq:oss-120b",
            messages=[LLMMessage(role="user", content="hi")],
            purpose="test.stream",
            tenant_id=_TENANT,
        ):
            pass

    assert captured["resp"] is None
    assert captured["status"] == "error"
    assert await get_balance(_TENANT) == 100  # full refund


@pytest.mark.asyncio
async def test_gateway_stream_refuses_an_empty_wallet_before_calling_provider(
    monkeypatch, db
):
    from app.modules.llm import gateway
    from app.modules.llm.providers import registry
    from app.modules.llm.providers.base import LLMMessage, ProviderError

    called = False

    class _P:
        async def stream(self, req):
            nonlocal called
            called = True
            yield "never"

    monkeypatch.setattr(registry, "get_provider_for_model", lambda model: _P())
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model", lambda model: ("api-x", "groq")
    )

    await _seed_live_wallet(db, _TENANT, 0)
    with pytest.raises(ProviderError) as exc:
        async for _ in gateway.stream(
            model="groq:oss-120b",
            messages=[LLMMessage(role="user", content="hi")],
            purpose="test.stream",
            tenant_id=_TENANT,
        ):
            pass

    assert exc.value.status_code == 402
    assert called is False
    assert await get_balance(_TENANT) == 0


@pytest.mark.asyncio
async def test_refuse_empty_wallet_only_blocks_a_known_zero(monkeypatch):
    from fastapi import HTTPException

    from app.modules.llm import router as llm_router

    async def _zero(_tenant):
        return 0

    monkeypatch.setattr(llm_router, "get_balance", _zero)
    with pytest.raises(HTTPException) as exc:
        await llm_router._refuse_empty_wallet("t")
    assert exc.value.status_code == 402

    async def _unknown(_tenant):
        return None

    monkeypatch.setattr(llm_router, "get_balance", _unknown)
    await llm_router._refuse_empty_wallet("t")  # Redis unknown → fail open

    async def _funded(_tenant):
        return 25

    monkeypatch.setattr(llm_router, "get_balance", _funded)
    await llm_router._refuse_empty_wallet("t")


@pytest.mark.parametrize("path", ["/api/v1/llm/chat", "/api/v1/llm/chat/stream"])
def test_chat_refuses_an_empty_wallet_before_creating_a_conversation(
    client, monkeypatch, path
):
    """A 402 must not leave an orphan conversation behind."""
    from fastapi import HTTPException

    from app.modules.llm import router as llm_router

    created = False

    async def _deny(_tenant):
        raise HTTPException(status_code=402, detail="empty")

    async def _create(*args, **kwargs):
        nonlocal created
        created = True
        raise AssertionError("conversation created before the wallet check")

    monkeypatch.setattr(llm_router, "_refuse_empty_wallet", _deny)
    monkeypatch.setattr(llm_router, "create_conversation", _create)

    response = client.post(
        path,
        json={
            "model": "groq:oss-120b",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 402
    assert created is False


@pytest.mark.asyncio
async def test_trial_grant_is_idempotent(db):
    from app.modules.billing import service as billing_service
    from app.modules.billing.models import BillingEvent, TenantSubscription
    from app.modules.users.models import User

    uid = "trial-grant-user-0001"
    user = User(
        id=uid,
        email="trial@sayvors.com",
        first_name="T",
        last_name="R",
        password_hash="x",
    )
    db.add(user)
    await db.commit()

    assert await billing_service.grant_trial_credit(user, db) is True
    await db.commit()
    assert await billing_service.grant_trial_credit(user, db) is False
    await db.commit()

    row = await db.get(User, uid)
    assert row.plan == "free-trial"
    assert row.ai_credit_cents == 1000
    events = (
        await db.execute(
            select(BillingEvent).where(BillingEvent.tenant_id == uid)
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].idempotency_key == f"trial:{uid}"
    sub = (
        await db.execute(
            select(TenantSubscription).where(TenantSubscription.tenant_id == uid)
        )
    ).scalar_one()
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_tenant_billing_surfaces_what_used_the_credit(db):
    from app.modules.admin.service import get_tenant_billing
    from app.modules.billing.models import BillingEvent
    from app.modules.llm.models import LLMUsageEvent
    from app.modules.users.models import User

    uid = "billing-purpose-user-0001"
    db.add(User(id=uid, email="purpose@sayvors.com", first_name="P",
                last_name="U", password_hash="x", plan="free-trial",
                ai_credit_cents=999))
    event = BillingEvent(
        id="billing-purpose-event-0001",
        tenant_id=uid,
        kind="ai_usage",
        status="settled",
        amount_cents=-1,
        reserved_cents=5,
        balance_after_cents=999,
        model_id="groq:qwen",
    )
    db.add(event)
    db.add(LLMUsageEvent(
        id="billing-purpose-usage-0001",
        tenant_id=uid,
        provider="groq",
        model_id="groq:qwen",
        api_model="qwen",
        purpose="analytics.enrichment",
        ledger_id=event.id,
        cost_cents=1,
        status="ok",
    ))
    await db.commit()

    billing = await get_tenant_billing(db, uid)
    row = next(e for e in billing["ledger"] if e["id"] == event.id)
    assert row["purpose"] == "analytics.enrichment"
    assert row["model_id"] == "groq:qwen"

    tenant_billing = await get_tenant_billing(db, uid, include_model=False)
    tenant_row = next(
        e for e in tenant_billing["ledger"] if e["id"] == event.id
    )
    assert tenant_row["purpose"] == "analytics.enrichment"
    assert "model_id" not in tenant_row


@pytest.mark.asyncio
async def test_tenant_billing_paginates_and_sorts_the_ledger(db):
    from datetime import datetime, timedelta, timezone

    from app.modules.admin.service import get_tenant_billing
    from app.modules.billing.models import BillingEvent
    from app.modules.users.models import User

    uid = "billing-page-user-0001"
    db.add(User(id=uid, email="paging@sayvors.com", first_name="P",
                last_name="U", password_hash="x", plan="free-trial",
                ai_credit_cents=985))
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    amounts = [-5, -1, -9, 1000]
    for i, cents in enumerate(amounts):
        db.add(BillingEvent(
            id=f"billing-page-event-{i:04d}",
            tenant_id=uid,
            kind="ai_usage" if cents < 0 else "plan_grant",
            status="settled",
            amount_cents=cents,
            created_at=base + timedelta(days=i),
        ))
    await db.commit()

    def amounts_of(page: dict) -> list[int]:
        return [row["amount_cents"] for row in page["ledger"]]

    newest = await get_tenant_billing(db, uid, limit=2, offset=0, sort="newest")
    assert newest["total"] == 4
    assert amounts_of(newest) == [1000, -9]

    newest_page_2 = await get_tenant_billing(db, uid, limit=2, offset=2, sort="newest")
    assert newest_page_2["total"] == 4
    assert amounts_of(newest_page_2) == [-1, -5]

    oldest = await get_tenant_billing(db, uid, limit=2, offset=0, sort="oldest")
    assert amounts_of(oldest) == [-5, -1]

    high = await get_tenant_billing(db, uid, limit=2, offset=0, sort="cost_high")
    assert amounts_of(high) == [-9, -5]

    # Grants are not spend, so they stay after every debit in both cost views.
    low = await get_tenant_billing(db, uid, limit=2, offset=0, sort="cost_low")
    assert amounts_of(low) == [-1, -5]
    low_page_2 = await get_tenant_billing(db, uid, limit=2, offset=2, sort="cost_low")
    assert amounts_of(low_page_2) == [-9, 1000]

    with pytest.raises(ValueError):
        await get_tenant_billing(db, uid, sort="random")


@pytest.mark.asyncio
async def test_ledger_endpoint_forwards_pagination_and_sort(client, db, user_id):
    from app.modules.billing.models import BillingEvent
    from app.modules.users.models import User

    db.add(User(id=user_id, email="ledger-api@sayvors.com", first_name="L",
                last_name="A", password_hash="x", plan="free-trial",
                ai_credit_cents=994))
    for i, cents in enumerate([-1, -6, -3]):
        db.add(BillingEvent(
            id=f"ledger-api-event-{i:04d}",
            tenant_id=user_id,
            kind="ai_usage",
            status="settled",
            amount_cents=cents,
            model_id="groq:qwen",
        ))
    await db.commit()

    r = client.get("/api/v1/billing/ledger?limit=2&offset=0&sort=cost_high")
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["total"] == 3
    assert [row["amount_cents"] for row in body["ledger"]] == [-6, -3]
    # The tenant call must never expose the provider/model.
    assert "model_id" not in body["ledger"][0]

    page2 = client.get("/api/v1/billing/ledger?limit=2&offset=2&sort=cost_high")
    assert page2.status_code == 200
    assert [row["amount_cents"] for row in page2.json()["ledger"]] == [-1]
    assert page2.json()["total"] == 3

    assert client.get("/api/v1/billing/ledger?sort=bogus").status_code == 422
    assert client.get("/api/v1/billing/ledger?limit=500").status_code == 422


@pytest.mark.asyncio
async def test_admin_credit_topup_works_for_free_trial_and_enterprise(client, db, user_id, _allow_admin_auth):
    """Admins can add credit without changing the tenant's plan."""
    from app.modules.billing.models import BillingEvent
    from app.modules.users.models import User
    from app.security import create_admin_token

    db.add(User(id=user_id, email="topup@sayvors.com", first_name="T",
                last_name="U", password_hash="x", plan="free-trial",
                ai_credit_cents=1000))
    db.add(BillingEvent(
        id="topup-trial-grant",
        tenant_id=user_id,
        kind="plan_grant",
        status="posted",
        amount_cents=1000,
        balance_after_cents=1000,
        idempotency_key="trial:topup-test",
    ))
    await db.commit()
    headers = {"Authorization": f"Bearer {create_admin_token()}"}

    r = client.post(
        f"/api/v1/admin/tenants/{user_id}/credit",
        json={"amount_cents": 5000, "note": "goodwill", "idempotency_key": "topup-1"},
        headers=headers,
    )
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["balance_cents"] == 6000
    assert body["granted_cents"] == 5000
    assert body["duplicate"] is False
    assert body["plan"] == "free-trial"

    # Same key: no second grant, same balance.
    repeat = client.post(
        f"/api/v1/admin/tenants/{user_id}/credit",
        json={"amount_cents": 5000, "idempotency_key": "topup-1"},
        headers=headers,
    )
    assert repeat.status_code == 200
    assert repeat.json()["balance_cents"] == 6000
    assert repeat.json()["granted_cents"] == 0
    assert repeat.json()["duplicate"] is True

    # Enterprise is still a tenant; a top-up must not be blocked by the
    # legacy free/pro-only plan grant.
    user = await db.get(User, user_id)
    user.plan = "enterprise"
    await db.commit()
    ent = client.post(
        f"/api/v1/admin/tenants/{user_id}/credit",
        json={"amount_cents": 2500, "idempotency_key": "topup-2"},
        headers=headers,
    )
    assert ent.status_code == 200
    assert ent.json()["balance_cents"] == 8500
    assert ent.json()["plan"] == "enterprise"

    bad = client.post(
        f"/api/v1/admin/tenants/{user_id}/credit",
        json={"amount_cents": 0},
        headers=headers,
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_grant_plan_bundles_pro_credits(db):
    """First Pro grant → plan=pro + $20 bundled; ledger row; Redis synced."""
    from app.modules.billing import service as billing_service
    from app.modules.users.models import User

    uid = "budget-grant-user-0001"
    db.add(User(id=uid, email="grant@sayvors.com", first_name="G",
                last_name="R", password_hash="x", onboarded=True))
    await db.commit()

    out = await billing_service.grant_plan(uid, "pro", 0, "test purchase", "admin", db)
    assert out["plan"] == "pro"
    assert out["balance_cents"] == 10000
    assert out["balance_dollars"] == 100.0

    row = await db.get(User, uid)
    assert row.plan == "pro"
    assert row.ai_credit_cents == 10000
    assert await get_balance(uid) == 10000

    from sqlalchemy import select
    from app.modules.billing.models import BillingEvent

    events = (await db.execute(
        select(BillingEvent).where(
            BillingEvent.tenant_id == uid,
            BillingEvent.kind == "plan_grant",
        )
    )).scalars().all()
    assert len(events) == 1
    assert events[0].amount_cents == 10000

    # Second grant on same plan + explicit top-up → credit_topup kind.
    out2 = await billing_service.grant_plan(uid, "pro", 500, "topup", "admin", db)
    assert out2["balance_cents"] == 10500


@pytest.mark.asyncio
async def test_admin_grant_endpoint_and_budget(client, db, user_id, _allow_admin_auth):
    """Admin POST /tenants/{id}/plan → 200; tenant GET /billing/budget shows it."""
    from app.modules.users.models import User
    from app.security import create_admin_token

    db.add(User(id=user_id, email="w@sayvors.com", first_name="W",
                last_name="A", password_hash="x", onboarded=True))
    await db.commit()

    admin_headers = {"Authorization": f"Bearer {create_admin_token()}"}
    r = client.post(f"/api/v1/admin/tenants/{user_id}/plan",
                    json={"plan": "pro", "add_credit_cents": 0, "note": "bought"},
                    headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["plan"] == "pro"
    assert r.json()["balance_cents"] == 10000

    b = client.get("/api/v1/billing/budget")
    assert b.status_code == 200
    assert b.json()["plan"] == "pro"
    assert b.json()["balance_cents"] == 10000

    t = client.get(f"/api/v1/admin/tenants/{user_id}", headers=admin_headers)
    assert t.status_code == 200
    assert t.json()["plan"] == "pro"
    assert t.json()["ai_credit_cents"] == 10000

    r2 = client.post("/api/v1/admin/tenants/nonexistent/plan",
                     json={"plan": "pro"}, headers=admin_headers)
    assert r2.status_code == 404
    # NOTE: no Redis cleanup here — the test body runs on the pytest loop
    # while TestClient serves requests on its own portal loop; touching the
    # loop-bound global client from both deadlocks. The test-only balance
    # key for the fixture user is harmless to leave behind.


@pytest.mark.asyncio
async def test_cache_is_a_mirror_not_the_balance(db):
    """A poisoned cache cannot block a funded wallet; the mirror is repaired."""
    await _seed_live_wallet(db, _TENANT, 100)
    await budget.sync_balance(_TENANT, 0)

    reservation = await reserve(_TENANT)
    assert reservation.amount_cents == budget.RESERVE_CENTS
    assert await get_balance(_TENANT) == 95
    assert _CACHE[_TENANT] == 95


@pytest.mark.asyncio
async def test_reserve_uses_db_when_cache_is_missing(db):
    """A missing cache key is irrelevant: the DB wallet is authoritative."""
    await _seed_live_wallet(db, _TENANT, 12)
    _CACHE.pop(_TENANT, None)

    reservation = await reserve(_TENANT)
    assert reservation.amount_cents == budget.RESERVE_CENTS
    assert await get_balance(_TENANT) == 7
    assert _CACHE[_TENANT] == 7


@pytest.mark.asyncio
async def test_reserve_empty_wallet_never_goes_negative(db):
    await _seed_live_wallet(db, _TENANT, 0)
    with pytest.raises(BudgetExhausted):
        await reserve(_TENANT)
    assert await get_balance(_TENANT) == 0


@pytest.mark.asyncio
async def test_settle_repairs_a_missing_cache_key(db):
    """Settle commits to the DB and re-creates the mirror if it vanished."""
    await _seed_live_wallet(db, _TENANT, 100)
    reservation = await reserve(_TENANT)
    _CACHE.pop(_TENANT, None)
    await settle(reservation, 1)
    assert await get_balance(_TENANT) == 99
    assert _CACHE[_TENANT] == 99


def _wallet_user(uid: str):
    from app.modules.users.models import User

    return User(
        id=uid,
        email=f"{uid}@sayvors.com",
        first_name="W",
        last_name="T",
        password_hash="x",
        onboarded=True,
    )


@pytest.mark.asyncio
async def test_compute_balance_uses_grants_minus_charged_calls(db):
    """Grants - per-call cost; errors, voice, and pre-grant rows are excluded."""
    from datetime import datetime, timedelta, timezone

    from app.modules.billing.models import BillingEvent
    from app.modules.billing.wallet import compute_balance
    from app.modules.llm.models import LLMUsageEvent

    uid = "wallet-compute-user-0001"
    now = datetime.now(timezone.utc)
    db.add(_wallet_user(uid))
    db.add(BillingEvent(
        id="wallet-grant-0001", tenant_id=uid, kind="plan_grant",
        amount_cents=2000, balance_after_cents=2000,
        created_at=now - timedelta(days=5),
    ))
    db.add(LLMUsageEvent(
        id="wallet-usage-ok-0001", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=3000, completion_tokens=500, total_tokens=3500,
        status="ok", created_at=now - timedelta(days=4),
    ))
    db.add(LLMUsageEvent(
        id="wallet-usage-error-0001", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=1_000_000, completion_tokens=1_000_000,
        total_tokens=2_000_000, status="error",
        created_at=now - timedelta(days=3),
    ))
    db.add(LLMUsageEvent(
        id="wallet-usage-voice-0001", tenant_id=uid, provider="voice",
        model_id="voice:tts", api_model="tts", purpose="voice.tts",
        prompt_tokens=0, completion_tokens=1_000_000,
        total_tokens=1_000_000, status="ok",
        created_at=now - timedelta(days=2),
    ))
    db.add(LLMUsageEvent(
        id="wallet-usage-before-0001", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=1_000_000, completion_tokens=0,
        total_tokens=1_000_000, status="ok",
        created_at=now - timedelta(days=10),
    ))
    await db.commit()

    out = await compute_balance(uid, db)
    assert out["credits_cents"] == 2000
    assert out["spent_cents"] == 1
    assert out["calls"] == 1
    assert out["balance_cents"] == 1999
    assert out["reliable"] is True


@pytest.mark.asyncio
async def test_compute_balance_starts_at_resync_baseline(db):
    """A balance_resync baseline prevents double-counting on re-run."""
    from datetime import datetime, timedelta, timezone

    from app.modules.billing.models import BillingEvent
    from app.modules.billing.wallet import compute_balance
    from app.modules.llm.models import LLMUsageEvent

    uid = "wallet-baseline-user-0001"
    now = datetime.now(timezone.utc)
    db.add(_wallet_user(uid))
    db.add(BillingEvent(
        id="wallet-base-grant", tenant_id=uid, kind="plan_grant",
        amount_cents=2000, balance_after_cents=2000,
        created_at=now - timedelta(days=30),
    ))
    db.add(BillingEvent(
        id="wallet-base-resync", tenant_id=uid, kind="balance_resync",
        amount_cents=-500, balance_after_cents=1500,
        created_at=now - timedelta(days=2),
    ))
    db.add(BillingEvent(
        id="wallet-base-topup", tenant_id=uid, kind="credit_topup",
        amount_cents=200, balance_after_cents=1700,
        created_at=now - timedelta(days=1),
    ))
    # Spend before and after the baseline: only the row after it counts.
    db.add(LLMUsageEvent(
        id="wallet-base-old-spend", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=1_000_000, completion_tokens=0,
        total_tokens=1_000_000, status="ok",
        created_at=now - timedelta(days=3),
    ))
    db.add(LLMUsageEvent(
        id="wallet-base-new-spend", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=3000, completion_tokens=500,
        total_tokens=3500, status="ok",
        created_at=now - timedelta(hours=1),
    ))
    await db.commit()

    out = await compute_balance(uid, db)
    assert out["opening_cents"] == 1500
    assert out["credits_cents"] == 200
    assert out["spent_cents"] == 1
    assert out["balance_cents"] == 1699


@pytest.mark.asyncio
async def test_compute_balance_flags_a_retention_gap(db):
    from datetime import datetime, timedelta, timezone

    from app.modules.billing.models import BillingEvent
    from app.modules.billing.wallet import compute_balance

    uid = "wallet-old-user-0001"
    now = datetime.now(timezone.utc)
    db.add(_wallet_user(uid))
    db.add(BillingEvent(
        id="wallet-old-grant", tenant_id=uid, kind="plan_grant",
        amount_cents=2000, balance_after_cents=2000,
        created_at=now - timedelta(days=100),
    ))
    await db.commit()

    out = await compute_balance(uid, db)
    assert out["reliable"] is False
    assert out["warning"]


@pytest.mark.asyncio
async def test_grant_uses_ledger_not_a_stale_zero(db):
    """A poisoned 0 key must not let a top-up forget credits already spent."""
    from datetime import datetime, timedelta, timezone

    from app.modules.billing import service as billing_service
    from app.modules.billing.models import BillingEvent
    from app.modules.llm.models import LLMUsageEvent
    from app.modules.users.models import User

    uid = "wallet-stale-key-user-0001"
    now = datetime.now(timezone.utc)
    db.add(User(
        id=uid, email="stale@sayvors.com", first_name="S",
        last_name="K", password_hash="x", onboarded=True, plan="pro",
    ))
    db.add(BillingEvent(
        id="wallet-stale-grant", tenant_id=uid, kind="plan_grant",
        amount_cents=2000, balance_after_cents=2000,
        created_at=now - timedelta(days=5),
    ))
    db.add(LLMUsageEvent(
        id="wallet-stale-spend", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=3000, completion_tokens=500, total_tokens=3500,
        status="ok", created_at=now - timedelta(days=1),
    ))
    await db.commit()

    # Simulate the production bug: the cache exists at 0 after the old TTL.
    await budget.sync_balance(uid, 0)
    out = await billing_service.grant_plan(uid, "pro", 500, "topup", "admin", db)
    assert out["balance_cents"] == 2499
    assert await get_balance(uid) == 2499
    row = await db.get(User, uid)
    assert row.ai_credit_cents == 2499


@pytest.mark.asyncio
async def test_admin_resync_previews_and_repairs_redis_to_db(
    client, db, user_id, _allow_admin_auth
):
    """The endpoint reconciles cache drift to the DB and is idempotent."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.modules.billing.ledger import ensure_ledger_initialized
    from app.modules.billing.models import BillingEvent
    from app.modules.llm.models import LLMUsageEvent
    from app.modules.users.models import User
    from app.security import create_admin_token

    uid = user_id
    now = datetime.now(timezone.utc)
    db.add(User(
        id=uid, email="resync@sayvors.com", first_name="R",
        last_name="S", password_hash="x", onboarded=True,
    ))
    db.add(BillingEvent(
        id="wallet-admin-grant", tenant_id=uid, kind="plan_grant",
        amount_cents=2000, balance_after_cents=2000,
        created_at=now - timedelta(days=5),
    ))
    db.add(LLMUsageEvent(
        id="wallet-admin-spend", tenant_id=uid, provider="groq",
        model_id="groq:oss-120b", api_model="oss", purpose="reply",
        prompt_tokens=3000, completion_tokens=500, total_tokens=3500,
        status="ok", created_at=now - timedelta(days=1),
    ))
    await db.commit()
    # Cut over the tenant to the ledger, then poison the cache.
    assert await ensure_ledger_initialized(uid, db) == 1999
    await db.commit()
    await budget.sync_balance(uid, 0)

    headers = {"Authorization": f"Bearer {create_admin_token()}"}
    url = f"/api/v1/admin/tenants/{uid}/resync-balance"

    preview = client.post(url, json={"dry_run": True}, headers=headers)
    assert preview.status_code == 200, preview.text[:300]
    assert preview.json()["applied"] is False
    assert preview.json()["db_balance_cents"] == 1999
    assert preview.json()["redis_balance_cents"] == 0
    assert preview.json()["delta_cents"] == 1999

    applied = client.post(url, json={"dry_run": False}, headers=headers)
    assert applied.status_code == 200, applied.text[:300]
    assert applied.json()["applied"] is True
    assert applied.json()["balance_cents"] == 1999
    assert applied.json()["redis_synced"] is True
    assert _CACHE[uid] == 1999

    b = client.get("/api/v1/billing/budget")
    assert b.status_code == 200
    assert b.json()["balance_cents"] == 1999

    events = (await db.execute(
        select(BillingEvent).where(
            BillingEvent.tenant_id == uid,
            BillingEvent.kind == "balance_reconcile",
        )
    )).scalars().all()
    assert len(events) == 1
    assert events[0].amount_cents == 0
    assert events[0].balance_after_cents == 1999

    # Re-running with no drift is safe and writes no second audit row.
    again = client.post(url, json={"dry_run": False}, headers=headers)
    assert again.status_code == 200, again.text[:300]
    assert again.json()["balance_cents"] == 1999
    db.expire_all()
    events = (await db.execute(
        select(BillingEvent).where(
            BillingEvent.tenant_id == uid,
            BillingEvent.kind == "balance_reconcile",
        )
    )).scalars().all()
    assert len(events) == 1
