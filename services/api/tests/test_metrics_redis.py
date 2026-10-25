"""Redis health and memory are exported on /metrics.

Rate limits, the token blacklist, sessions and OTPs live in Redis, so the
scrape is also the liveness signal for the auth path. The memory gauges exist
so the 75%-of-maxmemory alarm is a Prometheus rule rather than a manual check.
"""
import pytest

from app.modules.redis import client as redis_client

_HOST = {"host": "localhost"}
_MB = 1024 * 1024


class _FakeRedis:
    def __init__(self, used: int, maxmemory: int) -> None:
        self._used = used
        self._max = maxmemory

    async def info(self, section=None):
        assert section == "memory"
        return {"used_memory": self._used, "maxmemory": self._max}


@pytest.mark.asyncio
async def test_metrics_expose_redis_memory(client, monkeypatch):
    async def _get_redis():
        return _FakeRedis(used=100_000_000, maxmemory=128 * _MB)

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)

    r = client.get("/metrics", headers=_HOST)
    assert r.status_code == 200
    body = r.text
    assert "sayvors_redis_available 1" in body
    assert "sayvors_redis_used_memory_bytes 100000000" in body
    assert f"sayvors_redis_maxmemory_bytes {128 * _MB}" in body
    ratio = 100_000_000 / (128 * _MB)
    assert f"sayvors_redis_memory_utilization_ratio {ratio:.4f}" in body


@pytest.mark.asyncio
async def test_metrics_skip_the_ratio_when_maxmemory_is_unlimited(client, monkeypatch):
    async def _get_redis():
        return _FakeRedis(used=5_000_000, maxmemory=0)

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)

    body = client.get("/metrics", headers=_HOST).text
    assert "sayvors_redis_used_memory_bytes 5000000" in body
    assert "sayvors_redis_memory_utilization_ratio" not in body


@pytest.mark.asyncio
async def test_metrics_still_scrape_when_redis_is_down(client, monkeypatch):
    async def _down():
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_client, "get_redis", _down)

    r = client.get("/metrics", headers=_HOST)
    assert r.status_code == 200
    assert "sayvors_redis_available 0" in r.text
