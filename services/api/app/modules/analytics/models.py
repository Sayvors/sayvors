"""Analytics & business intelligence models.

Everything the intelligence layer needs is stored in PostgreSQL:

- ReviewInsight       per-review AI enrichment (sentiment, topics, products,
                      problems) — the "Understand" data set
- LocationDailyMetric per-channel daily rollups (review counts, sentiment
                      split, Google impressions/actions) — the "Grow" data set
- SearchKeywordStat per-channel daily search-keyword impressions (native
                      Google only — Localith exposes no keyword data)

Events flow through the outbox → Kafka (`review-events`, `metrics-events`),
mirroring the existing event architecture in `modules/outbox`.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class ReviewInsight(Base):
    """AI-enriched view of one Google review (idempotent upsert target)."""

    __tablename__ = "review_insights"
    __table_args__ = (
        UniqueConstraint("channel_id", "review_id", name="uq_review_insights_channel_review"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    # Google review resource name: accounts/{a}/locations/{l}/reviews/{r}
    review_id: Mapped[str] = mapped_column(String(500), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Reviewer profile photo (Google profilePhotoUrl on the native path;
    # upstream photo field on Localith when present). UI falls back to
    # initials when null.
    reviewer_photo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # positive / neutral / negative (LLM or heuristic)
    sentiment: Mapped[str] = mapped_column(
        Enum("positive", "neutral", "negative", name="review_sentiment"),
        default="neutral",
        index=True,
    )
    # -1.0 .. 1.0
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    # [{"name": "service", "sentiment": "positive"}, ...]
    topics: Mapped[list] = mapped_column(JSON, default=list)
    # [{"name": "Chicken Burger", "sentiment": "positive"}, ...]
    products: Mapped[list] = mapped_column(JSON, default=list)
    # [{"name": "slow service", "severity": "high"}, ...]
    problems: Mapped[list] = mapped_column(JSON, default=list)
    # pending -> done | failed
    enrichment_status: Mapped[str] = mapped_column(
        Enum("pending", "done", "failed", name="enrichment_status"),
        default="pending",
        index=True,
    )
    # Response bookkeeping (response-rate / response-time metrics)
    replied: Mapped[bool] = mapped_column(Boolean, default=False)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the reviewer deleted the review or Google removed it —
    # the review is still cached locally but no reply is possible.
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    # Reviewer edited the review after we first synced it (detected by
    # content comparison at sync time — Localith sends no edit timestamp).
    # Cleared when the updated reply is posted or the edit is dismissed.
    edited: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Merchant dismissed the draft (rejected in Outbox): sync/worker must
    # not auto-draft again. Cleared when the reviewer edits the review
    # (new content) — manual regenerate/retry bypass it regardless.
    draft_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Link to the review on Google (Localith `reviewLink`), for "View on Google".
    review_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # When Google last updated the review (bucket date for daily rollups)
    review_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LocationDailyMetric(Base):
    """One row per channel per day: review rollup + Google performance metrics."""

    __tablename__ = "location_daily_metrics"
    __table_args__ = (
        UniqueConstraint("channel_id", "date", name="uq_location_daily_channel_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[datetime] = mapped_column(Date, index=True)

    # ── Review rollups (recomputed from review_insights) ──
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, default=0)
    replies_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── Google performance (Business Profile Performance API) ──
    impressions_maps_desktop: Mapped[int] = mapped_column(Integer, default=0)
    impressions_maps_mobile: Mapped[int] = mapped_column(Integer, default=0)
    website_clicks: Mapped[int] = mapped_column(Integer, default=0)
    call_clicks: Mapped[int] = mapped_column(Integer, default=0)
    direction_requests: Mapped[int] = mapped_column(Integer, default=0)

    # Room for future metrics without a migration (e.g. bookings, menu interactions)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReviewIntelligenceReport(Base):
    """Cached AI review-intelligence analysis (analyze once, serve many).

    One row per (user, channel scope, window). Recomputed only when the
    user presses Analyze — the UI serves this row otherwise.
    """

    __tablename__ = "review_intelligence_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", "scope_key", name="uq_intel_report_scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # "" means all channels; otherwise the channel id.
    channel_id: Mapped[str] = mapped_column(String(36), default="")
    # Rolling-window length for preset intervals; 0 for an explicit date range.
    days: Mapped[int] = mapped_column(Integer, default=90)
    # Cache identity for the interval: "7"/"30"/"90"/"365"/"all" for presets,
    # or "2026-09-01..2026-09-30" for a custom month range.
    scope_key: Mapped[str] = mapped_column(String(40), default="90")

    source: Mapped[str] = mapped_column(String(16), default="fallback")  # ai | fallback
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    themes: Mapped[list] = mapped_column(JSON, default=list)
    opportunities: Mapped[list] = mapped_column(JSON, default=list)
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    # Business Health Scorecard (standard dimensions + LLM-discovered extras).
    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    # Where this business leads / trails the anonymised cohort.
    competitive: Mapped[dict] = mapped_column(JSON, default=dict)
    rag_used: Mapped[bool] = mapped_column(Boolean, default=False)
    rag_chunks: Mapped[int] = mapped_column(Integer, default=0)
    rag_bank: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Review count at analysis time (staleness signal).
    review_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SearchKeywordStat(Base):
    """Daily search-keyword impressions per channel (Grow data set).

    Populated ONLY for native-Google channels: keyword breakdowns come from
    the Business Profile Performance API (SEARCH_KEYWORD_IMPRESSIONS),
    which Localith does not expose. Localith-only tenants get an honest
    empty state in the UI until native Google OAuth lands — never fake rows.
    """

    __tablename__ = "search_keyword_stats"
    __table_args__ = (
        UniqueConstraint("channel_id", "keyword", "date", name="uq_keyword_channel_day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    keyword: Mapped[str] = mapped_column(String(255), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    impressions: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
