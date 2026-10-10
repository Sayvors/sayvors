"""Short-TTL redis cache in front of the live Instagram Graph reads.

Every hub tab click used to be a Graph call — the Posts and Comments tabs
even hit the same posts read twice. IG platform rate limits are per-account,
so a workspace of users clicking around can exhaust them and every tab
degrades to its stale snapshot at once. These caches keep reads honest
(seconds, not minutes) while absorbing the click storm.

Rules:
- Off under settings.TESTING (same guard as the rate limiter) so tests that
  share fixture ids and assert Graph behavior keep passing untouched.
- Best-effort both ways: redis down means a plain live fetch, never an error.
- `refresh=1` on the endpoint bypasses the read for an explicit re-fetch.
"""
import json
import logging

logger = logging.getLogger(__name__)

PROFILE_TTL_SECONDS = 300  # follower counts move slowly
LIST_TTL_SECONDS = 60  # new posts/comments should surface within a minute


def _key(kind: str, ig_id: str) -> str:
    return f"ig:{kind}:{ig_id}"


async def get(kind: str, ig_id: str) -> dict | None:
    from ....config import settings

    if settings.TESTING:
        return None
    try:
        from ....modules.redis.client import get_redis

        raw = await (await get_redis()).get(_key(kind, ig_id))
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001 — a cache miss must never fail a read
        logger.debug("ig cache read skipped (%s/%s): %s", kind, ig_id[:12], e)
        return None


async def set(kind: str, ig_id: str, value: dict, ttl_seconds: int) -> None:
    from ....config import settings

    if settings.TESTING:
        return
    try:
        from ....modules.redis.client import get_redis

        await (await get_redis()).set(
            _key(kind, ig_id), json.dumps(value), ex=ttl_seconds
        )
    except Exception as e:  # noqa: BLE001 — an unwritten cache is just a miss
        logger.debug("ig cache write skipped (%s/%s): %s", kind, ig_id[:12], e)
