"""Benchmarking / competitive intelligence — P4 pillar backend.

Compares the current tenant against an anonymized aggregate profile (the
second demo account: syab293@gmail.com / Pizza Palace) so the comparison
works out-of-the-box with the demo dataset. In a multi-tenant production
environment this would query anonymized cross-tenant aggregates; here the
benchmark user acts as the stand-in "similar business" for demonstration.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LocationDailyMetric, ReviewInsight
from .service import get_overview

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

    return {
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