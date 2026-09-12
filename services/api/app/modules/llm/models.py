from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str] = mapped_column(String(100), default="gpt-4")
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    conversation = relationship("Conversation", back_populates="messages")


class ProviderConfig(Base):
    """DB-backed LLM provider key (Fernet-encrypted), managed from admin.

    The database is the single source of truth — env vars are never read.
    enabled=False is a kill-switch even when a key exists.
    """

    __tablename__ = "llm_provider_configs"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ModelConfig(Base):
    """Per-model admin curation (test-first workflow) + custom definitions.

    A row exists once an admin touches the model. Columns:
    - enabled / tested_ok / tested_at: curation, applies to catalog AND custom.
    - display_name / provider / api_model / context_window / max_output /
      supports_stream: set ONLY for admin-added custom models. NULL means
      "this is a catalog model, definition lives in code".
    """

    __tablename__ = "llm_model_configs"

    model_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tested_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Custom-model definition (NULL = catalog model, defined in code).
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    api_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_stream: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
