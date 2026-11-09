"""Fast message-quota reads for hot paths.

`count_messages_this_month` is a real COUNT over the tenant's outbound
WhatsApp rows. Instagram, Facebook and every other channel are excluded: the
plan's "messages" allowance is WhatsApp-only.
Calling it on every inbound message would turn one customer message into a
month-sized scan; this module memoises the value in Redis for a short window
so a burst of messages pays for one count, not one per message.

The cache is advisory: if Redis is unavailable the database is still the
source of truth, and the caller decides whether a lookup failure should block
an AI reply.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Short enough that a burst cannot spend far past the limit, long enough that
# a conversation with 20 messages performs at most one COUNT.
CACHE_TTL_SECONDS = 30


def _key(tenant_id: str) -> str:
    return f"quota:whatsapp_messages:{tenant_id}:{datetime.now(timezone.utc):%Y-%m}"


async def get_message_usage(tenant_id: str, db=None) -> int:
    """Outbound WhatsApp messages this calendar month (cached, DB on miss)."""
    from .entitlements import count_messages_this_month

    key = _key(tenant_id)
    try:
        from ..redis.client import get_redis

        cached = await (await get_redis()).get(key)
        if cached is not None:
            return int(cached)
    except Exception as e:
        logger.debug("message quota cache read failed: %s", e)

    if db is not None:
        used = await count_messages_this_month(tenant_id, db)
    else:
        from ...database import async_session

        async with async_session() as session:
            used = await count_messages_this_month(tenant_id, session)
    try:
        from ..redis.client import get_redis

        await (await get_redis()).set(key, used, ex=CACHE_TTL_SECONDS)
    except Exception as e:
        logger.debug("message quota cache write failed: %s", e)
    return used


async def invalidate_message_usage(tenant_id: str) -> None:
    """Drop the cached count after an outbound message lands."""
    try:
        from ..redis.client import get_redis

        await (await get_redis()).delete(_key(tenant_id))
    except Exception as e:
        logger.debug("message quota cache delete failed: %s", e)


async def message_quota_state(tenant_id: str, db=None) -> dict:
    """Used / limit / remaining / ratio for one tenant.

    `limit is None` means unlimited (every plan currently offered has a limit,
    but the schema allows null and callers must handle it).
    """
    from .entitlements import get_entitlements

    if db is not None:
        ent = await get_entitlements(tenant_id, db)
    else:
        from ...database import async_session

        async with async_session() as session:
            ent = await get_entitlements(tenant_id, session)
    used = await get_message_usage(tenant_id, db)
    limit = ent.max_messages_per_month
    remaining = None if limit is None else max(0, limit - used)
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "ratio": None if not limit else used / limit,
        "exhausted": limit is not None and used >= limit,
    }


async def message_quota_available(tenant_id: str, db=None) -> bool:
    state = await message_quota_state(tenant_id, db)
    return not state["exhausted"]
