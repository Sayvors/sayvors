"""Voice notes: admin-managed TTS engines, per-language synthesis.

The tenant picks a tier ("simple" / "advanced"); the admin decides which
engine serves each tier (voice_model_configs — seeded with the free Edge
neural voices, ready for ElevenLabs/OpenAI rows without a migration).

synthesize_voice_note resolves the engine for (tier, language), renders the
text, and returns (audio_bytes, mime_type) — or None when voice is not
possible (no enabled engine for the tier, language outside the engine's
coverage, synthesis failure). Callers MUST treat None as "send text
instead": a voice problem may never eat the reply.
"""
import asyncio
import logging
import time

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Edge neural voices per language prefix. "simple" = clear female voice,
# "advanced" = the other gender / accent, so the tiers sound different.
# Languages missing here fall back to text (no voice invented).
_EDGE_VOICES: dict[str, dict[str, str]] = {
    "ar": {"simple": "ar-SA-ZariyahNeural", "advanced": "ar-SA-HamedNeural"},
    "ar-EG": {"simple": "ar-EG-SalmaNeural", "advanced": "ar-EG-ShakirNeural"},
    "en": {"simple": "en-US-JennyNeural", "advanced": "en-US-GuyNeural"},
    "ur": {"simple": "ur-PK-UzmaNeural", "advanced": "ur-PK-AsadNeural"},
    "ps": {"simple": "ps-AF-LatifaNeural", "advanced": "ps-AF-GulNawazNeural"},
    "hi": {"simple": "hi-IN-SwaraNeural", "advanced": "hi-IN-MadhurNeural"},
    "bn": {"simple": "bn-BD-NabanitaNeural", "advanced": "bn-BD-PradeepNeural"},
}

# Long voice notes lose the listener — the owner asked for 30-40s notes,
# which at a natural speaking pace is roughly this much text.
_MAX_VOICE_CHARS = 550


def normalize_voice_tier(value: str | None) -> str:
    """The stored tenant tier as the voice pipeline understands it.

    Anything unknown reads as "off" — a bad hand-edit disables voice rather
    than surprising the tenant with it.
    """
    return value if value in ("simple", "advanced") else "off"


def engine_supports_language(engine_languages: str, language: str) -> bool:
    """"*" serves all; otherwise a comma-list of BCP-47 prefixes ("ar,ur")."""
    entries = [e.strip().lower() for e in (engine_languages or "*").split(",") if e.strip()]
    if "*" in entries or not entries:
        return True
    return language.lower() in entries


async def resolve_voice_engine(db, tier: str, language: str):
    """The enabled VoiceModelConfig serving this tier+language, or None.

    Admin-added engines (fish, elevenlabs, openai — anything with a key)
    win over the built-in Edge fallback: an admin adding one is an explicit
    upgrade for the tier.
    """
    from ...llm.models import VoiceModelConfig

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


def voice_name(engine, language: str) -> str:
    """Human-readable voice/model label for metering (api_model column)."""
    if getattr(engine, "api_model", None):
        return engine.api_model
    if engine.provider == "edge":
        voices = _EDGE_VOICES.get(language) or {}
        return voices.get("simple") or f"edge:{language}"
    return f"{engine.provider}:{engine.tier}"


async def synthesize_voice_note(
    db, tier: str, language: str, text: str, tenant_id: str | None = None
) -> tuple[bytes, str] | None:
    """(audio_bytes, mime_type) for this reply — None when voice is not
    possible. Never raises. Successful and failed engine attempts are
    metered (fire-and-forget) for the admin voice-usage charts."""
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > _MAX_VOICE_CHARS:
        text = text[:_MAX_VOICE_CHARS].rsplit(" ", 1)[0] + "…"

    def _meter(status: str, error: str | None, latency_ms: int) -> None:
        try:
            from ...llm.usage import record_voice_event

            record_voice_event(
                tenant_id, engine.provider, f"voice:{engine.provider}:{engine.tier}",
                voice_name(engine, language), len(text), latency_ms,
                status=status, error=error,
            )
        except Exception:
            pass  # metering may never break synthesis

    try:
        engine = await resolve_voice_engine(db, tier, language)
        if engine is None:
            return None
        started = time.perf_counter()
        if engine.provider == "edge":
            result = await _synthesize_edge(engine.api_model, language, text)
        elif engine.provider == "fish":
            result = await _synthesize_fish(engine, text, language)
        else:
            logger.info(
                "Voice provider %r has no client wired yet — sending text "
                "instead tier=%s", engine.provider, tier,
            )
            return None
        latency_ms = int((time.perf_counter() - started) * 1000)
        if result is None:
            _meter("failed", "no audio", latency_ms)
            return None
        _meter("ok", None, latency_ms)
        return result
    except Exception as e:
        logger.warning(
            "Voice synthesis failed tier=%s language=%s: %s: %s",
            tier, language, type(e).__name__, str(e)[:150],
        )
        return None


def fish_voice_reference(engine, language: str) -> str | None:
    """The voice persona for this language: a per-language pin when the
    admin added one ("urdu sounds like X, arabic like Y"), else the
    engine-wide multilingual voice."""
    pins = engine.language_references or {}
    return pins.get(language) or engine.reference_id


async def _synthesize_fish(engine, text: str, language: str = "en") -> tuple[bytes, str] | None:
    """Fish Audio TTS (bearer auth, JSON body) as a WhatsApp voice note.

    The engine row carries api_url, api_model (sent as the `model` header —
    e.g. the free "s2.1-pro-free"), reference_id plus optional per-language
    pins (a pinned persona — without one Fish picks an arbitrary default
    per request, so the tenant would hear a different person every time)
    and the Fernet-encrypted API key. Output is Ogg/Opus 48kHz mono — the
    exact format WhatsApp renders as a real voice note (mp3 only ever
    renders as a media bubble).
    """
    import httpx

    from ..service import decrypt_token

    api_key = decrypt_token(engine.key_encrypted) if engine.key_encrypted else None
    if not api_key:
        logger.info("Fish voice engine has no API key — sending text instead")
        return None
    url = engine.api_url or "https://api.fish.audio/v1/tts"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if engine.api_model:
        headers["model"] = engine.api_model
    body: dict = {
        "text": text,
        # Ogg/Opus is the only format Meta renders as a voice note.
        "format": "opus",
        "sample_rate": 48000,
        "normalize": True,
        "latency": "normal",
    }
    reference_id = fish_voice_reference(engine, language)
    if reference_id:
        body["reference_id"] = reference_id
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        logger.warning(
            "Fish TTS failed (%s): %s", resp.status_code, resp.text[:200]
        )
        return None
    audio = resp.content
    if not audio:
        return None
    return audio, "audio/ogg"


_FISH_SORT_BY = ("score", "task_count", "created_at")
_FISH_CATALOG_PAGE_SIZE = 24


async def fish_voice_catalog(
    api_key: str, sort_by: str = "task_count", page: int = 1
) -> dict:
    """The fish.audio public voice library, slimmed for the admin picker.

    Fish's list endpoint ignores text search (verified live), but each
    model carries `languages` — the admin filters by language in the UI.
    Returns {"items": [{id, title, languages, tags, likes, uses}], "has_more"};
    raises ValueError with a readable message on failure.
    """
    import httpx

    if sort_by not in _FISH_SORT_BY:
        sort_by = "task_count"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://api.fish.audio/model",
            headers={"Authorization": f"Bearer {api_key}"},
            params={
                "page_size": _FISH_CATALOG_PAGE_SIZE,
                "page_number": max(1, page),
                "sort_by": sort_by,
            },
        )
    if resp.status_code >= 400:
        raise ValueError(f"fish.audio catalog failed ({resp.status_code})")
    data = resp.json()
    items = [
        {
            "id": it.get("_id", ""),
            "title": it.get("title") or "Untitled voice",
            "languages": it.get("languages") or [],
            "tags": (it.get("tags") or [])[:6],
            "likes": it.get("like_count"),
            "uses": it.get("task_count"),
        }
        for it in data.get("items", [])
        if it.get("_id")
    ]
    return {"items": items, "has_more": bool(data.get("has_more"))}


async def as_voice_note(audio: bytes, mime_type: str) -> tuple[bytes, str, bool]:
    """(bytes, mime, can_be_voice_note) — converts mp3 to Ogg/Opus when
    ffmpeg is available, because Meta only renders Ogg/Opus as a voice note.
    Unconvertible audio is still sent (as a plain audio bubble); the text
    fallback never depends on this."""
    if mime_type == "audio/ogg":
        return audio, mime_type, True
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.info("ffmpeg unavailable — audio goes out as a media bubble, not a voice note")
        return audio, mime_type, False
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as src:
            src.write(audio)
            src_path = src.name
        out_path = src_path[:-4] + ".ogg"
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-loglevel", "error", "-i", src_path,
            "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1",
            out_path,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("ffmpeg conversion failed: %s", (stderr or b"")[:150])
            return audio, mime_type, False
        with open(out_path, "rb") as f:
            converted = f.read()
        import os as _os

        _os.unlink(src_path)
        _os.unlink(out_path)
        if not converted or converted[:4] != b"OggS":
            return audio, mime_type, False
        return converted, "audio/ogg", True
    except Exception as e:
        logger.warning("Voice conversion failed: %s: %s", type(e).__name__, str(e)[:120])
        return audio, mime_type, False


async def _synthesize_edge(api_model: str | None, language: str, text: str) -> tuple[bytes, str] | None:
    """Free Microsoft Edge neural voices — no key, wide language coverage."""
    import edge_tts

    voices = _EDGE_VOICES.get(language)
    if not voices:
        return None
    voice = api_model if api_model else voices.get("simple") or next(iter(voices.values()))
    communicate = edge_tts.Communicate(text, voice)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        return None
    return bytes(audio), "audio/mpeg"
