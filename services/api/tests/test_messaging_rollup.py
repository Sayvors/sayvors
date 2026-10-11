"""Messaging rollup worker + the /messaging/overview read path (sqlite).

The architecture rule under test: every number the endpoint returns comes
from stored `channel_daily_metrics` rows — the worker is the only writer,
and the endpoint never touches channel_messages.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics.messaging_rollup import rollup_channel_days
from app.modules.analytics.models import ChannelDailyMetric
from app.modules.channels.models import Channel, ChannelMessage


def _ts(minutes_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


async def _whatsapp_channel(db, user_id: str) -> Channel:
    channel = Channel(
        id=f"wa-{uuid4().hex[:12]}",
        user_id=user_id,
        platform="whatsapp",
        platform_user_id=f"1555{abs(hash(user_id)) % 10**8}",
        display_name="WA Main",
        status="active",
    )
    db.add(channel)
    await db.commit()
    return channel


def _msg(db, channel: Channel, direction: str, minutes_ago: float, phone: str = "+966500000001"):
    db.add(ChannelMessage(
        id=str(uuid4()),
        channel_id=channel.id,
        direction=direction,
        content="hi",
        status="sent",
        contact_phone=phone,
        created_at=_ts(minutes_ago),
    ))


async def _rows(db, channel_id: str) -> dict:
    rows = (
        (await db.execute(select(ChannelDailyMetric).where(ChannelDailyMetric.channel_id == channel_id)))
    ).scalars().all()
    return {r.date: r for r in rows}


@pytest.mark.asyncio
async def test_rollup_response_health(db, user_id):
    """Answered / unanswered / next-day-reply land in the right buckets.

    Timeline (relative to now):
      - conv A: inbound 50 min ago, answered 45 min ago  → FRT 5 min
      - conv B: inbound 20 min ago, NO reply             → unanswered snapshot
      - conv C: inbound yesterday, answered 30 min ago   → FRT ~23h, still
        counts toward YESTERDAY's row via the 48h lookback.
    """
    channel = await _whatsapp_channel(db, user_id)
    _msg(db, channel, "inbound", 50)
    _msg(db, channel, "outbound", 45)
    _msg(db, channel, "inbound", 20, phone="+966500000002")
    # Conv C: spoke yesterday, answered this morning.
    _msg(db, channel, "inbound", 24 * 60 + 60, phone="+966500000003")
    _msg(db, channel, "outbound", 30, phone="+966500000003")
    await db.commit()

    today = datetime.now(timezone.utc).date()
    written = await rollup_channel_days(db, channel, [today - timedelta(days=1), today])
    assert written == 2

    rows = await _rows(db, channel.id)

    yesterday_row = rows[today - timedelta(days=1)]
    # Conv C's inbound is the only inbound that fell inside yesterday.
    assert yesterday_row.messages_in == 1
    assert yesterday_row.conversations_in == 1
    assert yesterday_row.conversations_replied == 1
    assert yesterday_row.frt_samples and yesterday_row.frt_samples[0] > 22 * 3600
    # Frozen day: unanswered is a NOW snapshot, NULL on history.
    assert yesterday_row.unanswered_open is None

    today_row = rows[today]
    # Today: conv A pair + conv B inbound + conv C's late reply (outbound).
    assert today_row.messages_in == 2
    assert today_row.messages_out == 2
    assert today_row.conversations_in == 2  # A and B
    assert today_row.conversations_replied == 1  # only A
    assert today_row.unanswered_open == 1
    assert today_row.oldest_unanswered_seconds is not None
    # Median over A only (C's sample lives in yesterday's row).
    assert today_row.median_first_response_seconds == 300

    # Idempotent: a second pass rewrites in place, never twins.
    await rollup_channel_days(db, channel, [today])
    again = list((await _rows(db, channel.id)).values())
    assert len(again) == 2
    today_again = next(r for r in again if r.date == today)
    assert today_again.messages_in == 2


@pytest.mark.asyncio
async def test_endpoint_reads_stored_rows(db, user_id, client):
    """The endpoint serves aggregates over stored rows, per channel + totals."""
    channel = await _whatsapp_channel(db, user_id)
    _msg(db, channel, "inbound", 60)
    _msg(db, channel, "outbound", 55)
    await db.commit()
    await rollup_channel_days(db, channel, [datetime.now(timezone.utc).date()])

    r = client.get(
        "/api/v1/analytics/messaging/overview?days=7", headers={"host": "localhost"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert body["goal"] == {"response_rate": 90.0, "median_seconds": 900}
    assert body["totals"]["messages_in"] == 1
    assert body["totals"]["messages_out"] == 1
    assert body["totals"]["response_rate"] == 100.0
    assert body["totals"]["median_first_response_seconds"] == 300
    assert body["totals"]["unanswered_now"] == 0
    assert len(body["channels"]) == 1
    row = body["channels"][0]
    assert row["platform"] == "whatsapp"
    assert row["label"] == "WA Main"
    assert row["messages_in"] == 1


@pytest.mark.asyncio
async def test_endpoint_window_median_and_prev_window(db, user_id, client):
    """Current vs previous windows; window median/p90 from real samples."""
    channel = await _whatsapp_channel(db, user_id)
    today = datetime.now(timezone.utc).date()
    for back, m_in, m_out, samples in [
        (0, 10, 8, [600, 1200]),  # current window
        (10, 5, 2, [300]),        # previous window for days=7 (covers 8..14 back)
    ]:
        db.add(ChannelDailyMetric(
            id=str(uuid4()),
            channel_id=channel.id,
            user_id=user_id,
            date=today - timedelta(days=back),
            messages_in=m_in,
            messages_out=m_out,
            conversations_in=m_in,
            conversations_replied=m_out,
            frt_samples=samples,
            computed_at=_ts(5),
        ))
    await db.commit()

    r = client.get(
        "/api/v1/analytics/messaging/overview?days=7", headers={"host": "localhost"}
    )
    assert r.status_code == 200
    body = r.json()
    t = body["totals"]
    assert t["messages_in"] == 10
    assert t["messages_in_prev"] == 5
    # Window median from the concatenated samples, not an average of medians:
    # median([600, 1200]) = 900.
    assert t["median_first_response_seconds"] == 900
    assert t["p90_first_response_seconds"] == 1200
    assert len(body["channels"]) == 1
    assert body["channels"][0]["messages_in_prev"] == 5
