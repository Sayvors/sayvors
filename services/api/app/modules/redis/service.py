from typing import Any

from .client import get_redis


async def cache_get(key: str) -> str | None:
    r = await get_redis()
    return await r.get(key)


async def cache_set(key: str, value: str, ttl: int | None = None) -> None:
    r = await get_redis()
    if ttl:
        await r.setex(key, ttl, value)
    else:
        await r.set(key, value)


async def cache_delete(key: str) -> None:
    r = await get_redis()
    await r.delete(key)


async def cache_exists(key: str) -> bool:
    r = await get_redis()
    return await r.exists(key) > 0


async def publish(channel: str, message: str) -> None:
    r = await get_redis()
    await r.publish(channel, message)


async def subscribe(*channels: str):
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(*channels)
    return pubsub
