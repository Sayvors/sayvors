"""Benchmark bench, snapshots and admin config.

BenchmarkPlace is tenant-scoped: a saved competitor is one tenant's personal
bench, never shared. BenchmarkSnapshot carries timestamped copies of provider
fields so trends can be computed without refetching history.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint, JSON
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
