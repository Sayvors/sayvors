"""Provider rate-limit pacer — Redis token bucket per provider.

Prevents 429 responses from burning retry attempts. When a provider
returns 429, the job moves to `blocked` (not `retrying`) and the
reaper releases it after the Retry-After window.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Default rates (requests per second). Override via settings if needed.
DEFAULT_RATES: dict[str, float] = {
    "meta": 10.0,
    "localith": 5.0,
    "google": 5.0,
}


async def acquire(provider: str, rate: float | None = None) -> bool:
    """Try to acquire a token for ``provider``. Returns True if allowed.

    Uses a Redis token bucket. If Redis is down, fail open (allow).
    """
    rps = rate or DEFAULT_RATES.get(provider, 10.0)
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        key = f"pacer:{provider}"
        # Simple sliding window: INCR with TTL.
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 1)  # 1-second window
        if count <= int(rps):
            return True
        # Over limit — decrement (we didn't actually use it)
        await redis.decr(key)
        return False
    except Exception:
        # Redis down — fail open
        return True


async def on_rate_limited(provider: str, retry_after: int = 60) -> None:
    """Called when a provider returns 429. Sets a cooldown key."""
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        key = f"pacer:cooldown:{provider}"
        await redis.set(key, "1", ex=retry_after)
    except Exception:
        pass


async def is_cooled_down(provider: str) -> int:
    """Returns remaining cooldown seconds, or 0 if not cooled down."""
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        key = f"pacer:cooldown:{provider}"
        ttl = await redis.ttl(key)
        return max(0, ttl) if ttl and ttl > 0 else 0
    except Exception:
        return 0
