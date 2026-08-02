from functools import lru_cache

from redis.asyncio import Redis

from ...config import settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


@lru_cache
def get_redis_url() -> str:
    return settings.REDIS_URL
