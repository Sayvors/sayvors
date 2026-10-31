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
import os
import tempfile
from pathlib import Path

import httpx

from ...config import settings

logger = logging.getLogger(__name__)


# One 25 MB clip is the ceiling for a customer-supplied media URL. See
# `_download_audio_bytes` for why the cap exists.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

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
    db=None,
) -> dict:
    """Transcribe audio from a public URL.

    Provider resolution mirrors the LLM/embedding stacks: the admin activates
    a hosted engine in the database and this function uses it. With no active
    engine (or a misconfigured one) it falls back to the local faster-whisper
    model, so a bad key degrades quality rather than killing every voice note.

    Returns a dict with:
        text            — transcribed text
        language        — detected or requested language code
        confidence      — average word-level confidence (0..1)
        duration_ms     — audio duration in milliseconds
        segments        — per-segment transcription with timestamps
    """
    hosted = await _active_hosted_engine(db, language)
    if hosted is not None:
        try:
            return await _transcribe_hosted(hosted, audio_url, language, model)
        except Exception as e:  # noqa: BLE001 - never lose the voice note
            logger.warning(
                "ASR provider %s failed (%s: %s) - falling back to faster-whisper",
                hosted.get("provider"), type(e).__name__, str(e)[:160],
            )

    # Download audio to a temp file (providers serve media over public URLs).
    audio_path = await _download_audio(audio_url)
    try:
        return await _transcribe_path(audio_path, language, model, beam_size, vad_filter)
    finally:
        _cleanup(audio_path)


async def transcribe_bytes(
    audio: bytes,
    *,
    filename: str = "audio.ogg",
    content_type: str = "audio/ogg",
    language: str | None = None,
    db=None,
    allow_local_fallback: bool = True,
) -> dict:
    """Transcribe audio already in memory (an inbound voice note).

    The channel path downloads the media itself — WhatsApp media URLs require
    the tenant's token — so there is nothing for this function to fetch.

    ``allow_local_fallback=False`` is for the API process: loading a Whisper
    model there can exhaust a container sized for web traffic. The caller
    prefers an honest "couldn't hear that" over an OOM that kills every
    conversation in flight.
    """
    hosted = await _active_hosted_engine(db, language)
    if hosted is not None:
        try:
            return await _transcribe_hosted_bytes(
                hosted, audio, filename, content_type, language
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "ASR provider %s failed (%s: %s)",
                hosted.get("provider"), type(e).__name__, str(e)[:160],
            )
            if not allow_local_fallback:
                raise
    elif not allow_local_fallback:
        raise RuntimeError("no hosted ASR engine is configured")

    import tempfile
    from pathlib import Path

    suffix = Path(filename).suffix or ".ogg"
    tmp_path = Path(tempfile.gettempdir()) / f"stt_{os_urandom_hex(8)}{suffix}"
    tmp_path.write_bytes(audio)
    try:
        return await _transcribe_path(tmp_path, language, None, None, None)
    finally:
        _cleanup(tmp_path)


async def _transcribe_path(
    audio_path: Path,
    language: str | None,
    model: str | None,
    beam_size: int | None,
    vad_filter: bool | None,
) -> dict:
    """Local faster-whisper transcription of a file already on disk."""
    loaded = _load_model()
    if loaded is None:
        raise RuntimeError(
            _model_loading_error
            or "faster-whisper model unavailable (not installed or load failed)"
        )

    # Run the blocking CPU/GPU inference in a thread pool so the event
    # loop is not blocked while Whisper crunches audio.
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _transcribe_sync,
        loaded,
        str(audio_path),
        language,
        beam_size,
        vad_filter,
    )


def _cleanup(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
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
    audio, ext, _content_type = await _download_audio_bytes(audio_url)
    tmp_path = Path(tempfile.gettempdir()) / f"stt_{os_urandom_hex(8)}{ext}"
    tmp_path.write_bytes(audio)
    return tmp_path


async def _download_audio_bytes(audio_url: str) -> tuple[bytes, str, str]:
    """Download the media once and report (bytes, extension, content type).

    Streamed with a hard cap: a bulk lane worker has ~384 MB of heap and a
    media URL is customer-controlled data. Without the cap one oversized (or
    malicious) file could OOM the process and take every queued voice note
    with it. WhatsApp voice notes are well under 16 MB; 25 MB leaves room for
    forwarded clips without trusting the sender.
    """
    ext = ".bin"
    content_type = "application/octet-stream"
    chunks: list[bytes] = []
    total = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("GET", audio_url, follow_redirects=True) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type") or content_type
            declared = resp.headers.get("content-length")
            if declared:
                try:
                    if int(declared) > MAX_AUDIO_BYTES:
                        raise RuntimeError(
                            f"audio too large: {declared} bytes (max {MAX_AUDIO_BYTES})"
                        )
                except ValueError:
                    pass
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_AUDIO_BYTES:
                    raise RuntimeError(
                        f"audio too large: exceeded {MAX_AUDIO_BYTES} bytes"
                    )
                chunks.append(chunk)

    # Guess extension from content-type so providers can sniff it.
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

    return b"".join(chunks), ext, content_type


async def _active_hosted_engine(db, language: str | None) -> dict | None:
    """The configured hosted engine, when it can serve this language.

    `faster_whisper` is never returned: it is the local path this function
    guards. A language outside the engine's declared coverage also falls
    back, so an engine pinned to Arabic does not mangle an English note.
    """
    try:
        from .config import get_active_asr_config

        config = await get_active_asr_config(db)
    except Exception as e:  # noqa: BLE001 - config must never block audio
        logger.warning("ASR config lookup failed: %s", e)
        return None
    if not config or config.get("provider") == "faster_whisper":
        return None
    if not config.get("api_key"):
        logger.warning(
            "ASR engine %s is active but has no API key - using local whisper",
            config.get("provider"),
        )
        return None
    languages = (config.get("languages") or "*").strip()
    if language and languages != "*":
        allowed = {part.strip().lower() for part in languages.split(",") if part.strip()}
        if allowed and language.lower()[:2] not in allowed:
            return None
    return config


async def _transcribe_hosted(
    config: dict,
    audio_url: str,
    language: str | None,
    model: str | None,
) -> dict:
    """Download then transcribe through the configured hosted provider."""
    audio, ext, content_type = await _download_audio_bytes(audio_url)
    return await _transcribe_hosted_bytes(
        config, audio, f"audio{ext}", content_type, language, model
    )


async def _transcribe_hosted_bytes(
    config: dict,
    audio: bytes,
    filename: str,
    content_type: str,
    language: str | None,
    model: str | None = None,
) -> dict:
    """Transcribe in-memory audio through the configured hosted provider."""
    import time

    from .providers import transcribe_elevenlabs

    provider = config.get("provider")
    if provider != "elevenlabs":
        raise RuntimeError(f"no client for ASR provider {provider!r}")

    started = time.perf_counter()
    result = await transcribe_elevenlabs(
        api_key=config["api_key"],
        audio=audio,
        filename=filename,
        content_type=content_type,
        model=model or config.get("model"),
        language=language,
        base_url=config.get("base_url"),
    )
    # Capacity numbers for the bulk lane: bytes in, wall time, characters out.
    # Without this an ASR slowdown is invisible until the queue backs up.
    logger.info(
        "ASR provider=%s model=%s bytes=%d lang=%s latency_ms=%d chars=%d",
        provider,
        model or config.get("model"),
        len(audio),
        result.get("language") or language or "auto",
        int((time.perf_counter() - started) * 1000),
        len(result.get("text") or ""),
    )
    return result


def os_urandom_hex(n: int) -> str:
    return os.urandom(n).hex()