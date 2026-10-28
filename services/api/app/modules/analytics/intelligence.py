"""Understand-pillar intelligence: topics, problems, products.

Aggregates the per-review enrichment stored in `review_insights`
(topics/products/problems JSON + sentiment) into ranked, trend-aware
summaries. Current period is compared against the immediately preceding
period of equal length to compute trend percentages and emerging items.

Aggregation happens in Python over a narrow column projection — the data
set per tenant/location is small (reviews/day), and this keeps the SQL
portable across the JSON layouts stored by the enrichment pipeline.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ReviewInsight

logger = logging.getLogger(__name__)

SEVERITY_WEIGHTS = {"high": 3, "medium": 2, "low": 1}
# A topic/problem/product with zero mentions last period and >= this many
# this period counts as "emerging".
EMERGING_THRESHOLD = 3
MAX_ITEMS = 25


def _bucket(expr):
    return func.coalesce(expr, ReviewInsight.created_at)


async def _fetch_rows(db: AsyncSession, user_id: str, channel_id: str | None, start: datetime, end: datetime):
    bucket = _bucket(ReviewInsight.review_updated_at)
    filters = [ReviewInsight.user_id == user_id, bucket >= start, bucket < end]
    if channel_id:
        filters.append(ReviewInsight.channel_id == channel_id)
    return (
        await db.execute(
            select(
                ReviewInsight.sentiment,
                ReviewInsight.rating,
                ReviewInsight.topics,
                ReviewInsight.products,
                ReviewInsight.problems,
                ReviewInsight.meaning,
                ReviewInsight.channel_id,
            ).where(*filters)
        )
    ).all()


# Canonical complaint areas. Repma-style triage needs stable buckets, not
# free-text problem names that differ per model run. Matching is substring on
# the lowercased name; order matters (waiting_time before quality so
# "cold food after a long wait" lands on the wait bucket when named that way).
_COMPLAINT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("waiting_time", ("wait", "queue", "slow", "delay", "late", "took", "time")),
    ("staff_service", ("staff", "rude", "service", "waiter", "waitress", "cashier", "employee", "manager", "attitude")),
    ("order_accuracy", ("wrong", "order", "missing", "incorrect", "forgot", "mixed")),
    ("cleanliness", ("clean", "dirty", "hygiene", "messy", "filthy", "smell", "sticky")),
    ("price_value", ("price", "expensive", "cost", "overpriced", "value", "charge", "bill")),
    ("quality", ("quality", "taste", "cold", "stale", "burnt", "food", "portion", "flavor", "flavour")),
]


def _canonical_complaint(name: str) -> str:
    low = name.lower()
    for category, keywords in _COMPLAINT_RULES:
        if any(k in low for k in keywords):
            return category
    return "other"


def _trend(cur: int, prev: int) -> float | None:
    """Percent change vs previous period; None when not meaningful."""
    if prev == 0:
        return None
    return round(((cur - prev) / prev) * 100.0, 1)


def _is_emerging(cur: int, prev: int) -> bool:
    return prev == 0 and cur >= EMERGING_THRESHOLD


def _period_bounds(days: int) -> tuple[datetime, datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)
    return period_start, now, prev_start, period_start


def _agg_entities(rows, list_field: str) -> dict[str, dict]:
    """Aggregate one JSON entity list across review rows.

    Returns {name: {"mentions", "positive", "neutral", "negative", "severity",
    "ratings", "staff_named", "serious"}}. ``staff_named``/``serious`` are
    populated for problems only, from the per-review meaning layer.
    """
    out: dict[str, dict] = {}
    for sentiment, rating, topics, products, problems, meaning, _channel_id in rows:
        for item in (topics if list_field == "topics" else products if list_field == "products" else problems) or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"]).strip().lower()
            if not name:
                continue
            entry = out.setdefault(
                name,
                {
                    "mentions": 0, "positive": 0, "neutral": 0, "negative": 0,
                    "severity": {}, "ratings": [], "staff_named": 0, "serious": 0,
                },
            )
            entry["mentions"] += 1
            if list_field == "problems":
                sev = str(item.get("severity", "medium")).lower()
                entry["severity"][sev] = entry["severity"].get(sev, 0) + 1
                staff = (meaning or {}).get("entities", {}).get("staff") if isinstance(meaning, dict) else None
                if staff:
                    entry["staff_named"] += 1
                if sev == "high":
                    entry["serious"] += 1
            else:
                s = str(item.get("sentiment", sentiment or "neutral")).lower()
                if s in ("positive", "neutral", "negative"):
                    entry[s] += 1
            if list_field == "products" and rating:
                entry["ratings"].append(int(rating))
    return out


def _agg_areas(cur: dict[str, dict], prev: dict[str, dict]) -> list[dict]:
    """Roll free-text problems into canonical complaint areas with trends."""
    def _roll(entities: dict[str, dict]) -> dict[str, dict]:
        areas: dict[str, dict] = {}
        for name, e in entities.items():
            cat = _canonical_complaint(name)
            a = areas.setdefault(
                cat,
                {"category": cat, "mentions": 0, "staff_named": 0, "serious": 0, "terms": {}},
            )
            a["mentions"] += e["mentions"]
            a["staff_named"] += e.get("staff_named", 0)
            a["serious"] += e.get("serious", 0)
            a["terms"][name] = a["terms"].get(name, 0) + e["mentions"]
        return areas

    cur_areas = _roll(cur)
    prev_areas = _roll(prev)
    out: list[dict] = []
    for cat, a in cur_areas.items():
        prev_mentions = prev_areas.get(cat, {}).get("mentions", 0)
        trend = _trend(a["mentions"], prev_mentions)
        out.append({
            "category": cat,
            "mentions": a["mentions"],
            "staff_named": a["staff_named"],
            "serious": a["serious"],
            "trend_pct": trend,
            "status": (
                "emerging" if _is_emerging(a["mentions"], prev_mentions)
                else "increasing" if (trend or 0) > 10
                else "decreasing" if (trend or 0) < -10
                else "recurring"
            ),
            "top_terms": [
                {"name": n, "mentions": m}
                for n, m in sorted(a["terms"].items(), key=lambda kv: -kv[1])[:3]
            ],
        })
    out.sort(key=lambda x: (-x["serious"], -x["mentions"]))
    return out


async def get_topics(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    cur_start, cur_end, prev_start, prev_end = _period_bounds(days)
    cur_rows = await _fetch_rows(db, user_id, channel_id, cur_start, cur_end)
    prev_rows = await _fetch_rows(db, user_id, channel_id, prev_start, prev_end)

    cur = _agg_entities(cur_rows, "topics")
    prev = _agg_entities(prev_rows, "topics")

    topics = []
    for name, e in cur.items():
        p = prev.get(name, {})
        prev_mentions = p.get("mentions", 0)
        sentiment_total = e["positive"] + e["neutral"] + e["negative"] or 1
        topics.append({
            "name": name,
            "mentions": e["mentions"],
            "positive": e["positive"],
            "neutral": e["neutral"],
            "negative": e["negative"],
            "positive_pct": round(e["positive"] / sentiment_total * 100, 1),
            "trend_pct": _trend(e["mentions"], prev_mentions),
            "emerging": _is_emerging(e["mentions"], prev_mentions),
        })
    topics.sort(key=lambda t: t["mentions"], reverse=True)

    return {
        "days": days,
        "topics": topics[:MAX_ITEMS],
        "positive_topics": [t["name"] for t in topics if t["positive_pct"] >= 60][:5],
        "negative_topics": [t["name"] for t in sorted(topics, key=lambda x: -x["negative"]) if t["negative"] > 0][:5],
    }


async def get_problems(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    cur_start, cur_end, prev_start, prev_end = _period_bounds(days)
    cur_rows = await _fetch_rows(db, user_id, channel_id, cur_start, cur_end)
    prev_rows = await _fetch_rows(db, user_id, channel_id, prev_start, prev_end)

    cur = _agg_entities(cur_rows, "problems")
    prev = _agg_entities(prev_rows, "problems")

    def _severity(entry: dict) -> str:
        sev = entry.get("severity", {})
        if sev.get("high", 0) > 0:
            return "high"
        if sev.get("medium", 0) > 0:
            return "medium"
        return "low"

    problems = []
    for name, e in cur.items():
        p = prev.get(name, {})
        prev_mentions = p.get("mentions", 0)
        trend = _trend(e["mentions"], prev_mentions)
        severity = _severity(e)
        # Impact = volume x severity weight x growth pressure
        impact = e["mentions"] * SEVERITY_WEIGHTS[severity] * (1 + max(0.0, (trend or 0) / 100.0))
        status = (
            "emerging" if _is_emerging(e["mentions"], prev_mentions)
            else "increasing" if (trend or 0) > 10
            else "decreasing" if (trend or 0) < -10
            else "recurring"
        )
        problems.append({
            "name": name,
            "category": _canonical_complaint(name),
            "mentions": e["mentions"],
            "severity": severity,
            "trend_pct": trend,
            "status": status,
            "impact_score": round(impact, 1),
            "staff_named": e.get("staff_named", 0),
            "serious": e.get("serious", 0),
        })
    problems.sort(key=lambda x: -x["impact_score"])

    return {
        "days": days,
        "problems": problems[:MAX_ITEMS],
        "by_area": _agg_areas(cur, prev),
    }


async def get_products(db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30) -> dict:
    cur_start, cur_end, prev_start, prev_end = _period_bounds(days)
    cur_rows = await _fetch_rows(db, user_id, channel_id, cur_start, cur_end)
    prev_rows = await _fetch_rows(db, user_id, channel_id, prev_start, prev_end)

    cur = _agg_entities(cur_rows, "products")
    prev = _agg_entities(prev_rows, "products")

    products = []
    for name, e in cur.items():
        p = prev.get(name, {})
        prev_mentions = p.get("mentions", 0)
        sentiment_total = e["positive"] + e["neutral"] + e["negative"] or 1
        products.append({
            "name": name,
            "mentions": e["mentions"],
            "positive": e["positive"],
            "negative": e["negative"],
            "positive_pct": round(e["positive"] / sentiment_total * 100, 1),
            "avg_rating": round(sum(e["ratings"]) / len(e["ratings"]), 2) if e["ratings"] else None,
            "trend_pct": _trend(e["mentions"], prev_mentions),
            "emerging": _is_emerging(e["mentions"], prev_mentions),
        })
    products.sort(key=lambda x: -x["mentions"])

    most_loved = max(products, key=lambda x: (x["positive_pct"], x["mentions"]), default=None) if products else None
    most_criticized = (
        max([p for p in products if p["negative"] > 0], key=lambda x: (x["negative"], x["mentions"]), default=None)
        if products else None
    )
    fastest_growing = (
        max([p for p in products if p["trend_pct"] is not None], key=lambda x: x["trend_pct"], default=None)
        if products else None
    )

    return {
        "days": days,
        "products": products[:MAX_ITEMS],
        "most_loved": most_loved["name"] if most_loved else None,
        "most_criticized": most_criticized["name"] if most_criticized else None,
        "fastest_growing": fastest_growing["name"] if fastest_growing else None,
    }
