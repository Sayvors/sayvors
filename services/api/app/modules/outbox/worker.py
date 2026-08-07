import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# How often to poll for pending events (seconds)
POLL_INTERVAL = 3
# How often to check Kafka health when it's down (seconds)
KAFKA_RETRY_INTERVAL = 30
# How often to run cleanup (seconds)
CLEANUP_INTERVAL = 3600  # 1 hour


class OutboxWorker:
    """Background worker that drains the event outbox to Kafka.

    Runs as an asyncio task in the FastAPI lifespan. Polls for pending
    events, sends them to Kafka, and retries failed ones with backoff.
    """

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Outbox worker started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Outbox worker stopped")

    async def _loop(self):
        last_cleanup = 0
        last_kafka_check = 0

        while self._running:
            try:
                now = asyncio.get_event_loop().time()

                # Periodic cleanup of old sent events
                if now - last_cleanup > CLEANUP_INTERVAL:
                    from .service import cleanup_sent_events
                    deleted = await cleanup_sent_events()
                    if deleted:
                        logger.info("Outbox cleanup: deleted %d sent events", deleted)
                    last_cleanup = now

                # If Kafka is down, periodically try to reconnect
                from ..kafka.client import _kafka_available
                if not _kafka_available and now - last_kafka_check > KAFKA_RETRY_INTERVAL:
                    last_kafka_check = now
                    try:
                        from ..kafka.client import get_kafka_producer, mark_kafka_available
                        await get_kafka_producer()
                        mark_kafka_available()
                        logger.info("Kafka reconnected!")
                    except Exception:
                        pass  # Still down, will retry next cycle

                # Drain pending events
                await self._drain()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Outbox worker error")

            await asyncio.sleep(POLL_INTERVAL)

    async def _drain(self):
        from .service import fetch_pending_events, mark_sent, mark_failed

        events = await fetch_pending_events(batch_size=100)
        if not events:
            return

        # Group by topic for batch sending
        by_topic: dict[str, list] = {}
        for event in events:
            by_topic.setdefault(event.topic, []).append(event)

        for topic, batch in by_topic.items():
            await self._send_batch(topic, batch)

    async def _send_batch(self, topic: str, events: list):
        from .service import mark_sent, mark_failed

        # Try to get a Kafka producer
        try:
            from ..kafka.client import get_kafka_producer
            producer = await get_kafka_producer()
        except Exception:
            # Kafka unavailable — events stay "pending", will retry next cycle
            return

        sent_ids = []
        for event in events:
            try:
                key = f"{event.event_type}:{event.payload.get('user_id', event.payload.get('email', ''))}".encode()
                value = json.dumps(event.payload).encode()
                await producer.send(topic, key=key, value=value)
                sent_ids.append(event.id)
            except Exception as e:
                logger.warning("Failed to send event %s: %s", event.id, e)
                await mark_failed(event.id, str(e))

        if sent_ids:
            await mark_sent(sent_ids)
            logger.debug("Sent %d events to %s", len(sent_ids), topic)
