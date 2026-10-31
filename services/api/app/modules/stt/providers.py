"""Speech-to-text provider registry and the hosted clients.

Same shape as the LLM and embedding stacks: the provider list lives in code,
the API key and model live in the database, and the admin picks which one is
active. A provider that is not configured (or is disabled) simply is not
used — transcription falls back to local faster-whisper.

ElevenLabs is the first hosted provider. Its key is expected to carry the
speech-to-text permission only: the client calls exactly one endpoint,
`POST /v1/speech-to-text`, and never probes voices/account endpoints that
would fail with a correctly scoped key.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Providers that can serve transcription. `faster_whisper` is the local
# fallback and needs no row, key or network.
ASR_PROVIDERS: tuple[str, ...] = ("elevenlabs", "faster_whisper")

PROVIDER_META: dict[str, dict] = {
    "elevenlabs": {
        "label": "ElevenLabs",
        "base_url": "https://api.elevenlabs.io",
        "default_model": "scribe_v1",
        "models": ["scribe_v1", "scribe_v1_experimental"],
        "needs_key": True,
        "docs": "https://elevenlabs.io/docs/capabilities/speech-to-text",
        "note": "Only the speech-to-text permission is required.",
    },
    "faster_whisper": {
        "label": "Local faster-whisper",
        "base_url": None,
        "default_model": None,
        "models": [],
        "needs_key": False,
        "docs": None,
        "note": "Runs on this machine; no key, no network, no per-minute cost.",
    },
}

# ElevenLabs reports ISO-639-3 codes ("eng"); our stored/tenant codes are
# ISO-639-1. Unknown codes pass through untouched.
_ELEVEN_TO_ISO1 = {
    "eng": "en", "ara": "ar", "urd": "ur", "pes": "fa", "fas": "fa",
    "hin": "hi", "ben": "bn", "pus": "ps", "tur": "tr", "fra": "fr",
    "deu": "de", "spa": "es", "ita": "it", "rus": "ru", "cmn": "zh",
    "zho": "zh", "jpn": "ja", "kor": "ko", "por": "pt", "nld": "nl",
}


def _iso1(code: str | None) -> str | None:
    if not code:
        return None
    lowered = code.strip().lower()
    return _ELEVEN_TO_ISO1.get(lowered, lowered)


def parse_words_confidence(words: list | None) -> float | None:
    """Average word probability from ElevenLabs' `words` list.

    Their response carries `logprob` per word (natural log). We store the
    same 0..1 confidence the local Whisper path produces so downstream
    consumers do not need provider-specific branches. Punctuation/spacing
    entries have no logprob and are skipped.
    """
    import math

    probs: list[float] = []
    for word in words or []:
        if not isinstance(word, dict):
            continue
        logprob = word.get("logprob")
        if logprob is None:
            continue
        try:
            value = math.exp(float(logprob))
        except (TypeError, ValueError, OverflowError):
            continue
        probs.append(max(0.0, min(1.0, value)))
    if not probs:
        return None
    return round(sum(probs) / len(probs), 4)


def normalize_elevenlabs(result: dict) -> dict:
    """Map the ElevenLabs payload onto the local whisper result shape."""
    words = result.get("words") or []
    segments: list[dict] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        if word.get("type") not in (None, "word"):
            continue
        try:
            start = float(word.get("start") or 0.0)
            end = float(word.get("end") or start)
        except (TypeError, ValueError):
            continue
        segments.append({
            "text": str(word.get("text") or ""),
            "start": start,
            "end": end,
            "start_ms": round(start * 1000),
            "end_ms": round(end * 1000),
        })
    text = (result.get("text") or "").strip()
    duration_ms = round(segments[-1]["end"] * 1000) if segments else 0
    return {
        "text": text,
        "language": _iso1(result.get("language_code")) or "en",
        "language_probability": result.get("language_probability"),
        "confidence": parse_words_confidence(words),
        "duration_ms": duration_ms,
        "segments": segments,
    }


async def transcribe_elevenlabs(
    *,
    api_key: str,
    audio: bytes,
    filename: str,
    content_type: str,
    model: str | None = None,
    language: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 120.0,
) -> dict:
    """Transcribe audio through ElevenLabs speech-to-text.

    Raises httpx.HTTPStatusError on a rejected key/model so the caller can
    surface a real error instead of an empty transcript.
    """
    url = (base_url or PROVIDER_META["elevenlabs"]["base_url"]).rstrip("/")
    form = {
        "model_id": model or PROVIDER_META["elevenlabs"]["default_model"],
        "tag_audio_events": "false",
        "diarize": "false",
    }
    if language and len(language) == 2:
        form["language_code"] = language.lower()

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.post(
            f"{url}/v1/speech-to-text",
            headers={"xi-api-key": api_key},
            data=form,
            files={"file": (filename, audio, content_type or "application/octet-stream")},
        )
    resp.raise_for_status()
    return normalize_elevenlabs(resp.json())
