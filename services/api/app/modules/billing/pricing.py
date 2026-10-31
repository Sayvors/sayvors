"""The billable rate card: what one unit costs, in USD cents.

One place decides money. Before this module the LLM rate table was a dict in
``budget.py`` (hardcoded, provider pass-through) and voice was not billed at
all. Now the same questions — "what does a token cost?", "what does an audio
minute cost?" — are answered here from a code default that an admin can
override in the dashboard.

Units
-----
llm_input / llm_output : cents per 1,000,000 tokens, keyed by provider family
                         ("groq", "openai", ...), matching the model id prefix.
asr_minute             : cents per minute of audio transcribed.
tts_kchar              : cents per 1,000 characters spoken.

The rate is what the TENANT is charged (retail). Defaults for LLM are the
existing pass-through values, so nothing changes until an admin edits them.
Voice defaults to 0 = not billed, so enabling a rate is an explicit choice.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from sqlalchemy import select

from .models import PricingRate

logger = logging.getLogger(__name__)

LLM_INPUT = "llm_input"
LLM_OUTPUT = "llm_output"
ASR_MINUTE = "asr_minute"
TTS_KCHAR = "tts_kchar"

KINDS: tuple[str, ...] = (LLM_INPUT, LLM_OUTPUT, ASR_MINUTE, TTS_KCHAR)

# Human labels for the admin page. Units are stated there too, so an operator
# never has to guess what "15" means.
KIND_META: dict[str, dict[str, str]] = {
    LLM_INPUT: {
        "label": "LLM input",
        "unit": "cents per 1M prompt tokens",
    },
    LLM_OUTPUT: {
        "label": "LLM output",
        "unit": "cents per 1M completion tokens",
    },
    ASR_MINUTE: {
        "label": "Speech-to-text",
        "unit": "cents per audio minute",
    },
    TTS_KCHAR: {
        "label": "Text-to-speech",
        "unit": "cents per 1k characters",
    },
}

# Provider families the LLM meter knows. Keep in sync with budget._family.
LLM_FAMILIES: tuple[str, ...] = (
    "groq", "openai", "openrouter", "anthropic", "google", "gemini",
    "mistral", "ollama", "local", "mock", "unknown",
)

# Defaults: the pre-existing pass-through LLM table (USD cents per 1M tokens)
# and 0 for voice (not billed). (kind, key) -> cents per unit.
DEFAULTS: dict[tuple[str, str], float] = {
    (LLM_INPUT, "groq"): 15.0,
    (LLM_OUTPUT, "groq"): 60.0,
    (LLM_INPUT, "openai"): 150.0,
    (LLM_OUTPUT, "openai"): 600.0,
    # OpenRouter resells every family at its own price; the middle
    # OpenAI-compatible rate is safer than zero.
    (LLM_INPUT, "openrouter"): 150.0,
    (LLM_OUTPUT, "openrouter"): 600.0,
    (LLM_INPUT, "anthropic"): 300.0,
    (LLM_OUTPUT, "anthropic"): 1500.0,
    (LLM_INPUT, "google"): 30.0,
    (LLM_OUTPUT, "google"): 120.0,
    (LLM_INPUT, "gemini"): 30.0,
    (LLM_OUTPUT, "gemini"): 120.0,
    (LLM_INPUT, "mistral"): 50.0,
    (LLM_OUTPUT, "mistral"): 150.0,
    (LLM_INPUT, "ollama"): 0.0,
    (LLM_OUTPUT, "ollama"): 0.0,
    (LLM_INPUT, "local"): 0.0,
    (LLM_OUTPUT, "local"): 0.0,
    (LLM_INPUT, "mock"): 0.0,
    (LLM_OUTPUT, "mock"): 0.0,
    (LLM_INPUT, "unknown"): 0.0,
    (LLM_OUTPUT, "unknown"): 0.0,
    (ASR_MINUTE, "default"): 0.0,
    (TTS_KCHAR, "default"): 0.0,
}

_CACHE_TTL_SECONDS = 60.0
_rates: dict[tuple[str, str], float] = dict(DEFAULTS)
_loaded_at: float = 0.0

# Tests point this at the in-memory engine; production leaves it None.
_session_factory = None


def _family(model_id: str | None) -> str:
    if model_id and ":" in model_id:
        return model_id.split(":", 1)[0].lower()
    return "unknown"


async def _read_overrides(db=None) -> dict[tuple[str, str], float]:
    async def _query(session) -> dict[tuple[str, str], float]:
        rows = (await session.execute(select(PricingRate))).scalars().all()
        return {(r.kind, r.key): float(r.unit_price_cents) for r in rows}

    if db is not None:
        return await _query(db)
    if _session_factory is not None:
        async with _session_factory() as session:
            return await _query(session)
    from ...database import async_session

    async with async_session() as session:
        return await _query(session)


async def ensure_fresh(db=None, *, force: bool = False) -> None:
    """Refresh the in-process rate cache (bounded TTL).

    The cost functions are called from sync code deep in the provider path,
    so they cannot await a query. This refreshes the snapshot they read;
    a stale snapshot prices at the previous rate for at most one minute,
    never at zero.
    """
    global _rates, _loaded_at
    now = time.monotonic()
    if not force and _loaded_at and now - _loaded_at < _CACHE_TTL_SECONDS:
        return
    try:
        overrides = await _read_overrides(db)
    except Exception as e:  # noqa: BLE001 - billing must not stop a reply
        logger.warning("pricing rate load failed: %s", e)
        return
    merged = dict(DEFAULTS)
    for (kind, key), value in overrides.items():
        if kind in KINDS:
            merged[(kind, key)] = float(value)
    _rates = merged
    _loaded_at = now


def invalidate() -> None:
    global _loaded_at
    _loaded_at = 0.0


def rate(kind: str, key: str) -> float:
    return float(_rates.get((kind, key), DEFAULTS.get((kind, key), 0.0)))


def llm_cost_cents(
    model_id: str | None, prompt_tokens: int, completion_tokens: int
) -> int:
    family = _family(model_id)
    total = (max(0, prompt_tokens) / 1_000_000) * rate(LLM_INPUT, family)
    total += (max(0, completion_tokens) / 1_000_000) * rate(LLM_OUTPUT, family)
    return max(0, math.ceil(total))


def asr_cost_cents(duration_ms: int | None) -> int:
    minutes = max(0, int(duration_ms or 0)) / 60_000
    return max(0, math.ceil(minutes * rate(ASR_MINUTE, "default")))


def tts_cost_cents(characters: int | None) -> int:
    thousands = max(0, int(characters or 0)) / 1000
    return max(0, math.ceil(thousands * rate(TTS_KCHAR, "default")))


async def list_rates(db=None) -> list[dict[str, Any]]:
    """Every editable rate, effective value included (default or override)."""
    await ensure_fresh(db)
    overrides = await _read_overrides(db)
    out: list[dict[str, Any]] = []
    for kind in KINDS:
        meta = KIND_META[kind]
        keys = LLM_FAMILIES if kind in (LLM_INPUT, LLM_OUTPUT) else ("default",)
        for key in keys:
            effective = _rates.get((kind, key), DEFAULTS.get((kind, key), 0.0))
            out.append({
                "kind": kind,
                "key": key,
                "label": meta["label"],
                "unit": meta["unit"],
                "unit_price_cents": effective,
                "default_cents": DEFAULTS.get((kind, key), 0.0),
                "overridden": (kind, key) in overrides,
            })
    return out


async def save_rate(db, kind: str, key: str, unit_price_cents: float) -> dict[str, Any]:
    """Upsert one rate. ``unit_price_cents`` is cents per the kind's unit."""
    from datetime import datetime, timezone

    if kind not in KINDS:
        raise ValueError(f"unknown pricing kind {kind!r}")
    if unit_price_cents < 0:
        raise ValueError("a rate cannot be negative")
    if kind in (LLM_INPUT, LLM_OUTPUT) and key not in LLM_FAMILIES:
        raise ValueError(f"unknown model family {key!r}")
    if kind not in (LLM_INPUT, LLM_OUTPUT):
        key = "default"

    row = await db.get(PricingRate, (kind, key))
    if row is None:
        row = PricingRate(kind=kind, key=key)
        db.add(row)
    row.unit_price_cents = float(unit_price_cents)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await ensure_fresh(db, force=True)
    return {
        "kind": kind,
        "key": key,
        "unit_price_cents": float(unit_price_cents),
        "overridden": True,
    }


async def charge_voice(
    tenant_id: str,
    cents: int,
    *,
    purpose: str,
    idempotency_key: str,
) -> int:
    """Best-effort charge for a voice unit already consumed.

    The provider call has happened by the time we know the duration, so this
    is post-paid: an exhausted wallet is logged and the customer still gets
    the reply. Reuses the durable hold ledger (reserve → settle) so the wallet
    stays the single source of truth and a retry cannot double-charge.
    """
    amount = max(0, int(cents))
    if amount <= 0 or not tenant_id:
        return 0
    from .budget import BudgetExhausted
    from .ledger import reserve, settle

    try:
        reservation = await reserve(
            tenant_id, amount, purpose=purpose, idempotency_key=idempotency_key
        )
    except BudgetExhausted:
        logger.warning(
            "Voice charge skipped (no balance) tenant=%s amount=%d purpose=%s",
            tenant_id, amount, purpose,
        )
        return 0
    except Exception as e:  # noqa: BLE001 - never lose the reply over billing
        logger.warning("Voice charge reserve failed tenant=%s: %s", tenant_id, e)
        return 0
    try:
        await settle(reservation, amount, tenant_id=tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Voice charge settle failed tenant=%s: %s", tenant_id, e)
        return 0
    return amount
