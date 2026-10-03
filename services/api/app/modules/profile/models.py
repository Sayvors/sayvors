import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base
from ..user_feedback.models import UserFeedback

__all__ = ["BusinessProfile", "UserFeedback"]


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
