"""Durable email delivery: outbox, events and suppressions.

Transactional email must not depend on the request that triggered it. The API
writes an ``email_outbox`` row and returns; a worker sends it with retries,
records provider events, and refuses addresses that bounced, complained or
unsubscribed. No API key ever reaches the browser.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class EmailOutbox(Base):
    """One queued email. ``idempotency_key`` is the dedupe boundary."""

    __tablename__ = "email_outbox"
    __table_args__ = (
        Index("ix_email_outbox_status_due", "status", "next_attempt_at"),
        Index("ix_email_outbox_tenant_created", "tenant_id", "created_at"),
        Index(
            "uq_email_outbox_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_email_outbox_provider_id", "provider_id"),
        Index("ix_email_outbox_campaign", "campaign_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    to_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    html: Mapped[str] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # auth.otp | welcome | password_reset | team_invite | notification |
    # review_request | newsletter | billing
    kind: Mapped[str] = mapped_column(String(32), index=True)
    headers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'"))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Newsletter campaign that produced this row (NULL for transactional mail).
    campaign_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # queued | sending | sent | failed | dead | suppressed
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # When the worker moved the row to `sending`. A crash before the provider
    # result leaves the row there forever; the reaper uses this timestamp to
    # requeue it safely (the provider idempotency key prevents a double send).
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailEvent(Base):
    """Provider webhook history, independent of the outbox row's final state."""

    __tablename__ = "email_events"
    __table_args__ = (
        Index("ix_email_events_email_created", "email", "created_at"),
        Index("ix_email_events_type_created", "type", "created_at"),
        Index(
            "uq_email_events_provider_event",
            "provider_event_id",
            unique=True,
            postgresql_where=sa_text("provider_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    outbox_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    type: Mapped[str] = mapped_column(String(24), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EmailSuppression(Base):
    """Addresses we must never send to again."""

    __tablename__ = "email_suppressions"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    # bounce | complaint | unsubscribe
    reason: Mapped[str] = mapped_column(String(24))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EmailCampaign(Base):
    """A newsletter composed once and expanded into the durable outbox.

    Expansion is a keyset walk over a snapshot of the audience taken at start
    (`max_user_id`), so new signups do not join a campaign already in flight
    and a crash resumes from `last_user_id` instead of re-mailing the list.
    """

    __tablename__ = "email_campaigns"
    __table_args__ = (
        Index("ix_email_campaigns_status_due", "status", "next_expand_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str] = mapped_column(String(500))
    html: Mapped[str] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # draft | running | completed | cancelled
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", index=True
    )
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expanded_recipients: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Keyset snapshot: expand users with last_user_id < id <= max_user_id.
    last_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    max_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=500, server_default="500")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    next_expand_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
