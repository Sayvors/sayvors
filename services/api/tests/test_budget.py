"""P0 D1: AI credit budget — pricing, reserve/settle, provider gate, grants."""
import pytest
import pytest_asyncio

from app.modules.billing import budget
from app.modules.billing.budget import (
    BudgetExhausted,
    cost_cents,
    get_balance,
    reserve,
    settle,
    sync_balance,
)

_TENANT = "budget-test-tenant-0001"


async def _redis():
    from app.modules.redis.client import get_redis

    return await get_redis()


@pytest_asyncio.fixture
async def _clean_key():
    r = await _redis()
    await r.delete(f"ai_balance:{_TENANT}")
    yield
    await r.delete(f"ai_balance:{_TENANT}")


def test_cost_cents_math():
    assert cost_cents("groq:oss-120b", 3000, 500) == 1  # ceil(0.045 + 0.03)
    assert cost_cents("mock:anything", 1_000_000, 1_000_000) == 0
    assert cost_cents("openai:gpt-4o", 0, 0) == 0
    assert cost_cents(None, 100, 100) == 0
    assert cost_cents("weirdmodel", 2_000_000, 0) == 0  # unknown family → free
    # OpenRouter resells other families; it must not fall through to "free".
    assert cost_cents("openrouter:openai/gpt-4o-mini", 1_000_000, 0) == 150


@pytest.mark.asyncio
async def test_reserve_settle_roundtrip(_clean_key):
    await sync_balance(_TENANT, 100)
    assert await get_balance(_TENANT) == 100
    assert await reserve(_TENANT) == budget.RESERVE_CENTS
    assert await get_balance(_TENANT) == 100 - budget.RESERVE_CENTS
    await settle(_TENANT, budget.RESERVE_CENTS, 1)
    assert await get_balance(_TENANT) == 99


@pytest.mark.asyncio
async def test_reserve_empty_wallet_raises_and_refunds(_clean_key):
    await sync_balance(_TENANT, 0)
    with pytest.raises(BudgetExhausted):
        await reserve(_TENANT)
    assert await get_balance(_TENANT) == 0  # refunded, never negative


@pytest.mark.asyncio
async def test_provider_complete_gated(monkeypatch, _clean_key):
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

    await sync_balance(_TENANT, 0)
    with pytest.raises(ProviderError) as exc:
        await p.complete(req)
    assert exc.value.status_code == 402
    assert p.calls == 0

    await sync_balance(_TENANT, 10_000)
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
async def test_gateway_stream_reserves_meters_and_settles(monkeypatch, _clean_key):
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

    await sync_balance(_TENANT, 100)
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
    monkeypatch, _clean_key
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

    await sync_balance(_TENANT, 100)
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
    monkeypatch, _clean_key
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

    await sync_balance(_TENANT, 0)
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
    assert out["balance_cents"] == 2000
    assert out["balance_dollars"] == 20.0

    row = await db.get(User, uid)
    assert row.plan == "pro"
    assert row.ai_credit_cents == 2000
    assert await get_balance(uid) == 2000

    from sqlalchemy import select
    from app.modules.billing.models import BillingEvent

    events = (await db.execute(
        select(BillingEvent).where(BillingEvent.tenant_id == uid)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "plan_grant"
    assert events[0].amount_cents == 2000

    # Second grant on same plan + explicit top-up → credit_topup kind.
    out2 = await billing_service.grant_plan(uid, "pro", 500, "topup", "admin", db)
    assert out2["balance_cents"] == 2500

    r = await _redis()
    await r.delete(f"ai_balance:{uid}")


@pytest.mark.asyncio
async def test_admin_grant_endpoint_and_budget(client, db, user_id):
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
    assert r.json()["balance_cents"] == 2000

    b = client.get("/api/v1/billing/budget")
    assert b.status_code == 200
    assert b.json()["plan"] == "pro"
    assert b.json()["balance_cents"] == 2000

    t = client.get(f"/api/v1/admin/tenants/{user_id}", headers=admin_headers)
    assert t.status_code == 200
    assert t.json()["plan"] == "pro"
    assert t.json()["ai_credit_cents"] == 2000

    r2 = client.post("/api/v1/admin/tenants/nonexistent/plan",
                     json={"plan": "pro"}, headers=admin_headers)
    assert r2.status_code == 404
    # NOTE: no Redis cleanup here — the test body runs on the pytest loop
    # while TestClient serves requests on its own portal loop; touching the
    # loop-bound global client from both deadlocks. The test-only balance
    # key for the fixture user is harmless to leave behind.
