"""Analytics aggregation service: KPIs, trends, scores.

All figures are computed from persisted rows (`review_insights`,
`location_daily_metrics`, `review_replies`) — no external calls on the read
path, so dashboards stay fast and deterministic.
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import ReviewReply
from .models import ChannelDailyMetric, LocationDailyMetric, ReviewInsight

logger = logging.getLogger(__name__)


def _day_bounds(day) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def reputation_score(avg_rating: float, response_rate: float, positive_ratio: float) -> int:
    """0-100 composite: rating (50) + response rate (25) + sentiment (25)."""
    return int(round(
        (avg_rating / 5.0) * 50 + response_rate * 25 + positive_ratio * 25
    ))


def health_score(avg_rating: float, response_rate: float, positive_ratio: float, velocity_ratio: float) -> int:
    """0-100 business health: reputation blended with review momentum.

    velocity_ratio: reviews this period vs previous period (1.0 = flat).
    """
    rep = reputation_score(avg_rating, response_rate, positive_ratio)
    momentum = min(1.0, velocity_ratio / 2.0)  # 2x growth = full momentum credit
    return int(round(rep * 0.8 + momentum * 100 * 0.2))


async def get_overview(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30
) -> dict:
    """Top-level KPI block for the dashboard home."""
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)

    review_filter = [ReviewInsight.user_id == user_id]
    metric_filter = [LocationDailyMetric.user_id == user_id]
    if channel_id:
        review_filter.append(ReviewInsight.channel_id == channel_id)
        metric_filter.append(LocationDailyMetric.channel_id == channel_id)
    # A review Google no longer serves is not part of the merchant's visible
    # performance. Excluding it keeps a deleted 1-star review from dragging the
    # rating average and the response rate indefinitely.
    review_filter.append(ReviewInsight.removed_at.is_(None))

    # ── Totals (all time) ──
    total_row = (
        await db.execute(
            select(func.count(), func.avg(ReviewInsight.rating)).where(*review_filter)
        )
    ).one()
    total_reviews = total_row[0] or 0
    avg_rating = round(float(total_row[1] or 0.0), 2)

    # ── Rating distribution ──
    distribution_rows = (
        await db.execute(
            select(ReviewInsight.rating, func.count())
            .where(*review_filter)
            .group_by(ReviewInsight.rating)
        )
    ).all()
    distribution = {str(r): 0 for r in range(1, 6)}
    for rating, count in distribution_rows:
        distribution[str(rating)] = count

    # ── Sentiment split ──
    sentiment_rows = (
        await db.execute(
            select(ReviewInsight.sentiment, func.count())
            .where(*review_filter)
            .group_by(ReviewInsight.sentiment)
        )
    ).all()
    sentiment_counts = {s: c for s, c in sentiment_rows}
    pos = sentiment_counts.get("positive", 0)
    neu = sentiment_counts.get("neutral", 0)
    neg = sentiment_counts.get("negative", 0)
    sentiment_total = pos + neu + neg or 1

    # ── Response rate / avg response time ──
    replied_count = (
        await db.execute(
            select(func.count()).where(*review_filter, ReviewInsight.replied == True)  # noqa: E712
        )
    ).scalar() or 0
    response_rate = (replied_count / total_reviews) if total_reviews else 0.0

    response_seconds = None
    rt_row = (
        await db.execute(
            select(func.avg(
                func.extract("epoch", ReviewReply.created_at)
                - func.extract("epoch", func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at))
            )).where(
                *review_filter,
                ReviewInsight.replied == True,  # noqa: E712
                ReviewReply.review_id == ReviewInsight.review_id,
                ReviewReply.status == "posted",
            )
        )
    ).scalar()
    if rt_row is not None:
        response_seconds = int(rt_row)

    # ── Period vs previous period ──
    async def _period_counts(start: datetime, end: datetime) -> dict:
        bucket = func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)
        row = (
            await db.execute(
                select(
                    func.count(),
                    func.avg(ReviewInsight.rating),
                    func.sum(func.cast(ReviewInsight.sentiment == "positive", Integer)),
                ).where(*review_filter, bucket >= start, bucket < end)
            )
        ).one()
        reviews = row[0] or 0
        return {
            "reviews": reviews,
            "avg_rating": round(float(row[1] or 0.0), 2) if reviews else None,
            "positive": int(row[2] or 0),
        }

    current = await _period_counts(period_start, now)
    previous = await _period_counts(prev_start, period_start)

    def _delta(curr, prev) -> float | None:
        if prev in (None, 0) or curr is None:
            return None
        return round(((curr - prev) / prev) * 100.0, 1)

    velocity_ratio = (
        current["reviews"] / previous["reviews"] if previous["reviews"] else None
    )

    reputation = reputation_score(avg_rating, response_rate, pos / sentiment_total)
    health = health_score(
        avg_rating,
        response_rate,
        pos / sentiment_total,
        velocity_ratio if velocity_ratio else 1.0,
    )

    # ── Google performance totals (period) ──
    perf_row = (
        await db.execute(
            select(
                func.sum(LocationDailyMetric.impressions_maps_desktop),
                func.sum(LocationDailyMetric.impressions_maps_mobile),
                func.sum(LocationDailyMetric.website_clicks),
                func.sum(LocationDailyMetric.call_clicks),
                func.sum(LocationDailyMetric.direction_requests),
            ).where(
                *metric_filter,
                LocationDailyMetric.date >= (now - timedelta(days=days)).date(),
            )
        )
    ).one()
    customer_actions = (perf_row[2] or 0) + (perf_row[3] or 0) + (perf_row[4] or 0)

    return {
        "total_reviews": total_reviews,
        "avg_rating": avg_rating,
        "rating_distribution": distribution,
        "sentiment": {
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "positive_pct": round(pos / sentiment_total * 100, 1),
            "neutral_pct": round(neu / sentiment_total * 100, 1),
            "negative_pct": round(neg / sentiment_total * 100, 1),
        },
        "response_rate": round(response_rate * 100, 1),
        "avg_response_seconds": response_seconds,
        "unanswered": total_reviews - replied_count,
        "reputation_score": reputation,
        "health_score": health,
        "period": {
            "days": days,
            "reviews": current["reviews"],
            "avg_rating": current["avg_rating"],
            "reviews_delta_pct": _delta(current["reviews"], previous["reviews"]),
            "rating_delta": (
                round(current["avg_rating"] - previous["avg_rating"], 2)
                if current["avg_rating"] is not None and previous["avg_rating"] is not None
                else None
            ),
            "velocity_ratio": round(velocity_ratio, 2) if velocity_ratio else None,
        },
        "google_performance": {
            "impressions_maps": (perf_row[0] or 0) + (perf_row[1] or 0),
            "website_clicks": perf_row[2] or 0,
            "call_clicks": perf_row[3] or 0,
            "direction_requests": perf_row[4] or 0,
            "customer_actions": customer_actions,
        },
    }


async def get_timeseries(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30
) -> list[LocationDailyMetric]:
    """Daily rollup rows for charts."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    stmt = (
        select(LocationDailyMetric)
        .where(LocationDailyMetric.user_id == user_id, LocationDailyMetric.date >= since)
        .order_by(LocationDailyMetric.date)
    )
    if channel_id:
        stmt = stmt.where(LocationDailyMetric.channel_id == channel_id)
    return list((await db.execute(stmt)).scalars().all())


async def list_insights(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None = None,
    sentiment: str | None = None,
    rating: int | None = None,
    status: str | None = None,
    edited: bool | None = None,
    search: str | None = None,
    removed: bool | None = None,
    abusive: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ReviewInsight], int]:
    """Filterable, paginated enriched-review list (AI Review Inbox backbone).

    `removed` tri-state: None (default) hides reviews a complete sync no longer
    returns, True shows only those, False shows only the live ones. Hidden by
    default because a review Google dropped is not a review the merchant can
    act on, and leaving it in skews the response-rate counts.
    """
    filters = [ReviewInsight.user_id == user_id]
    if channel_id:
        filters.append(ReviewInsight.channel_id == channel_id)
    if sentiment in ("positive", "neutral", "negative"):
        filters.append(ReviewInsight.sentiment == sentiment)
    if rating is not None and 1 <= rating <= 5:
        filters.append(ReviewInsight.rating == rating)
    if edited is not None:
        filters.append(ReviewInsight.edited == edited)
    if removed is True:
        filters.append(ReviewInsight.removed_at.isnot(None))
    elif removed is not True:
        filters.append(ReviewInsight.removed_at.is_(None))
    if abusive is not None:
        filters.append(ReviewInsight.abuse_flagged == abusive)
    if status == "replied":
        filters.append(ReviewInsight.replied == True)  # noqa: E712
        filters.append(ReviewInsight.skipped == False)  # noqa: E722
    elif status == "unanswered":
        filters.append(ReviewInsight.replied == False)  # noqa: E722
        filters.append(ReviewInsight.skipped == False)  # noqa: E722
    elif status == "skipped":
        filters.append(ReviewInsight.skipped == True)  # noqa: E722
        filters.append(ReviewInsight.skipped == False)  # noqa: E722
    if search:
        like = f"%{search.lower()}%"
        filters.append(
            func.lower(func.coalesce(ReviewInsight.review_text, "")).like(like)
            | func.lower(func.coalesce(ReviewInsight.reviewer_name, "")).like(like)
        )

    total = (
        await db.execute(select(func.count()).where(*filters))
    ).scalar() or 0
    rows = (
        await db.execute(
            select(ReviewInsight)
            .where(*filters)
            .order_by(ReviewInsight.created_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
    ).scalars().all()
    await _attach_latest_replies(db, rows)
    return list(rows), total


async def _attach_latest_replies(db: AsyncSession, rows: list[ReviewInsight]) -> None:
    """Attach each insight's latest live response row (reply_id / reply_text
    / reply_status) in one batched query. Newest row wins per review;
    discarded (rejected) rows never surface as the response."""
    from ..channels.models import ReviewReply

    if not rows:
        return
    pairs = {(r.channel_id, r.review_id) for r in rows}
    channel_ids = {c for c, _ in pairs}
    review_ids = {r for _, r in pairs}
    replies = (
        await db.execute(
            select(ReviewReply)
            .where(
                ReviewReply.channel_id.in_(channel_ids),
                ReviewReply.review_id.in_(review_ids),
                ReviewReply.status.in_(
                    ["pending_approval", "posted", "failed", "approved"]
                ),
            )
            .order_by(ReviewReply.created_at.desc())
            .limit(2000)
        )
    ).scalars().all()
    latest: dict[tuple[str, str], ReviewReply] = {}
    for rep in replies:
        latest.setdefault((rep.channel_id, rep.review_id), rep)
    for insight in rows:
        rep = latest.get((insight.channel_id, insight.review_id))
        insight.reply_id = rep.id if rep else None  # type: ignore[attr-defined]
        insight.reply_text = rep.reply_text if rep else None  # type: ignore[attr-defined]
        insight.reply_status = rep.status if rep else None  # type: ignore[attr-defined]


# ── Messaging overview (read path over channel_daily_metrics) ─────────
#
# Meta grades a Page "Very responsive to messages" at a 90% response rate
# with a median reply under 15 minutes. Those two numbers are the goal line
# here too — Meta gives owners the badge pressure, Sayvors gives them the
# tooling to actually see and move the numbers.

MESSAGING_GOAL = {"response_rate": 90.0, "median_seconds": 900}


def _delta_pct(cur: float | int | None, prev: float | int | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


async def get_messaging_overview(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None,
    days: int,
) -> dict:
    """Window aggregates for the messaging section, served from stored
    `channel_daily_metrics` rows only. The window median/p90 come from the
    days' real FRT samples (never an average of daily medians); `unanswered`
    is the sum of each channel's latest snapshot."""
    from statistics import median as _median

    from ..channels.models import Channel

    today = datetime.now(timezone.utc).date()
    cur_start = today - timedelta(days=days - 1)
    prev_start = today - timedelta(days=2 * days - 1)
    prev_end = cur_start  # exclusive

    def _scope():
        f = [ChannelDailyMetric.user_id == user_id]
        if channel_id:
            f.append(ChannelDailyMetric.channel_id == channel_id)
        return f

    cur_rows = (
        await db.execute(
            select(ChannelDailyMetric).where(
                *_scope(), ChannelDailyMetric.date >= cur_start
            )
        )
    ).scalars().all()
    prev_rows = (
        await db.execute(
            select(ChannelDailyMetric).where(
                *_scope(),
                ChannelDailyMetric.date >= prev_start,
                ChannelDailyMetric.date < prev_end,
            )
        )
    ).scalars().all()

    cur_by_channel: dict[str, list] = {}
    for r in cur_rows:
        cur_by_channel.setdefault(r.channel_id, []).append(r)
    prev_by_channel: dict[str, list] = {}
    for r in prev_rows:
        prev_by_channel.setdefault(r.channel_id, []).append(r)

    # Label + platform for every channel that appears in either window.
    channel_ids = sorted(set(cur_by_channel) | set(prev_by_channel))
    meta: dict[str, Channel] = {}
    if channel_ids:
        rows = await db.execute(
            select(Channel).where(Channel.id.in_(channel_ids))
        )
        meta = {c.id: c for c in rows.scalars().all()}

    def _sum(rs: list, attr: str) -> int:
        return sum(getattr(r, attr) or 0 for r in rs)

    def _rate(rs: list) -> float | None:
        convs = _sum(rs, "conversations_in")
        if convs == 0:
            return None
        return round(_sum(rs, "conversations_replied") / convs * 100, 1)

    def _samples(rs: list) -> list[int]:
        all_: list[int] = []
        for r in rs:
            all_.extend(r.frt_samples or [])
        return sorted(all_)

    def _channel_row(cid: str) -> dict:
        cur = cur_by_channel.get(cid, [])
        prev = prev_by_channel.get(cid, [])
        # Snapshot numbers come from the row with the highest date — that is
        # today's partial row whenever the worker has run recently.
        latest = max(cur, key=lambda r: r.date, default=None)
        samples = _samples(cur)
        return {
            "channel_id": cid,
            "platform": meta[cid].platform if cid in meta else "unknown",
            "label": meta[cid].display_name or meta[cid].platform if cid in meta else "Channel",
            "messages_in": _sum(cur, "messages_in"),
            "messages_out": _sum(cur, "messages_out"),
            "messages_in_prev": _sum(prev, "messages_in"),
            "conversations": _sum(cur, "conversations_in"),
            "conversations_prev": _sum(prev, "conversations_in"),
            "response_rate": _rate(cur),
            "median_first_response_seconds": (
                int(round(_median(samples))) if samples else None
            ),
            "unanswered_now": latest.unanswered_open if latest else None,
            "comments_in": _sum(cur, "comments_in"),
            "comments_replied": _sum(cur, "comments_replied"),
        }

    channel_rows = []
    for cid in channel_ids:
        row = _channel_row(cid)
        # A channel with zero traffic in BOTH windows is dead weight in the
        # scorecard — skip it rather than show a row of zeros.
        if row["messages_in"] or row["messages_out"] or row["messages_in_prev"]:
            channel_rows.append(row)
    channel_rows.sort(key=lambda r: -r["messages_in"])

    all_cur = cur_rows
    all_prev = prev_rows
    cur_samples = _samples(all_cur)
    prev_samples = _samples(all_prev)

    # Unanswered NOW = today's snapshots across channels; the oldest one
    # sets the worst age. NULL only when the worker has not run yet.
    latest_per_channel = [
        max(rs, key=lambda r: r.date) for rs in cur_by_channel.values()
    ]
    unanswered_now = sum(
        (r.unanswered_open or 0) for r in latest_per_channel
    )
    oldest = [
        r.oldest_unanswered_seconds for r in latest_per_channel
        if r.oldest_unanswered_seconds is not None
    ]
    as_of = max(
        (r.computed_at for r in latest_per_channel if r.computed_at is not None),
        default=None,
    )

    return {
        "days": days,
        "goal": MESSAGING_GOAL,
        "totals": {
            "messages_in": _sum(all_cur, "messages_in"),
            "messages_out": _sum(all_cur, "messages_out"),
            "messages_in_prev": _sum(all_prev, "messages_in"),
            "messages_out_prev": _sum(all_prev, "messages_out"),
            "conversations": _sum(all_cur, "conversations_in"),
            "conversations_prev": _sum(all_prev, "conversations_in"),
            "response_rate": _rate(all_cur),
            "response_rate_prev": _rate(all_prev),
            "median_first_response_seconds": (
                int(round(_median(cur_samples))) if cur_samples else None
            ),
            "median_first_response_seconds_prev": (
                int(round(_median(prev_samples))) if prev_samples else None
            ),
            "p90_first_response_seconds": (
                cur_samples[min(len(cur_samples) - 1, max(0, math.ceil(0.9 * len(cur_samples)) - 1))]
                if cur_samples else None
            ),
            "unanswered_now": unanswered_now if latest_per_channel else None,
            "oldest_unanswered_seconds": max(oldest) if oldest else None,
            "as_of": as_of,
        },
        "channels": channel_rows,
    }
