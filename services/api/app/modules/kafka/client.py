import asyncio
import logging

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

from ...config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None
_kafka_available = True


async def get_kafka_producer() -> AIOKafkaProducer:
    global _producer, _kafka_available
    if not _kafka_available:
        raise ConnectionError("Kafka marked unavailable")
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="sayvors-api",
            request_timeout_ms=3000,
            metadata_max_age_ms=5000,
        )
        try:
            await asyncio.wait_for(_producer.start(), timeout=5.0)
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
) -> AIOKafkaConsumer:
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    return consumer
