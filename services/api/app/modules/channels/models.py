import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    platform: Mapped[str] = mapped_column(
        Enum(
            "facebook",
            "instagram",
            "x",
            "telegram",
            "whatsapp",
            "linkedin",
            "google_reviews",
            name="platform_type",
        )
    )
    platform_user_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "expired", "disconnected", "error", name="channel_status"),
        default="active",
    )
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    messages = relationship("ChannelMessage", back_populates="channel", cascade="all, delete-orphan")


class ChannelMessage(Base):
    __tablename__ = "channel_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), index=True
    )
    platform_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    direction: Mapped[str] = mapped_column(Enum("inbound", "outbound", name="message_direction"))
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(50), default="text")
    status: Mapped[str] = mapped_column(
        Enum("sent", "delivered", "read", "failed", name="message_status"),
        default="sent",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    channel = relationship("Channel", back_populates="messages")


class AutoReplyConfig(Base):
    """Per-channel auto-reply settings (Phase 1: Google Reviews)."""

    __tablename__ = "auto_reply_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Tone preset: friendly, professional, apologetic, playful, ...
    tone: Mapped[str] = mapped_column(String(50), default="friendly")
    # Optional Databank linked for grounding replies in merchant knowledge
    databank_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Reviews with rating below this are queued for human approval, not auto-posted
    min_rating_auto: Mapped[int] = mapped_column(Integer, default=4)
    # "auto" = post above min_rating_auto, queue below.
    # "approval" = every reply waits for human approval.
    approval_mode: Mapped[str] = mapped_column(
        Enum("auto", "approval", name="reply_approval_mode"), default="auto"
    )
    # Free-text brand voice / house rules injected into every reply prompt
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM model id (provider catalog id, e.g. "groq:openai/gpt-oss-120b")
    model: Mapped[str] = mapped_column(String(100), default="groq:openai/gpt-oss-120b")
    # Arabic dialect code (review_engine.dialects catalog) or "auto".
    dialect: Mapped[str] = mapped_column(String(30), default="auto")
    # Reply language policy: match the review, or force en/ar.
    reply_language: Mapped[str] = mapped_column(String(10), default="match")
    # Promotional toggles — all default OFF (historical no-promo behavior).
    promo_product_mentions: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_links: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_only_relevant: Mapped[bool] = mapped_column(Boolean, default=True)
    promo_max_ctas: Mapped[int] = mapped_column(Integer, default=1)
    # Polling lease (atomic claim across worker instances)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    polling_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class VerificationRecord(Base):
    """Sayvors-side verification request state for a Google channel."""

    __tablename__ = "channel_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="unstarted")
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class BusinessService(Base):
    """Merchant services managed for one connected Google channel."""

    __tablename__ = "channel_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(120), default="Custom")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_offered: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(30), default="custom")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class ReviewReply(Base):
    """A (candidate or posted) reply to a Google review."""

    __tablename__ = "review_replies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    # Google review resource name: accounts/{a}/locations/{l}/reviews/{r}
    review_id: Mapped[str] = mapped_column(String(500), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        # "approved" = merchant approved a Localith draft; it is NOT on
        # Google yet — they post it from their Localith/GBP dashboard.
        Enum("posted", "pending_approval", "failed", "rejected", "approved",
             name="review_reply_status"),
        default="pending_approval",
    )
    # How many times a draft has been generated for this review
    # (1 = first draft; regenerate/retry/resume increments it).
    generation_attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
