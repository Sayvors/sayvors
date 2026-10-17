import asyncio
import logging

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

from ...config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None
_kafka_available = True
_producer_lock = asyncio.Lock()


async def get_kafka_producer() -> AIOKafkaProducer:
    global _producer, _kafka_available
    if not _kafka_available:
        raise ConnectionError("Kafka marked unavailable")

    async with _producer_lock:
        if _producer is None:
            _producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                client_id="sayvors-api",
                # Hardened for durability: exactly-once semantics, no lost messages.
                acks="all",
                enable_idempotence=True,
                linger_ms=5,
                compression_type="gzip",
                request_timeout_ms=30000,
                delivery_timeout_ms=120000,
                max_in_flight=1,
                metadata_max_age_ms=5000,
            )
            try:
                await asyncio.wait_for(_producer.start(), timeout=15.0)
            except Exception as e:
                _producer = None
                _kafka_available = False
                logger.warning("Kafka unavailable (will retry): %s", e)
                raise
    return _producer


def mark_kafka_unavailable():
    global _kafka_available
    _kafka_available = False
    logger.warning("Kafka marked unavailable, will retry in worker")


def mark_kafka_available():
    global _kafka_available
    _kafka_available = True
    logger.info("Kafka marked available")


async def close_kafka() -> None:
    global _producer
    if _producer is not None:
        try:
            await _producer.stop()
        except Exception:
            pass
        _producer = None


async def create_consumer(
    group_id: str,
    topics: list[str],
    *,
    max_poll_interval_ms: int = 900_000,
    session_timeout_ms: int = 30_000,
    max_poll_records: int = 1,
    enable_auto_commit: bool = False,
) -> AIOKafkaConsumer:
    """Create a Kafka consumer with manual offset commit.

    enable_auto_commit=False by default: offsets are committed only after
    the job reaches a durable terminal-or-retry state (R1 in the design doc).
    """
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=enable_auto_commit,
        auto_offset_reset="earliest",
        max_poll_interval_ms=max_poll_interval_ms,
        session_timeout_ms=session_timeout_ms,
        max_poll_records=max_poll_records,
        value_deserializer=lambda b: __import__("json").loads(b.decode()),
    )
    await consumer.start()
    return consumer
