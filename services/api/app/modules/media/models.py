"""Location media (photos scheduled to go live on Google).

A media row is one photo. It can publish inside a Google local post, into the
location gallery, or as the profile photo — all through the native Business
Profile media API. Videos are stored as library rows only: the publisher
takes image URLs, not video.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class LocationMedia(Base):
    __tablename__ = "location_media"
    __table_args__ = (
        Index("ix_media_due", "status", "scheduled_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(String(64), index=True)
    # Link to the unified jobs table. NULL for rows created before migration.
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    image_url: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(
        Enum("PHOTO", "VIDEO", name="media_type"), default="PHOTO"
    )
    category: Mapped[str] = mapped_column(String(32), default="EXTERIOR")
    caption: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(
        Enum("draft", "scheduled", "published", "failed", name="media_status"),
        default="draft",
        index=True,
    )
    # How this photo reaches Google: "post" (local post), "gallery" (location
    # media in its category), or "profile" (PROFILE slot).
    publish_method: Mapped[str] = mapped_column(String(16), default="post")
    scheduled_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Scheduled local cleanup (Google follows its own lifecycle).
    delete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Google-side post/media id captured at publish time (reserved for
    # future remote deletion).
    google_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    google_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Retry-then-park, same policy as posts.
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Library flags (local organization; Google has no equivalent API).
    is_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CoverMonitor(Base):
    """Tracks the Google cover photo we set and whether Google kept it.

    The GBP API exposes the *designated* cover but not the image Google chooses
    to display publicly, so this row records what we uploaded and compares it
    with the cover Google reports on each check. A mismatch is surfaced to the
    merchant as "Google changed it — replace again" rather than silently
    drifting.
    """

    __tablename__ = "cover_monitors"
    __table_args__ = (
        Index("uq_cover_monitor_tenant_channel", "tenant_id", "channel_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[str] = mapped_column(String(255), default="")
    location_id: Mapped[str] = mapped_column(String(255), default="")

    expected_name: Mapped[str] = mapped_column(String(512), default="")
    expected_image_url: Mapped[str] = mapped_column(Text, default="")
    actual_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    actual_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ok | changed | error
    status: Mapped[str] = mapped_column(String(12), default="ok", index=True)
    drift_count: Mapped[int] = mapped_column(default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BannerCheck(Base):
    """One AI suitability analysis of a banner/promotion photo.

    Runs on the realtime job lane because a publication is waiting on it; the
    row is what the composer polls, so a worker crash surfaces as "failed"
    instead of a hung publish dialog. Payload columns mirror the synchronous
    /analyze-banner response so the UI consumes either identically.
    """

    __tablename__ = "banner_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    media_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    suitable: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidence: Mapped[int | None] = mapped_column(nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_verdict_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
