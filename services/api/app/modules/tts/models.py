from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
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


class TTSJob(Base):
    __tablename__ = "tts_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    text: Mapped[str] = mapped_column(Text)
    voice_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("voices.id"), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    speed: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="tts_status"),
        default="pending",
    )
    audio_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
