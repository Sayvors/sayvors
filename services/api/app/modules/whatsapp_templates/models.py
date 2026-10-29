"""WhatsApp message templates.

Outside the 24-hour customer-service window Meta rejects free-form messages;
the only allowed send is a pre-approved template. This module stores the
templates the business has in WhatsApp Manager, the consent basis for using
them, and every send attempt.

Templates are created and approved in Meta's WhatsApp Manager — the API can
list and send them, not conjure them. "Sync" is therefore the source of truth
for status, and a local row that Meta does not know cannot be sent.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class WhatsAppTemplate(Base):
    """One pre-approved template, keyed by Meta's (name, language) pair."""

    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        # Meta identifies a template by name + language; syncing must upsert,
        # not duplicate.
        UniqueConstraint(
            "tenant_id", "name", "language", name="uq_whatsapp_templates_name_lang"
        ),
        Index("ix_whatsapp_templates_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(20), default="en")
    # utility | marketing | authentication
    category: Mapped[str] = mapped_column(String(20), default="utility")
    # approved | pending | rejected | paused | disabled | draft
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # The template body with {{1}} placeholders, for previews and validation.
    body: Mapped[str] = mapped_column(Text, default="")
    # How many {{n}} variables the body uses — the send form validates it.
    variables: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    meta_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
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


class TemplateSend(Base):
    """One attempt to send a template, with the consent basis it relied on.

    ``idempotency_key`` makes a retried POST (double click, network retry) one
    send instead of two — Meta bills and the customer notices either way.
    """

    __tablename__ = "template_sends"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_template_sends_idempotency"
        ),
        Index("ix_template_sends_tenant_created", "tenant_id", "created_at"),
        Index("ix_template_sends_lead", "lead_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("whatsapp_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    contact_phone: Mapped[str] = mapped_column(String(32))
    template_name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(20))
    variables: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    # sent | failed | blocked
    status: Mapped[str] = mapped_column(String(16), default="sent")
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The consent row that authorised it (lead.whatsapp_opt_in_at as of send).
    consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
