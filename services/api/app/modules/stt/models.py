from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class ASREngineConfig(Base):
    """Admin-managed speech-to-text provider, configured like embeddings.

    One row per provider; exactly one may be active. Keys are
    Fernet-encrypted at rest and never returned by the API. A provider with
    no active row falls back to the local faster-whisper model, so an
    installation that never configured ASR keeps transcribing.
    """

    __tablename__ = "asr_engine_configs"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Fernet-encrypted, same helper as every other provider key.
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Comma-separated BCP-47 prefixes ("ar,en") or "*" for everything.
    languages: Mapped[str] = mapped_column(String(200), default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class STTJob(Base):
    __tablename__ = "stt_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Link to the unified jobs table. NULL for rows created before migration.
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    audio_url: Mapped[str] = mapped_column(String(1000))
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="stt_status"),
        default="pending",
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
