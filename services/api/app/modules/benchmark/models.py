"""Benchmark bench, snapshots and admin config.

BenchmarkPlace is tenant-scoped: a saved competitor is one tenant's personal
bench, never shared. BenchmarkSnapshot carries timestamped copies of provider
fields so trends can be computed without refetching history.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CHAR, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, JSON, text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class BenchmarkConfig(Base):
    """Single admin-owned config row for the benchmark feature."""

    __tablename__ = "benchmark_config"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    place_cache_enabled: Mapped[bool] = mapped_column(default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=730)
    refresh_hours: Mapped[int] = mapped_column(Integer, default=24)
    max_saved_places: Mapped[int] = mapped_column(Integer, default=50)
    # Public Google endpoints are the fallback; official Places is the default.
    # Full-history mode is opt-in and bounded for 1M+ tenant scale.
    source: Mapped[str] = mapped_column(String(20), default="google_places")
    review_history_mode: Mapped[str] = mapped_column(String(16), default="recent")
    max_reviews_per_place: Mapped[int] = mapped_column(Integer, default=2000)
    full_history_batch: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BenchmarkPlace(Base):
    """One saved competitor on one tenant's bench."""

    __tablename__ = "benchmark_places"
    __table_args__ = (
        UniqueConstraint("tenant_id", "place_id", name="uq_benchmark_tenant_place"),
        Index("ix_benchmark_places_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    place_id: Mapped[str] = mapped_column(String(255))
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_heatmap: Mapped[bool] = mapped_column(default=True)
    # Membership in the tenant's named benchmark set (max 5, enforced in
    # service.set_bench_set). Drives the compare page's default selection;
    # in_heatmap stays independent (heatmap ≠ benchmark set).
    in_bench_set: Mapped[bool] = mapped_column(default=False)
    # Cached provider fields (only written when place_cache_enabled).
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviews: Mapped[list | None] = mapped_column(JSON, nullable=True)
    photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Canonical Maps URL captured at save time; carries the feature id used by
    # the free place-detail and review endpoints.
    maps_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Google place photo URL for the card avatar.
    thumbnail: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Star distribution (e.g. {"1": n, ... "5": n}) from the provider.
    reviews_per_score: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last scraper failure, so an outage is visible to the admin instead of
    # silently freezing the history at an old date.
    last_scrape_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BenchmarkSnapshot(Base):
    """Timestamped copy of a place's provider fields, for trend computation."""

    __tablename__ = "benchmark_snapshots"
    __table_args__ = (
        UniqueConstraint("place_id", "fetched_at", name="uq_benchmark_snapshot_place_time"),
        Index("ix_benchmark_snapshots_tenant_fetched", "tenant_id", "fetched_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    place_id: Mapped[str] = mapped_column(String(36), index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviews: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class BenchmarkThemeAnalysis(Base):
    """One durable, versioned theme analysis per tenant-owned subject.

    ``sample_json`` freezes the exact bounded evidence used for ``themes``.
    A changed sample hash starts a new job; an older worker can no longer
    overwrite the newer analysis because handlers re-check job id and hash.
    """

    __tablename__ = "benchmark_theme_analyses"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "subject_type", "subject_id",
            name="uq_benchmark_theme_analysis_subject",
        ),
        Index(
            "ix_benchmark_theme_analysis_status_updated",
            "status", "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    subject_type: Mapped[str] = mapped_column(String(8))
    subject_id: Mapped[str] = mapped_column(String(36))
    sample_hash: Mapped[str] = mapped_column(CHAR(64))
    sample_json: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    themes: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    source: Mapped[str | None] = mapped_column(String(8), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
