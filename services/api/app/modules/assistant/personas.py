"""AI persona registry.

The customer-facing assistant is a named team member, not a generic bot. The
admin chooses which persona is active; the reply prompt reads that row (with a
30-second process cache) so a name/gender/tone change reaches every tenant
without a deploy.

Only one persona is active at a time. If none is active, the built-in Sarah
fallback keeps the assistant working.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base
from datetime import datetime, timezone


class AIPersona(Base):
    __tablename__ = "ai_personas"
    __table_args__ = (
        Index("ix_ai_personas_active", "is_active"),
        Index("ix_ai_personas_name", "name", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # female | male | neutral. Drives the grammar instruction, not the voice
    # engine — the TTS voice is chosen in Voice models and must match.
    gender: Mapped[str] = mapped_column(String(16), default="female", server_default="female")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


@dataclass(frozen=True)
class PersonaSpec:
    name: str
    gender: str
    description: str | None
    instructions: str | None


DEFAULT_PERSONA = PersonaSpec(
    name="Sarah",
    gender="female",
    description="Warm, capable support teammate",
    instructions=None,
)

_CACHE_TTL_SECONDS = 30
_cache: tuple[float, PersonaSpec] | None = None


def invalidate_persona_cache() -> None:
    global _cache
    _cache = None


def _spec(row: AIPersona) -> PersonaSpec:
    return PersonaSpec(
        name=(row.name or DEFAULT_PERSONA.name).strip()[:80],
        gender=(row.gender or "female").strip().lower(),
        description=(row.description or "").strip() or None,
        instructions=(row.instructions or "").strip() or None,
    )


async def get_active_persona(db) -> PersonaSpec:
    """The active persona, cached briefly; Sarah when none is configured."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    row = (
        await db.execute(
            select(AIPersona)
            .where(AIPersona.is_active.is_(True))
            .order_by(AIPersona.sort_order, AIPersona.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    spec = _spec(row) if row is not None else DEFAULT_PERSONA
    _cache = (now, spec)
    return spec
