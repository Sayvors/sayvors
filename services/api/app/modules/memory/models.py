"""Cumulative memory: what resolved conversations taught the business.

One row per resolution summary, gated by a human review queue. Pending rows
are inert; only approved rows reach the reply prompt. The content is
PII-scrubbed before it is stored, and it never carries the customer's phone,
name, email or order ids.

`source_context_id` is provenance, not identity: deleting the thread nulls it
and the scrubbed business facts survive. The summary is business knowledge,
not a customer record.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class ConversationMemory(Base):
    __tablename__ = "conversation_memories"
    __table_args__ = (
        # The review queue and the retrieval scan are both tenant + status.
        Index(
            "ix_memories_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        # A resolve that produces the same context twice must not queue it
        # twice. NULL (thread deleted) is allowed to repeat.
        UniqueConstraint(
            "source_context_id", name="uq_memories_source_context"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36))
    # Provenance only. The thread can be deleted; the scrubbed lesson stays.
    source_context_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("conversation_contexts.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary: Mapped[str] = mapped_column(Text)
    # One line: quote sent, booking confirmed, issue resolved, ...
    outcome: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Team-approved reusable facts extracted from the conversation.
    facts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="memory_status"),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    # The model that extracted the draft; "manual" when a human wrote it.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
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
