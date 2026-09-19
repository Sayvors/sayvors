import logging
from functools import lru_cache

from redis.asyncio import Redis

from ...config import settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None
_redis_available = True


async def get_redis() -> Redis:
    global _redis, _redis_available
    if not _redis_available:
        raise ConnectionError("Redis marked unavailable")
    if _redis is None:
        _redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None


def mark_redis_unavailable():
    global _redis_available
    _redis_available = False
    logger.warning("Redis marked unavailable, will retry in 30s")


def mark_redis_available():
    global _redis_available
    _redis_available = True


@lru_cache
def get_redis_url() -> str:
    return settings.REDIS_URL
