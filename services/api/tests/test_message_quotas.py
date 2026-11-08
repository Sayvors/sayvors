"""Message quota state: remaining, exhaustion and the 10% warning inputs."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.billing import quotas
from app.modules.billing.entitlements import Entitlements, count_messages_this_month
from app.modules.billing.messaging_quota import ensure_messaging_quota
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.team.context import TenantContext

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


async def test_usage_counts_only_outbound_whatsapp(db, user_id):
    """The plan allowance is WhatsApp-only and outbound-only.

    Instagram/Facebook traffic and inbound WhatsApp messages must not consume
    the allowance an admin sets for WhatsApp sending.
    """
    db.add_all(
        [
            Channel(
                id="q-wa-channel",
                user_id=user_id,
                platform="whatsapp",
                platform_user_id="wa-1",
                status="active",
            ),
            Channel(
                id="q-ig-channel",
                user_id=user_id,
                platform="instagram",
                platform_user_id="ig-1",
                status="active",
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            ChannelMessage(
                id="q-wa-out-1",
                channel_id="q-wa-channel",
                direction="outbound",
                content="hi",
            ),
            ChannelMessage(
                id="q-wa-out-2",
                channel_id="q-wa-channel",
                direction="outbound",
                content="there",
            ),
            ChannelMessage(
                id="q-wa-in-1",
                channel_id="q-wa-channel",
                direction="inbound",
                content="hello",
            ),
            ChannelMessage(
                id="q-ig-out-1",
                channel_id="q-ig-channel",
                direction="outbound",
                content="reply",
            ),
            # Previous month: outside the current calendar window.
            ChannelMessage(
                id="q-wa-old",
                channel_id="q-wa-channel",
                direction="outbound",
                content="old",
                created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    await db.commit()

    assert await count_messages_this_month(user_id, db) == 2


async def test_gate_blocks_whatsapp_only(monkeypatch, db, user_id):
    """An exhausted allowance must not block an Instagram send."""
    db.add_all(
        [
            Channel(
                id="gate-wa-channel",
                user_id=user_id,
                platform="whatsapp",
                platform_user_id="wa-1",
                status="active",
            ),
            Channel(
                id="gate-ig-channel",
                user_id=user_id,
                platform="instagram",
                platform_user_id="ig-1",
                status="active",
            ),
        ]
    )
    await db.commit()

    async def fake_entitlements(tenant_id, session):
        return _entitlements(limit=100)

    async def fake_count(tenant_id, session):
        return 100

    monkeypatch.setattr(
        "app.modules.billing.entitlements.get_entitlements", fake_entitlements
    )
    monkeypatch.setattr(
        "app.modules.billing.entitlements.count_messages_this_month", fake_count
    )
    ctx = TenantContext(
        user=SimpleNamespace(id=user_id, tenant_id=None),
        tenant_id=user_id,
        member=None,
        role=None,
        permissions=frozenset(),
        channel_overrides={},
    )

    await ensure_messaging_quota(ctx, db, "gate-ig-channel")

    with pytest.raises(HTTPException) as excinfo:
        await ensure_messaging_quota(ctx, db, "gate-wa-channel")
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["X-Entitlement-Denied"] == "quota"


async def test_unlimited_plan_never_exhausts(monkeypatch):
    await _patch(monkeypatch, limit=None, used=10_000)

    state = await quotas.message_quota_state("tenant", db=object())

    assert state["limit"] is None
    assert state["remaining"] is None
    assert state["exhausted"] is False
    assert await quotas.message_quota_available("tenant", db=object()) is True
