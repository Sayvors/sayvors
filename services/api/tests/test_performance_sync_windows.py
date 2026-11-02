"""Day-window policy for the Localith performance sync.

Verified live against Localith on 2026-11-02: a day's listing_metrics are
materialized days late — T+1 returns an empty ``listings`` array, T+2/T+3
return all-zero rows, and real numbers appear around T+4..5. A sync that
fetches each day exactly once (the morning after) therefore bakes zeros in
permanently, which is exactly what the Overview Discovery/Actions cards
showed: every row from Oct 1 on was zero while Sep 18–28 carried real data.

The policy under test:
  * the trailing window is re-walked on every pass (idempotent upsert);
  * all-zero rows older than the trailing window are re-walked while their
    ``zero_checks`` counter is under the cap — a lagged day heals, a genuinely
    quiet day converges to confirmed-quiet and stops costing calls.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics import performance
from app.modules.analytics.models import LocationDailyMetric
from app.modules.channels.models import Channel

# tests/ has no __init__.py: pytest loads the conftest as top-level module
# "conftest". Importing "tests.conftest" would create a SECOND module
# instance with a second, empty in-memory engine.
from conftest import TEST_ENGINE


def _session_factory():
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


def _end() -> date:
    """The sync's end date: yesterday UTC."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date() - timedelta(days=1)


class _Recorder:
    """Stands in for embedsocial.fetch_listing_metrics_for_day."""

    def __init__(self, value_for=None):
        self.requested: list[date] = []
        self.value_for = value_for or {}

    def __call__(self, listing_id, day):
        self.requested.append(day)
        return self.value_for.get(day, {
            "impressions_maps_desktop": 0,
            "impressions_maps_mobile": 0,
            "impressions_search": 0,
            "website_clicks": 0,
            "call_clicks": 0,
            "direction_requests": 0,
            "messages": 0,
            "bookings": 0,
        })


@pytest_asyncio.fixture
async def localith_channel(db, user_id):
    channel = Channel(
        id="perf-sync-channel-0000-0000-000000000001",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="localith-listing",
        display_name="Perf Sync Test",
        status="active",
        metadata_json='{"provider": "localith", "listing_id": "listing-1"}',
    )
    db.add(channel)
    await db.commit()
    return channel


def _patch_sync(monkeypatch, recorder: _Recorder) -> None:
    monkeypatch.setattr(performance, "async_session", _session_factory())
    monkeypatch.setattr(performance.embedsocial,
                        "fetch_listing_metrics_for_day", recorder)


def _zero_row(channel_id: str, user_id: str, day: date, zero_checks: int = 0):
    return LocationDailyMetric(
        id=f"row-{channel_id[:6]}-{day.isoformat()}-{zero_checks}",
        channel_id=channel_id,
        user_id=user_id,
        date=day,
        impressions_maps_desktop=0,
        impressions_maps_mobile=0,
        website_clicks=0,
        call_clicks=0,
        direction_requests=0,
        extra={"impressions_search": 0, "messages": 0, "bookings": 0,
               "source": "localith", "zero_checks": zero_checks},
    )


@pytest.mark.asyncio
async def test_trailing_window_is_rewalked_when_everything_exists(
    db, user_id, localith_channel, monkeypatch
):
    """A fully-synced channel must still re-fetch the trailing window —
    that is what overwrites the zeros Localith wrote before its metrics
    materialized."""
    end = _end()
    for i in range(10):
        db.add(_zero_row(localith_channel.id, user_id, end - timedelta(days=i)))
    await db.commit()

    recorder = _Recorder()
    _patch_sync(monkeypatch, recorder)
    await performance._sync_localith_channel(localith_channel)

    trailing = {end - timedelta(days=i) for i in range(performance._LOCALITH_METRICS_LAG_DAYS)}
    assert trailing <= set(recorder.requested), (
        f"trailing window not re-walked: missing {trailing - set(recorder.requested)}"
    )


@pytest.mark.asyncio
async def test_suspect_zero_row_is_rewalked_and_heals(
    db, user_id, localith_channel, monkeypatch
):
    """An all-zero row older than the lag window is premature until proven
    quiet: it must be re-fetched, and real values must overwrite it."""
    end = _end()
    suspect_day = end - timedelta(days=performance._LOCALITH_METRICS_LAG_DAYS + 3)
    db.add(_zero_row(localith_channel.id, user_id, suspect_day, zero_checks=0))
    # A recent day so `latest` sits ahead of the suspect row.
    db.add(_zero_row(localith_channel.id, user_id, end))
    await db.commit()

    healed = _Recorder(value_for={
        suspect_day: {
            "impressions_maps_desktop": 0, "impressions_maps_mobile": 3,
            "impressions_search": 1, "website_clicks": 0, "call_clicks": 0,
            "direction_requests": 2, "messages": 0, "bookings": 0,
        },
    })
    _patch_sync(monkeypatch, healed)
    await performance._sync_localith_channel(localith_channel)
    assert suspect_day in healed.requested

    row = (
        await db.execute(
            select(LocationDailyMetric).where(
                LocationDailyMetric.channel_id == localith_channel.id,
                LocationDailyMetric.date == suspect_day,
            )
        )
    ).scalar_one()
    await db.refresh(row)
    assert row.impressions_maps_mobile == 3
    assert row.direction_requests == 2
    assert row.extra["impressions_search"] == 1


@pytest.mark.asyncio
async def test_confirmed_quiet_day_stops_costing_calls(
    db, user_id, localith_channel, monkeypatch
):
    """A day that stayed zero through the re-check cap is quiet: it must
    not be requested again — bounded API spend, convergent behavior."""
    end = _end()
    quiet_day = end - timedelta(days=performance._LOCALITH_METRICS_LAG_DAYS + 5)
    db.add(_zero_row(localith_channel.id, user_id, quiet_day,
                     zero_checks=performance._LOCALITH_ZERO_RECHECKS))
    db.add(_zero_row(localith_channel.id, user_id, end))
    await db.commit()

    recorder = _Recorder()
    _patch_sync(monkeypatch, recorder)
    await performance._sync_localith_channel(localith_channel)
    assert quiet_day not in recorder.requested


@pytest.mark.asyncio
async def test_all_zero_upsert_bumps_the_recheck_counter(
    db, user_id, localith_channel, monkeypatch
):
    """Every all-zero rewrite advances the counter; any real value clears
    it — that is what makes the suspect-day walk converge."""
    end = _end()
    day = end - timedelta(days=performance._LOCALITH_METRICS_LAG_DAYS + 2)
    db.add(_zero_row(localith_channel.id, user_id, day, zero_checks=1))
    db.add(_zero_row(localith_channel.id, user_id, end))
    await db.commit()

    recorder = _Recorder()
    _patch_sync(monkeypatch, recorder)
    await performance._sync_localith_channel(localith_channel)
    assert day in recorder.requested  # counter 1 < cap 2

    row = (
        await db.execute(
            select(LocationDailyMetric).where(
                LocationDailyMetric.channel_id == localith_channel.id,
                LocationDailyMetric.date == day,
            )
        )
    ).scalar_one()
    await db.refresh(row)
    assert row.extra["zero_checks"] == 2

    # Next pass: counter at cap → not requested again.
    recorder2 = _Recorder()
    _patch_sync(monkeypatch, recorder2)
    await performance._sync_localith_channel(localith_channel)
    assert day not in recorder2.requested


@pytest.mark.asyncio
async def test_fresh_channel_backfills_oldest_first_with_trailing_priority(
    db, user_id, localith_channel, monkeypatch
):
    """No history: the first pass must cover the trailing window plus the
    oldest gap days, under the per-pass cap."""
    recorder = _Recorder()
    _patch_sync(monkeypatch, recorder)
    await performance._sync_localith_channel(localith_channel)

    end = _end()
    oldest_wanted = end - timedelta(days=performance._LOCALITH_BACKFILL_DAYS - 1)
    requested = set(recorder.requested)
    trailing = {end - timedelta(days=i) for i in range(performance._LOCALITH_METRICS_LAG_DAYS)}
    assert trailing <= requested
    assert len(recorder.requested) <= max(
        performance._LOCALITH_DAYS_PER_PASS, performance._LOCALITH_METRICS_LAG_DAYS
    )
    assert oldest_wanted in requested, "backfill must start at the oldest wanted day"
