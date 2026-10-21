"""Public TTS interface.

This is the only module channels, job handlers and the HTTP API should
import. It owns engine selection, provider dispatch, optional container
conversion and metering; callers own *policy* (when to speak, how long the
text may be, which channel limit applies).

Two rules keep the module extractable into its own service later:

* ``synthesize`` never raises for a rendering problem — it returns ``None``
  and the caller degrades to text. A voice failure may never eat a reply.
* Request and result are plain data. No ORM row and no session leaks out
  (``db`` is a test hook only).
"""

import logging
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from .audio import AudioFormat, convert_audio, format_for_mime
from .engines import edge, fish
from .registry import resolve_engine, voice_name

logger = logging.getLogger(__name__)

# Hard ceiling on one synthesis. The HTTP schema caps requests at the same
# length; this is the backstop for internal callers that bypass the schema.
MAX_SYNTH_CHARS = 5000

# Transport chunk size for ``synthesize_stream``. 4 KB is one Opus page —
# small enough for a call bridge to start playback early, large enough that
# the per-chunk overhead stays irrelevant.
STREAM_CHUNK_BYTES = 4096

# Target container -> Fish's format name. Fish can render the container
# directly, so no ffmpeg pass is needed for it.
_FISH_FORMAT = {
    AudioFormat.NATIVE: "opus",
    AudioFormat.OGG_OPUS: "opus",
    AudioFormat.MP3: "mp3",
    AudioFormat.WAV: "wav",
    AudioFormat.PCM16_8K: "pcm",
}


@dataclass(frozen=True)
class VoiceRef:
    """Which voice to use.

    ``tier`` picks the platform default for a tenant tier; ``engine_id`` names
    a configured engine explicitly (admin probes and tests); ``persona_id``
    overrides the engine's voice pin for one request.
    """

    tier: str = "simple"
    engine_id: str | None = None
    persona_id: str | None = None


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    language: str = "en"
    tenant_id: str | None = None
    voice: VoiceRef = field(default_factory=VoiceRef)
    format: AudioFormat = AudioFormat.NATIVE
    speed: float = 1.0
    purpose: str = "generic"


@dataclass(frozen=True)
class SynthesisResult:
    audio: bytes
    mime_type: str
    format: AudioFormat
    provider: str
    model: str
    voice: str
    latency_ms: int


def _meter(
    req: SynthesisRequest,
    engine,
    voice: str,
    chars: int,
    latency_ms: int,
    status: str,
    error: str | None = None,
) -> None:
    """Fire-and-forget usage metering. Never breaks synthesis."""
    try:
        from ..llm.usage import record_voice_event

        record_voice_event(
            req.tenant_id,
            engine.provider,
            f"voice:{engine.provider}:{engine.tier}",
            voice,
            chars,
            latency_ms,
            status=status,
            error=error,
        )
    except Exception as e:  # metering is diagnostics, not the product
        logger.warning("Voice metering failed: %s", e)


async def _render(req: SynthesisRequest, db) -> SynthesisResult | None:
    engine = await resolve_engine(
        db, req.voice.tier, req.language, req.voice.engine_id
    )
    if engine is None:
        return None

    text = req.text
    started = time.perf_counter()

    try:
        if engine.provider == "edge":
            rendered = await edge.synthesize(engine.api_model, req.language, text)
            actual_format = AudioFormat.MP3
        elif engine.provider == "fish":
            rendered = await fish.synthesize(
                engine,
                text,
                req.language,
                audio_format=_FISH_FORMAT.get(req.format, "opus"),
                persona_id=req.voice.persona_id,
            )
            actual_format = (
                AudioFormat.OGG_OPUS
                if _FISH_FORMAT.get(req.format, "opus") == "opus"
                else req.format
            )
        else:
            logger.info(
                "Voice provider %r has no client wired — degrading to text (tier=%s)",
                engine.provider,
                req.voice.tier,
            )
            return None
    except Exception as e:
        # Provider failures (network, quota, malformed response) degrade to
        # text; a voice problem may never eat the reply.
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "Voice synthesis failed provider=%s language=%s: %s: %s",
            engine.provider, req.language, type(e).__name__, str(e)[:150],
        )
        _meter(
            req, engine, voice_name(engine, req.language), len(text),
            latency_ms, "failed", f"{type(e).__name__}: {str(e)[:120]}",
        )
        return None

    latency_ms = int((time.perf_counter() - started) * 1000)
    if rendered is None:
        _meter(
            req, engine, voice_name(engine, req.language), len(text),
            latency_ms, "failed", "no audio",
        )
        return None

    audio, mime_type = rendered
    speed_changed = abs(req.speed - 1.0) > 0.01
    if req.format != AudioFormat.NATIVE:
        target_format = req.format
    elif speed_changed:
        # No container change was requested, but the tempo still needs an
        # encode — keep the provider's container.
        target_format = format_for_mime(mime_type)
    else:
        target_format = AudioFormat.NATIVE

    if target_format != AudioFormat.NATIVE and (
        mime_type != target_format.value or speed_changed
    ):
        converted = await convert_audio(
            audio, mime_type, target_format, speed=req.speed
        )
        if converted is None:
            # The caller asked for a container/tempo we cannot produce. Keep
            # the audio it can still send (a media bubble beats no reply) and
            # report the real container so it can label it correctly.
            logger.info(
                "Could not convert %s to %s at %.2fx — returning native audio",
                mime_type, target_format.value, req.speed,
            )
        else:
            audio, mime_type = converted
            actual_format = target_format
    else:
        actual_format = format_for_mime(mime_type)

    voice = (
        fish.voice_reference(engine, req.language, req.voice.persona_id)
        if engine.provider == "fish"
        else (engine.api_model or edge.voice_for(req.language))
    )
    _meter(
        req, engine, voice_name(engine, req.language), len(text),
        latency_ms, "ok",
    )
    return SynthesisResult(
        audio=audio,
        mime_type=mime_type,
        format=actual_format,
        provider=engine.provider,
        model=voice_name(engine, req.language),
        voice=voice or "",
        latency_ms=latency_ms,
    )


async def synthesize(
    req: SynthesisRequest, *, db=None
) -> SynthesisResult | None:
    """Render ``req.text`` with the best engine for the voice and language.

    Returns ``None`` when voice is not possible (no enabled engine, language
    outside the engine's coverage, provider failure). Never raises for those
    cases — callers treat ``None`` as "send text instead".

    ``db`` is a test hook; production callers omit it and the function opens
    its own session.
    """
    text = (req.text or "").strip()
    if not text:
        return None
    if len(text) > MAX_SYNTH_CHARS:
        logger.warning(
            "TTS request truncated from %d to %d characters (purpose=%s)",
            len(text), MAX_SYNTH_CHARS, req.purpose,
        )
        text = text[:MAX_SYNTH_CHARS]

    speed = float(req.speed)
    if not math.isfinite(speed) or speed <= 0:
        logger.warning("Invalid TTS speed %r — using 1.0 (purpose=%s)", req.speed, req.purpose)
        speed = 1.0
    clamped = min(2.0, max(0.5, speed))
    if clamped != speed:
        logger.warning(
            "TTS speed %.2f outside 0.5–2.0 — clamped to %.2f (purpose=%s)",
            speed, clamped, req.purpose,
        )
    speed = clamped

    bounded = SynthesisRequest(
        text=text,
        language=req.language,
        tenant_id=req.tenant_id,
        voice=req.voice,
        format=req.format,
        speed=speed,
        purpose=req.purpose,
    )

    if db is not None:
        return await _render(bounded, db)

    from ...database import async_session

    async with async_session() as session:
        return await _render(bounded, session)


async def synthesize_stream(
    req: SynthesisRequest, *, db=None
) -> AsyncIterator[bytes]:
    """Yield the rendered audio in transport-sized chunks.

    The contract is chunked bytes so a future telephony adapter can start
    playback before the whole clip exists. Today the chunking is transport
    level — first-byte latency still equals full synthesis — and an engine
    that supports native streaming can override this without changing any
    caller.
    """
    result = await synthesize(req, db=db)
    if result is None:
        return
    for offset in range(0, len(result.audio), STREAM_CHUNK_BYTES):
        yield result.audio[offset:offset + STREAM_CHUNK_BYTES]
