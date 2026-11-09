"""Per-address OTP throttling, independent of the per-IP limits."""
import pytest

from app.config import settings
from app.modules.email.service import _otp_send_allowed

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, object] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True


async def test_resend_within_cooldown_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60)
    monkeypatch.setattr(settings, "OTP_DAILY_LIMIT", 10)
    redis = _FakeRedis()

    assert await _otp_send_allowed(redis, "person@example.com") is True
    assert await _otp_send_allowed(redis, "person@example.com") is False
    # A different address is not affected by the first one's cooldown.
    assert await _otp_send_allowed(redis, "other@example.com") is True


async def test_daily_cap_is_enforced(monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60)
    monkeypatch.setattr(settings, "OTP_DAILY_LIMIT", 2)
    redis = _FakeRedis()
    cooldown = "otp:cooldown:person@example.com"

    assert await _otp_send_allowed(redis, "person@example.com") is True
    redis.values.pop(cooldown, None)
    assert await _otp_send_allowed(redis, "person@example.com") is True
    redis.values.pop(cooldown, None)
    assert await _otp_send_allowed(redis, "person@example.com") is False
