from datetime import datetime, timezone

from ..redis.client import get_redis


async def rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Returns True if allowed, False if rate limited."""
    redis = await get_redis()
    now = int(datetime.now(timezone.utc).timestamp())
    window_start = now - window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()

    request_count = results[2]
    return request_count <= max_requests


async def get_rate_limit_count(key: str, window_seconds: int) -> int:
    redis = await get_redis()
    now = int(datetime.now(timezone.utc).timestamp())
    window_start = now - window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()

    return results[1]


async def blacklist_token(jti: str, expires_in_seconds: int) -> None:
    """Add a token JTI to the blacklist in Redis."""
    redis = await get_redis()
    await redis.setex(f"bl:{jti}", expires_in_seconds, "1")


async def is_token_blacklisted(jti: str) -> bool:
    """Check if a token JTI is blacklisted."""
    redis = await get_redis()
    return await redis.exists(f"bl:{jti}")


async def store_session(user_id: str, session_id: str, data: dict, expires_in_seconds: int) -> None:
    """Store session data in Redis."""
    import json
    redis = await get_redis()
    await redis.setex(f"session:{user_id}:{session_id}", expires_in_seconds, json.dumps(data))


async def get_session(user_id: str, session_id: str) -> dict | None:
    """Get session data from Redis."""
    import json
    redis = await get_redis()
    data = await redis.get(f"session:{user_id}:{session_id}")
    return json.loads(data) if data else None


async def delete_session(user_id: str, session_id: str) -> None:
    """Delete a session from Redis."""
    redis = await get_redis()
    await redis.delete(f"session:{user_id}:{session_id}")


async def delete_all_sessions(user_id: str) -> None:
    """Delete all sessions for a user."""
    redis = await get_redis()
    pattern = f"session:{user_id}:*"
    keys = []
    async for key in redis.scan_iter(match=pattern):
        keys.append(key)
    if keys:
        await redis.delete(*keys)
