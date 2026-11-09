"""The performance sync announces genuinely-new days on the Notifications
page (metrics_synced) and stays silent on steady-state re-syncs of days it
already has — at most one bell per channel per new day."""
import json
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analytics import performance
from app.modules.channels.models import Channel
from app.modules.channels.service import encrypt_token
from app.modules.notifications.models import Notification

_DAY_A = date(2026, 11, 8)
_DAY_B = date(2026, 11, 9)


def _series(days):
    """Google-shaped timeseries: metric -> [(date, value), ...]."""
    return {
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": [(d, 10) for d in days],
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS": [(d, 5) for d in days],
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": [(d, 2) for d in days],
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": [(d, 3) for d in days],
        "CALL_CLICKS": [(d, 1) for d in days],
        "WEBSITE_CLICKS": [(d, 4) for d in days],
        "BUSINESS_DIRECTION_REQUESTS": [(d, 7) for d in days],
    }


async def _channel(db, user_id):
    ch = Channel(
        id="perf-notify-channel",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="accounts/1",
        display_name="Perf Shop",
        access_token=encrypt_token("tok"),
        status="active",
        metadata_json=json.dumps({"location_id": "loc-9"}),
    )
    db.add(ch)
    await db.commit()
    return ch


def _install(monkeypatch, db, days):
    series = _series(days)

    class _FakeClient:
        def __init__(self, access_token, refresh_token=None):
            pass

        def set_known_expiry(self, expires_at):
            pass

        async def fetch_performance_timeseries(self, location_id, start, end):
            return series

        async def fetch_keyword_timeseries(self, location_id, start, end):
            return {}

        async def close(self):
            pass

    monkeypatch.setattr(performance, "GoogleReviewsClient", _FakeClient)
    monkeypatch.setattr(performance.settings, "GOOGLE_REVIEWS_MOCK", False)
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(performance, "async_session", factory)


async def _metrics_notes(db, user_id):
    rows = (
        await db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type == "metrics_synced",
            )
        )
    ).scalars().all()
    return rows


@pytest.mark.asyncio
async def test_first_sync_announces_new_days_with_numbers(db, user_id, monkeypatch):
    await _channel(db, user_id)
    _install(monkeypatch, db, [_DAY_A])

    touched = await performance._sync_channel(
        await db.get(Channel, "perf-notify-channel")
    )

    assert touched == 1
    notes = await _metrics_notes(db, user_id)
    assert len(notes) == 1
    assert (notes[0].data or {}).get("days") == 1
    assert (notes[0].data or {}).get("listing") == "Perf Shop"
    # Maps 10+5 plus search 2+3 impressions for the latest (only) day.
    assert "Impressions 20" in (notes[0].body or "")
    assert "Calls 1" in (notes[0].body or "")
    assert notes[0].href == "/dashboard/growth"


@pytest.mark.asyncio
async def test_resync_is_silent_and_new_day_announces_once(db, user_id, monkeypatch):
    channel = await _channel(db, user_id)
    _install(monkeypatch, db, [_DAY_A])
    await performance._sync_channel(channel)
    assert len(await _metrics_notes(db, user_id)) == 1

    # Steady state: the same days come back from Google and are re-upserted
    # — no new bell, or the 6h loop would ring four times a day forever.
    await performance._sync_channel(channel)
    assert len(await _metrics_notes(db, user_id)) == 1

    # A genuinely new day lands — exactly one more bell, naming that day.
    _install(monkeypatch, db, [_DAY_A, _DAY_B])
    await performance._sync_channel(channel)
    notes = await _metrics_notes(db, user_id)
    assert len(notes) == 2
    bodies = [n.body or "" for n in notes]
    assert sum(_DAY_B.isoformat() in b for b in bodies) == 1
