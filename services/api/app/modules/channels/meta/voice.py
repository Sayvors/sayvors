"""Voice-note policy for Meta channels.

Synthesis itself lives in ``app.modules.tts``. This module only decides how a
Meta reply uses it: the 550-character voice-note budget, the Ogg/Opus
requirement (Meta renders nothing else as a real voice note), and the
text-fallback contract.

Other channels must call ``app.modules.tts.api`` directly — nothing outside
``channels.meta`` should import this module.
"""

from ...tts.api import AudioFormat, SynthesisRequest, VoiceRef, synthesize
from ...tts.audio import convert_audio

# Long voice notes lose the listener — the owner asked for 30-40s notes,
# which at a natural speaking pace is roughly this much text.
MAX_VOICE_CHARS = 550


def normalize_voice_tier(value: str | None) -> str:
    """The stored tenant tier as the voice pipeline understands it.

    Anything unknown reads as "off" — a bad hand-edit disables voice rather
    than surprising the tenant with it.
    """
    return value if value in ("simple", "advanced") else "off"


def truncate_for_voice_note(text: str | None) -> str:
    """Trim a reply to the voice-note budget, cutting at a word boundary."""
    text = (text or "").strip()
    if len(text) <= MAX_VOICE_CHARS:
        return text
    return text[:MAX_VOICE_CHARS].rsplit(" ", 1)[0] + "…"


async def as_voice_note(audio: bytes, mime_type: str) -> tuple[bytes, str, bool]:
    """(bytes, mime, can_be_voice_note) — converts to Ogg/Opus when possible.

    Meta only renders Ogg/Opus as a voice note; anything else goes out as a
    plain audio bubble. The text fallback never depends on this succeeding.
    """
    if mime_type == "audio/ogg":
        return audio, mime_type, True
    converted = await convert_audio(audio, mime_type, AudioFormat.OGG_OPUS)
    if converted is None:
        return audio, mime_type, False
    return converted[0], converted[1], True


async def synthesize_voice_note(
    db, tier: str, language: str, text: str, tenant_id: str | None = None
) -> tuple[bytes, str] | None:
    """(audio_bytes, mime_type) for this reply — None when voice is not
    possible. Never raises: a voice problem may never eat the reply.
    """
    text = truncate_for_voice_note(text)
    if not text:
        return None

    result = await synthesize(
        SynthesisRequest(
            text=text,
            language=language or "en",
            tenant_id=tenant_id,
            voice=VoiceRef(tier=tier),
            format=AudioFormat.NATIVE,
            purpose="meta_voice_note",
        ),
        db=db,
    )
    if result is None:
        return None
    return result.audio, result.mime_type
