"""Which configured engine serves a (tier, language) request.

Admin-added engines (fish, elevenlabs, openai — anything with a key) win over
the built-in Edge fallback: an admin adding one is an explicit upgrade for the
tier.
"""

from sqlalchemy import select

from .engines import edge
from .models import VoiceModelConfig


def engine_supports_language(engine_languages: str, language: str) -> bool:
    """"*" serves all; otherwise a comma-list of BCP-47 prefixes ("ar,ur")."""
    entries = [e.strip().lower() for e in (engine_languages or "*").split(",") if e.strip()]
    if "*" in entries or not entries:
        return True
    return language.lower() in entries


def voice_name(engine, language: str) -> str:
    """Human-readable voice/model label for metering (api_model column)."""
    if getattr(engine, "api_model", None):
        return engine.api_model
    if engine.provider == "edge":
        return edge.voice_for(language, engine.tier) or f"edge:{language}"
    return f"{engine.provider}:{engine.tier}"


async def resolve_engine(
    db, tier: str, language: str, engine_id: str | None = None
) -> VoiceModelConfig | None:
    """The enabled engine serving this request, or None.

    An explicit ``engine_id`` is an admin/test override: it is honoured only
    when the row is enabled and covers the language. Otherwise engines are
    ranked keyed-first, Edge last.
    """
    if engine_id:
        row = (
            await db.execute(
                select(VoiceModelConfig).where(
                    VoiceModelConfig.id == engine_id,
                    VoiceModelConfig.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if row is None or not engine_supports_language(row.languages, language):
            return None
        return row

    rows = (
        await db.execute(
            select(VoiceModelConfig).where(
                VoiceModelConfig.enabled.is_(True),
                VoiceModelConfig.tier == tier,
            )
        )
    ).scalars().all()
    keyed: list = []
    fallback: list = []
    for row in rows:
        if not engine_supports_language(row.languages, language):
            continue
        if row.provider == "edge":
            fallback.append(row)
        else:
            keyed.append(row)
    return (keyed + fallback or [None])[0]
