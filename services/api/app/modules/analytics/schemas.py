"""Analytics API schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PeriodComparison(BaseModel):
    days: int
    reviews: int
    avg_rating: float | None = None
    reviews_delta_pct: float | None = None
    rating_delta: float | None = None
    velocity_ratio: float | None = None


class SentimentSplit(BaseModel):
    positive: int
    neutral: int
    negative: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class GooglePerformance(BaseModel):
    impressions_maps: int
    website_clicks: int
    call_clicks: int
    direction_requests: int
    customer_actions: int


class OverviewResponse(BaseModel):
    total_reviews: int
    avg_rating: float
    rating_distribution: dict[str, int]
    sentiment: SentimentSplit
    response_rate: float
    avg_response_seconds: int | None = None
    unanswered: int
    reputation_score: int
    health_score: int
    period: PeriodComparison
    google_performance: GooglePerformance


class TimeseriesPoint(BaseModel):
    date: str
    channel_id: str
    reviews_count: int
    avg_rating: float
    positive_count: int
    neutral_count: int
    negative_count: int
    replies_count: int
    impressions_maps: int
    website_clicks: int
    call_clicks: int
    direction_requests: int


class TimeseriesResponse(BaseModel):
    points: list[TimeseriesPoint]


class ReviewInsightItem(BaseModel):
    id: str
    channel_id: str
    review_id: str
    rating: int
    review_text: str | None = None
    reviewer_name: str | None = None
    sentiment: str
    sentiment_score: float
    topics: list[Any]
    products: list[Any]
    problems: list[Any]
    replied: bool
    replied_at: datetime | None = None
    skipped: bool = False
    edited: bool = False
    edited_at: datetime | None = None
    previous_rating: int | None = None
    previous_review_text: str | None = None
    review_url: str | None = None
    review_updated_at: datetime | None = None
    created_at: datetime
    # Latest response row for this review, if any (pending / posted /
    # failed / approved). Lets the review page show and edit every
    # response inline.
    reply_id: str | None = None
    reply_text: str | None = None
    reply_status: str | None = None

    class Config:
        from_attributes = True


class ReviewInsightListResponse(BaseModel):
    total: int
    items: list[ReviewInsightItem]


# ── AI Review Intelligence (LLM + RAG, verified) ──────────────

class IntelThemeOut(BaseModel):
    name: str
    mentions: int
    avg_rating: float
    positive_pct: int
    phrases: list[str] = []
    trend: str = "stable"


class IntelOpportunityOut(BaseModel):
    level: str
    title: str
    detail: str
    impact: str


class IntelStrengthOut(BaseModel):
    title: str
    mentions: int
    avg: float


class IntelActionOut(BaseModel):
    title: str
    detail: str


class IntelStatsOut(BaseModel):
    total: int
    avg_rating: float
    distribution: dict[str, int]
    positive: int
    neutral: int
    negative: int
    replied: int
    unanswered: int
    response_rate: int


class ReviewIntelligenceResponse(BaseModel):
    source: str  # "ai" | "fallback"
    model: str | None = None
    stats: IntelStatsOut
    summary: str
    themes: list[IntelThemeOut] = []
    opportunities: list[IntelOpportunityOut] = []
    strengths: list[IntelStrengthOut] = []
    actions: list[IntelActionOut] = []
    rag_used: bool = False
    rag_chunks: int = 0
    rag_bank: str | None = None
    fallback_reason: str | None = None
    analyzed_at: str | None = None
    review_count: int = 0
    current_count: int = 0
    stale: bool = False


class AnalyzeIntelligenceRequest(BaseModel):
    channel_id: str | None = None
    days: int = Field(90, ge=1, le=365)
    databank_id: str | None = None


# ── Understand pillar ──────────────────────────────────────────────────

class TopicStat(BaseModel):
    name: str
    mentions: int
    positive: int
    neutral: int
    negative: int
    positive_pct: float
    trend_pct: float | None = None
    emerging: bool


class TopicsResponse(BaseModel):
    days: int
    topics: list[TopicStat]
    positive_topics: list[str]
    negative_topics: list[str]


class ProblemStat(BaseModel):
    name: str
    mentions: int
    severity: str
    trend_pct: float | None = None
    status: str
    impact_score: float


class ProblemsResponse(BaseModel):
    days: int
    problems: list[ProblemStat]


class ProductStat(BaseModel):
    name: str
    mentions: int
    positive: int
    negative: int
    positive_pct: float
    avg_rating: float | None = None
    trend_pct: float | None = None
    emerging: bool


class ProductsResponse(BaseModel):
    days: int
    products: list[ProductStat]
    most_loved: str | None = None
    most_criticized: str | None = None
    fastest_growing: str | None = None


# ── Grow pillar ────────────────────────────────────────────────────────

class VisibilityResponse(BaseModel):
    days: int
    impressions_maps: int
    impressions_trend_pct: float | None = None
    customer_actions: int
    actions_trend_pct: float | None = None
    click_through_pct: float | None = None


class ActionStat(BaseModel):
    total: int
    trend_pct: float | None = None


class AcquisitionResponse(BaseModel):
    days: int
    website_clicks: ActionStat
    call_clicks: ActionStat
    direction_requests: ActionStat
    customer_actions: ActionStat


class Opportunity(BaseModel):
    priority: int
    type: str
    title: str
    detail: str


class OpportunitiesResponse(BaseModel):
    days: int
    opportunities: list[Opportunity]


# ── Benchmarking pillar ─────────────────────────────────────────────

class BranchBenchmark(BaseModel):
    channel_id: str
    name: str
    avg_rating: float
    reviews_total: int
    positive_pct: float
    response_rate: float
    reputation_score: int
    health_score: int | None = None
    rating_delta: float | None = None
    reviews_delta_pct: float | None = None
    velocity_ratio: float | None = None
    reviews_last_period: int = 0
    velocity_per_month: float | None = None
    impressions_maps: int = 0
    customer_actions: int = 0
    action_rate: float | None = None
    gap_vs_leader_per_year: int | None = None
    top_problem: str | None = None
    top_problem_mentions: int = 0
    rank: int


class BranchHighlight(BaseModel):
    channel_id: str
    name: str
    reasons: list[str]


class ServiceHighlight(BaseModel):
    name: str
    mentions: int = 0
    positive_pct: float = 0
    avg_rating: float | None = None
    negative: int = 0


class BranchRecommendation(BaseModel):
    channel_id: str
    name: str
    priority: str
    text: str


class BenchmarkResponse(BaseModel):
    days: int
    current_avg_rating: float
    similar_avg_rating: float
    current_reviews_total: int
    similar_reviews_total: int
    current_sentiment_positive_pct: float
    similar_sentiment_positive_pct: float
    current_response_rate: float
    similar_response_rate: float
    current_customer_actions: int
    similar_customer_actions: int
    current_reputation_score: int
    similar_reputation_score: int
    benchmark_text: str
    percentile_text: str
    outperforms: list[str]
    underperforms: list[str]
    competitive_opportunities: list[str]
    industry_trends: list[str]
    branches: list[BranchBenchmark] = []
    leader: BranchHighlight | None = None
    needs_attention: BranchHighlight | None = None
    recommendations: list[BranchRecommendation] = []
    top_services: list[ServiceHighlight] = []
    needs_fix_services: list[ServiceHighlight] = []
    top_topics: list[dict] = []
    # Owner-centric additions
    distribution: dict[str, dict] | None = None
    portfolio_health_score: int | None = None
    portfolio_action_rate: float | None = None
    portfolio_velocity_per_month: float | None = None
    portfolio_impressions: int | None = None
    portfolio_actions: int | None = None
    plain_summary: str | None = None
    # Tenant-cohort market view: your branches ranked against every other
    # Sayvors business in your city + category. No manual entry, no
    # synthetic aggregates.
    cohort: dict | None = None
    market: list[dict] = []
    my_rank: int | None = None


class ExecutiveSummaryResponse(BaseModel):
    days: int
    headline: str
    avg_rating: float
    reputation_score: int
    health_score: int
    wins: list[str]
    problems: list[str]
    opportunity: str
    recommended_action: str
    benchmark_text: str
