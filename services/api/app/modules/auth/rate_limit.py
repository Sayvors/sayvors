import time
from collections import defaultdict


# In-process fallback rate limiter when Redis is unavailable.
# Per-key sliding window stored in a dict (resets on restart, single-process only).
_fallback_store: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT_ENABLED = True


async def rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Returns True if allowed, False if rate limited.

    Uses Redis when available; falls back to an in-process dict when Redis is down.
    """
    if not RATE_LIMIT_ENABLED:
        return True

    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        now = int(time.time())
        window_start = now - window_seconds

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

        request_count = results[2]
        return request_count <= max_requests
    except Exception:
        # In-process fallback
        now = time.time()
        window_start = now - window_seconds
        entries = _fallback_store[key]
        _fallback_store[key] = [t for t in entries if t > window_start]
        _fallback_store[key].append(now)
        return len(_fallback_store[key]) <= max_requests


async def blacklist_token(jti: str, expires_in_seconds: int) -> None:
    """Add a token JTI to the blacklist in Redis."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        await redis.setex(f"bl:{jti}", expires_in_seconds, "1")
    except Exception:
        pass


async def is_token_blacklisted(jti: str) -> bool:
    """Check if a token JTI is blacklisted. Falls back to not blacklisted if Redis unavailable."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        return await redis.exists(f"bl:{jti}")
    except Exception:
        return False


async def store_session(user_id: str, session_id: str, data: dict, expires_in_seconds: int) -> None:
    """Store session data in Redis."""
    try:
        import json
        from ..redis.client import get_redis
        redis = await get_redis()
        await redis.setex(f"session:{user_id}:{session_id}", expires_in_seconds, json.dumps(data))
    except Exception:
        pass


async def delete_session(user_id: str, session_id: str) -> None:
    """Delete a session from Redis."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        await redis.delete(f"session:{user_id}:{session_id}")
    except Exception:
        pass


async def delete_all_sessions(user_id: str) -> None:
    """Delete all sessions for a user."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        pattern = f"session:{user_id}:*"
        keys = []
        async for key in redis.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
