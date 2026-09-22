"""AI credit budget: pre-authorize + settle per LLM call (D1 enforcement).

How it works
------------
Every LLM completion spends USD cents from the tenant's AI credit balance:

1. BEFORE the provider is called, a flat ``RESERVE_CENTS`` pre-authorization
   is atomically decremented from ``ai_balance:{tenant}`` in Redis. If the
   balance would go negative the reservation is refunded and
   :class:`BudgetExhausted` is raised — the provider is never called, so an
   empty wallet cannot burn money.
2. AFTER the call, the real cost (actual tokens × :data:`TOKEN_PRICES`) is
   computed and the difference (reserve − actual) is credited back.

The live balance lives in Redis (atomic, no DB session needed inside the
provider hot path). The DB columns (``users.ai_credit_cents`` + the
``billing_events`` ledger) are the top-up source of truth — grants sync the
Redis key via :func:`sync_balance`.

Redis-down policy: FAIL OPEN with a loud log. Redis is internal
infrastructure the tenant cannot take down themselves; refusing all AI
during a Redis blip would be an availability outage, while the spend is
still recorded afterwards in ``llm_usage_events`` for reconciliation.

Free plan: no grant → balance 0 → every gated call raises 402 immediately.
System calls pass ``tenant_id=None`` and are never gated.
"""
import logging
import math

logger = logging.getLogger(__name__)

# Flat pre-authorization per LLM call (cents). Covers a typical grounded
# reply (~3k prompt + ~500 completion tokens on a budget model); the
# difference to the real cost is settled afterwards.
RESERVE_CENTS = 5

# Credits bundled with each plan on grant (cents). Pro = $20 of AI budget.
PLAN_INCLUDED_CENTS = {"free": 0, "pro": 2000}

# Conservative USD cents per 1M tokens: (prompt, completion), keyed by the
# model-id family prefix (the part before ":"). Deliberately above list
# price — headroom for price moves plus margin; admin tunes per model later.
TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "groq": (15.0, 60.0),
    "openai": (150.0, 600.0),
    "anthropic": (300.0, 1500.0),
    "google": (30.0, 120.0),
    "gemini": (30.0, 120.0),
    "mistral": (50.0, 150.0),
    "ollama": (0.0, 0.0),
    "local": (0.0, 0.0),
    "mock": (0.0, 0.0),
    "unknown": (0.0, 0.0),
}


class BudgetExhausted(Exception):
    """Raised before any provider call when the wallet cannot cover it."""

    status_code = 402

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(
            "AI credit balance exhausted. Top up your plan to keep using AI features."
        )


def _key(tenant_id: str) -> str:
    return f"ai_balance:{tenant_id}"


def _family(model_id: str | None) -> str:
    if model_id and ":" in model_id:
        return model_id.split(":", 1)[0].lower()
    return "unknown"


def cost_cents(model_id: str | None, prompt_tokens: int, completion_tokens: int) -> int:
    """Real cost of a call in USD cents (rounded up, never negative)."""
    prompt_p, completion_p = TOKEN_PRICES.get(_family(model_id), TOKEN_PRICES["unknown"])
    total = (max(0, prompt_tokens) / 1_000_000) * prompt_p
    total += (max(0, completion_tokens) / 1_000_000) * completion_p
    return max(0, math.ceil(total))


async def get_balance(tenant_id: str) -> int | None:
    """Live Redis balance, or None when unknown (fail-open upstream)."""
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        raw = await redis.get(_key(tenant_id))
        return int(raw) if raw is not None else None
    except Exception as e:
        logger.error("AI budget balance check failed (fail-open): %s", e)
        return None


async def sync_balance(tenant_id: str, cents: int) -> None:
    """Overwrite the live balance (called on every grant/topup/adjust)."""
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        await redis.set(_key(tenant_id), int(cents))
    except Exception as e:
        logger.error("AI budget sync failed for %s (DB remains source of truth): %s",
                     tenant_id, e)


async def reserve(tenant_id: str, cents: int = RESERVE_CENTS) -> int | None:
    """Atomically pre-authorize ``cents``. Returns the reserved amount on
    success, None when Redis is down (fail-open), or raises BudgetExhausted."""
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        new_balance = await redis.decrby(_key(tenant_id), int(cents))
        if new_balance < 0:
            await redis.incrby(_key(tenant_id), int(cents))  # refund
            raise BudgetExhausted(tenant_id)
        return int(cents)
    except BudgetExhausted:
        raise
    except Exception as e:
        logger.error("AI budget reserve failed (fail-open, spend still metered): %s", e)
        return None


async def settle(tenant_id: str, reserved_cents: int, actual_cents: int) -> None:
    """Credit back (reserve − actual). Never raises — metering must not
    break generation."""
    try:
        delta = int(reserved_cents) - int(actual_cents)
        if delta == 0:
            return
        from ..redis.client import get_redis

        redis = await get_redis()
        await redis.incrby(_key(tenant_id), delta)
    except Exception as e:
        logger.warning("AI budget settle failed (reconcile from usage events): %s", e)
