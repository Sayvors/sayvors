"""LLM metering: template records events, aggregations add up."""
import asyncio

import pytest
import pytest_asyncio

from app.modules.llm import usage as usage_mod
from app.modules.llm.models import LLMUsageEvent
from app.modules.llm.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderError,
)


class _FakeProvider(LLMProvider):
    def __init__(self, usage=None, fail=False):
        self._usage = usage or LLMUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        self._fail = fail

    def name(self) -> str:
        return "fake"

    async def _complete(self, req: LLMRequest) -> LLMResponse:
        if self._fail:
            raise ProviderError("fake", "boom", 502)
        return LLMResponse(content="hi", provider="fake", model="fake-1", usage=self._usage)

    async def stream(self, req: LLMRequest):
        yield "hi"


@pytest_asyncio.fixture
async def usage_factory(db, monkeypatch):
    """Route metering inserts into the test DB."""
    from conftest import TEST_SESSION

    monkeypatch.setattr(usage_mod, "_session_factory", TEST_SESSION)
    return TEST_SESSION


def _req(**kw):
    base = dict(model="fake-1", messages=[LLMMessage(role="user", content="hi")],
                tenant_id="t1", model_id="fake:fake-1", purpose="test.ping")
    base.update(kw)
    return LLMRequest(**base)


async def _drain():
    await asyncio.sleep(0.05)


async def _flush(timeout: float = 10.0):
    """Await all pending metering inserts (deterministic, no sleep-guessing)."""
    import time

    start = time.monotonic()
    while usage_mod._pending and time.monotonic() - start < timeout:
        pending = list(usage_mod._pending)
        if not pending:
            return
        await asyncio.wait(pending, timeout=timeout)
    await asyncio.sleep(0)


async def _events(db):
    from sqlalchemy import select

    return (await db.execute(select(LLMUsageEvent))).scalars().all()


async def test_complete_records_event(engine, db, usage_factory):
    p = _FakeProvider()
    resp = await p.complete(_req())
    assert resp.content == "hi"
    await _flush()
    rows = await _events(db)
    assert len(rows) == 1
    e = rows[0]
    assert e.tenant_id == "t1"
    assert e.provider == "fake"
    assert e.model_id == "fake:fake-1"
    assert e.api_model == "fake-1"
    assert e.purpose == "test.ping"
    assert (e.prompt_tokens, e.completion_tokens, e.total_tokens) == (10, 20, 30)
    assert e.status == "ok"
    assert e.latency_ms >= 0


async def test_complete_error_records_and_reraises(engine, db, usage_factory):
    p = _FakeProvider(fail=True)
    with pytest.raises(ProviderError):
        await p.complete(_req())
    await _flush()
    rows = await _events(db)
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert "boom" in (rows[0].error or "")
    assert rows[0].total_tokens == 0


async def test_record_without_loop_is_silent():
    # No running loop here (sync test) — must not raise.
    usage_mod.record_usage_event(_req(), None, 5, status="error", error="x")


async def test_tenant_summary_math(engine, db, usage_factory):
    from app.modules.llm.usage import get_tenant_summary

    db.add_all([
        LLMUsageEvent(tenant_id="t1", provider="groq", model_id="groq:oss-120b",
                      api_model="openai/gpt-oss-120b", purpose="review_engine.generate",
                      prompt_tokens=100, completion_tokens=50, total_tokens=150, latency_ms=1000),
        LLMUsageEvent(tenant_id="t1", provider="groq", model_id="groq:oss-120b",
                      api_model="openai/gpt-oss-120b", purpose="review_engine.analysis",
                      prompt_tokens=200, completion_tokens=100, total_tokens=300, latency_ms=2000),
        LLMUsageEvent(tenant_id="t2", provider="gemini", model_id="gemini:x",
                      api_model="x", purpose="chat.message",
                      prompt_tokens=10, completion_tokens=10, total_tokens=20, latency_ms=500),
    ])
    await db.commit()

    s = await get_tenant_summary(db, "t1")
    assert s["totals"]["calls"] == 2
    assert s["totals"]["total_tokens"] == 450
    assert s["totals"]["prompt_tokens"] == 300
    assert s["totals"]["avg_latency_ms"] == 1500
    assert len(s["by_model"]) == 1 and s["by_model"][0]["model"] == "groq:oss-120b"
    assert {p["purpose"] for p in s["by_purpose"]} == {"review_engine.generate", "review_engine.analysis"}
    assert len(s["daily"]) == 1 and s["daily"][0]["total_tokens"] == 450


async def test_admin_overview_math(engine, db, usage_factory):
    from app.modules.llm.usage import get_admin_overview
    from app.modules.users.models import User

    db.add(User(id="t1", email="a@x.com", first_name="A", last_name="B",
               password_hash="x", onboarded=True))
    db.add(LLMUsageEvent(tenant_id="t1", provider="groq", model_id="groq:oss-120b",
                         api_model="y", purpose="p", total_tokens=100, latency_ms=100))
    db.add(LLMUsageEvent(tenant_id=None, provider="groq", model_id="groq:oss-120b",
                         api_model="y", purpose="admin.test", total_tokens=50, latency_ms=50))
    await db.commit()

    o = await get_admin_overview(db)
    assert o["totals"]["calls"] == 2
    assert o["totals"]["total_tokens"] == 150
    assert o["totals"]["active_tenants"] == 1
    row = next(r for r in o["per_tenant"] if r["tenant_id"] == "t1")
    assert row["email"] == "a@x.com" and row["total_tokens"] == 100
    assert len(o["daily"]) == 1 and o["daily"][0]["total_tokens"] == 150


async def test_usage_summary_endpoint(client, db, user_id, usage_factory):
    db.add(LLMUsageEvent(tenant_id=user_id, provider="groq", model_id="groq:oss-120b",
                         api_model="y", purpose="review_engine.generate",
                         prompt_tokens=10, completion_tokens=5, total_tokens=15, latency_ms=200))
    await db.commit()
    res = client.get("/api/v1/llm/usage/summary?days=30", headers={"host": "localhost"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["totals"]["total_tokens"] == 15
    assert data["by_model"][0]["model"] == "groq:oss-120b"
