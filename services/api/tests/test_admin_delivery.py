"""Admin Meta delivery reconciliation: provider-confirmed vs our rows."""
from datetime import datetime, timezone

import pytest

from app.modules.admin.delivery import get_delivery_reconciliation
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

CHANNEL_ID = "meta-delivery-channel-00000000001"


async def _seed(db, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    db.add(User(
        id=user_id,
        email="delivery@example.com",
        first_name="Delivery",
        last_name="Tenant",
        password_hash="x",
    ))
    db.add(Channel(
        id=CHANNEL_ID,
        user_id=user_id,
        platform="whatsapp",
        platform_user_id="wa",
        display_name="Support line",
        status="active",
    ))
    # Deliberately unrelated channel: must never leak into the totals.
    db.add(Channel(
        id="google-delivery-channel-0000000001",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="g",
        display_name="Google",
        status="active",
    ))
    rows = [
        ChannelMessage(
            id="dm-in-000000000000000000000000001",
            channel_id=CHANNEL_ID,
            platform_message_id="wamid.in.1",
            direction="inbound",
            content="hi",
            status="read",
        ),
        ChannelMessage(
            id="dm-out-sent-0000000000000000000001",
            channel_id=CHANNEL_ID,
            platform_message_id="wamid.out.1",
            direction="outbound",
            content="sent only",
            status="sent",
        ),
        ChannelMessage(
            id="dm-out-delivered-00000000000000001",
            channel_id=CHANNEL_ID,
            platform_message_id="wamid.out.2",
            direction="outbound",
            content="delivered",
            status="delivered",
            delivered_at=now,
        ),
        ChannelMessage(
            id="dm-out-read-00000000000000000001",
            channel_id=CHANNEL_ID,
            platform_message_id="wamid.out.3",
            direction="outbound",
            content="read",
            status="read",
            delivered_at=now,
            read_at=now,
        ),
        ChannelMessage(
            id="dm-out-failed-00000000000000001",
            channel_id=CHANNEL_ID,
            platform_message_id="wamid.out.4",
            direction="outbound",
            content="failed",
            status="failed",
            failed_at=now,
        ),
        ChannelMessage(
            id="dm-out-nowamid-00000000000000001",
            channel_id=CHANNEL_ID,
            direction="outbound",
            content="never reached meta",
            status="failed",
            failed_at=now,
        ),
    ]
    db.add_all(rows)
    await db.commit()


async def test_reconciliation_counts_statuses_and_ids(db, user_id):
    await _seed(db, user_id)

    result = await get_delivery_reconciliation(db, user_id, days=30)

    totals = result["totals"]
    assert totals["inbound"] == 1
    assert totals["outbound"] == 5
    assert totals["outbound_with_id"] == 4
    assert totals["outbound_without_id"] == 1
    assert totals["sent"] == 1
    assert totals["delivered"] == 1
    assert totals["read"] == 1
    assert totals["failed"] == 2
    # Delivered + read over the four messages Meta actually accepted.
    assert totals["delivery_rate_pct"] == 50.0

    assert len(result["by_channel"]) == 1
    channel = result["by_channel"][0]
    assert channel["platform"] == "whatsapp"
    assert channel["name"] == "Support line"

    assert result["daily"]
    day = result["daily"][0]
    assert day["outbound"] == 5


async def test_reconciliation_is_empty_without_meta_channels(db, user_id):
    db.add(User(
        id=user_id,
        email="no-meta@example.com",
        first_name="No",
        last_name="Meta",
        password_hash="x",
    ))
    db.add(Channel(
        id="only-google-channel-000000000000001",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="g",
        display_name="Google only",
        status="active",
    ))
    await db.commit()

    result = await get_delivery_reconciliation(db, user_id, days=7)

    assert result["totals"]["outbound"] == 0
    assert result["by_channel"] == []
    assert result["daily"] == []
    assert result["platforms"] == []
