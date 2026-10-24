import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10))
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class VoiceModelConfig(Base):
    """Admin-managed text-to-speech engine for any channel's voice replies.

    Mirrors the LLM model curation: the database is the single source of
    truth — tenants never name a provider, they pick a tier ("simple" /
    "advanced") and the admin decides which engine serves that tier.

    provider "edge" needs no key (Microsoft Edge voices, free);
    "fish", "elevenlabs" and "openai" are ready for when an admin adds keys.
    `languages` is a comma-separated list of BCP-47 prefixes the engine can
    speak ("ar", "en", "ur", ...) or "*" for everything.
    """

    __tablename__ = "voice_model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    label: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32), default="edge")
    api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_model: Mapped[str | None] = mapped_column(String(200), nullable=True)  # engine/voice override
    # Voice identity pin (e.g. Fish reference_id). Without it Fish picks an
    # arbitrary default per request — the tenant would hear a different
    # persona in every voice note. Pinned = persistent across conversations.
    reference_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Optional per-language voice pins, {"ur": "<reference_id>", "ar": ...}.
    # A pin for the customer's language wins; everyone else hears the
    # multilingual `reference_id` above. Empty/None = one voice for all.
    language_references: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Provider API key, Fernet-encrypted at rest; set/rotated via the admin
    # API, never in code.
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(String(16), default="simple")  # "simple" | "advanced"
    languages: Mapped[str] = mapped_column(String(500), default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TTSJob(Base):
    __tablename__ = "tts_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Link to the unified jobs table. NULL for rows created before migration.
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    voice_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("voices.id"), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    speed: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="tts_status"),
        default="pending",
    )
    audio_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Private docs key (relative to the tenant's docs prefix) — the audio is
    # not public; the router serves it after checking ownership.
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
