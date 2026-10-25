"""Regression guard: the AI-credit wallet mirror must never expire.

The original wallet-loss bug was a 24h TTL (``BUDGET_TTL_SECONDS = 86_400``)
applied with ``SETEX``; a tenant who did not use AI for a day came back to a
missing balance. The mirror is a cache of ``users.ai_credit_cents``, so losing
the key is survivable — but it must be a *deliberate* Redis loss, never an
expiry the application set itself.

These tests exercise the real Redis calls (the main budget suite replaces
them with plain dicts), so a reintroduced TTL fails here.
"""
import pytest

from app.modules.billing import budget

_TENANT = "ttl-guard-tenant-0001"
_KEY = f"ai_balance:{_TENANT}"


class _FakeRedis:
    """Minimal async Redis double that records expiry changes."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expiry: dict[str, int] = {}
        self.calls: list[tuple[str, str]] = []

    async def get(self, key: str):
        self.calls.append(("get", key))
        return self.data.get(key)

    async def set(self, key: str, value, nx: bool = False, ex: int | None = None, **kw):
        self.calls.append(("set", key))
        if nx and key in self.data:
            return False
        self.data[key] = str(value)
        if ex is None:
            self.expiry.pop(key, None)
        else:
            self.expiry[key] = int(ex)
        return True

    async def setex(self, key: str, ttl: int, value):
        self.calls.append(("setex", key))
        self.data[key] = str(value)
        self.expiry[key] = int(ttl)
        return True

    async def expire(self, key: str, ttl: int):
        self.calls.append(("expire", key))
        self.expiry[key] = int(ttl)
        return True

    async def persist(self, key: str):
        self.calls.append(("persist", key))
        return self.expiry.pop(key, None) is not None

    async def exists(self, key: str):
        self.calls.append(("exists", key))
        return 1 if key in self.data else 0


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()

    async def _get_redis():
        return fake

    import app.modules.redis.client as redis_client

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)
    return fake


@pytest.mark.asyncio
async def test_sync_balance_writes_without_any_expiry(fake_redis):
    assert await budget.sync_balance(_TENANT, 1234) is True
    assert fake_redis.data[_KEY] == "1234"
    assert _KEY not in fake_redis.expiry
    assert not [c for c in fake_redis.calls if c[0] in ("setex", "expire")]


@pytest.mark.asyncio
async def test_seed_balance_writes_without_any_expiry(fake_redis):
    assert await budget.seed_balance(_TENANT, 500) is True
    assert fake_redis.data[_KEY] == "500"
    assert _KEY not in fake_redis.expiry
    assert not [c for c in fake_redis.calls if c[0] in ("setex", "expire")]


@pytest.mark.asyncio
async def test_seed_balance_is_a_noop_when_a_wallet_exists(fake_redis):
    fake_redis.data[_KEY] = "900"
    assert await budget.seed_balance(_TENANT, 500) is True
    assert fake_redis.data[_KEY] == "900"


@pytest.mark.asyncio
async def test_reading_a_legacy_key_clears_its_ttl(fake_redis):
    """Keys written before the fix still carry the 24h expiry."""
    fake_redis.data[_KEY] = "500"
    fake_redis.expiry[_KEY] = 86_400

    assert await budget.get_cached_balance(_TENANT) == 500
    assert _KEY not in fake_redis.expiry
    assert ("persist", _KEY) in fake_redis.calls


@pytest.mark.asyncio
async def test_wallet_still_readable_after_simulated_redis_eviction(fake_redis):
    """The mirror is disposable: a missing key reads None, never a fake zero."""
    assert await budget.get_cached_balance(_TENANT) is None
