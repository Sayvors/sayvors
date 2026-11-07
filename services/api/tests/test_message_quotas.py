"""Message quota state: remaining, exhaustion and the 10% warning inputs."""
import pytest

from app.modules.billing import quotas
from app.modules.billing.entitlements import Entitlements

pytestmark = pytest.mark.asyncio


def _entitlements(limit: int | None) -> Entitlements:
    return Entitlements(
        plan_slug="growth",
        plan_name="Growth",
        status="active",
        max_channels=None,
        max_messages_per_month=limit,
        included_credit_cents=0,
        features={"messaging": True},
        plan_features={"messaging": True},
        features_override={},
        granted_by=None,
        granted_until=None,
        promo_active=False,
    )


async def _patch(monkeypatch, limit: int | None, used: int) -> None:
    async def fake_entitlements(tenant_id, db):
        return _entitlements(limit)

    async def fake_usage(tenant_id, db=None):
        return used

    monkeypatch.setattr(
        "app.modules.billing.entitlements.get_entitlements", fake_entitlements
    )
    monkeypatch.setattr(quotas, "get_message_usage", fake_usage)


async def test_quota_state_reports_remaining_and_ratio(monkeypatch):
    await _patch(monkeypatch, limit=500, used=455)

    state = await quotas.message_quota_state("tenant", db=object())

    assert state == {
        "used": 455,
        "limit": 500,
        "remaining": 45,
        "ratio": pytest.approx(0.91),
        "exhausted": False,
    }


async def test_quota_is_exhausted_at_the_limit(monkeypatch):
    await _patch(monkeypatch, limit=500, used=500)

    state = await quotas.message_quota_state("tenant", db=object())

    assert state["exhausted"] is True
    assert state["remaining"] == 0
    assert await quotas.message_quota_available("tenant", db=object()) is False


async def test_unlimited_plan_never_exhausts(monkeypatch):
    await _patch(monkeypatch, limit=None, used=10_000)

    state = await quotas.message_quota_state("tenant", db=object())

    assert state["limit"] is None
    assert state["remaining"] is None
    assert state["exhausted"] is False
    assert await quotas.message_quota_available("tenant", db=object()) is True
