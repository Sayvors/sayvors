"""Notification rows: one per user-visible event.

Types: sync_completed | sync_failed | review_pulled | reply_posted
       | reply_failed | review_edited
`data` carries the detail payload (reviewer, rating, branch, counts…).
`href` deep-links the dashboard page that shows the full context.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    href: Mapped[str | None] = mapped_column(String(500), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


Index("ix_notifications_user_unread", Notification.user_id, Notification.read_at)

# Retention only deletes notifications that were read, and only by age. A
# partial index keeps that sweep proportional to the rows it can actually
# remove instead of scanning every notification ever created. The predicate
# is Postgres-only; SQLite (tests) builds a plain index and ignores it.
Index(
    "ix_notifications_read_created",
    Notification.created_at,
    postgresql_where=text("read_at IS NOT NULL"),
)
