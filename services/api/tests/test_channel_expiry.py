"""A channel whose Google connection is gone must say so (D7).

Before this, a revoked token / removed location left the channel "active":
the worker kept polling it every cycle and the merchant saw nothing. Now the
channel is marked expired once and the merchant gets one notification.
"""
import json

import pytest
from sqlalchemy import select

from app.modules.channels import reviews_worker
from app.modules.channels.google_reviews import GoogleReviewsError
from app.modules.channels.models import AutoReplyConfig, Channel
from app.modules.channels.service import encrypt_token
from app.modules.notifications.models import Notification


def _fake_client(monkeypatch, error: GoogleReviewsError | None):
    # The test suite runs Google Reviews in mock mode; this path needs the
    # real client contract.
    monkeypatch.setattr(reviews_worker.settings, "GOOGLE_REVIEWS_MOCK", False)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def set_known_expiry(self, *args, **kwargs):
            pass

        def set_token_persister(self, *args, **kwargs):
            pass

        async def close(self):
            pass

        async def list_locations(self, *args, **kwargs):
            return []

        async def list_reviews(self, *args, **kwargs):
            if error is not None:
                raise error
            return []

    monkeypatch.setattr(reviews_worker, "GoogleReviewsClient", _FakeClient)


async def _channel_and_config(db, user_id, suffix: str):
    channel = Channel(
        id=f"expiry-channel-{suffix}",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="accounts/123",
        display_name="Shop",
        access_token=encrypt_token("token"),
        status="active",
        metadata_json=json.dumps({"location_id": "loc-1"}),
    )
    db.add(channel)
    await db.flush()
    config = AutoReplyConfig(
        id=f"expiry-config-{suffix}",
        channel_id=channel.id,
        enabled=True,
        tone="friendly",
        min_rating_auto=4,
        model="openai:gpt-4o-mini",
        approval_mode="auto",
    )
    db.add(config)
    await db.commit()
    return channel, config


@pytest.mark.asyncio
async def test_revoked_token_expires_the_channel_and_notifies(db, user_id, monkeypatch):
    _fake_client(monkeypatch, GoogleReviewsError("token revoked", 401))
    channel, config = await _channel_and_config(db, user_id, "revoked")

    with pytest.raises(GoogleReviewsError):
        await reviews_worker.process_channel(db, channel, config)

    await db.refresh(channel)
    assert channel.status == "expired"

    notes = (
        (await db.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(notes) == 1
    assert notes[0].type == "channel_expired"
    assert notes[0].data["channel_id"] == channel.id


@pytest.mark.asyncio
async def test_removed_location_expires_the_channel(db, user_id, monkeypatch):
    _fake_client(monkeypatch, GoogleReviewsError("location not found", 404))
    channel, config = await _channel_and_config(db, user_id, "removed")

    with pytest.raises(GoogleReviewsError):
        await reviews_worker.process_channel(db, channel, config)

    await db.refresh(channel)
    assert channel.status == "expired"


@pytest.mark.asyncio
async def test_transient_error_does_not_expire_the_channel(db, user_id, monkeypatch):
    """A 500 is Google having a bad minute, not a dead connection."""
    _fake_client(monkeypatch, GoogleReviewsError("upstream error", 500))
    channel, config = await _channel_and_config(db, user_id, "transient")

    with pytest.raises(GoogleReviewsError):
        await reviews_worker.process_channel(db, channel, config)

    await db.refresh(channel)
    assert channel.status == "active"
    notes = (
        (await db.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )
    assert notes == []


@pytest.mark.asyncio
async def test_the_merchant_is_not_notified_twice(db, user_id, monkeypatch):
    _fake_client(monkeypatch, GoogleReviewsError("token revoked", 401))
    channel, config = await _channel_and_config(db, user_id, "once")

    with pytest.raises(GoogleReviewsError):
        await reviews_worker.process_channel(db, channel, config)
    await db.refresh(channel)
    with pytest.raises(GoogleReviewsError):
        await reviews_worker.process_channel(db, channel, config)

    notes = (
        (await db.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(notes) == 1
