"""Localith connections: one row per (user_id, listing_id).

Each Sayvors user can save ANY number of Localith listings — one row per
(user_id, listing_id). Every connected branch is stored, synced, and kept;
pages filter per branch instead of assuming one location.
Each row may carry the tenant's own Fernet-encrypted API key
(`api_key_encrypted`); rows without one fall back to the shared
LOCALITH_API_KEY env.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class LocalithConnection(Base):
    __tablename__ = "localith_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_localith_user_listing"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(String(64))
    listing_name: Mapped[str] = mapped_column(String(255))
    listing_google_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-tenant Localith API key (Fernet via channels.service.encrypt_token).
    # Empty → shared LOCALITH_API_KEY env fallback. Never serialized to clients.
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Business profile snapshot (from GET /rest/v1/listings/{id}) ──
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    maps_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    store_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_disabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_suspended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    total_reviews: Mapped[int] = mapped_column(Integer, default=0)
    average_rating: Mapped[float] = mapped_column(Float, default=0.0)
    last_review_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reply_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_listing_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Metrics snapshots (summarized over [metrics_start, metrics_end]) ──
    # listing_metrics: impressions/clicks/calls/directions/... per source
    raw_metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # listing_item_metrics: review counts, rating splits, reply stats
    raw_item_metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    metrics_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    metrics_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
