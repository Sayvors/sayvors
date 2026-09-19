"""Location posts (Google Posts via Localith).

Sayvors is the schedule of record: drafts/scheduled posts live here and a
background worker publishes due rows. Publishing goes through Localith's
content_publishing_media endpoint; there is no read/update API for posts,
so Google-side edits/deletes are impossible — local state is authoritative
for everything except the moment of publishing.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class LocationPost(Base):
    __tablename__ = "location_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(String(64), index=True)
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str] = mapped_column(String(255), default="")

    title: Mapped[str] = mapped_column(String(500), default="")
    post_type: Mapped[str] = mapped_column(
        Enum("update", "event", "offer", name="post_type"), default="update"
    )
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    image_urls: Mapped[list] = mapped_column(JSON, default=list)
    cta_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cta_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("draft", "scheduled", "published", "failed", "archived", name="post_status"),
        default="draft",
        index=True,
    )
    scheduled_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    localith_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
