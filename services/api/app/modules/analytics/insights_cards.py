"""Insights dashboard cards: themes, what changed, location sentiment, summary,
and the action plan.

One read for the Insights tab, built from persisted rows only. The heavy
aggregations (topics/problems) are reused from the intelligence layer; this
module adds the presentation-shaped pieces the cards need: a representative
quote, a location split, the 7-day change, and the stored action items.

Everything is tenant-scoped and bounded by the selected window. The summary is
deterministic (no model call on page load): every bullet carries the count it
was built from, so a skeptical owner can trace it. The stored AI report still
lives at /analytics/review-intelligence for the narrative version.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from . import intelligence
from .models import LocationIssue, ReviewInsight

logger = logging.getLogger(__name__)

MAX_THEMES = 5
MAX_ACTIONS = 5


def _bucket():
    return func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)


def _tz(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _confidence(review_count: int) -> str:
    if review_count >= 100:
        return "high"
    if review_count >= 20:
        return "medium"
    return "low"


async def _channel_names(db: AsyncSession, user_id: str) -> dict[str, str]:
    rows = (
        await db.execute(
            select(Channel.id, Channel.display_name, Channel.platform).where(Channel.user_id == user_id)
        )
    ).all()
    return {cid: (name or platform or "Location") for cid, name, platform in rows}


async def get_insights_cards(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None = None,
    days: int = 30,
) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    base = [
        ReviewInsight.user_id == user_id,
        ReviewInsight.removed_at.is_(None),
        ReviewInsight.skipped.is_(False),
    ]
    if channel_id:
        base.append(ReviewInsight.channel_id == channel_id)
    bucket = _bucket()

    topics_payload = await intelligence.get_topics(db, user_id, channel_id, days)
    problems_payload = await intelligence.get_problems(db, user_id, channel_id, days)
    names = await _channel_names(db, user_id)
    review_count = (
        await db.execute(select(func.count()).where(*base, bucket >= start, bucket < now))
    ).scalar() or 0

    # One narrow read for the representative quotes + location split.
    rows = (
        await db.execute(
            select(
                ReviewInsight.topics,
                ReviewInsight.review_text,
                ReviewInsight.rating,
                ReviewInsight.channel_id,
            ).where(*base, bucket >= start, bucket < now)
        )
    ).all()
    locale_counts: dict[str, dict[str, int]] = {}
    quotes: dict[str, str] = {}
    for topics, text, rating, cid in rows:
        for item in topics or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"]).lower()
            locale_counts.setdefault(name, {})
            locale_counts[name][cid] = locale_counts[name].get(cid, 0) + 1
            if text and (name not in quotes or rating <= 3):
                quotes[name] = text.strip()[:220]

    top_themes = []
    for t in (topics_payload.get("topics") or [])[:MAX_THEMES]:
        name = str(t.get("name") or "").lower()
        per_loc = locale_counts.get(name, {})
        top_cid = max(per_loc, key=lambda k: per_loc[k]) if per_loc else None
        mentions = int(t.get("mentions") or 0)
        negative = int(t.get("negative") or 0)
        top_location = None
        if top_cid:
            total = sum(per_loc.values())
            # Name a location only when the theme is actually concentrated
            # there (sole location, or a clear majority). A theme spread evenly
            # across locations has no meaningful "top" one.
            if len(per_loc) == 1 or (total and per_loc[top_cid] / total >= 0.5):
                top_location = names.get(top_cid)
        top_themes.append({
            "name": name,
            "mentions": mentions,
            "negative": negative,
            "negative_pct": round((negative / mentions) * 100.0, 1) if mentions else 0.0,
            "trend_pct": t.get("trend_pct"),
            "top_location": top_location,
            "quote": quotes.get(name),
        })

    # ── What changed this week: last 7d vs the prior 7d ───────────────────
    week_start = now - timedelta(days=7)
    prior_week_start = week_start - timedelta(days=7)
    week_rows = (
        await db.execute(
            select(
                ReviewInsight.rating,
                ReviewInsight.problems,
                ReviewInsight.review_text,
                ReviewInsight.channel_id,
            ).where(*base, bucket >= week_start, bucket < now)
        )
    ).all()
    prior_neg = (
        await db.execute(
            select(func.count()).where(
                *base,
                bucket >= prior_week_start,
                bucket < week_start,
                ReviewInsight.rating <= 2,
            )
        )
    ).scalar() or 0
    low = [r for r in week_rows if int(r[0] or 0) <= 2]
    theme_counts: dict[str, int] = {}
    loc_counts: dict[str, int] = {}
    example = None
    for _rating, problems, text, cid in low:
        for item in problems or []:
            if isinstance(item, dict) and item.get("name"):
                name = str(item["name"]).lower()
                theme_counts[name] = theme_counts.get(name, 0) + 1
        loc_counts[cid] = loc_counts.get(cid, 0) + 1
        if text and example is None:
            example = text.strip()[:220]
    top_theme = max(theme_counts, key=lambda k: theme_counts[k]) if theme_counts else None
    top_loc_cid = max(loc_counts, key=lambda k: loc_counts[k]) if loc_counts else None

    what_changed = {
        "low_reviews": len(low),
        "prior_low_reviews": int(prior_neg),
        "theme": top_theme,
        "location": names.get(top_loc_cid) if top_loc_cid else None,
        "example": example,
        "period_days": 7,
    }

    # ── Sentiment by location: 90d vs prior 90d ───────────────────────────
    ninety_start = now - timedelta(days=90)
    prior_ninety_start = ninety_start - timedelta(days=90)
    loc_rows = (
        await db.execute(
            select(
                ReviewInsight.channel_id,
                func.avg(ReviewInsight.rating),
                func.count(),
                func.sum(case((ReviewInsight.replied.is_(True), 1), else_=0)),
            ).where(*base, bucket >= ninety_start, bucket < now).group_by(ReviewInsight.channel_id)
        )
    ).all()
    prior_rows = (
        await db.execute(
            select(ReviewInsight.channel_id, func.avg(ReviewInsight.rating)).where(
                *base, bucket >= prior_ninety_start, bucket < ninety_start
            ).group_by(ReviewInsight.channel_id)
        )
    ).all()
    prior_rating = {cid: float(avg) for cid, avg in prior_rows if avg is not None}
    theme_by_channel: dict[str, dict[str, int]] = {}
    # Derive the per-location negative theme from the period's problems rows.
    problem_rows = (
        await db.execute(
            select(ReviewInsight.channel_id, ReviewInsight.problems).where(*base, bucket >= start, bucket < now)
        )
    ).all()
    for cid, problems in problem_rows:
        for item in problems or []:
            if isinstance(item, dict) and item.get("name"):
                name = str(item["name"]).lower()
                theme_by_channel.setdefault(cid, {})
                theme_by_channel[cid][name] = theme_by_channel[cid].get(name, 0) + 1

    # Latest messaging snapshot for outstanding counts.
    from .pulse import get_pulse

    pulse = await get_pulse(db, user_id, channel_id, max(days, 30))
    unanswered_by_channel = {loc["channel_id"]: loc["unanswered"] for loc in pulse.get("locations", [])}

    sentiment_by_location = []
    for cid, avg, count, replied in loc_rows:
        rating = round(float(avg), 2) if avg is not None else None
        prior = prior_rating.get(cid)
        counts = theme_by_channel.get(cid, {})
        top_neg = max(counts, key=lambda k: counts[k]) if counts else None
        sentiment_by_location.append({
            "channel_id": cid,
            "name": names.get(cid, "Location"),
            "avg_rating": rating,
            "rating_trend": round(rating - prior, 2) if rating is not None and prior is not None else None,
            "top_negative_theme": top_neg,
            "response_rate": round((int(replied or 0) / int(count or 0)) * 100.0, 1) if count else 0.0,
            "unanswered": unanswered_by_channel.get(cid, 0),
        })
    sentiment_by_location.sort(key=lambda x: (x["avg_rating"] is None, x["avg_rating"] or 0))

    # ── Summary with receipts (deterministic) ─────────────────────────────
    bullets = []
    praised = [t for t in (topics_payload.get("topics") or []) if int(t.get("positive") or 0) > 0]
    if praised:
        best = max(praised, key=lambda t: int(t.get("positive") or 0))
        bullets.append({"text": f"Customers praise {best['name']}.", "n": int(best["positive"])})
    complaints = [p for p in (problems_payload.get("problems") or []) if int(p.get("mentions") or 0) > 0]
    if complaints:
        worst = max(complaints, key=lambda p: p.get("impact_score") or 0)
        bullets.append({"text": f"{worst['name']} is the main complaint.", "n": int(worst["mentions"])})
    if what_changed["low_reviews"] > 0:
        bullets.append({
            "text": f"{what_changed['low_reviews']} low-star reviews this week (prior week: {what_changed['prior_low_reviews']}).",
            "n": what_changed["low_reviews"],
        })
    summary = {
        "bullets": bullets,
        "review_count": int(review_count),
        "confidence": _confidence(review_count),
        "source": "data",
        "analyzed_at": now,
    }

    # ── Action plan: stored location issues ───────────────────────────────
    issue_filters = [LocationIssue.user_id == user_id, LocationIssue.status.in_(("open", "in_progress"))]
    if channel_id:
        issue_filters.append(LocationIssue.channel_id == channel_id)
    issues = (
        await db.execute(
            select(LocationIssue)
            .where(*issue_filters)
            .order_by(LocationIssue.negative_count.desc(), LocationIssue.created_at.desc())
            .limit(MAX_ACTIONS)
        )
    ).scalars().all()
    action_plan = [
        {
            "id": i.id,
            "subject": i.subject,
            "title": i.title,
            "detail": i.detail,
            "status": i.status,
            "negative_count": i.negative_count,
            "review_count": i.review_count,
        }
        for i in issues
    ]

    return {
        "days": days,
        "top_themes": top_themes,
        "what_changed": what_changed,
        "sentiment_by_location": sentiment_by_location,
        "summary": summary,
        "action_plan": action_plan,
    }
