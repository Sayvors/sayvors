"""AI credit pricing plus the Redis mirror for the durable wallet.

PostgreSQL is the source of truth: ``users.ai_credit_cents`` is the available
balance and ``billing_events`` is the ledger. The reserve/settle implementation
lives in :mod:`billing.ledger`; the functions here keep the historical import
surface and own the best-effort Redis cache.

Redis policy
------------
The cache is written only after a DB commit. If Redis is down, reserve/settle
still work and the DB stays correct. The cache is never used to decide a
charge; it exists for dashboard compatibility and cheap reads. Keys have no
TTL (the previous 24h TTL was the original wallet-loss bug).
"""
import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ledger import Reservation, SettleResult

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


class BudgetExhausted(Exception):
    """Raised before any provider call when the wallet cannot cover it."""

    status_code = 402

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(
            "AI credit balance exhausted. Top up your plan to keep using AI features."
        )


class BudgetUnavailable(Exception):
    """The durable wallet could not be read/locked. Never call the provider."""

    status_code = 503

    def __init__(self, tenant_id: str, reason: str | None = None):
        self.tenant_id = tenant_id
        detail = f" ({reason})" if reason else ""
        super().__init__(
            "The AI credit wallet is temporarily unavailable. Try again shortly." + detail
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


async def get_cached_balance(tenant_id: str) -> int | None:
    """Raw Redis mirror, or None when the key is missing/unavailable.

    Never decide a charge from this value. The reconciler uses it only to
    report and repair drift.
    """
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        raw = await redis.get(_key(tenant_id))
        if raw is None:
            return None
        try:
            await redis.persist(_key(tenant_id))
        except Exception as e:  # a failed PERSIST must not hide a valid value
            logger.warning("AI budget PERSIST failed for %s: %s", tenant_id, e)
        return int(raw)
    except Exception as e:
        logger.warning("AI budget cache read failed for %s: %s", tenant_id, e)
        return None


async def sync_balance(tenant_id: str, cents: int) -> bool:
    """Overwrite the Redis mirror without a TTL.

    Returns True when Redis accepted the write. DB state is already committed;
    a False result is a cache warning, never a billing failure.
    """
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        # Keep the mirror byte-for-byte equal to the DB wallet, including a
        # negative overage debt. Clamping here would make the reconciler see
        # permanent drift after a real cost exceeded its hold.
        await redis.set(_key(tenant_id), int(cents))
        return True
    except Exception as e:
        logger.warning(
            "AI budget cache sync failed for %s (DB remains authoritative): %s",
            tenant_id,
            e,
        )
        return False


async def seed_balance(tenant_id: str, cents: int) -> bool:
    """Set the mirror only when it is missing (legacy/cold-start helper)."""
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        key = _key(tenant_id)
        wrote = await redis.set(key, int(cents), nx=True)
        if wrote:
            return True
        return bool(await redis.exists(key))
    except Exception as e:
        logger.warning("AI budget cache seed failed for %s: %s", tenant_id, e)
        return False


async def get_balance(tenant_id: str) -> int | None:
    """Durable available balance from PostgreSQL.

    Missing tenant returns 0 so a pre-flight check denies instead of treating
    the caller as funded. A DB failure returns the Redis mirror when possible
    (the caller's reserve still fails closed); otherwise None.
    """
    try:
        from sqlalchemy import select

        from ..users.models import User
        from .ledger import (
            OPENING_KEY_PREFIX,
            _get_session_factory,
            ensure_ledger_initialized,
        )
        from .models import BillingEvent

        async with _get_session_factory()() as db:
            user = (
                await db.execute(select(User).where(User.id == tenant_id))
            ).scalar_one_or_none()
            if user is None:
                return 0
            opening = (
                await db.execute(
                    select(BillingEvent.id).where(
                        BillingEvent.tenant_id == tenant_id,
                        BillingEvent.idempotency_key == (
                            f"{OPENING_KEY_PREFIX}{tenant_id}"
                        ),
                    )
                )
            ).scalar_one_or_none()
            if opening is not None:
                return int(user.ai_credit_cents or 0)
            balance, created = await ensure_ledger_initialized(
                tenant_id, db, allow_unreliable=True, _return_created=True
            )
            if created:
                await db.commit()
            else:
                await db.rollback()
        return int(balance)
    except Exception as e:
        logger.warning(
            "AI budget DB read failed for %s; falling back to cache: %s", tenant_id, e
        )
        return await get_cached_balance(tenant_id)


# ── Compatibility surface (implementation in billing.ledger) ─────────────


async def reserve(
    tenant_id: str,
    cents: int = RESERVE_CENTS,
    *,
    model_id: str | None = None,
    purpose: str | None = None,
    idempotency_key: str | None = None,
) -> "Reservation":
    """Pre-authorize credit against the durable wallet. See ledger.reserve."""
    from .ledger import reserve as _reserve

    return await _reserve(
        tenant_id,
        cents,
        model_id=model_id,
        purpose=purpose,
        idempotency_key=idempotency_key,
    )


async def settle(
    reservation: "Reservation | str",
    actual_cents: int,
    *,
    tenant_id: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> "SettleResult | None":
    """Finalize a hold exactly once. See ledger.settle."""
    from .ledger import settle as _settle

    return await _settle(
        reservation,
        actual_cents,
        tenant_id=tenant_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
