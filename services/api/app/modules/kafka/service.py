import json
from typing import Any

from .client import get_kafka_producer


async def publish_event(topic: str, key: str, value: dict[str, Any]) -> None:
    """Fire-and-forget event publish to Kafka."""
    producer = await get_kafka_producer()
    await producer.send(
        topic,
        key=key.encode("utf-8"),
        value=json.dumps(value).encode("utf-8"),
    )


async def publish_message(topic: str, value: dict[str, Any]) -> None:
    """Fire-and-forget message publish to Kafka."""
    producer = await get_kafka_producer()
    await producer.send(
        topic,
        value=json.dumps(value).encode("utf-8"),
    )
