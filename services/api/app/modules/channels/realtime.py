"""Fan-out of inbox events to connected browsers via Redis pub/sub.

Shared subscriber: one Redis pub/sub connection per process subscribes to
all inbox channels (pattern inbox:*). Incoming messages are fanned out to
local WebSocket connections registered per tenant. This avoids one Redis
connection per open browser tab (the old design), which doesn't scale past
a few hundred concurrent dashboards.

Usage:
  client, pubsub = await subscribe_inbox(tenant_id)
  async for msg in pubsub.listen():
      ...
  # cleanup: pubsub.unsubscribe(); pubsub.close(); client.close()
"""
import asyncio
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Shared subscriber state (per process) ──────────────────────────────
_shared_client = None
_shared_pubsub = None
_fanout_task: asyncio.Task | None = None
# tenant_id -> set of local queues (one per connected WS tab)
_local_queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
_lock = asyncio.Lock()


async def _ensure_shared_subscriber():
    """Start the shared pub/sub connection and fanout loop once."""
    global _shared_client, _shared_pubsub, _fanout_task
    if _shared_pubsub is not None:
        return
    from ...config import settings
    from redis.asyncio import Redis

    _shared_client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=None,
        retry_on_timeout=False,
        max_connections=4,  # pooled: one shared connection, not one per tab
    )
    _shared_pubsub = _shared_client.pubsub()
    await _shared_pubsub.psubscribe("inbox:*")
    _fanout_task = asyncio.create_task(_fanout_loop())
    logger.info("Shared inbox subscriber started (pattern inbox:*)")


async def _fanout_loop():
    """Read from the shared pub/sub and fan out to local queues.

    Retries on connection loss so a Redis blip doesn't permanently disable
    realtime for the process (re-arm pattern).
    """
    global _shared_client, _shared_pubsub
    while True:
        try:
            async for msg in _shared_pubsub.listen():
                if msg.get("type") not in ("pmessage", "message"):
                    continue
                channel = msg.get("channel", "")
                # channel is like "inbox:{tenant_id}"
                tenant_id = channel.split(":", 1)[1] if ":" in channel else channel
                data = msg.get("data")
                if not data:
                    continue
                queues = list(_local_queues.get(tenant_id, set()))
                for q in queues:
                    try:
                        q.put_nowait({"type": "message", "data": data})
                    except asyncio.QueueFull:
                        pass  # slow consumer — drop, client will refresh
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Shared inbox fanout loop error: %s — retrying in 5s", e)
            await asyncio.sleep(5)
            # Try to reconnect
            try:
                from ...config import settings
                from redis.asyncio import Redis
                _shared_pubsub = None
                _shared_client = Redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=None,
                    retry_on_timeout=False,
                    max_connections=4,
                )
                _shared_pubsub = _shared_client.pubsub()
                await _shared_pubsub.psubscribe("inbox:*")
                logger.info("Shared inbox subscriber reconnected")
            except Exception as e2:
                logger.warning("Reconnect failed: %s — retrying in 10s", e2)
                await asyncio.sleep(10)


async def publish_inbox_event(tenant_id: str, event: dict) -> None:
    try:
        from ...modules.redis.client import get_redis

        redis = await get_redis()
        await redis.publish(f"inbox:{tenant_id}", json.dumps(event, default=str))
    except Exception as e:  # noqa: BLE001 — redis down must never break ingestion
        logger.debug("inbox realtime publish skipped: %s", e)


class _LocalPubSub:
    """Local pub/sub shim that reads from a per-tenant queue populated by
    the shared fanout loop. Implements the subset of the redis.asyncio
    PubSub interface used by the inbox WebSocket handler."""

    def __init__(self, tenant_id: str, queue: asyncio.Queue):
        self._tenant_id = tenant_id
        self._queue = queue

    async def listen(self):
        while True:
            msg = await self._queue.get()
            yield msg

    async def unsubscribe(self):
        pass  # shared subscriber stays subscribed

    async def close(self):
        pass  # shared subscriber stays alive


async def subscribe_inbox(tenant_id: str):
    """Register a local listener for this tenant and return (client, pubsub).

    The returned client/pubsub pair is a shim over the shared subscriber —
    no new Redis connection is created per tab.
    """
    await _ensure_shared_subscriber()
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    async with _lock:
        _local_queues[tenant_id].add(queue)
    # Return the shared client (for close() compat) and the local shim.
    return _shared_client, _LocalPubSub(tenant_id, queue)


# Cleanup: when a WS disconnects, unregister the queue.
async def unsubscribe_inbox(tenant_id: str, queue: asyncio.Queue):
    async with _lock:
        _local_queues[tenant_id].discard(queue)
        if not _local_queues[tenant_id]:
            del _local_queues[tenant_id]