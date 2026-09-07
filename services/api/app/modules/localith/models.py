"""Localith connections (single-shared-key mode v1).

Each Sayvors user can save one Localith listing -> their user account.
The API key itself is shared (LOCALITH_API_KEY env) until we ship
per-tenant keys; only the listing choice is per-tenant here. Same
table + model will work for the per-tenant-key upgrade — just add an
encrypted key column.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class LocalithConnection(Base):
    __tablename__ = "localith_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_localith_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(String(64))
    listing_name: Mapped[str] = mapped_column(String(255))
    listing_google_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
