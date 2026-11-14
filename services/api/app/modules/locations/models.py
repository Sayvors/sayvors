"""Location profiles — the Locations page backing store.

Google-synced fields (name, address, phone, website, description) live on
the native Google channel metadata and are pushed with the Business
Information API. Everything Google exposes as editable (categories, hours,
service area, attributes, opening date, description override) is stored
here per user+listing, so every tab persists for real.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class LocationGroup(Base):
    """A named set of listings, so bulk actions can target "North Riyadh"
    instead of every branch. Members live in `listing_ids` — a plain JSON
    list of Google location IDs, deliberately not a join table: group
    membership is only ever read and written whole, never queried across
    groups, and listings come and go from Google independently."""
    __tablename__ = "location_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    listing_ids: Mapped[list] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


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
    # Business opening date (Google openInfo.openingDate). Nullable —
    # older rows simply have none.
    opening_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LocationBusinessOverride(Base):
    """Merchant-edited business details for one Google location.

    Google's Business Profile data (name, categories, hours) can be stale or
    pending review for days/weeks. This row stores what the merchant says is
    true — it wins over Google when building the AI's facts — while
    ``google_snapshot`` keeps the official Google values captured at save
    time, so the UI can show the difference side-by-side.
    """

    __tablename__ = "location_business_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_location_business_override_listing"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(String(64), index=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # {"category": ..., "subcategories": [...], "sub_subcategories": [...]}
    categories: Mapped[dict] = mapped_column(JSON, default=dict)
    # list of {"label": ...} (or plain strings)
    services: Mapped[list] = mapped_column(JSON, default=list)
    # Same weekly shape as LocationProfile.hours
    hours: Mapped[dict] = mapped_column(JSON, default=dict)
    # list of {"date": "YYYY-MM-DD", "open": ..., "close": ..., "closed": bool}
    special_hours: Mapped[list] = mapped_column(JSON, default=list)
    # Frozen official Google values at save time, for the compare view.
    google_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    # "auto" (seeded from Google, untouched) | "edited" (user saved)
    source: Mapped[str] = mapped_column(String(16), default="auto")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
