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

from sqlalchemy import and_, case, func, select
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

    # ── Location league: one aggregate, grouped by channel ────────────────
    in_period = bucket >= start
    loc_rows = (
        await db.execute(
            select(
                Channel.id,
                Channel.display_name,
                Channel.platform,
                func.count(case((in_period, 1), else_=None)),
                func.avg(case((in_period, ReviewInsight.rating), else_=None)),
                func.sum(case((and_(in_period, ReviewInsight.replied.is_(True)), 1), else_=0)),
                func.sum(case((ReviewInsight.replied.is_(False), 1), else_=0)),
            )
            .join(ReviewInsight, ReviewInsight.channel_id == Channel.id)
            .where(*base)
            .group_by(Channel.id, Channel.display_name, Channel.platform)
        )
    ).all()
    locations = []
    for cid, display_name, platform, n, avg, replied, unanswered in loc_rows:
        n = int(n or 0)
        rating = round(float(avg), 2) if avg is not None else None
        locations.append({
            "channel_id": cid,
            "name": display_name or platform or "Location",
            "platform": platform or "unknown",
            "new_reviews": n,
            "avg_rating": rating,
            "response_rate": round((int(replied or 0) / n) * 100.0, 1) if n else 0.0,
            "unanswered": int(unanswered or 0),
            "below_threshold": rating is not None and rating < 4.5 and n > 0,
        })
    # Worst-first: the location that needs a conversation leads the league.
    locations.sort(key=lambda x: (x["avg_rating"] is None, x["avg_rating"] or 0))

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

    # ── One thing that changed: the complaint area with the biggest move ──
    one_thing = None
    try:
        from . import intelligence

        problems = await intelligence.get_problems(db, user_id, channel_id, days)
        areas = problems.get("by_area") or []
        movers = [a for a in areas if a.get("trend_pct") is not None]
        top = max(movers, key=lambda a: abs(a["trend_pct"])) if movers else (max(areas, key=lambda a: a["mentions"]) if areas else None)
        if top is not None:
            one_thing = {
                "kind": "complaint_area",
                "category": top["category"],
                "mentions": top["mentions"],
                "trend_pct": top.get("trend_pct"),
                "status": top.get("status"),
                "staff_named": top.get("staff_named", 0),
                "serious": top.get("serious", 0),
                "top_terms": top.get("top_terms", []),
                "period_days": days,
            }
    except Exception as e:  # secondary card: log and omit, never fail the pulse
        logger.warning("pulse one_thing aggregation failed: %s", e)

    # ── Needs attention: built from the numbers already in hand ───────────
    attention: list[dict] = []
    if awaiting_reply > 0:
        attention.append({
            "kind": "reviews",
            "severity": "high" if (oldest_wait_days or 0) >= 2 else "medium",
            "title": f"{awaiting_reply} review{'s' if awaiting_reply != 1 else ''} awaiting reply",
            "detail": f"oldest {oldest_wait_days}d" if oldest_wait_days is not None else None,
            "href": "/dashboard/reviews?status=unanswered",
        })
    if waiting_over_1h > 0:
        attention.append({
            "kind": "messages",
            "severity": "high",
            "title": f"{waiting_over_1h} channel{'s' if waiting_over_1h != 1 else ''} with a customer waiting >1h",
            "detail": f"oldest {oldest_unanswered_seconds // 60} min" if oldest_unanswered_seconds is not None else None,
            "href": "/dashboard/channels/inbox",
        })
    for loc in [l for l in locations if l["below_threshold"]][:3]:
        attention.append({
            "kind": "location",
            "severity": "medium",
            "title": f"{loc['name']} at {loc['avg_rating']:.1f}\u2605",
            "detail": f"{loc['unanswered']} unanswered" if loc["unanswered"] else None,
            "href": "/dashboard/analytics?tab=insights",
        })
    if last_synced is not None:
        synced_at = last_synced if last_synced.tzinfo else last_synced.replace(tzinfo=timezone.utc)
        if (now - synced_at).total_seconds() > 86400:
            attention.append({
                "kind": "sync",
                "severity": "medium",
                "title": "Review sync is stale",
                "detail": "last success >24h ago",
                "href": "/dashboard/channels",
            })
    attention = attention[:5]

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
        "locations": locations,
        "one_thing": one_thing,
        "attention": attention,
    }
