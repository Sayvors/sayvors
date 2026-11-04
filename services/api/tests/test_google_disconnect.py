"""Google soft disconnect/reconnect: data is hidden, never deleted."""
import json

import pytest
from sqlalchemy import select

from app.modules.analytics.models import ReviewInsight
from app.modules.analytics.service import get_overview
from app.modules.channels.models import Channel
from app.modules.channels.service import encrypt_token


def _google_channel(user_id: str, idx: int, status: str = "active") -> Channel:
    location_id = f"loc-{idx}"
    return Channel(
        id=f"ch-google-{idx}",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="acct-1",
        display_name=f"Branch {idx}",
        status=status,
        listing_key=location_id,
        access_token=encrypt_token(f"access-{idx}") if status != "disconnected" else None,
        refresh_token=encrypt_token(f"refresh-{idx}") if status != "disconnected" else None,
        metadata_json=json.dumps({
            "location_id": location_id,
            "address": f"Riyadh {idx}",
            "phone": "+966 55 000 0000",
            "website": "https://example.test",
        }),
    )


@pytest.mark.asyncio
async def test_disconnect_google_is_soft_and_hides_channels(client, db, user_id):
    db.add_all([_google_channel(user_id, 1), _google_channel(user_id, 2)])
    await db.commit()

    res = client.post("/api/v1/channels/google/disconnect")
    assert res.status_code == 200, res.text
    assert res.json()["disconnected"] == 2

    rows = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
            )
        )
    ).scalars().all()
    assert len(rows) == 2
    for channel in rows:
        assert channel.status == "disconnected"
        assert channel.access_token is None
        assert channel.refresh_token is None
        # Business data is preserved for reconnect and for the audit trail.
        assert channel.display_name.startswith("Branch")
        assert json.loads(channel.metadata_json)["address"].startswith("Riyadh")

    default_list = client.get("/api/v1/channels").json()["channels"]
    assert not [c for c in default_list if c["platform"] == "google_reviews"]

    with_disconnected = client.get(
        "/api/v1/channels?include_disconnected=true"
    ).json()["channels"]
    google = [c for c in with_disconnected if c["platform"] == "google_reviews"]
    assert len(google) == 2
    assert {c["status"] for c in google} == {"disconnected"}


@pytest.mark.asyncio
async def test_disconnected_reviews_hidden_then_restored(db, user_id):
    channel = _google_channel(user_id, 1)
    db.add(channel)
    db.add(ReviewInsight(
        id="rev-disconnect-1",
        user_id=user_id,
        channel_id=channel.id,
        review_id="rid-1",
        rating=5,
        review_text="Great",
        reviewer_name="Guest",
        sentiment="positive",
        sentiment_score=0.9,
    ))
    await db.commit()

    visible = await get_overview(db, user_id, None, 30)
    assert visible["total_reviews"] == 1

    channel.status = "disconnected"
    await db.commit()
    hidden = await get_overview(db, user_id, None, 30)
    assert hidden["total_reviews"] == 0

    # Reconnect = same row/status; the original review returns untouched.
    channel.status = "active"
    await db.commit()
    restored = await get_overview(db, user_id, None, 30)
    assert restored["total_reviews"] == 1
