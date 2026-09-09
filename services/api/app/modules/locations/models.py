"""Location profiles — the Locations page backing store.

Google-synced fields (name, phone, website, description) live on the
Localith connection and are pushed to Google via the Localith API.
Everything the API does NOT expose (categories, hours, service area,
attributes) is stored here per user+listing, so every tab persists for
real. The UI labels which is which — never presented as Google data.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class LocationProfile(Base):
    __tablename__ = "location_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_location_profile_listing"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(String(64), index=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    categories: Mapped[dict] = mapped_column(JSON, default=dict)
    hours: Mapped[dict] = mapped_column(JSON, default=dict)
    service_area: Mapped[list] = mapped_column(JSON, default=list)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
