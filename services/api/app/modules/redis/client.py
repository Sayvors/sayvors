import asyncio
import logging
from functools import lru_cache

from redis.asyncio import Redis

from ...config import settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None
# The loop that created the cached client. redis-py connections bind to
# their creating loop, so a client cached by one loop (a test's loop, a
# TestClient portal loop, a reloaded worker) raises "Event loop is closed"
# when reused from another. Track it and recreate on mismatch instead of
# failing every caller (which would trip fail-closed auth/blacklist paths).
_redis_loop = None
_redis_available = True


def _fresh_client() -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=False,
    )


async def get_redis() -> Redis:
    global _redis, _redis_available, _redis_loop
    if not _redis_available:
        raise ConnectionError("Redis marked unavailable")
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if _redis is None or (
        _redis_loop is not None and running is not None and _redis_loop is not running
    ):
        if _redis is not None:
            try:
                await _redis.close()
            except Exception:
                pass
        _redis = _fresh_client()
        _redis_loop = running
    return _redis


async def close_redis() -> None:
    global _redis, _redis_loop
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None
        _redis_loop = None


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
