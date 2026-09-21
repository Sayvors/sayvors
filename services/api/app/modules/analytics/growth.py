"""Grow-pillar intelligence: Google visibility, customer acquisition,
and rule-based growth opportunities.

All figures come from `location_daily_metrics` rollups written by the
performance sync worker (GBP Performance API) — no Google calls on the
read path.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LocationDailyMetric, ReviewInsight, SearchKeywordStat

logger = logging.getLogger(__name__)


def _prev_window(days: int) -> tuple[datetime, datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    return start, now, prev_start, start


async def _totals(db: AsyncSession, user_id: str, channel_id: str | None, start: datetime, end: datetime) -> dict:
    filters = [LocationDailyMetric.user_id == user_id, LocationDailyMetric.date >= start.date(), LocationDailyMetric.date < end.date()]
    if channel_id:
        filters.append(LocationDailyMetric.channel_id == channel_id)
    row = (
        await db.execute(
            select(
                func.sum(LocationDailyMetric.impressions_maps_desktop),
                func.sum(LocationDailyMetric.impressions_maps_mobile),
                func.sum(LocationDailyMetric.website_clicks),
                func.sum(LocationDailyMetric.call_clicks),
                func.sum(LocationDailyMetric.direction_requests),
            ).where(*filters)
        )
    ).one()
    desktop, mobile = row[0] or 0, row[1] or 0
    return {
        "impressions_maps": desktop + mobile,
        "website_clicks": row[2] or 0,
        "call_clicks": row[3] or 0,
        "direction_requests": row[4] or 0,
        "customer_actions": (row[2] or 0) + (row[3] or 0) + (row[4] or 0),
    }


def _delta(cur: int, prev: int) -> float | None:
    if prev == 0:
        return None
    return round(((cur - prev) / prev) * 100.0, 1)


async def get_visibility(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    start, end, prev_start, prev_end = _prev_window(days)
    cur = await _totals(db, user_id, channel_id, start, end)
    prev = await _totals(db, user_id, channel_id, prev_start, prev_end)
    return {
        "days": days,
        "impressions_maps": cur["impressions_maps"],
        "impressions_trend_pct": _delta(cur["impressions_maps"], prev["impressions_maps"]),
        "customer_actions": cur["customer_actions"],
        "actions_trend_pct": _delta(cur["customer_actions"], prev["customer_actions"]),
        "click_through_pct": round(cur["customer_actions"] / cur["impressions_maps"] * 100, 2) if cur["impressions_maps"] else None,
    }


async def get_acquisition(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    start, end, prev_start, prev_end = _prev_window(days)
    cur = await _totals(db, user_id, channel_id, start, end)
    prev = await _totals(db, user_id, channel_id, prev_start, prev_end)
    return {
        "days": days,
        "website_clicks": {"total": cur["website_clicks"], "trend_pct": _delta(cur["website_clicks"], prev["website_clicks"])},
        "call_clicks": {"total": cur["call_clicks"], "trend_pct": _delta(cur["call_clicks"], prev["call_clicks"])},
        "direction_requests": {"total": cur["direction_requests"], "trend_pct": _delta(cur["direction_requests"], prev["direction_requests"])},
        "customer_actions": {"total": cur["customer_actions"], "trend_pct": _delta(cur["customer_actions"], prev["customer_actions"])},
    }


async def get_opportunities(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    """Rule-based growth opportunities ranked by priority (P1-5, 1 = highest).

    Derived from live stored data: response rate, sentiment, problem trends,
    visibility, and review momentum. No LLM required — deterministic and fast.
    """
    from .service import get_overview
    from .intelligence import get_problems, get_products

    overview = await get_overview(db, user_id, channel_id, days)
    problems = (await get_problems(db, user_id, channel_id, days))["problems"]
    products = (await get_products(db, user_id, channel_id, days))

    opportunities: list[dict] = []

    # 1. Top problem growing -> operational fix
    top = next((p for p in problems if p["status"] in ("emerging", "increasing")), problems[0] if problems else None)
    if top:
        top_trend = top.get("trend_pct") or 0
        trend_txt = f", +{top_trend}%" if top_trend > 0 else ""
        opportunities.append({
            "priority": len(opportunities) + 1,
            "type": "operations",
            "title": f"Fix \u201c{top['name']}\u201d",
            "detail": (
                f"{top['mentions']} mentions this period ({top['status']})"
                + trend_txt
                + f". Severity: {top['severity']}."
            ),
        })

    # 2. Unanswered reviews -> response rate
    if overview["unanswered"] > 0:
        opportunities.append({
            "priority": len(opportunities) + 1,
            "type": "reputation",
            "title": f"Reply to {overview['unanswered']} unanswered reviews",
            "detail": f"Response rate is {overview['response_rate']}%. Replying to every review lifts both trust and your reputation score.",
        })

    # 3. Loved product -> promote via posts
    if products["most_loved"]:
        loved = next(p for p in products["products"] if p["name"] == products["most_loved"])
        opportunities.append({
            "priority": len(opportunities) + 1,
            "type": "marketing",
            "title": f"Promote \u201c{loved['name']}\u201d",
            "detail": f"{loved['positive_pct']}% positive across {loved['mentions']} mentions — a proven crowd-pleaser worth featuring in Google Posts.",
        })

    # 4. Visibility momentum
    gp = overview["google_performance"]
    if gp["impressions_maps"] > 0 and gp["customer_actions"] == 0:
        opportunities.append({
            "priority": len(opportunities) + 1,
            "type": "profile",
            "title": "Convert visibility into actions",
            "detail": f"{gp['impressions_maps']} impressions but no clicks/calls/directions yet — add photos, hours and a strong business description.",
        })

    # 5. Review momentum slowing
    p = overview["period"]
    if p["reviews_delta_pct"] is not None and p["reviews_delta_pct"] < 0:
        opportunities.append({
            "priority": len(opportunities) + 1,
            "type": "marketing",
            "title": "Ask happy customers for reviews",
            "detail": f"Review volume dropped {abs(p['reviews_delta_pct'])}% vs the previous period. A simple ask at checkout keeps momentum.",
        })

    return {"days": days, "opportunities": opportunities[:5]}


async def get_keywords(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    """Search keywords tenants were found by: keyword, impressions, trend.

    `available` is False for Localith-only tenants — keyword breakdowns
    come solely from the native Performance API, so the UI shows an honest
    empty state instead of fake rows.
    """
    from ..channels.models import Channel

    start, end, prev_start, prev_end = _prev_window(days)
    native = (
        await db.execute(
            select(Channel.id).where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
                Channel.access_token.is_not(None),
            )
        )
    ).scalars().all()
    if not native:
        return {"days": days, "available": False, "keywords": []}

    filters = [
        SearchKeywordStat.user_id == user_id,
        SearchKeywordStat.date >= start.date(),
        SearchKeywordStat.date < end.date(),
    ]
    prev_filters = [
        SearchKeywordStat.user_id == user_id,
        SearchKeywordStat.date >= prev_start.date(),
        SearchKeywordStat.date < prev_end.date(),
    ]
    if channel_id:
        filters.append(SearchKeywordStat.channel_id == channel_id)
        prev_filters.append(SearchKeywordStat.channel_id == channel_id)

    cur_rows = (
        await db.execute(
            select(SearchKeywordStat.keyword, func.sum(SearchKeywordStat.impressions))
            .where(*filters)
            .group_by(SearchKeywordStat.keyword)
            .order_by(func.sum(SearchKeywordStat.impressions).desc())
            .limit(25)
        )
    ).all()
    prev_rows = (
        await db.execute(
            select(SearchKeywordStat.keyword, func.sum(SearchKeywordStat.impressions))
            .where(*prev_filters)
            .group_by(SearchKeywordStat.keyword)
        )
    ).all()
    prev_map = {k: int(v or 0) for k, v in prev_rows}
    keywords = [
        {
            "keyword": k,
            "impressions": int(v or 0),
            "trend_pct": _delta(int(v or 0), prev_map.get(k, 0)),
        }
        for k, v in cur_rows
    ]
    return {"days": days, "available": True, "keywords": keywords}
