import asyncio
import logging
import time
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
_redis_marked_unavailable_at = 0.0
# How long to wait before re-probing Redis after it was marked unavailable.
# Fail-closed paths (rate limiting, token blacklist) call get_redis() on every
# request, so without this cooldown a single Redis blip would permanently latch
# the client offline and 429 every login until restart.
REDIS_REPROBE_COOLDOWN_SECONDS = 5.0


def _fresh_client() -> Redis:
    url = settings.REDIS_URL
    kwargs = dict(
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=5,
        retry_on_timeout=False,
    )
    # TLS for managed Redis (Memorystore/ Elasticache with in-transit
    # encryption). Only consulted for the rediss:// scheme; plain redis://
    # ignores these.
    if url.startswith("rediss://"):
        reqs = (settings.REDIS_SSL_CERT_REQS or "required").lower()
        mapping = {"none": "none", "optional": "optional", "required": "required"}
        kwargs["ssl_cert_reqs"] = mapping.get(reqs, "required")
        if settings.REDIS_SSL_CA_CERTS:
            kwargs["ssl_ca_certs"] = settings.REDIS_SSL_CA_CERTS
    return Redis.from_url(url, **kwargs)


async def get_redis() -> Redis:
    global _redis, _redis_available, _redis_loop, _redis_marked_unavailable_at
    if not _redis_available:
        if (time.monotonic() - _redis_marked_unavailable_at) < REDIS_REPROBE_COOLDOWN_SECONDS:
            raise ConnectionError("Redis marked unavailable")
        # Cooldown elapsed: re-probe instead of staying latched offline.
        probe = _fresh_client()
        try:
            await probe.ping()
        except Exception as e:
            _redis_marked_unavailable_at = time.monotonic()
            raise ConnectionError(f"Redis unavailable: {e}") from e
        finally:
            try:
                await probe.aclose()
            except Exception:
                pass
        # Redis is back: drop the stale client so the normal path below builds
        # a fresh one on this loop instead of reusing a dead connection.
        if _redis is not None:
            try:
                await _redis.aclose()
            except Exception:
                pass
            _redis = None
            _redis_loop = None
        mark_redis_available()
        logger.info("Redis recovered, rate limiting re-enabled")
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if _redis is None or (
        _redis_loop is not None and running is not None and _redis_loop is not running
):
        if _redis is not None:
            try:
                await _redis.aclose()
            except Exception:
                pass
        _redis = _fresh_client()
        _redis_loop = running
    return _redis


async def close_redis() -> None:
    global _redis, _redis_loop
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
        _redis_loop = None


def mark_redis_unavailable():
    global _redis_available, _redis_marked_unavailable_at
    _redis_available = False
    _redis_marked_unavailable_at = time.monotonic()
    logger.warning(
        "Redis marked unavailable, re-probing in %ss",
        REDIS_REPROBE_COOLDOWN_SECONDS,
    )


def mark_redis_available():
    global _redis_available
    _redis_available = True


async def run_redis_rearmer() -> None:
    """Background prober that re-arms Redis after an outage.

    ``mark_redis_unavailable()`` latches Redis offline (used by fail-closed
    paths like rate limiting and auth). This prober periodically unlatches
    it so the next ``get_redis()`` call attempts a real reconnect.

    Without this, if no caller invokes ``get_redis()`` for an extended
    period, Redis stays latched offline indefinitely even after it has
    recovered — fail-closed paths (rate limiting, auth) stay broken.
    """
    while True:
        await asyncio.sleep(REDIS_REPROBE_COOLDOWN_SECONDS)
        mark_redis_available()


def redis_connection_kwargs() -> dict:
    """Shared Redis connection kwargs for callers that build their own client
    (e.g. the realtime pub/sub subscriber). Mirrors ``_fresh_client``."""
    url = settings.REDIS_URL
    kwargs = dict(
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=None,
        retry_on_timeout=False,
    )
    if url.startswith("rediss://"):
        reqs = (settings.REDIS_SSL_CERT_REQS or "required").lower()
        kwargs["ssl_cert_reqs"] = {"none": "none", "optional": "optional", "required": "required"}.get(reqs, "required")
        if settings.REDIS_SSL_CA_CERTS:
            kwargs["ssl_ca_certs"] = settings.REDIS_SSL_CA_CERTS
    return kwargs
