"""Channel list API exposes stored verification without per-channel fetches."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.channels.models import Channel, VerificationRecord


@pytest.mark.asyncio
async def test_channel_list_includes_stored_verification(client, db, user_id):
    now = datetime.now(timezone.utc)
    db.add_all([
        Channel(
            id="channel-unverified",
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="account-1",
            display_name="Unverified Branch",
            status="active",
            created_at=now,
        ),
        Channel(
            id="channel-verified",
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="account-1",
            display_name="Verified Branch",
            status="active",
            created_at=now - timedelta(days=1),
        ),
        VerificationRecord(
            channel_id="channel-unverified",
            status="pending",
        ),
        VerificationRecord(
            channel_id="channel-verified",
            status="verified",
            verified_at=now,
        ),
    ])
    await db.commit()

    response = client.get("/api/v1/channels")
    assert response.status_code == 200, response.text
    channels = {channel["id"]: channel for channel in response.json()["channels"]}

    assert channels["channel-verified"]["verification_status"] == "verified"
    assert channels["channel-verified"]["verified"] is True
    assert channels["channel-unverified"]["verification_status"] == "pending"
    assert channels["channel-unverified"]["verified"] is False
