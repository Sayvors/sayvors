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
# Sayvors Credits accounting. Stored in the same rate card so the admin can
# change the formula without a deploy. 1 SC = 1/sc_per_usd dollars.
SC_PER_USD = "sc_per_usd"
MARGIN_BP = "margin_bp"
INFRA_MICRO_USD = "infra_cost_micro_usd"

KINDS: tuple[str, ...] = (
    LLM_INPUT, LLM_OUTPUT, ASR_MINUTE, TTS_KCHAR,
    SC_PER_USD, MARGIN_BP, INFRA_MICRO_USD,
)

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
    SC_PER_USD: {
        "label": "Sayvors Credits rate",
        "unit": "credits per $1 (default 1,000)",
    },
    MARGIN_BP: {
        "label": "Gross margin",
        "unit": "basis points (6000 = 60%)",
    },
    INFRA_MICRO_USD: {
        "label": "Infrastructure cost",
        "unit": "micro-USD added to every billable call",
    },
}

# Provider families the LLM meter knows. Keep in sync with budget._family.
LLM_FAMILIES: tuple[str, ...] = (
    "groq", "openai", "openrouter", "anthropic", "google", "gemini",
    "mistral", "zhipu", "zhipu-coding", "ollama", "local", "mock", "unknown",
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
    (LLM_INPUT, "zhipu"): 60.0,
    (LLM_OUTPUT, "zhipu"): 220.0,
    (LLM_INPUT, "zhipu-coding"): 60.0,
    (LLM_OUTPUT, "zhipu-coding"): 220.0,
    (LLM_INPUT, "ollama"): 0.0,
    (LLM_OUTPUT, "ollama"): 0.0,
    (LLM_INPUT, "local"): 0.0,
    (LLM_OUTPUT, "local"): 0.0,
    (LLM_INPUT, "mock"): 0.0,
    (LLM_OUTPUT, "mock"): 0.0,
    (LLM_INPUT, "unknown"): 0.0,
    (LLM_OUTPUT, "unknown"): 0.0,
    # Sayvors Credits v1.0: 1,000 SC = $1 and a 60% gross margin (2.5x).
    (SC_PER_USD, "rate"): 1000.0,
    (MARGIN_BP, "default"): 6000.0,
    (INFRA_MICRO_USD, "call"): 0.0,
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
    """Retail cents for one call, including the target margin.

    ``pprovider`` cost is exact micro-USD; the multiplier and the per-call
    infrastructure cost are applied before the single cent rounding, so the
    ledger can never charge less than the delivery cost.
    """
    micro = llm_cost_micro_usd(model_id, prompt_tokens, completion_tokens)
    charged = charge_micro_usd(micro)
    return max(0, math.ceil(charged / 10_000))


def llm_provider_cost_micro_usd(
    model_id: str | None, prompt_tokens: int, completion_tokens: int
) -> int:
    """Provider-side cost of the tokens, in micro-USD (1e-6 dollars).

    Rate cards are cents per 1M tokens, so micro-USD per token is
    ``cents / 100``.
    """
    family = _family(model_id)
    prompt = max(0, prompt_tokens) * rate(LLM_INPUT, family) / 100
    completion = max(0, completion_tokens) * rate(LLM_OUTPUT, family) / 100
    return int(math.ceil(prompt + completion))


def llm_cost_micro_usd(
    model_id: str | None, prompt_tokens: int, completion_tokens: int
) -> int:
    """Delivery cost: provider tokens plus attributable infrastructure."""
    return llm_provider_cost_micro_usd(
        model_id, prompt_tokens, completion_tokens
    ) + infra_cost_micro_usd()


def infra_cost_micro_usd() -> int:
    return max(0, int(round(rate(INFRA_MICRO_USD, "call"))))


def sc_per_usd() -> int:
    return max(1, int(round(rate(SC_PER_USD, "rate"))))


def margin_bp() -> int:
    """Target gross margin in basis points, clamped to a sane range."""
    value = int(round(rate(MARGIN_BP, "default")))
    return min(9_500, max(0, value))


def cost_multiplier_bp() -> int:
    """Cost -> price multiplier in basis points (60% margin -> 25000)."""
    margin = margin_bp()
    denominator = 10_000 - margin
    if denominator <= 0:
        return 25_000
    return int(round(10_000 * 10_000 / denominator))


def charge_micro_usd(delivery_cost_micro_usd: int) -> int:
    """Retail price in micro-USD, rounded once per call (banker-free)."""
    cost = max(0, int(delivery_cost_micro_usd))
    return (cost * cost_multiplier_bp() + 9_999) // 10_000


def credits_micro_for(delivery_cost_micro_usd: int) -> int:
    """Customer-facing Sayvors Credits in micro-SC (1 SC = 1e6 micro-SC).

    micro-SC = charge_micro_usd * sc_per_usd because 1 SC = $1/sc_per_usd.
    Integer math keeps the ledger exact; display rounds only at the edge.
    """
    return charge_micro_usd(delivery_cost_micro_usd) * sc_per_usd()


def credits_for_cents(cents: int) -> float:
    """Display helper: an amount charged in cents expressed in credits."""
    return (max(0, int(cents)) / 100) * sc_per_usd()


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
        if kind in (LLM_INPUT, LLM_OUTPUT):
            keys = LLM_FAMILIES
        elif kind == SC_PER_USD:
            keys = ("rate",)
        elif kind == INFRA_MICRO_USD:
            keys = ("call",)
        else:
            keys = ("default",)
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
    if kind == SC_PER_USD:
        key = "rate"
    elif kind == INFRA_MICRO_USD:
        key = "call"
    elif kind not in (LLM_INPUT, LLM_OUTPUT):
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
