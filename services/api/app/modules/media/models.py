"""Location media (photos scheduled to go live on Google).

Localith exposes no photo-library upload — the only photo path to Google
is publishing a post that carries image URLs. So a "scheduled photo" here
is a photo queued to go live inside a Google post at its time, via the
same content_publishing_media endpoint posts use. Videos are stored as
library rows only: the provider takes image URLs, not video.
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
    scheduled_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Scheduled local cleanup (Google follows its own lifecycle).
    delete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Google-side post id captured at publish time, when the provider
    # returns one (reserved for future remote deletion).
    google_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    localith_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
