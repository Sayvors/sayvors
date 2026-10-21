"""AI credit wallet: atomic Redis counter + cold-path reconciliation (D1).

How it works
------------
Every LLM completion spends USD cents from the tenant's AI credit balance:

1. BEFORE the provider is called, a flat ``RESERVE_CENTS`` pre-authorization
   is atomically checked and decremented from ``ai_balance:{tenant}`` in
   Redis. If the balance cannot cover it, :class:`BudgetExhausted` is raised
   and the provider is never called.
2. AFTER the call, the real cost (actual tokens × :data:`TOKEN_PRICES`) is
   computed and the difference (reserve − actual) is applied.

The live balance lives in Redis (atomic, no DB session needed inside the
provider hot path). Balance keys deliberately have **no TTL**; the old 24h
TTL made a wallet disappear and a subsequent ``DECRBY`` create a permanent
``0`` key. If a key is missing anyway (Redis restart, eviction, flush), the
cold path in :mod:`billing.wallet` reconstructs it from the grant ledger and
metered usage, then seeds it with ``SET NX``.

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
    # OpenRouter resells every family at its own price. Use the middle
    # OpenAI-compatible rate rather than the zero "unknown" fallback, so a
    # cheap model is slightly overcharged and an expensive one is not free.
    "openrouter": (150.0, 600.0),
    "anthropic": (300.0, 1500.0),
    "google": (30.0, 120.0),
    "gemini": (30.0, 120.0),
    "mistral": (50.0, 150.0),
    "ollama": (0.0, 0.0),
    "local": (0.0, 0.0),
    "mock": (0.0, 0.0),
    "unknown": (0.0, 0.0),
}

# Redis Lua keeps the check-and-decrement atomic. Return values:
#   -1 key missing (caller may rehydrate)
#   -2 insufficient balance
#   -3 malformed value (treat as an infrastructure error, fail open)
#   >=0 the balance after the reservation
_RESERVE_LUA = """
local value = redis.call('GET', KEYS[1])
if not value then return -1 end
local balance = tonumber(value)
local amount = tonumber(ARGV[1])
if not balance or not amount then return -3 end
if balance < amount then return -2 end
redis.call('DECRBY', KEYS[1], amount)
redis.call('PERSIST', KEYS[1])
return balance - amount
"""

# Settle must not create a key. If the key vanished between reserve and
# settle, the spend is already in llm_usage_events and the next cold-path
# rehydration will count it; creating a partial key here would corrupt it.
_SETTLE_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -1 end
local value = redis.call('INCRBY', KEYS[1], ARGV[1])
redis.call('PERSIST', KEYS[1])
return value
"""


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
    """Live Redis balance, or None when unknown (fail-open upstream).

    Also clears any legacy TTL left on a key by the pre-hotfix code. PERSIST
    is a no-op when the key already has no expiry.
    """
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        key = _key(tenant_id)
        raw = await redis.get(key)
        if raw is None:
            return None
        try:
            await redis.persist(key)
        except Exception as e:  # a failed PERSIST must not hide a valid balance
            logger.warning("AI budget PERSIST failed for %s: %s", tenant_id, e)
        return int(raw)
    except Exception as e:
        logger.error("AI budget balance check failed (fail-open): %s", e)
        return None


async def sync_balance(tenant_id: str, cents: int) -> bool:
    """Overwrite the live balance without a TTL.

    Returns True when Redis accepted the write. Callers that care (admin
    resync) can surface the failure; grants keep the DB ledger as fallback.
    """
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        await redis.set(_key(tenant_id), max(0, int(cents)))
        return True
    except Exception as e:
        logger.error(
            "AI budget sync failed for %s (DB remains source of truth): %s",
            tenant_id,
            e,
        )
        return False


async def seed_balance(tenant_id: str, cents: int) -> bool:
    """Set the balance only when the key is missing.

    Returns True when the key exists after the call (either this worker seeded
    it or another worker won the race). Never overwrites a newer value.
    """
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        key = _key(tenant_id)
        wrote = await redis.set(key, max(0, int(cents)), nx=True)
        if wrote:
            return True
        return bool(await redis.exists(key))
    except Exception as e:
        logger.error("AI budget seed failed for %s: %s", tenant_id, e)
        return False


async def _rehydrate_balance(tenant_id: str) -> bool:
    """Rebuild a missing Redis key from the DB.

    Uses ``seed_balance`` (SET NX) so two workers that both notice the missing
    key cannot overwrite each other's (possibly newer) seed. Returns False
    only when the DB read or Redis seed failed; a tenant with no grants seeds
    0 and returns True, which then correctly results in BudgetExhausted.
    """
    try:
        from ...database import async_session
        from .wallet import compute_balance

        async with async_session() as db:
            preview = await compute_balance(tenant_id, db)
        if preview["warning"]:
            logger.warning(
                "AI budget rehydrate for %s is approximate: %s",
                tenant_id,
                preview["warning"],
            )
        seeded = await seed_balance(tenant_id, int(preview["balance_cents"]))
        if seeded:
            logger.info(
                "AI budget rehydrated for %s: %s¢ (grants=%s, spend=%s)",
                tenant_id,
                preview["balance_cents"],
                preview["credits_cents"],
                preview["spent_cents"],
            )
        return seeded
    except Exception as e:
        logger.error(
            "AI budget rehydrate failed for %s (fail-open): %s", tenant_id, e
        )
        return False


async def reserve(tenant_id: str, cents: int = RESERVE_CENTS) -> int | None:
    """Atomically pre-authorize ``cents``.

    Returns the reserved amount on success, None when Redis/DB is down
    (fail-open), or raises BudgetExhausted when the wallet cannot cover it.
    A missing key is rehydrated once from the DB before deciding.
    """
    amount = int(cents)
    if amount <= 0:
        return 0
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        for attempt in range(2):
            result = await redis.eval(_RESERVE_LUA, 1, _key(tenant_id), amount)
            result = int(result)
            if result == -1:
                if attempt == 0 and await _rehydrate_balance(tenant_id):
                    continue
                logger.warning(
                    "AI budget key missing for %s and could not be rehydrated; "
                    "failing open",
                    tenant_id,
                )
                return None
            if result == -2:
                raise BudgetExhausted(tenant_id)
            if result < 0:
                logger.error(
                    "AI budget reserve got malformed Redis value for %s (%s); "
                    "failing open",
                    tenant_id,
                    result,
                )
                return None
            return amount
        logger.warning(
            "AI budget key still missing for %s after rehydrate; failing open",
            tenant_id,
        )
        return None
    except BudgetExhausted:
        raise
    except Exception as e:
        logger.error("AI budget reserve failed (fail-open, spend still metered): %s", e)
        return None


async def settle(tenant_id: str, reserved_cents: int, actual_cents: int) -> None:
    """Apply (reserve − actual) to the live balance. Never raises.

    A missing key is left missing on purpose: the usage row is the durable
    record, and rehydration reconstructs the full balance from it.
    """
    try:
        delta = int(reserved_cents) - int(actual_cents)
        if delta == 0:
            return
        from ..redis.client import get_redis

        redis = await get_redis()
        result = await redis.eval(_SETTLE_LUA, 1, _key(tenant_id), delta)
        if int(result) == -1:
            logger.warning(
                "AI budget settle skipped for %s: balance key disappeared; "
                "rely on usage-event reconciliation",
                tenant_id,
            )
    except Exception as e:
        logger.warning("AI budget settle failed (reconcile from usage events): %s", e)
