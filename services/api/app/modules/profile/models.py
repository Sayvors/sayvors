import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base
from ..user_feedback.models import UserFeedback

__all__ = ["BusinessProfile", "TenantFacts", "TenantIntakeAnswer", "UserFeedback"]


class BusinessProfile(Base):
    """Tenant-level AI business card — ONE per account (unique user_id).

    Distilled from the tenant's databank uploads by an LLM, shown on the
    Databank screen, editable (edits always win over regeneration), and
    injected into every AI prompt so the assistant never has to crawl the
    databank just to say what the business does.
    """

    __tablename__ = "business_profiles"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )
    # 2-3 sentence overview of what the business does
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # industry/category in a few words, e.g. "Food & Restaurant"
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # what the business sells / offers
    products_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    # what it does NOT offer + policies worth knowing (halal, refunds, delivery)
    not_offered_and_policies: Mapped[str | None] = mapped_column(Text, nullable=True)
    # who the customers are and the languages they write in
    audience_languages: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # "auto" = LLM-generated, untouched by the user; "edited" = user has saved
    # this card at least once — auto-refresh never overwrites an edited card
    source: Mapped[str] = mapped_column(String(16), default="auto")
    generated_at: Mapped[datetime | None] = mapped_column(
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


class TenantFacts(Base):
    """The single source the AI's fact tools read.

    One row per tenant, rebuilt from the owner profile, WhatsApp business
    profile, channel services, team and every location's hours. The reply
    path calls the facts tool instead of querying nine tables, so there is
    exactly one place to inspect and one place to fix when the assistant
    "doesn't know" something.

    `updated_at` is the freshness contract: a read older than the TTL is
    rebuilt on demand, and write paths rebuild eagerly.
    """

    __tablename__ = "tenant_facts"

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    facts: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'")
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TenantIntakeAnswer(Base):
    """Merchant-owned answers from the business-intake cascade.

    This is a source of truth, NOT part of the rebuildable ``TenantFacts``
    cache — writing intake answers into that row would erase them on the next
    facts rebuild. A "skipped" row is deliberate: the owner was asked and
    chose not to answer, which is different from never having been asked.
    """

    __tablename__ = "tenant_intake_answers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    vertical_key: Mapped[str] = mapped_column(String(40), nullable=False)
    question_key: Mapped[str] = mapped_column(String(80), nullable=False)
    # JSON list of chosen chip labels, or a string for free text.
    answer: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # "manual" | "google_confirmed" — records how the answer was accepted.
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default=text("'manual'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
