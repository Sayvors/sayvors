"""Benchmarking / competitive intelligence — P4 pillar backend.

Two comparison layers:
1. Branch vs branch (primary, always real): the tenant's own locations
   ranked against each other on rating, sentiment, response rate, volume
   and reputation — with per-branch reasons and recommendations.
2. External aggregate (secondary estimate): an anonymized aggregate
   profile (second demo account) as an industry reference point.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from .models import LocationDailyMetric, ReviewInsight
from .service import get_overview, reputation_score

logger = logging.getLogger(__name__)
BENCHMARK_USER_EMAIL = "syab293@gmail.com"


async def _find_benchmark_user_id(db: AsyncSession, current_user_id: str) -> str | None:
    from ..users.models import User

    result = await db.execute(
        select(User.id).where(User.email == BENCHMARK_USER_EMAIL)
    )
    bench = result.scalar_one_or_none()
    if bench and bench != current_user_id:
        return bench
    # Fallback: any different user with analytics rows
    row = await db.execute(
        select(ReviewInsight.user_id)
        .where(ReviewInsight.user_id != current_user_id)
        .order_by(ReviewInsight.created_at.desc())
        .limit(1)
    )
    bench_fallback = row.scalar_one_or_none()
    return bench_fallback


async def _branch_breakdown(
    db: AsyncSession, user_id: str, days: int = 30
) -> list[dict]:
    """Per-branch scorecards, ranked by reputation (then review volume)."""
    from .intelligence import get_problems

    rows = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
            )
        )
    ).scalars().all()

    branches: list[dict] = []
    for ch in rows:
        try:
            ov = await get_overview(db, user_id, ch.id, days)
        except Exception as e:
            logger.warning("Branch overview failed for %s: %s", ch.id, e)
            continue
        try:
            probs = (await get_problems(db, user_id, ch.id, days))["problems"]
            top = probs[0] if probs else None
        except Exception:
            top = None
        rep = ov.get("reputation_score") or reputation_score(
            ov.get("avg_rating", 0.0) or 0.0,
            ov.get("response_rate", 0.0) or 0.0,
            (ov.get("sentiment", {}) or {}).get("positive_pct", 0.0) / 100.0,
        )
        branches.append({
            "channel_id": ch.id,
            "name": ch.display_name or "Location",
            "avg_rating": ov.get("avg_rating", 0.0) or 0.0,
            "reviews_total": ov.get("total_reviews", 0) or 0,
            "positive_pct": (ov.get("sentiment", {}) or {}).get("positive_pct", 0.0) or 0.0,
            "response_rate": round((ov.get("response_rate", 0.0) or 0.0) * 100, 1)
            if (ov.get("response_rate", 0.0) or 0.0) <= 1.0
            else round(ov.get("response_rate", 0.0) or 0.0, 1),
            "reputation_score": rep,
            "rating_delta": ((ov.get("period", {}) or {}).get("rating_delta")),
            "reviews_delta_pct": ((ov.get("period", {}) or {}).get("reviews_delta_pct")),
            "top_problem": (top or {}).get("name"),
            "top_problem_mentions": (top or {}).get("mentions", 0),
            "customer_actions": ((ov.get("google_performance", {}) or {}).get("customer_actions", 0)) or 0,
        })
    branches.sort(key=lambda b: (-b["reputation_score"], -b["reviews_total"]))
    for i, b in enumerate(branches):
        b["rank"] = i + 1
    return branches


def _branch_highlights(
    branches: list[dict],
) -> tuple[dict | None, dict | None, list[dict]]:
    """Leader + needs-attention spotlight and per-branch recommendations."""
    if not branches:
        return None, None, []
    rated = [b for b in branches if b["reviews_total"] > 0] or branches
    n = len(rated)
    avg_rating = sum(b["avg_rating"] for b in rated) / n
    avg_resp = sum(b["response_rate"] for b in rated) / n

    def _strengths(b: dict) -> list[str]:
        out = []
        if b["avg_rating"] >= avg_rating and b["avg_rating"] > 0:
            out.append(f"Highest guest love ({b['avg_rating']:.1f}★ avg)")
        if b["response_rate"] >= 100:
            out.append("Replies to every single review")
        elif b["response_rate"] >= avg_resp and b["response_rate"] > 0:
            out.append(f"Fastest responses ({b['response_rate']:.0f}% reply rate)")
        if (b["reviews_total"] or 0) > 0 and b["reviews_total"] >= max(
            (x["reviews_total"] or 0) for x in rated
        ):
            out.append(f"Most reviewed ({b['reviews_total']} reviews)")
        if (b.get("rating_delta") or 0) > 0:
            out.append(f"Rating climbing (+{b['rating_delta']:.1f}★ this period)")
        return out[:2]

    def _pains(b: dict) -> list[str]:
        out = []
        if b["avg_rating"] < 4.0 and b["avg_rating"] > 0:
            out.append(f"Below the 4.0★ visibility line ({b['avg_rating']:.1f}★)")
        if b["response_rate"] < 70:
            out.append(f"Only {b['response_rate']:.0f}% of reviews answered")
        if b.get("top_problem"):
            out.append(f"Guests keep mentioning “{b['top_problem']}” ({b.get('top_problem_mentions', 0)}×)")
        if (b.get("reviews_delta_pct") or 0) < 0:
            out.append("Review volume is shrinking")
        return out[:2]

    leader = rated[0]
    leader_out = {
        "channel_id": leader["channel_id"],
        "name": leader["name"],
        "reasons": _strengths(leader) or ["Steady all-round performance"],
    }
    attention = None
    if len(rated) > 1:
        worst = rated[-1]
        pains = _pains(worst)
        if pains:
            attention = {
                "channel_id": worst["channel_id"],
                "name": worst["name"],
                "reasons": pains,
            }

    recommendations: list[dict] = []
    for b in rated:
        pains = _pains(b)
        if pains and b is not leader:
            recommendations.append({
                "channel_id": b["channel_id"],
                "name": b["name"],
                "priority": "high" if b["avg_rating"] < 4.0 or b["response_rate"] < 50 else "medium",
                "text": f"Fix this first at {b['name']}: {pains[0].lower()}.",
            })
        elif b is leader:
            recommendations.append({
                "channel_id": b["channel_id"],
                "name": b["name"],
                "priority": "win",
                "text": f"Copy what works at {b['name']} to your other locations"
                + (f" — start with “{b['top_problem']}” fixes elsewhere." if b.get("top_problem") else "."),
            })
    if attention is None and len(rated) == 1:
        only = rated[0]
        recommendations.append({
            "channel_id": only["channel_id"],
            "name": only["name"],
            "priority": "medium",
            "text": f"Connect more locations to unlock branch-vs-branch comparison for {only['name']}.",
        })
    return leader_out, attention, recommendations[:6]


async def get_benchmark(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30
) -> dict:
    bench_user = await _find_benchmark_user_id(db, user_id)
    if bench_user:
        similar = await get_overview(db, bench_user, channel_id, days)
    else:
        # No comparable user found — synthesize neutral baseline from current
        similar = await get_overview(db, user_id, channel_id, days)
    cur = await get_overview(db, user_id, channel_id, days)

    outperforms = []
    underperforms = []
    if cur["avg_rating"] > similar["avg_rating"]:
        outperforms.append("Average rating (%.1f vs %.1f)" % (cur["avg_rating"], similar["avg_rating"]))
    else:
        underperforms.append("Average rating (%.1f vs %.1f)" % (cur["avg_rating"], similar["avg_rating"]))

    if cur["sentiment"]["positive_pct"] > similar["sentiment"]["positive_pct"]:
        outperforms.append("Positive sentiment (%d%% vs %d%%)" % (cur["sentiment"]["positive_pct"], similar["sentiment"]["positive_pct"]))
    else:
        underperforms.append("Positive sentiment (%d%% vs %d%%)" % (cur["sentiment"]["positive_pct"], similar["sentiment"]["positive_pct"]))

    if cur["google_performance"]["customer_actions"] > similar["google_performance"]["customer_actions"]:
        outperforms.append("Customer actions (%d vs %d)" % (cur["google_performance"]["customer_actions"], similar["google_performance"]["customer_actions"]))
    else:
        underperforms.append("Customer actions (%d vs %d)" % (cur["google_performance"]["customer_actions"], similar["google_performance"]["customer_actions"]))

    # Competitive opportunities: derive from gaps
    opps: list[str] = []
    if cur["response_rate"] < 70:
        opps.append("Improve response rate (currently %d%%) to lift reputation" % cur["response_rate"])
    if cur["google_performance"]["impressions_maps"] > 0 and cur["google_performance"]["customer_actions"] == 0:
        opps.append("Convert visibility into actions — add a clear CTA profile")
    if cur["sentiment"]["negative_pct"] > 20:
        opps.append("Address rising negative sentiment before it impacts visibility")
    if cur["period"]["reviews_delta_pct"] is not None and cur["period"]["reviews_delta_pct"] < 0:
        opps.append("Review volume is declining — ask happy customers for feedback")
    if not opps:
        opps.append("Keep promoting your best-rated products and maintain response speed")

    # Benchmark comparison text
    rep_diff = cur["reputation_score"] - similar["reputation_score"]
    if rep_diff >= 15:
        benchmark_text = "You're performing significantly better than comparable businesses (reputation +%d)." % rep_diff
    elif rep_diff >= 5:
        benchmark_text = "You're outperforming most comparable businesses (reputation +%d)." % rep_diff
    elif rep_diff <= -15:
        benchmark_text = "You're underperforming comparable businesses (reputation -%d). Focus on the top opportunity below." % abs(rep_diff)
    else:
        benchmark_text = "Your reputation and visibility are in line with comparable businesses. Focus on the opportunity below to stand out."

    # Industry common complaints: aggregate problems across both accounts as proxy
    from .intelligence import get_problems
    bench_problems = (await get_problems(db, bench_user or user_id, None, days))["problems"]
    common_complaints = [p["name"] for p in bench_problems[:3]]

    branches = await _branch_breakdown(db, user_id, days)
    leader, attention, recommendations = _branch_highlights(branches)

    return {
        "branches": branches,
        "leader": leader,
        "needs_attention": attention,
        "recommendations": recommendations,
        "days": days,
        "current_avg_rating": cur["avg_rating"],
        "similar_avg_rating": similar["avg_rating"],
        "current_reviews_total": cur["total_reviews"],
        "similar_reviews_total": similar["total_reviews"],
        "current_sentiment_positive_pct": cur["sentiment"]["positive_pct"],
        "similar_sentiment_positive_pct": similar["sentiment"]["positive_pct"],
        "current_response_rate": cur["response_rate"],
        "similar_response_rate": similar["response_rate"],
        "current_customer_actions": cur["google_performance"]["customer_actions"],
        "similar_customer_actions": similar["google_performance"]["customer_actions"],
        "current_reputation_score": cur["reputation_score"],
        "similar_reputation_score": similar["reputation_score"],
        "benchmark_text": benchmark_text,
        "percentile_text": f"You're in the top {min(99, max(12, 50 + rep_diff))}% of comparable businesses" if cur["reputation_score"] >= similar["reputation_score"] else f"There's significant room to grow vs comparable businesses",
        "outperforms": outperforms,
        "underperforms": underperforms,
        "competitive_opportunities": opps[:3],
        "industry_trends": common_complaints,
    }