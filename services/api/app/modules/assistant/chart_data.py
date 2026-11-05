"""Read-only business datasets for Ask Sayvors charts.

Every dataset is a fixed, tenant-scoped aggregate. The chart planner can only
choose from this catalog and can only chart columns that exist in a returned
dataset, which is what keeps a generated visualization tied to real rows.

The module deliberately returns aggregates, never raw message bodies or review
text. `review_topics` reads the stored topic labels only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import (
    ChannelDailyMetric,
    LocationDailyMetric,
    ReviewInsight,
)
from ..channels.models import (
    Channel,
    ChannelMessage,
    ChannelThread,
    Lead,
    ReviewReply,
)
from ..jobs.models import Job
from ..llm.models import LLMUsageEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    label: str
    domain: str
    description: str
    supports_days: bool = True
    supports_platform: bool = False
    supports_location: bool = False
    suggested_type: str = "bar"


DATASETS: dict[str, DatasetSpec] = {
    "review_volume": DatasetSpec(
        "review_volume",
        "Review volume",
        "reviews",
        "Reviews over time with positive, neutral, negative and rating columns. "
        "Use line/area for the trend or stacked_bar for sentiment mix.",
        supports_platform=True,
        suggested_type="line",
    ),
    "rating_distribution": DatasetSpec(
        "rating_distribution",
        "Rating distribution",
        "reviews",
        "How many reviews sit at each star rating. Part-to-whole; bar or donut.",
        supports_platform=True,
        suggested_type="bar",
    ),
    "sentiment_distribution": DatasetSpec(
        "sentiment_distribution",
        "Sentiment distribution",
        "reviews",
        "Positive / neutral / negative review counts. Donut or bar.",
        supports_platform=True,
        suggested_type="donut",
    ),
    "reviews_by_location": DatasetSpec(
        "reviews_by_location",
        "Reviews by location",
        "reviews",
        "Review count and average rating per connected location. Bar or ranking.",
        supports_platform=True,
        supports_location=True,
        suggested_type="bar",
    ),
    "review_topics": DatasetSpec(
        "review_topics",
        "What reviewers mention",
        "reviews",
        "Most mentioned review topics with positive and negative counts. Ranking.",
        supports_platform=True,
        suggested_type="ranking",
    ),
    "reply_status": DatasetSpec(
        "reply_status",
        "Reply status",
        "reviews",
        "Review replies by status (posted, pending approval, failed, rejected). Donut or bar.",
        supports_platform=True,
        suggested_type="donut",
    ),
    "customer_growth": DatasetSpec(
        "customer_growth",
        "New customers",
        "customers",
        "New customer threads over time. Line or area.",
        supports_platform=True,
        suggested_type="area",
    ),
    "customers_by_platform": DatasetSpec(
        "customers_by_platform",
        "Customers by platform",
        "customers",
        "Customer count per channel platform. Donut or bar.",
        suggested_type="donut",
    ),
    "customer_categories": DatasetSpec(
        "customer_categories",
        "Customer categories",
        "customers",
        "Conversation categories (complaint, inquiry, feedback, normal). Bar or donut.",
        suggested_type="bar",
    ),
    "top_customers": DatasetSpec(
        "top_customers",
        "Most active customers",
        "customers",
        "Customers with the most messages. Ranking.",
        supports_platform=True,
        suggested_type="ranking",
    ),
    "message_volume": DatasetSpec(
        "message_volume",
        "Message volume",
        "whatsapp",
        "Inbound and outbound messages per day. Line, area or stacked bar.",
        supports_platform=True,
        suggested_type="area",
    ),
    "response_time": DatasetSpec(
        "response_time",
        "First response time",
        "whatsapp",
        "Daily median and p90 first-response time. Line.",
        supports_platform=True,
        suggested_type="line",
    ),
    "lead_pipeline": DatasetSpec(
        "lead_pipeline",
        "Lead pipeline",
        "sales",
        "Leads by sales stage (new, qualified, follow-up, converted, lost). Donut or bar.",
        supports_platform=True,
        suggested_type="donut",
    ),
    "lead_categories": DatasetSpec(
        "lead_categories",
        "Lead categories",
        "sales",
        "Leads by category (retail, wholesale, booking, quote, support, info). Bar.",
        supports_platform=True,
        suggested_type="bar",
    ),
    "lead_growth": DatasetSpec(
        "lead_growth",
        "New leads",
        "sales",
        "Leads created over time. Line or area.",
        supports_platform=True,
        suggested_type="area",
    ),
    "publishing_outcomes": DatasetSpec(
        "publishing_outcomes",
        "Publishing outcomes",
        "social",
        "Published-post jobs by status (succeeded, queued, failed, cancelled). Donut or bar.",
        suggested_type="donut",
    ),
    "post_activity": DatasetSpec(
        "post_activity",
        "Posting activity",
        "social",
        "Publishing jobs created over time. Line or area.",
        suggested_type="line",
    ),
    "follower_counts": DatasetSpec(
        "follower_counts",
        "Followers by platform",
        "social",
        "Latest follower count per platform. Bar or donut.",
        supports_days=False,
        suggested_type="bar",
    ),
    "google_visibility": DatasetSpec(
        "google_visibility",
        "Google visibility",
        "marketing",
        "Google impressions, calls, direction requests and website clicks over time.",
        suggested_type="line",
    ),
    "ai_spend_by_purpose": DatasetSpec(
        "ai_spend_by_purpose",
        "AI credit by purpose",
        "ai",
        "AI spend and call count by purpose (review reply, analytics, assistant). Bar or donut.",
        suggested_type="bar",
    ),
    "ai_spend_trend": DatasetSpec(
        "ai_spend_trend",
        "AI spend over time",
        "ai",
        "Daily AI spend and call count. Line or area.",
        suggested_type="line",
    ),
}


# Distributions and rankings are meaningful across all history. If the
# requested short window is empty, widening to all time is more useful than
# declaring "no data" about a business that simply has older records.
ALL_TIME_FALLBACK = {
    "rating_distribution",
    "sentiment_distribution",
    "reviews_by_location",
    "review_topics",
    "reply_status",
    "customers_by_platform",
    "customer_categories",
    "lead_pipeline",
    "lead_categories",
    "publishing_outcomes",
}


PURPOSE_LABELS: dict[str, str] = {    "review_engine.generate": "Review reply",
    "review_engine.analysis": "Review analysis",
    "review_engine.relevance_judge": "Review relevance",
    "analytics.enrichment": "Review enrichment",
    "analytics.meaning": "Review meaning",
    "analytics.intelligence": "Analytics insight",
    "analytics.summary": "Analytics summary",
    "analytics.mine_conversations": "Conversation mining",
    "analytics.abuse_triage": "Abuse triage",
    "conversation.context": "Conversation context",
    "review.qa": "Review Q&A",
    "review_request.template": "Review request",
    "chat.message": "Assistant chat",
    "assistant.chat": "Assistant chat",
    "posts.ai_draft": "Post draft",
    "memory.extract": "Memory extraction",
    "databank.business_profile": "Business profile",
    "databank.ask": "Databank answer",
    "whatsapp.render_style": "Reply style",
    "whatsapp.thread_stats": "Thread stats",
    "instagram.caption_suggest": "Instagram caption",
    "meta_voice_note": "Voice note",
    "voice.tts": "Text to speech",
    "tts.job": "Text to speech",
    "admin.test": "Admin test",
}

PLATFORM_LABELS = {
    "google_reviews": "Google Business",
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
    "facebook": "Messenger",
    "x": "X",
    "telegram": "Telegram",
    "linkedin": "LinkedIn",
}


def dataset_catalog() -> list[dict[str, Any]]:
    return [
        {
            "dataset": spec.key,
            "label": spec.label,
            "domain": spec.domain,
            "description": spec.description,
            "supports_days": spec.supports_days,
            "supports_platform": spec.supports_platform,
            "supports_location": spec.supports_location,
        }
        for spec in DATASETS.values()
    ]


def catalog_prompt() -> str:
    lines = []
    for spec in DATASETS.values():
        lines.append(f"- {spec.key}: {spec.description}")
    return "\n".join(lines)


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _kpi(label: str, value: Any, fmt: str = "number", delta: float | None = None) -> dict:
    return {"label": label, "value": _num(value) if value is not None else None,
            "format": fmt, "delta": delta}


def _col(key: str, label: str, kind: str = "number") -> dict:
    return {"key": key, "label": label, "type": kind}


def _window_start(days: int) -> datetime | None:
    if days <= 0:
        return None
    start = datetime.now(timezone.utc) - timedelta(days=days)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


async def _channels(
    db: AsyncSession,
    tenant_id: str,
    *,
    platform: str | None = None,
    location: str | None = None,
) -> list[Channel]:
    stmt = select(Channel).where(Channel.user_id == tenant_id)
    if platform:
        stmt = stmt.where(Channel.platform == platform)
    if location:
        stmt = stmt.where(func.lower(Channel.display_name).like(f"%{location.strip().lower()}%"))
    stmt = stmt.order_by(Channel.display_name.asc())
    return list((await db.execute(stmt)).scalars().all())


def _empty(spec: DatasetSpec, note: str) -> dict:
    return {
        "rows": [],
        "columns": [],
        "kpis": [],
        "suggested_type": spec.suggested_type,
        "suggested_x": "label",
        "suggested_series": [],
        "note": note,
    }


def _result(
    *,
    rows: list[dict],
    columns: list[dict],
    kpis: list[dict],
    suggested_type: str,
    suggested_series: list[str],
    note: str | None = None,
    suggested_x: str = "label",
) -> dict:
    return {
        "rows": rows,
        "columns": columns,
        "kpis": kpis,
        "suggested_type": suggested_type,
        "suggested_x": suggested_x,
        "suggested_series": suggested_series,
        "note": note,
    }


# ── Reviews ──────────────────────────────────────────────────────────

async def _review_volume(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["review_volume"], "No connected channels.")
    ids = [c.id for c in channels]
    day = func.date(func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at))
    stmt = (
        select(
            day.label("day"),
            func.count(ReviewInsight.id).label("reviews"),
            func.sum(case((ReviewInsight.sentiment == "positive", 1), else_=0)).label("positive"),
            func.sum(case((ReviewInsight.sentiment == "neutral", 1), else_=0)).label("neutral"),
            func.sum(case((ReviewInsight.sentiment == "negative", 1), else_=0)).label("negative"),
            func.avg(ReviewInsight.rating).label("average_rating"),
        )
        .where(ReviewInsight.user_id == tenant_id, ReviewInsight.channel_id.in_(ids))
        .group_by(day)
        .order_by(day)
    )
    if start is not None:
        stmt = stmt.where(
            func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= start
        )
    rows = []
    total = 0
    rating_sum = 0.0
    rating_n = 0
    for day_value, reviews, positive, neutral, negative, avg in (await db.execute(stmt)).all():
        reviews = int(reviews or 0)
        total += reviews
        if avg is not None:
            rating_sum += float(avg) * reviews
            rating_n += reviews
        rows.append({
            "label": _iso_date(day_value),
            "reviews": reviews,
            "positive": int(positive or 0),
            "neutral": int(neutral or 0),
            "negative": int(negative or 0),
            "average_rating": round(float(avg), 2) if avg is not None else None,
        })
    if not rows:
        return _empty(DATASETS["review_volume"], "No reviews in this window.")
    kpis = [
        _kpi("Reviews", total),
        _kpi("Average rating", round(rating_sum / rating_n, 2) if rating_n else None, "rating"),
        _kpi("Positive share", round(100 * sum(r["positive"] for r in rows) / total, 1) if total else None, "percent"),
    ]
    return _result(
        rows=rows[-90:],
        columns=[_col("label", "Date", "date"), _col("reviews", "Reviews"),
                 _col("positive", "Positive"), _col("neutral", "Neutral"),
                 _col("negative", "Negative"), _col("average_rating", "Average rating", "rating")],
        kpis=kpis,
        suggested_type="line",
        suggested_series=["reviews"],
    )


async def _rating_distribution(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["rating_distribution"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(ReviewInsight.rating, func.count(ReviewInsight.id))
        .where(ReviewInsight.user_id == tenant_id, ReviewInsight.channel_id.in_(ids))
        .group_by(ReviewInsight.rating)
        .order_by(ReviewInsight.rating.desc())
    )
    if start is not None:
        stmt = stmt.where(
            func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= start
        )
    values = [(int(r), int(n)) for r, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["rating_distribution"], "No reviews in this window.")
    total = sum(n for _, n in values)
    rating_sum = sum(r * n for r, n in values)
    rows = [{"label": f"{r} star", "reviews": n} for r, n in values]
    return _result(
        rows=rows,
        columns=[_col("label", "Rating", "string"), _col("reviews", "Reviews")],
        kpis=[_kpi("Reviews", total), _kpi("Average rating", round(rating_sum / total, 2), "rating")],
        suggested_type="bar",
        suggested_series=["reviews"],
    )


async def _sentiment_distribution(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["sentiment_distribution"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(ReviewInsight.sentiment, func.count(ReviewInsight.id))
        .where(ReviewInsight.user_id == tenant_id, ReviewInsight.channel_id.in_(ids))
        .group_by(ReviewInsight.sentiment)
    )
    if start is not None:
        stmt = stmt.where(
            func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= start
        )
    values = [(str(s or "neutral"), int(n)) for s, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["sentiment_distribution"], "No reviews in this window.")
    order = {"positive": 0, "neutral": 1, "negative": 2}
    values.sort(key=lambda x: order.get(x[0], 9))
    total = sum(n for _, n in values)
    positive = sum(n for s, n in values if s == "positive")
    rows = [{"label": s.title(), "reviews": n} for s, n in values]
    return _result(
        rows=rows,
        columns=[_col("label", "Sentiment", "string"), _col("reviews", "Reviews")],
        kpis=[_kpi("Positive share", round(100 * positive / total, 1), "percent"),
              _kpi("Reviews", total)],
        suggested_type="donut",
        suggested_series=["reviews"],
    )


async def _reviews_by_location(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["reviews_by_location"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(
            Channel.display_name,
            func.count(ReviewInsight.id),
            func.avg(ReviewInsight.rating),
        )
        .join(Channel, Channel.id == ReviewInsight.channel_id)
        .where(ReviewInsight.user_id == tenant_id, ReviewInsight.channel_id.in_(ids))
        .group_by(Channel.display_name)
        .order_by(func.count(ReviewInsight.id).desc())
    )
    if start is not None:
        stmt = stmt.where(
            func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= start
        )
    values = [(name or "Unnamed location", int(n), float(avg or 0)) for name, n, avg in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["reviews_by_location"], "No reviews in this window.")
    rows = [
        {"label": name, "reviews": n, "average_rating": round(avg, 2)}
        for name, n, avg in values[:12]
    ]
    return _result(
        rows=rows,
        columns=[_col("label", "Location", "string"), _col("reviews", "Reviews"),
                 _col("average_rating", "Average rating", "rating")],
        kpis=[_kpi("Locations", len(values)),
              _kpi("Reviews", sum(n for _, n, _ in values))],
        suggested_type="bar",
        suggested_series=["reviews"],
        note="Top 12 locations." if len(values) > 12 else None,
    )


async def _review_topics(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["review_topics"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(ReviewInsight.topics)
        .where(ReviewInsight.user_id == tenant_id, ReviewInsight.channel_id.in_(ids))
        .order_by(func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at).desc())
        .limit(3000)
    )
    if start is not None:
        stmt = stmt.where(
            func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= start
        )
    counts: dict[str, dict[str, int]] = {}
    for (topics,) in (await db.execute(stmt)).all():
        if not isinstance(topics, list):
            continue
        for topic in topics:
            if isinstance(topic, dict):
                name = str(topic.get("name") or "").strip()
                sentiment = str(topic.get("sentiment") or "").lower()
            else:
                name = str(topic or "").strip()
                sentiment = ""
            if not name:
                continue
            slot = counts.setdefault(name, {"mentions": 0, "positive": 0, "negative": 0})
            slot["mentions"] += 1
            if sentiment == "positive":
                slot["positive"] += 1
            elif sentiment == "negative":
                slot["negative"] += 1
    if not counts:
        return _empty(DATASETS["review_topics"], "No review topics in this window.")
    ordered = sorted(counts.items(), key=lambda item: item[1]["mentions"], reverse=True)[:10]
    rows = [{"label": name, **slot} for name, slot in ordered]
    return _result(
        rows=rows,
        columns=[_col("label", "Topic", "string"), _col("mentions", "Mentions"),
                 _col("positive", "Positive"), _col("negative", "Negative")],
        kpis=[_kpi("Topics", len(counts)), _kpi("Top topic", ordered[0][0], "text")],
        suggested_type="ranking",
        suggested_series=["mentions"],
    )


async def _reply_status(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["reply_status"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(ReviewReply.status, func.count(ReviewReply.id))
        .where(ReviewReply.channel_id.in_(ids))
        .group_by(ReviewReply.status)
    )
    if start is not None:
        stmt = stmt.where(ReviewReply.created_at >= start)
    values = [(str(s or "unknown"), int(n)) for s, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["reply_status"], "No review replies in this window.")
    total = sum(n for _, n in values)
    posted = sum(n for s, n in values if s == "posted")
    rows = [{"label": s.replace("_", " ").title(), "replies": n} for s, n in values]
    return _result(
        rows=rows,
        columns=[_col("label", "Status", "string"), _col("replies", "Replies")],
        kpis=[_kpi("Replies", total),
              _kpi("Posted share", round(100 * posted / total, 1), "percent")],
        suggested_type="donut",
        suggested_series=["replies"],
    )


# ── Customers ────────────────────────────────────────────────────────

async def _customer_growth(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["customer_growth"], "No connected channels.")
    ids = [c.id for c in channels]
    day = func.date(ChannelThread.created_at)
    stmt = (
        select(day, func.count(ChannelThread.id))
        .where(ChannelThread.channel_id.in_(ids))
        .group_by(day)
        .order_by(day)
    )
    if start is not None:
        stmt = stmt.where(ChannelThread.created_at >= start)
    values = [(_iso_date(d), int(n)) for d, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["customer_growth"], "No new customers in this window.")
    rows = [{"label": d, "new_customers": n} for d, n in values[-90:]]
    return _result(
        rows=rows,
        columns=[_col("label", "Date", "date"), _col("new_customers", "New customers")],
        kpis=[_kpi("New customers", sum(n for _, n in values))],
        suggested_type="area",
        suggested_series=["new_customers"],
    )


async def _customers_by_platform(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["customers_by_platform"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(Channel.platform, func.count(ChannelThread.id))
        .join(Channel, Channel.id == ChannelThread.channel_id)
        .where(ChannelThread.channel_id.in_(ids))
        .group_by(Channel.platform)
        .order_by(func.count(ChannelThread.id).desc())
    )
    if start is not None:
        stmt = stmt.where(ChannelThread.last_message_at >= start)
    values = [(str(p), int(n)) for p, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["customers_by_platform"], "No customers in this window.")
    rows = [{"label": PLATFORM_LABELS.get(p, p.replace("_", " ").title()), "customers": n} for p, n in values]
    return _result(
        rows=rows,
        columns=[_col("label", "Platform", "string"), _col("customers", "Customers")],
        kpis=[_kpi("Customers", sum(n for _, n in values)), _kpi("Platforms", len(values))],
        suggested_type="donut",
        suggested_series=["customers"],
    )


async def _customer_categories(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["customer_categories"], "No connected channels.")
    ids = [c.id for c in channels]
    label = func.coalesce(ChannelThread.category, "normal")
    stmt = (
        select(label, func.count(ChannelThread.id))
        .where(ChannelThread.channel_id.in_(ids))
        .group_by(label)
        .order_by(func.count(ChannelThread.id).desc())
    )
    if start is not None:
        stmt = stmt.where(ChannelThread.last_message_at >= start)
    values = [(str(c or "normal"), int(n)) for c, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["customer_categories"], "No customer categories in this window.")
    rows = [{"label": c.replace("_", " ").title(), "customers": n} for c, n in values]
    return _result(
        rows=rows,
        columns=[_col("label", "Category", "string"), _col("customers", "Customers")],
        kpis=[_kpi("Customers", sum(n for _, n in values))],
        suggested_type="bar",
        suggested_series=["customers"],
    )


async def _top_customers(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["top_customers"], "No connected channels.")
    ids = [c.id for c in channels]
    stmt = (
        select(
            ChannelThread.contact_name,
            ChannelThread.total_count,
            ChannelThread.unread_count,
            Channel.platform,
        )
        .join(Channel, Channel.id == ChannelThread.channel_id)
        .where(ChannelThread.channel_id.in_(ids))
        .order_by(ChannelThread.total_count.desc())
        .limit(10)
    )
    if start is not None:
        stmt = stmt.where(ChannelThread.last_message_at >= start)
    values = [
        (name or "Unknown customer", int(total or 0), int(unread or 0), str(platform or ""))
        for name, total, unread, platform in (await db.execute(stmt)).all()
    ]
    if not values:
        return _empty(DATASETS["top_customers"], "No customers in this window.")
    rows = [
        {"label": name, "messages": total, "unread": unread,
         "platform": PLATFORM_LABELS.get(platform, platform)}
        for name, total, unread, platform in values
    ]
    return _result(
        rows=rows,
        columns=[_col("label", "Customer", "string"), _col("messages", "Messages"),
                 _col("unread", "Unread"), _col("platform", "Platform", "string")],
        kpis=[_kpi("Customers shown", len(rows)),
              _kpi("Messages", sum(v[1] for v in values))],
        suggested_type="ranking",
        suggested_series=["messages"],
    )


# ── Messaging / WhatsApp ─────────────────────────────────────────────

async def _message_volume(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["message_volume"], "No connected channels.")
    ids = [c.id for c in channels]
    day = func.date(ChannelDailyMetric.date)
    stmt = (
        select(
            day,
            func.sum(ChannelDailyMetric.messages_in),
            func.sum(ChannelDailyMetric.messages_out),
        )
        .where(ChannelDailyMetric.user_id == tenant_id, ChannelDailyMetric.channel_id.in_(ids))
        .group_by(day)
        .order_by(day)
    )
    if start is not None:
        stmt = stmt.where(ChannelDailyMetric.date >= start.date())
    values = [
        (_iso_date(d), int(i or 0), int(o or 0))
        for d, i, o in (await db.execute(stmt)).all()
    ]
    fallback = False
    if not values:
        # Rollups are written by the analytics worker. A new tenant can have
        # real messages before the first rollup exists, so count the bounded
        # message window directly instead of claiming there is no data.
        fallback = True
        raw_day = func.date(ChannelMessage.created_at)
        raw_stmt = (
            select(
                raw_day,
                func.sum(case((ChannelMessage.direction == "inbound", 1), else_=0)),
                func.sum(case((ChannelMessage.direction == "outbound", 1), else_=0)),
            )
            .where(ChannelMessage.channel_id.in_(ids))
            .group_by(raw_day)
            .order_by(raw_day)
        )
        if start is not None:
            raw_stmt = raw_stmt.where(ChannelMessage.created_at >= start)
        values = [
            (_iso_date(d), int(i or 0), int(o or 0))
            for d, i, o in (await db.execute(raw_stmt)).all()
        ]
    if not values:
        return _empty(
            DATASETS["message_volume"],
            "No messages in this window.",
        )
    rows = [
        {"label": d, "inbound": i, "outbound": o, "messages": i + o}
        for d, i, o in values[-90:]
    ]
    total_in = sum(i for _, i, _ in values)
    total_out = sum(o for _, _, o in values)
    return _result(
        rows=rows,
        columns=[_col("label", "Date", "date"), _col("inbound", "Inbound"),
                 _col("outbound", "Outbound"), _col("messages", "Total")],
        kpis=[_kpi("Inbound", total_in), _kpi("Outbound", total_out),
              _kpi("Reply ratio", round(total_out / total_in, 2) if total_in else None, "ratio")],
        suggested_type="area",
        suggested_series=["inbound", "outbound"],
        note="Computed from messages until the daily rollup catches up." if fallback else None,
    )


async def _response_time(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["response_time"], "No connected channels.")
    ids = [c.id for c in channels]
    day = func.date(ChannelDailyMetric.date)
    stmt = (
        select(
            day,
            func.avg(ChannelDailyMetric.median_first_response_seconds),
            func.avg(ChannelDailyMetric.p90_first_response_seconds),
        )
        .where(
            ChannelDailyMetric.user_id == tenant_id,
            ChannelDailyMetric.channel_id.in_(ids),
            ChannelDailyMetric.median_first_response_seconds.is_not(None),
        )
        .group_by(day)
        .order_by(day)
    )
    if start is not None:
        stmt = stmt.where(ChannelDailyMetric.date >= start.date())
    values = [
        (_iso_date(d), round(float(m or 0)), round(float(p or 0)))
        for d, m, p in (await db.execute(stmt)).all()
    ]
    if not values:
        return _empty(DATASETS["response_time"], "No first-response samples in this window.")
    rows = [
        {"label": d, "median": m, "p90": p}
        for d, m, p in values[-90:]
    ]
    all_medians = [m for _, m, _ in values if m > 0]
    return _result(
        rows=rows,
        columns=[_col("label", "Date", "date"), _col("median", "Median", "seconds"),
                 _col("p90", "P90", "seconds")],
        kpis=[_kpi("Avg daily median", round(sum(all_medians) / len(all_medians)) if all_medians else None,
                   "seconds")],
        suggested_type="line",
        suggested_series=["median"],
    )


# ── Sales / leads ────────────────────────────────────────────────────

async def _lead_pipeline(db, tenant_id, channels, start, days) -> dict:
    stmt = (
        select(Lead.stage, func.count(Lead.id))
        .where(Lead.tenant_id == tenant_id)
        .group_by(Lead.stage)
    )
    if channels:
        stmt = stmt.where(Lead.channel_id.in_([c.id for c in channels]))
    if start is not None:
        stmt = stmt.where(Lead.created_at >= start)
    values = [(str(s or "new"), int(n)) for s, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["lead_pipeline"], "No leads in this window.")
    order = {"new": 0, "qualified": 1, "follow_up": 2, "converted": 3, "lost": 4}
    values.sort(key=lambda x: order.get(x[0], 9))
    rows = [{"label": s.replace("_", " ").title(), "leads": n} for s, n in values]
    converted = sum(n for s, n in values if s == "converted")
    total = sum(n for _, n in values)
    return _result(
        rows=rows,
        columns=[_col("label", "Stage", "string"), _col("leads", "Leads")],
        kpis=[_kpi("Leads", total), _kpi("Converted", converted),
              _kpi("Conversion", round(100 * converted / total, 1) if total else None, "percent")],
        suggested_type="donut",
        suggested_series=["leads"],
    )


async def _lead_categories(db, tenant_id, channels, start, days) -> dict:
    col = func.coalesce(Lead.category, "unclassified")
    stmt = (
        select(col, func.count(Lead.id))
        .where(Lead.tenant_id == tenant_id)
        .group_by(col)
        .order_by(func.count(Lead.id).desc())
    )
    if channels:
        stmt = stmt.where(Lead.channel_id.in_([c.id for c in channels]))
    if start is not None:
        stmt = stmt.where(Lead.created_at >= start)
    values = [(str(c or "unclassified"), int(n)) for c, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["lead_categories"], "No leads in this window.")
    rows = [{"label": c.replace("_", " ").title(), "leads": n} for c, n in values]
    return _result(
        rows=rows,
        columns=[_col("label", "Category", "string"), _col("leads", "Leads")],
        kpis=[_kpi("Leads", sum(n for _, n in values))],
        suggested_type="bar",
        suggested_series=["leads"],
    )


async def _lead_growth(db, tenant_id, channels, start, days) -> dict:
    day = func.date(Lead.created_at)
    stmt = (
        select(day, func.count(Lead.id))
        .where(Lead.tenant_id == tenant_id)
        .group_by(day)
        .order_by(day)
    )
    if channels:
        stmt = stmt.where(Lead.channel_id.in_([c.id for c in channels]))
    if start is not None:
        stmt = stmt.where(Lead.created_at >= start)
    values = [(_iso_date(d), int(n)) for d, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["lead_growth"], "No leads in this window.")
    rows = [{"label": d, "new_leads": n} for d, n in values[-90:]]
    return _result(
        rows=rows,
        columns=[_col("label", "Date", "date"), _col("new_leads", "New leads")],
        kpis=[_kpi("New leads", sum(n for _, n in values))],
        suggested_type="area",
        suggested_series=["new_leads"],
    )


# ── Social ───────────────────────────────────────────────────────────

async def _publishing_outcomes(db, tenant_id, channels, start, days) -> dict:
    stmt = (
        select(Job.status, func.count(Job.id))
        .where(Job.tenant_id == tenant_id, Job.job_type == "post_publish")
        .group_by(Job.status)
        .order_by(func.count(Job.id).desc())
    )
    if start is not None:
        stmt = stmt.where(Job.created_at >= start)
    values = [(str(s or "unknown"), int(n)) for s, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["publishing_outcomes"], "No publishing jobs in this window.")
    rows = [{"label": s.replace("_", " ").title(), "posts": n} for s, n in values]
    succeeded = sum(n for s, n in values if s in ("succeeded", "accepted"))
    total = sum(n for _, n in values)
    return _result(
        rows=rows,
        columns=[_col("label", "Status", "string"), _col("posts", "Posts")],
        kpis=[_kpi("Posts", total), _kpi("Succeeded", succeeded),
              _kpi("Success rate", round(100 * succeeded / total, 1) if total else None, "percent")],
        suggested_type="donut",
        suggested_series=["posts"],
    )


async def _post_activity(db, tenant_id, channels, start, days) -> dict:
    day = func.date(Job.created_at)
    stmt = (
        select(day, func.count(Job.id))
        .where(Job.tenant_id == tenant_id, Job.job_type == "post_publish")
        .group_by(day)
        .order_by(day)
    )
    if start is not None:
        stmt = stmt.where(Job.created_at >= start)
    values = [(_iso_date(d), int(n)) for d, n in (await db.execute(stmt)).all()]
    if not values:
        return _empty(DATASETS["post_activity"], "No publishing jobs in this window.")
    rows = [{"label": d, "posts": n} for d, n in values[-90:]]
    return _result(
        rows=rows,
        columns=[_col("label", "Date", "date"), _col("posts", "Posts")],
        kpis=[_kpi("Posts", sum(n for _, n in values))],
        suggested_type="line",
        suggested_series=["posts"],
    )


async def _follower_counts(db, tenant_id, channels, start, days) -> dict:
    if not channels:
        return _empty(DATASETS["follower_counts"], "No connected channels.")
    ids = [c.id for c in channels]
    rows = (
        await db.execute(
            select(
                ChannelDailyMetric.channel_id,
                Channel.platform,
                ChannelDailyMetric.followers_count,
                ChannelDailyMetric.date,
            )
            .join(Channel, Channel.id == ChannelDailyMetric.channel_id)
            .where(
                ChannelDailyMetric.user_id == tenant_id,
                ChannelDailyMetric.channel_id.in_(ids),
                ChannelDailyMetric.followers_count.is_not(None),
            )
            .order_by(ChannelDailyMetric.date.desc())
        )
    ).all()
    latest: dict[str, int] = {}
    seen_channels: set[str] = set()
    for channel_id, platform, count, _ in rows:
        if channel_id in seen_channels or count is None:
            continue
        seen_channels.add(channel_id)
        key = str(platform or "")
        latest[key] = latest.get(key, 0) + int(count)
    if not latest:
        return _empty(DATASETS["follower_counts"], "No follower snapshots yet.")
    ordered = sorted(latest.items(), key=lambda item: item[1], reverse=True)
    out = [
        {"label": PLATFORM_LABELS.get(p, p.replace("_", " ").title()), "followers": n}
        for p, n in ordered
    ]
    return _result(
        rows=out,
        columns=[_col("label", "Platform", "string"), _col("followers", "Followers")],
        kpis=[_kpi("Followers", sum(latest.values()))],
        suggested_type="bar",
        suggested_series=["followers"],
    )


# ── Marketing visibility ─────────────────────────────────────────────

async def _google_visibility(db, tenant_id, channels, start, days) -> dict:
    ids = [c.id for c in channels if c.platform == "google_reviews"]
    if not ids:
        return _empty(DATASETS["google_visibility"], "No Google Business locations connected.")
    stmt = (
        select(LocationDailyMetric)
        .where(LocationDailyMetric.user_id == tenant_id,
               LocationDailyMetric.channel_id.in_(ids))
        .order_by(LocationDailyMetric.date)
    )
    if start is not None:
        stmt = stmt.where(LocationDailyMetric.date >= start.date())
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return _empty(DATASETS["google_visibility"], "No Google performance rows in this window.")
    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        key = _iso_date(row.date)
        slot = by_day.setdefault(key, {"impressions": 0, "calls": 0, "directions": 0, "website": 0})
        slot["impressions"] += int(row.impressions_maps_desktop or 0) + int(row.impressions_maps_mobile or 0)
        slot["calls"] += int(row.call_clicks or 0)
        slot["directions"] += int(row.direction_requests or 0)
        slot["website"] += int(row.website_clicks or 0)
        extra = row.extra if isinstance(row.extra, dict) else {}
        slot["impressions"] += int(extra.get("impressions_search", 0) or 0)
    ordered = sorted(by_day.items())
    out = [{"label": d, **vals} for d, vals in ordered[-90:]]
    totals = {k: sum(v[k] for _, v in ordered) for k in ("impressions", "calls", "directions", "website")}
    return _result(
        rows=out,
        columns=[_col("label", "Date", "date"), _col("impressions", "Impressions"),
                 _col("calls", "Calls"), _col("directions", "Directions"),
                 _col("website", "Website clicks")],
        kpis=[_kpi("Impressions", totals["impressions"]), _kpi("Calls", totals["calls"]),
              _kpi("Direction requests", totals["directions"]),
              _kpi("Website clicks", totals["website"])],
        suggested_type="line",
        suggested_series=["impressions"],
    )


# ── AI usage ─────────────────────────────────────────────────────────

async def _ai_spend_by_purpose(db, tenant_id, channels, start, days) -> dict:
    stmt = (
        select(
            LLMUsageEvent.purpose,
            func.sum(LLMUsageEvent.cost_cents),
            func.count(LLMUsageEvent.id),
        )
        .where(LLMUsageEvent.tenant_id == tenant_id)
        .group_by(LLMUsageEvent.purpose)
        .order_by(func.sum(LLMUsageEvent.cost_cents).desc())
    )
    if start is not None:
        stmt = stmt.where(LLMUsageEvent.created_at >= start)
    values = [
        (str(p or "other"), int(cost or 0), int(calls or 0))
        for p, cost, calls in (await db.execute(stmt)).all()
    ]
    if not values:
        return _empty(DATASETS["ai_spend_by_purpose"], "No AI usage in this window.")
    rows = [
        {"label": PURPOSE_LABELS.get(p, p.replace("_", " ").replace(".", " · ")),
         "cost": round(cost / 100, 2), "calls": calls}
        for p, cost, calls in values[:12]
    ]
    total_cost = sum(c for _, c, _ in values)
    total_calls = sum(n for _, _, n in values)
    return _result(
        rows=rows,
        columns=[_col("label", "Purpose", "string"), _col("cost", "Cost", "currency"),
                 _col("calls", "Calls")],
        kpis=[_kpi("AI spend", round(total_cost / 100, 2), "currency"),
              _kpi("AI calls", total_calls)],
        suggested_type="bar",
        suggested_series=["cost"],
        note="Top 12 purposes." if len(values) > 12 else None,
    )


async def _ai_spend_trend(db, tenant_id, channels, start, days) -> dict:
    day = func.date(LLMUsageEvent.created_at)
    stmt = (
        select(day, func.sum(LLMUsageEvent.cost_cents), func.count(LLMUsageEvent.id))
        .where(LLMUsageEvent.tenant_id == tenant_id)
        .group_by(day)
        .order_by(day)
    )
    if start is not None:
        stmt = stmt.where(LLMUsageEvent.created_at >= start)
    values = [
        (_iso_date(d), int(cost or 0), int(calls or 0))
        for d, cost, calls in (await db.execute(stmt)).all()
    ]
    if not values:
        return _empty(DATASETS["ai_spend_trend"], "No AI usage in this window.")
    rows = [{"label": d, "cost": round(cost / 100, 2), "calls": calls}
            for d, cost, calls in values[-90:]]
    return _result(
        rows=rows,
        columns=[_col("label", "Date", "date"), _col("cost", "Cost", "currency"),
                 _col("calls", "Calls")],
        kpis=[_kpi("AI spend", round(sum(c for _, c, _ in values) / 100, 2), "currency"),
              _kpi("AI calls", sum(n for _, _, n in values))],
        suggested_type="area",
        suggested_series=["cost"],
    )


Querier = Callable[..., Awaitable[dict]]


async def query_dataset(
    db: AsyncSession,
    tenant_id: str,
    dataset: str,
    *,
    days: int = 30,
    platform: str | None = None,
    location: str | None = None,
) -> dict:
    """Run one catalog dataset. Raises ValueError for an unknown key."""
    spec = DATASETS.get(dataset)
    if spec is None:
        raise ValueError(f"Unknown dataset: {dataset}")
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    days = max(0, min(days, 3650))
    if not spec.supports_days:
        days = 0
    start = _window_start(days)
    platform = (platform or "").strip().lower() or None
    if platform == "all":
        platform = None
    if not spec.supports_platform:
        platform = None
    location = (location or "").strip() or None
    if not spec.supports_location:
        location = None

    channels = await _channels(db, tenant_id, platform=platform, location=location)

    channel_scoped = {
        "review_volume", "rating_distribution", "sentiment_distribution",
        "reviews_by_location", "review_topics", "reply_status",
        "customer_growth", "customers_by_platform", "customer_categories",
        "top_customers", "message_volume", "response_time",
        "lead_pipeline", "lead_categories", "lead_growth",
        "google_visibility",
    }
    if dataset in channel_scoped and not channels:
        return {
            **_empty(spec, "No matching connected channel for this filter."),
            "dataset": spec.key,
            "title": spec.label,
            "domain": spec.domain,
            "window_days": days,
            "query_key": f"{spec.key}|{days}|{platform or ''}|{location or ''}",
        }

    runners: dict[str, Querier] = {
        "review_volume": _review_volume,
        "rating_distribution": _rating_distribution,
        "sentiment_distribution": _sentiment_distribution,
        "reviews_by_location": _reviews_by_location,
        "review_topics": _review_topics,
        "reply_status": _reply_status,
        "customer_growth": _customer_growth,
        "customers_by_platform": _customers_by_platform,
        "customer_categories": _customer_categories,
        "top_customers": _top_customers,
        "message_volume": _message_volume,
        "response_time": _response_time,
        "lead_pipeline": _lead_pipeline,
        "lead_categories": _lead_categories,
        "lead_growth": _lead_growth,
        "publishing_outcomes": _publishing_outcomes,
        "post_activity": _post_activity,
        "follower_counts": _follower_counts,
        "google_visibility": _google_visibility,
        "ai_spend_by_purpose": _ai_spend_by_purpose,
        "ai_spend_trend": _ai_spend_trend,
    }
    result = await runners[dataset](db, tenant_id, channels, start, days)
    if not result.get("rows") and days > 0 and dataset in ALL_TIME_FALLBACK:
        requested = days
        result = await runners[dataset](db, tenant_id, channels, None, 0)
        if result.get("rows"):
            result["note"] = (
                f"No rows in the last {requested} days; showing all time."
            )
            days = 0
    result.update({
        "dataset": spec.key,
        "title": spec.label,
        "domain": spec.domain,
        "window_days": days,
        "query_key": f"{spec.key}|{days}|{platform or ''}|{location or ''}",
    })
    return result
