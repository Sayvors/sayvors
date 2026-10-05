"""Fan-out of inbox events to connected browsers via Redis pub/sub.

The consumer publishes after each persisted message/status change; the
WebSocket endpoint (router) subscribes per user. Fire-and-forget: any
failure here is logged and swallowed — a missed publish degrades to the
manual Refresh, never an ingestion error.
"""
import json
import logging

logger = logging.getLogger(__name__)


def _channel(user_id: str) -> str:
    return f"inbox:{user_id}"


async def publish_inbox_event(user_id: str, event: dict) -> None:
    try:
        from ...modules.redis.client import get_redis

        redis = await get_redis()
        await redis.publish(_channel(user_id), json.dumps(event, default=str))
    except Exception as e:  # noqa: BLE001 — redis down must never break ingestion
        logger.debug("inbox realtime publish skipped: %s", e)


async def subscribe_inbox(user_id: str):
    """Pub/sub object for this user's event stream. Caller owns aclose()."""
    from redis.asyncio import Redis

    from ...config import settings

    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=None,
        retry_on_timeout=False,
    )
    pubsub = client.pubsub()
    await pubsub.subscribe(_channel(user_id))
    return client, pubsub
