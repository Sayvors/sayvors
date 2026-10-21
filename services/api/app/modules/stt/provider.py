"""Speech-to-text provider using faster-whisper (CTranslate2).

General-purpose speech transcription: any audio URL from any channel
(WhatsApp voice notes, Instagram voice messages, Facebook voice notes,
Telegram voice messages, Google voice posts, user uploads, etc.). Not
hardcoded to any platform — any caller can enqueue an STT job.

Model weights are loaded once and cached for the life of the process so
transcription latency is dominated by inference, not model loading.

Requires `faster-whisper` (pip install faster-whisper). If it is not
installed or model loading fails, transcription degrades gracefully:
the job fails with a clear error instead of silently producing garbage.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

# Cached model instance — loaded once on first use.
_model: "WhisperModel | None" = None
_model_loading_error: str | None = None


def _load_model() -> "WhisperModel | None":
    """Load the faster-whisper model once, cache it.

    Returns None (and logs a warning) if faster-whisper is not installed
    or the model cannot be loaded — callers degrade gracefully.
    """
    global _model, _model_loading_error

    if _model is not None:
        return _model
    if _model_loading_error is not None:
        return None

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _model_loading_error = (
            "faster-whisper is not installed. "
            "pip install faster-whisper to enable STT."
        )
        logger.warning(_model_loading_error)
        return None

    try:
        _model = WhisperModel(
            settings.STT_MODEL,
            device=settings.STT_DEVICE,
            compute_type=settings.STT_COMPUTE_TYPE,
        )
        logger.info(
            "Faster-Whisper model loaded: model=%s device=%s compute_type=%s",
            settings.STT_MODEL,
            settings.STT_DEVICE,
            settings.STT_COMPUTE_TYPE,
        )
    except Exception as e:  # noqa: BLE001 — model load can fail for many reasons
        _model_loading_error = str(e)
        logger.warning("Faster-Whisper model load failed: %s", e)
        return None

    return _model


async def transcribe_audio(
    audio_url: str,
    language: str | None = None,
    model: str | None = None,
    beam_size: int | None = None,
    vad_filter: bool | None = None,
) -> dict:
    """Transcribe audio from a public URL using faster-whisper.

    General-purpose: any audio URL from any channel (WhatsApp voice notes,
    Instagram voice messages, Facebook voice notes, Telegram voice messages,
    Google voice posts, user uploads, etc.).

    Returns a dict with:
        text            — transcribed text
        language        — detected or requested language code
        confidence      — average word-level confidence (0..1)
        duration_ms     — audio duration in milliseconds
        segments        — per-segment transcription with timestamps
    """
    # Download audio to a temp file (providers serve media over public URLs).
    audio_path = await _download_audio(audio_url)

    try:
        model = _load_model()
        if model is None:
            raise RuntimeError(
                _model_loading_error
                or "faster-whisper model unavailable (not installed or load failed)"
            )

        # Run the blocking CPU/GPU inference in a thread pool so the event
        # loop is not blocked while Whisper crunches audio.
        import asyncio

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _transcribe_sync,
            model,
            str(audio_path),
            language,
            beam_size,
            vad_filter,
        )

        return result
    finally:
        # Clean up the temp file.
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 — best effort cleanup
            pass


def _transcribe_sync(
    model: "WhisperModel",
    audio_path: str,
    language: str | None,
    beam_size: int | None,
    vad_filter: bool | None,
) -> dict:
    """Synchronous transcription (runs in a thread pool)."""
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=beam_size or settings.STT_BEAM_SIZE,
        vad_filter=vad_filter if vad_filter is not None else settings.STT_VAD_FILTER,
        word_timestamps=True,
    )

    segments = []
    total_duration_ms = 0.0

    for segment in segments_iter:
        segments.append(
            {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "start_ms": round(segment.start * 1000),
                "end_ms": round(segment.end * 1000),
                "text": segment.text,
                "avg_logprob": segment.avg_logprob,
                "no_speech_prob": segment.no_speech_prob,
            }
        )
        total_duration_ms = max(total_duration_ms, segment.end)

    # Average word-level confidence across all words in all segments.
    all_words = [w for segment in segments_iter for w in segment.words]
    avg_confidence = None
    if all_words:
        confidences = [
            w.probability for w in all_words if w.probability is not None
        ]
        if confidences:
            avg_confidence = sum(confidences) / len(confidences)

    return {
        "text": " ".join(s.text for s in segments).strip(),
        "language": info.language,
        "language_probability": info.language_probability,
        "confidence": round(avg_confidence, 4) if avg_confidence is not None else None,
        "duration_ms": round(total_duration_ms * 1000),
        "segments": segments,
    }


async def _download_audio(audio_url: str) -> Path:
    """Download audio from a public URL to a temp file.

    Returns the local path. Caller is responsible for cleanup.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(audio_url, follow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        # Guess extension from content-type so faster-whisper can sniff it.
        ext = ".bin"
        if "audio/mpeg" in content_type or "audio/mp3" in content_type:
            ext = ".mp3"
        elif "audio/wav" in content_type:
            ext = ".wav"
        elif "audio/ogg" in content_type or "audio/opus" in content_type:
            ext = ".ogg"
        elif "audio/mp4" in content_type or "audio/aac" in content_type:
            ext = ".m4a"
        elif "audio/webm" in content_type:
            ext = ".webm"
        elif "audio/flac" in content_type:
            ext = ".flac"
        elif "audio/x-m4a" in content_type:
            ext = ".m4a"

        tmp_path = Path(tempfile.gettempdir()) / f"stt_{os_urandom_hex(8)}{ext}"
        tmp_path.write_bytes(resp.content)
        return tmp_path


def os_urandom_hex(n: int) -> str:
    import os

    return os.urandom(n).hex()