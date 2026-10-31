"""The billable rate card: what a token and a voice minute cost.

Before this, LLM rates were a hardcoded provider pass-through dict and voice
was not billed at all. `/api/v1/admin/pricing` now exposes every unit, and the
in-process cache powers the sync cost functions used in the provider path.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings
from app.modules.billing import pricing

TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=_HOST,
    )
    assert r.status_code == 200, r.text
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


def test_llm_defaults_match_the_old_pass_through_table():
    """An empty rate card must price exactly as before the migration."""
    assert pricing.llm_cost_cents("groq:oss-120b", 3000, 500) == 1
    assert pricing.llm_cost_cents("mock:anything", 1_000_000, 1_000_000) == 0
    assert pricing.llm_cost_cents("openrouter:openai/gpt-4o-mini", 1_000_000, 0) == 150


def test_voice_is_free_until_a_rate_is_set():
    assert pricing.asr_cost_cents(60_000) == 0
    assert pricing.tts_cost_cents(1000) == 0


@pytest.mark.asyncio
async def test_admin_can_change_a_llm_rate_and_it_applies_immediately(db):
    before = pricing.llm_cost_cents("groq:oss-120b", 1_000_000, 0)
    assert before == 15

    await pricing.save_rate(db, pricing.LLM_INPUT, "groq", 100.0)

    assert pricing.rate(pricing.LLM_INPUT, "groq") == 100.0
    assert pricing.llm_cost_cents("groq:oss-120b", 1_000_000, 0) == 100


@pytest.mark.asyncio
async def test_asr_rate_is_per_minute_and_rounds_up(db):
    await pricing.save_rate(db, pricing.ASR_MINUTE, "default", 10.0)

    assert pricing.asr_cost_cents(60_000) == 10
    assert pricing.asr_cost_cents(30_000) == 5
    assert pricing.asr_cost_cents(1) == 1, "any started minute rounds up"
    assert pricing.asr_cost_cents(0) == 0


@pytest.mark.asyncio
async def test_tts_rate_is_per_thousand_characters(db):
    await pricing.save_rate(db, pricing.TTS_KCHAR, "default", 3.0)

    assert pricing.tts_cost_cents(1000) == 3
    assert pricing.tts_cost_cents(1500) == 5
    assert pricing.tts_cost_cents(0) == 0


@pytest.mark.asyncio
async def test_negative_and_unknown_rates_are_rejected(db):
    with pytest.raises(ValueError):
        await pricing.save_rate(db, pricing.ASR_MINUTE, "default", -1)
    with pytest.raises(ValueError):
        await pricing.save_rate(db, "nonsense", "default", 1)
    with pytest.raises(ValueError):
        await pricing.save_rate(db, pricing.LLM_INPUT, "not-a-family", 1)


def test_admin_pricing_list_shape(client, admin_headers):
    r = client.get("/api/v1/admin/pricing", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    kinds = {row["kind"] for row in rows}
    assert kinds == {"llm_input", "llm_output", "asr_minute", "tts_kchar"}

    voice = next(r for r in rows if r["kind"] == "asr_minute")
    assert voice["key"] == "default"
    assert voice["unit"] == "cents per audio minute"
    assert voice["unit_price_cents"] == 0
    assert voice["overridden"] is False

    groq = next(r for r in rows if r["kind"] == "llm_input" and r["key"] == "groq")
    assert groq["unit_price_cents"] == 15
    assert groq["default_cents"] == 15


def test_admin_can_put_a_rate(client, admin_headers):
    r = client.put(
        "/api/v1/admin/pricing",
        headers=admin_headers,
        json={"kind": "asr_minute", "key": "default", "unit_price_cents": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["unit_price_cents"] == 2

    listed = client.get("/api/v1/admin/pricing", headers=admin_headers).json()
    voice = next(r for r in listed if r["kind"] == "asr_minute")
    assert voice["unit_price_cents"] == 2
    assert voice["overridden"] is True


def test_admin_rejects_an_unknown_kind(client, admin_headers):
    r = client.put(
        "/api/v1/admin/pricing",
        headers=admin_headers,
        json={"kind": "carrier_pigeon", "key": "default", "unit_price_cents": 1},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_charge_voice_is_a_noop_at_zero_and_uses_the_ledger_above_it(
    monkeypatch,
):
    calls: list[tuple] = []

    async def _reserve(tenant_id, cents, **kwargs):
        calls.append(("reserve", tenant_id, cents, kwargs.get("idempotency_key")))
        return "hold-1"

    async def _settle(reservation, cents, **kwargs):
        calls.append(("settle", reservation, cents))

    from app.modules.billing import ledger

    monkeypatch.setattr(ledger, "reserve", _reserve)
    monkeypatch.setattr(ledger, "settle", _settle)

    assert await pricing.charge_voice("t1", 0, purpose="asr", idempotency_key="k") == 0
    assert calls == []

    assert await pricing.charge_voice(
        "t1", 7, purpose="asr", idempotency_key="asr:job-1"
    ) == 7
    assert calls == [
        ("reserve", "t1", 7, "asr:job-1"),
        ("settle", "hold-1", 7),
    ]
