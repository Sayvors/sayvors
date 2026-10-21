"""Microsoft Edge neural voices — free, no API key, wide language coverage."""

import logging

logger = logging.getLogger(__name__)

# Edge neural voices per language prefix. "simple" = clear female voice,
# "advanced" = the other gender / accent, so the tiers sound different.
# Languages missing here fall back to text (no voice invented).
EDGE_VOICES: dict[str, dict[str, str]] = {
    "ar": {"simple": "ar-SA-ZariyahNeural", "advanced": "ar-SA-HamedNeural"},
    "ar-EG": {"simple": "ar-EG-SalmaNeural", "advanced": "ar-EG-ShakirNeural"},
    "en": {"simple": "en-US-JennyNeural", "advanced": "en-US-GuyNeural"},
    "ur": {"simple": "ur-PK-UzmaNeural", "advanced": "ur-PK-AsadNeural"},
    "ps": {"simple": "ps-AF-LatifaNeural", "advanced": "ps-AF-GulNawazNeural"},
    "hi": {"simple": "hi-IN-SwaraNeural", "advanced": "hi-IN-MadhurNeural"},
    "bn": {"simple": "bn-BD-NabanitaNeural", "advanced": "bn-BD-PradeepNeural"},
}


def voice_for(language: str, tier: str = "simple") -> str | None:
    """The Edge voice name serving a language, or None when uncovered."""
    voices = EDGE_VOICES.get(language)
    if not voices:
        return None
    return voices.get(tier) or next(iter(voices.values()))


async def synthesize(
    api_model: str | None, language: str, text: str
) -> tuple[bytes, str] | None:
    """Render text with Edge. Returns MP3 bytes — the caller converts if the
    channel needs another container (e.g. Ogg/Opus for a voice note)."""
    import edge_tts

    voice = api_model or voice_for(language)
    if not voice:
        return None
    communicate = edge_tts.Communicate(text, voice)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        return None
    return bytes(audio), "audio/mpeg"
