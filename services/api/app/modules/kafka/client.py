from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

from ...config import settings

_producer: AIOKafkaProducer | None = None


async def get_kafka_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="sayvors-api",
        )
        await _producer.start()
    return _producer


async def close_kafka() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
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
