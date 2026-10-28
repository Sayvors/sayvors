"""Pulse cards: reputation and "who is waiting" for the Overview page.

Two read-only aggregates over persisted rows, designed for a hot dashboard
path:

* Reputation pulse - period rating/count, prior-period delta, response rate,
  outstanding replies, source mix, last sync.
* Who is waiting - current unanswered conversations, median first response,
  channels with a customer waiting > 1 hour.

Every query is a SQL aggregate or a bounded window (tenant x days x channels),
so cost is proportional to one tenant's recent data, not the platform. No
external calls and no per-conversation scans on the request path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from .models import ChannelDailyMetric, ReviewInsight

logger = logging.getLogger(__name__)

# A customer waiting longer than this counts as "waiting too long" in the
# pulse. Chosen to match the alert threshold in the analytics plan (15 min is
# too noisy for a headline; one hour is the first real escalation).
WAITING_LONG_SECONDS = 60 * 60

# Upper bound on FRT samples held in memory per request. The rollup already
# thins each day to <=500 values; this cap keeps a 90-day x many-channel
# tenant from turning the pulse into a multi-million-int sort.
MAX_FRT_SAMPLES = 50_000


def _bucket():
    return func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)


def _delta_pct(curr: float | int | None, prev: float | int | None) -> float | None:
    if curr is None or prev in (None, 0):
        return None
    return round(((float(curr) - float(prev)) / float(prev)) * 100.0, 1)


async def get_pulse(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None = None,
    days: int = 30,
) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    # A removed review (Google no longer serves it) or a skipped one (reviewer
    # deleted it / reply impossible) is not part of the merchant's visible
    # performance, and counting it would depress the response rate forever.
    base = [
        ReviewInsight.user_id == user_id,
        ReviewInsight.removed_at.is_(None),
        ReviewInsight.skipped.is_(False),
    ]
    if channel_id:
        base.append(ReviewInsight.channel_id == channel_id)
    bucket = _bucket()

    # ── Reputation: current and prior period ──────────────────────────────
    cur_row = (
        await db.execute(
            select(
                func.count(),
                func.avg(ReviewInsight.rating),
                func.sum(case((ReviewInsight.replied.is_(True), 1), else_=0)),
            ).where(*base, bucket >= start, bucket < now)
        )
    ).one()
    prev_row = (
        await db.execute(
            select(
                func.count(),
                func.avg(ReviewInsight.rating),
            ).where(*base, bucket >= prev_start, bucket < start)
        )
    ).one()

    new_reviews = int(cur_row[0] or 0)
    avg_rating = round(float(cur_row[1] or 0.0), 2)
    replied_in_period = int(cur_row[2] or 0)
    prev_reviews = int(prev_row[0] or 0)
    prev_rating = round(float(prev_row[1]), 2) if prev_row[1] is not None else None

    response_rate = round((replied_in_period / new_reviews) * 100.0, 1) if new_reviews else 0.0

    # Outstanding replies are current state, not period state: a review from
    # 60 days ago still needs an answer today.
    outstanding = (
        await db.execute(
            select(
                func.count(),
                func.min(bucket),
            ).where(
                *base,
                ReviewInsight.replied.is_(False),
                ReviewInsight.skipped.is_(False),
            )
        )
    ).one()
    awaiting_reply = int(outstanding[0] or 0)
    oldest_wait_days = None
    oldest_at = outstanding[1]
    if oldest_at is not None:
        # SQLite returns naive datetimes; Postgres is tz-aware. Normalise so
        # the subtraction never mixes the two.
        if oldest_at.tzinfo is None:
            oldest_at = oldest_at.replace(tzinfo=timezone.utc)
        oldest_wait_days = max(0, int((now - oldest_at).total_seconds() // 86400))

    # Source mix for the period (channel -> platform), one aggregate query.
    source_rows = (
        await db.execute(
            select(Channel.platform, func.count())
            .join(ReviewInsight, ReviewInsight.channel_id == Channel.id)
            .where(*base, bucket >= start, bucket < now)
            .group_by(Channel.platform)
            .order_by(func.count().desc())
        )
    ).all()
    sources = [
        {"platform": platform or "unknown", "count": int(count or 0)}
        for platform, count in source_rows
    ]

    last_synced = (
        await db.execute(select(func.max(bucket)).where(*base))
    ).scalar()

    # ── Messaging: current wait + period response time ────────────────────
    today = now.date()
    lookback_start = today - timedelta(days=max(days, 2) - 1)
    metric_filters = [ChannelDailyMetric.user_id == user_id, ChannelDailyMetric.date >= lookback_start]
    if channel_id:
        metric_filters.append(ChannelDailyMetric.channel_id == channel_id)
    metrics = (
        await db.execute(
            select(
                ChannelDailyMetric.channel_id,
                ChannelDailyMetric.date,
                ChannelDailyMetric.frt_samples,
                ChannelDailyMetric.unanswered_open,
                ChannelDailyMetric.oldest_unanswered_seconds,
                ChannelDailyMetric.computed_at,
            ).where(*metric_filters)
        )
    ).all()

    latest_by_channel: dict[str, tuple] = {}
    samples: list[int] = []
    for cid, day, frt, unanswered, oldest, computed_at in metrics:
        current = latest_by_channel.get(cid)
        if current is None or day > current[0]:
            latest_by_channel[cid] = (day, unanswered, oldest, computed_at)
        if frt and len(samples) < MAX_FRT_SAMPLES:
            remaining = MAX_FRT_SAMPLES - len(samples)
            samples.extend(int(v) for v in frt[:remaining] if v is not None)

    unanswered_texts = sum(int(row[1] or 0) for row in latest_by_channel.values())
    oldest_values = [int(row[2]) for row in latest_by_channel.values() if row[2] is not None]
    waiting_over_1h = sum(1 for v in oldest_values if v > WAITING_LONG_SECONDS)
    oldest_unanswered_seconds = max(oldest_values) if oldest_values else None
    median_first_response_seconds = int(round(median(samples))) if samples else None
    messaging_as_of = max(
        (row[3] for row in latest_by_channel.values() if row[3] is not None),
        default=None,
    )

    return {
        "as_of": now,
        "period_days": days,
        "reputation": {
            "avg_rating": avg_rating,
            "rating_delta": (
                round(avg_rating - prev_rating, 2)
                if prev_rating is not None and new_reviews > 0
                else None
            ),
            "new_reviews": new_reviews,
            "new_reviews_delta_pct": _delta_pct(new_reviews, prev_reviews),
            "response_rate": response_rate,
            "awaiting_reply": awaiting_reply,
            "oldest_wait_days": oldest_wait_days,
            "sources": sources,
            "last_synced_at": last_synced,
        },
        "waiting": {
            "unanswered_texts": unanswered_texts,
            "missed_calls": None,
            "missed_calls_available": False,
            "median_first_response_seconds": median_first_response_seconds,
            "waiting_over_1h": waiting_over_1h,
            "oldest_unanswered_seconds": oldest_unanswered_seconds,
            "business_hours": None,
            "as_of": messaging_as_of,
        },
    }
