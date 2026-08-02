import json
from typing import Any

from .client import get_kafka_producer


async def publish_event(topic: str, key: str, value: dict[str, Any]) -> None:
    producer = await get_kafka_producer()
    await producer.send_and_wait(
        topic,
        key=key.encode("utf-8"),
        value=json.dumps(value).encode("utf-8"),
    )


async def publish_message(topic: str, value: dict[str, Any]) -> None:
    producer = await get_kafka_producer()
    await producer.send_and_wait(
        topic,
        value=json.dumps(value).encode("utf-8"),
    )
