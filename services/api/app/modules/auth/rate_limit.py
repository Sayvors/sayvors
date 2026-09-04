import logging
import time

from ...config import settings

logger = logging.getLogger(__name__)

# Auth-critical rate limiting and blacklisting FAIL CLOSED when Redis is down.
# (The old behavior silently disabled all brute-force protection at scale.)
# Set AUTH_RATE_LIMIT_FAIL_CLOSED=false only for local dev without Redis.


async def rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Returns True if allowed, False if rate limited.

    Uses a Redis sliding window (ZSET). When Redis is unavailable:
    - fail-closed mode (default): deny the request (return False) for
      auth-critical endpoints, so brute-force protection cannot be bypassed
      by simply knocking Redis over.
    - fail-open mode (dev only): allow the request.
    """
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        now = int(time.time())
        window_start = now - window_seconds

        # Unique member: sub-second precision avoids collisions within the same second
        member = f"{now}:{time.monotonic_ns()}"

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

        request_count = results[2]
        return request_count <= max_requests
    except Exception as e:
        if settings.AUTH_RATE_LIMIT_FAIL_CLOSED:
            logger.error("RATE LIMIT FAIL-CLOSED (Redis unavailable): key=%s err=%s", key, e)
            return False
        logger.warning("Rate limit fail-open (dev mode, Redis unavailable): %s", e)
        return True


async def blacklist_token(jti: str, expires_in_seconds: int) -> None:
    """Add a token JTI to the blacklist in Redis."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        await redis.setex(f"bl:{jti}", expires_in_seconds, "1")
    except Exception as e:
        # Blacklist write failure is survivable: the DB-side revoked flag is the
        # authoritative check for refresh tokens. Log loudly so it's visible.
        logger.error("Failed to blacklist jti (DB revoked flag still protects): %s", e)


async def is_token_blacklisted(jti: str) -> bool:
    """Check if a token JTI is blacklisted in Redis."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        return bool(await redis.exists(f"bl:{jti}"))
    except Exception as e:
        if settings.AUTH_RATE_LIMIT_FAIL_CLOSED:
            # Fail closed: treat as blacklisted so a Redis outage cannot
            # resurrect revoked tokens.
            logger.error("Blacklist check FAIL-CLOSED (Redis unavailable): %s", e)
            return True
        logger.warning("Blacklist check skipped (dev mode, Redis unavailable): %s", e)
        return False


# ── Sessions ─────────────────────────────────────────────
# Each user has a Set index `user_sessions:{user_id}` so deletion is
# O(sessions-of-user) instead of SCAN over the whole keyspace.


def _session_key(user_id: str, session_id: str) -> str:
    return f"session:{user_id}:{session_id}"


def _index_key(user_id: str) -> str:
    return f"user_sessions:{user_id}"


async def store_session(user_id: str, session_id: str, data: dict, expires_in_seconds: int) -> None:
    """Store session data in Redis and index it in the user's session set."""
    import json

    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        pipe = redis.pipeline()
        pipe.setex(_session_key(user_id, session_id), expires_in_seconds, json.dumps(data))
        pipe.sadd(_index_key(user_id), _session_key(user_id, session_id))
        pipe.expire(_index_key(user_id), expires_in_seconds)
        await pipe.execute()
    except Exception as e:
        logger.warning("Failed to store session in Redis: %s", e)


async def delete_session(user_id: str, session_id: str) -> None:
    """Delete a session from Redis."""
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        key = _session_key(user_id, session_id)
        pipe = redis.pipeline()
        pipe.delete(key)
        pipe.srem(_index_key(user_id), key)
        await pipe.execute()
    except Exception as e:
        logger.warning("Failed to delete session from Redis: %s", e)


async def delete_all_sessions(user_id: str) -> int:
    """Delete all sessions for a user via the per-user Set index (no SCAN).

    Returns number of session keys deleted.
    """
    try:
        from ..redis.client import get_redis
        redis = await get_redis()
        index = _index_key(user_id)
        keys = list(await redis.smembers(index))
        pipe = redis.pipeline()
        if keys:
            pipe.delete(*keys)
        pipe.delete(index)
        await pipe.execute()
        return len(keys)
    except Exception as e:
        logger.error("Failed to delete all sessions for user (Redis unavailable): %s", e)
        return 0
