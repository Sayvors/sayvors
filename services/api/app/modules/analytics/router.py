"""Analytics API: business overview, timeseries, enriched-review list."""
import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...core.deps import get_current_user, get_db
from ..users.models import User
from ...config import settings
from . import benchmark, growth, intelligence, service, summary
from .models import ReviewInsight
from .schemas import (
    AcquisitionResponse,
    AnalyzeIntelligenceRequest,
    BenchmarkResponse,
    ExecutiveSummaryResponse,
    KeywordsResponse,
    OpportunitiesResponse,
    OverviewResponse,
    ProblemsResponse,
    ProductsResponse,
    ReviewInsightItem,
    ReviewInsightListResponse,
    ReviewIntelligenceResponse,
    TimeseriesPoint,
    TimeseriesResponse,
    TopicsResponse,
    VisibilityResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


from ...config import settings

DEMO_USER_ID_FALLBACK = "ce2fc147"
DEMO_USER_ID = DEMO_USER_ID_FALLBACK


def _resolve_uid(db: AsyncSession, user) -> str:
    if settings.DEMO_MODE:
        # Demo mode MUST only ever run on an isolated demo deployment with a
        # seeded demo account. It substitutes a fixed demo user id — never a
        # dynamically resolved tenant (an earlier "user with most rows"
        # resolver was a cross-tenant leak and has been removed).
        return DEMO_USER_ID_FALLBACK
    return user.id


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """KPI block: ratings, sentiment, response metrics, scores, Google performance."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await service.get_overview(db, uid, channel_id, days)


@router.get("/timeseries", response_model=TimeseriesResponse)
async def get_timeseries(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily rollup series for charts (reviews, sentiment, impressions, actions)."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    rows = await service.get_timeseries(db, uid, channel_id, days)
    return TimeseriesResponse(
        points=[
            TimeseriesPoint(
                date=row.date.isoformat(),
                channel_id=row.channel_id,
                reviews_count=row.reviews_count,
                avg_rating=row.avg_rating,
                positive_count=row.positive_count,
                neutral_count=row.neutral_count,
                negative_count=row.negative_count,
                replies_count=row.replies_count,
                impressions_maps=row.impressions_maps_desktop + row.impressions_maps_mobile,
                website_clicks=row.website_clicks,
                call_clicks=row.call_clicks,
                direction_requests=row.direction_requests,
            )
            for row in rows
        ]
    )


@router.get("/reviews/insights", response_model=ReviewInsightListResponse)
async def list_review_insights(
    channel_id: str | None = Query(None),
    sentiment: str | None = Query(None, pattern="^(positive|neutral|negative)$"),
    rating: int | None = Query(None, ge=1, le=5),
    status: str | None = Query(None, pattern="^(replied|unanswered|skipped)$"),
    edited: bool | None = Query(None),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enriched reviews for the AI Review Inbox (filter/sort/paginate)."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    items, total = await service.list_insights(
        db,
        user.id,
        channel_id=channel_id,
        sentiment=sentiment,
        rating=rating,
        status=status,
        edited=edited,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ReviewInsightListResponse(
        total=total,
        items=[ReviewInsightItem.model_validate(r) for r in items],
    )


@router.post("/reviews/insights/{insight_id}/skip", response_model=ReviewInsightItem)
async def skip_review(
    insight_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a review as skipped — reviewer deleted it or Google removed it.

    The cached insight stays visible but is treated as unavailable:
    it no longer counts toward "unanswered" and cannot be replied to.
    """
    if settings.DEMO_MODE:
        # Demo data belongs to the demo tenant: never let a demo viewer
        # mutate another account's rows.
        raise HTTPException(status_code=403, detail="Demo mode is read-only")
    row = await db.execute(select(ReviewInsight).where(ReviewInsight.id == insight_id))
    insight = row.scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="Review insight not found")
    if insight.user_id != (DEMO_USER_ID if settings.DEMO_MODE else user.id):
        raise HTTPException(status_code=403, detail="Not your review")
    insight.skipped = True
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return insight


@router.post("/reviews/insights/{insight_id}/dismiss-edit", response_model=ReviewInsightItem)
async def dismiss_review_edit(
    insight_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the 'review edited' flag once the merchant has seen the change.

    Sync-time content comparison flags edited reviews; this endpoint is the
    manual acknowledge path (posting an updated reply clears it too).
    """
    if settings.DEMO_MODE:
        raise HTTPException(status_code=403, detail="Demo mode is read-only")
    row = await db.execute(select(ReviewInsight).where(ReviewInsight.id == insight_id))
    insight = row.scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="Review insight not found")
    if insight.user_id != (DEMO_USER_ID if settings.DEMO_MODE else user.id):
        raise HTTPException(status_code=403, detail="Not your review")
    insight.edited = False
    insight.edited_at = None
    insight.previous_rating = None
    insight.previous_review_text = None
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return insight


@router.get("/review-intelligence", response_model=ReviewIntelligenceResponse | None)
async def get_review_intelligence(
    channel_id: str | None = Query(None),
    days: int = Query(90, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stored intelligence report (no re-analysis). Null when never analyzed."""
    from .intelligence_ai import get_stored_report

    stored = await get_stored_report(db, user.id, channel_id, days)
    if stored is None:
        return None
    stored["stats"]["distribution"] = {
        str(k): v for k, v in stored["stats"]["distribution"].items()
    }
    return stored


@router.post("/review-intelligence/analyze", response_model=ReviewIntelligenceResponse)
async def analyze_review_intelligence(
    body: AnalyzeIntelligenceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the AI analysis now and store it (replaces any previous report)."""
    from .intelligence_ai import analyze_and_store

    result = await analyze_and_store(db, user, body.channel_id, body.days, body.databank_id)
    result["stats"]["distribution"] = {
        str(k): v for k, v in result["stats"]["distribution"].items()
    }
    return result


# ── Understand pillar ──────────────────────────────────────────────────

@router.get("/topics", response_model=TopicsResponse)
async def get_topics(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What customers talk about: frequency, sentiment, trend, emerging topics."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await intelligence.get_topics(db, uid, channel_id, days)


@router.get("/problems", response_model=ProblemsResponse)
async def get_problems(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most common problems, AI-prioritized by impact (volume x severity x growth)."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await intelligence.get_problems(db, uid, channel_id, days)


@router.get("/products", response_model=ProductsResponse)
async def get_products(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Product/service intelligence: mentions, sentiment, loved vs criticized."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await intelligence.get_products(db, uid, channel_id, days)


# ── Grow pillar ────────────────────────────────────────────────────────

@router.get("/visibility", response_model=VisibilityResponse)
async def get_visibility(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Google visibility: impressions and conversion into customer actions."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await growth.get_visibility(db, uid, channel_id, days)


@router.get("/acquisition", response_model=AcquisitionResponse)
async def get_acquisition(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Google-generated customer actions: clicks, calls, directions."""
    return await growth.get_acquisition(db, user.id, channel_id, days)


@router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prioritized growth actions derived from live business data."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await growth.get_opportunities(db, uid, channel_id, days)


@router.get("/growth/keywords", response_model=KeywordsResponse)
async def get_keywords(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search keywords tenants were found by (native Google only)."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await growth.get_keywords(db, uid, channel_id, days)


@router.get("/benchmark/comparison", response_model=BenchmarkResponse)
async def get_benchmark_comparison(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Benchmark the tenant against the second demo business profile (stand-in for comparable businesses)."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await benchmark.get_benchmark(db, uid, channel_id, days)


@router.get("/executive-summary", response_model=ExecutiveSummaryResponse)
async def get_executive_summary(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-composed business briefing pinned to the top of the dashboard."""
    uid = DEMO_USER_ID if settings.DEMO_MODE else user.id
    return await summary.get_executive_summary(db, uid, channel_id, days)
