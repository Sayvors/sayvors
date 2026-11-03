"""WhatsApp outbound pacing: one token per message call, shared per number."""
import math

import httpx
import pytest

from app.config import settings
from app.modules.channels.meta.providers import whatsapp as whatsapp_module
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter
from app.modules.redis import client as redis_client


class _TokenBucketRedis:
    """Redis double that implements the same bucket math as the Lua script.

    The production path calls EVAL atomically; this double keeps the test
    independent of a Redis server and lets the suite drive exact boundaries.
    """

    def __init__(self) -> None:
        self.buckets: dict[str, tuple[float, float]] = {}

    async def eval(self, script, numkeys, *args):
        assert numkeys == 1
        assert "HMGET" in script
        key = args[0]
        capacity = float(args[1])
        refill = float(args[2])
        now_ms = float(args[3])
        bucket = self.buckets.get(key)
        tokens = capacity if bucket is None else bucket[0]
        updated_at = now_ms if bucket is None else bucket[1]
        tokens = min(capacity, tokens + max(0.0, now_ms - updated_at) / 1000.0 * refill)
        if tokens >= 1.0:
            tokens -= 1.0
            result = [1, str(tokens), 0]
        else:
            wait_ms = max(1, math.ceil(((1.0 - tokens) / refill) * 1000))
            result = [0, str(tokens), wait_ms]
        self.buckets[key] = (tokens, now_ms)
        return result


@pytest.fixture
def paced_redis(monkeypatch):
    fake = _TokenBucketRedis()
    unavailable = []

    async def _get_redis():
        return fake

    def _mark_unavailable():
        unavailable.append(True)

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)
    monkeypatch.setattr(redis_client, "mark_redis_unavailable", _mark_unavailable)
    monkeypatch.setattr(settings, "TESTING", False)
    return fake, unavailable


def _adapter(handler) -> WhatsAppAdapter:
    adapter = WhatsAppAdapter()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


def test_bucket_keys_are_hashed_and_per_number():
    assert whatsapp_module._send_bucket_key("pn-1") != whatsapp_module._send_bucket_key("pn-2")
    assert "pn-1" not in whatsapp_module._send_bucket_key("pn-1")
    assert whatsapp_module._send_bucket_key("pn-1").startswith("meta:wa:send-bucket:")


async def test_message_post_waits_for_a_token(monkeypatch, paced_redis):
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_BUCKET_CAPACITY", 2)
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_LIMIT_PER_SECOND", 1)
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_MAX_WAIT_SECONDS", 0)
    assert (await whatsapp_module._acquire_whatsapp_send_token("pn-1"))[0]
    assert (await whatsapp_module._acquire_whatsapp_send_token("pn-1"))[0]
    allowed, retry_after_ms = await whatsapp_module._acquire_whatsapp_send_token("pn-1")
    assert not allowed
    assert retry_after_ms > 0


async def test_saturated_bucket_fails_locally_before_meta(monkeypatch, paced_redis):
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_BUCKET_CAPACITY", 1)
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_LIMIT_PER_SECOND", 1)
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_MAX_WAIT_SECONDS", 0)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "wamid-1"}]})

    adapter = _adapter(handler)
    assert await adapter.send_text_message("pn-1", "tok", "966500000001", "first")
    with pytest.raises(MetaAPIError) as excinfo:
        await adapter.send_text_message("pn-1", "tok", "966500000001", "second")

    assert excinfo.value.status_code == 429
    assert calls["n"] == 1


async def test_get_and_non_message_posts_do_not_consume_tokens(paced_redis):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"success": True})

    adapter = _adapter(handler)
    await adapter._graph("GET", "/me", "tok")
    await adapter._graph("POST", "/pn-1/message_templates", "tok")

    assert calls["n"] == 2


async def test_send_failure_in_redis_allows_the_send(monkeypatch, paced_redis):
    async def _unavailable():
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_client, "get_redis", _unavailable)
    calls = {"n": 0}
    unavailable = []

    def _mark_unavailable():
        unavailable.append(True)

    monkeypatch.setattr(redis_client, "mark_redis_unavailable", _mark_unavailable)

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "wamid-1"}]})

    adapter = _adapter(handler)
    assert await adapter.send_text_message("pn-1", "tok", "966500000001", "hello")
    assert calls["n"] == 1
    assert unavailable == [True]


async def test_redis_script_failure_allows_the_send(monkeypatch, paced_redis):
    class _BrokenRedis:
        async def eval(self, *_args, **_kwargs):
            raise RuntimeError("script load failed")

    async def _get_redis():
        return _BrokenRedis()

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "wamid-1"}]})

    adapter = _adapter(handler)
    assert await adapter.send_text_message("pn-1", "tok", "966500000001", "hello")
    assert calls["n"] == 1


async def test_buckets_are_shared_across_adapter_instances(monkeypatch, paced_redis):
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_BUCKET_CAPACITY", 1)
    monkeypatch.setattr(whatsapp_module, "WHATSAPP_SEND_MAX_WAIT_SECONDS", 0)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "wamid-1"}]})

    first = _adapter(handler)
    second = _adapter(handler)
    await first.send_text_message("pn-share", "tok", "966500000001", "first")

    with pytest.raises(MetaAPIError) as excinfo:
        await second.send_text_message("pn-share", "tok", "966500000001", "second")

    assert excinfo.value.status_code == 429
    assert calls["n"] == 1
