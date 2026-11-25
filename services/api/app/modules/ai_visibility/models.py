"""Tenant-scoped prompts, durable research runs, and source snapshots."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AiVisibilityPrompt(Base):
    __tablename__ = "ai_visibility_prompts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel_id",
            "normalized_prompt_hash",
            name="uq_ai_visibility_prompt_branch_hash",
        ),
        Index(
            "ix_ai_visibility_prompts_tenant_channel",
            "tenant_id",
            "channel_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    prompt_text: Mapped[str] = mapped_column(Text)
    normalized_prompt_hash: Mapped[str] = mapped_column(CHAR(64))
    intent: Mapped[str] = mapped_column(String(80), default="custom")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AiVisibilityRun(Base):
    __tablename__ = "ai_visibility_runs"
    __table_args__ = (
        Index("ix_ai_visibility_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_visibility_runs_channel_status", "channel_id", "status"),
        Index(
            "uq_ai_visibility_one_active_run",
            "tenant_id",
            "prompt_id",
            unique=True,
            postgresql_where=text(
                "status IN ('queued','searching','fetching','reading','validating','writing')"
            ),
            sqlite_where=text(
                "status IN ('queued','searching','fetching','reading','validating','writing')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    prompt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_visibility_prompts.id", ondelete="RESTRICT")
    )
    prompt_snapshot: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(24), default="queued")
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    search_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentioned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cited: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recommended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    incorrect: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(16), default="pending")
    evidence_coverage: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    validated_claim_count: Mapped[int] = mapped_column(Integer, default=0)
    unsupported_claim_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_mentions: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )
    claims_json: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )
    actions_json: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AiVisibilitySource(Base):
    __tablename__ = "ai_visibility_sources"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "position", name="uq_ai_visibility_source_position"
        ),
        Index("ix_ai_visibility_sources_run", "run_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_visibility_runs.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(2048))
    canonical_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)

