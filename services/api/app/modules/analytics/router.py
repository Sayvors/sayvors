"""Analytics API: business overview, timeseries, enriched-review list."""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from . import growth, intelligence, service
from .schemas import (
    AcquisitionResponse,
    OpportunitiesResponse,
    OverviewResponse,
    ProblemsResponse,
    ProductsResponse,
    ReviewInsightItem,
    ReviewInsightListResponse,
    TimeseriesPoint,
    TimeseriesResponse,
    TopicsResponse,
    VisibilityResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """KPI block: ratings, sentiment, response metrics, scores, Google performance."""
    return await service.get_overview(db, user.id, channel_id, days)


@router.get("/timeseries", response_model=TimeseriesResponse)
async def get_timeseries(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily rollup series for charts (reviews, sentiment, impressions, actions)."""
    rows = await service.get_timeseries(db, user.id, channel_id, days)
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
    status: str | None = Query(None, pattern="^(replied|unanswered)$"),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enriched reviews for the AI Review Inbox (filter/sort/paginate)."""
    items, total = await service.list_insights(
        db,
        user.id,
        channel_id=channel_id,
        sentiment=sentiment,
        rating=rating,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ReviewInsightListResponse(
        total=total,
        items=[ReviewInsightItem.model_validate(r) for r in items],
    )


# ── Understand pillar ──────────────────────────────────────────────────

@router.get("/topics", response_model=TopicsResponse)
async def get_topics(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What customers talk about: frequency, sentiment, trend, emerging topics."""
    return await intelligence.get_topics(db, user.id, channel_id, days)


@router.get("/problems", response_model=ProblemsResponse)
async def get_problems(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most common problems, AI-prioritized by impact (volume x severity x growth)."""
    return await intelligence.get_problems(db, user.id, channel_id, days)


@router.get("/products", response_model=ProductsResponse)
async def get_products(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Product/service intelligence: mentions, sentiment, loved vs criticized."""
    return await intelligence.get_products(db, user.id, channel_id, days)


# ── Grow pillar ────────────────────────────────────────────────────────

@router.get("/visibility", response_model=VisibilityResponse)
async def get_visibility(
    channel_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Google visibility: impressions and conversion into customer actions."""
    return await growth.get_visibility(db, user.id, channel_id, days)


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
    return await growth.get_opportunities(db, user.id, channel_id, days)
