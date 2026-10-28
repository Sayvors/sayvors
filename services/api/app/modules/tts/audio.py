"""Audio container conversion.

Synthesis providers each speak a different container (Edge: MP3, Fish:
Ogg/Opus or MP3). Channels need a specific one — Meta renders only Ogg/Opus
as a real voice note, telephony wants 8 kHz PCM — so conversion belongs to
the TTS capability, not to each caller.

Conversion uses ffmpeg when it is installed. ``None`` means "could not
convert" and the caller keeps the original audio; no exception crosses the
boundary.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from enum import Enum

logger = logging.getLogger(__name__)

# Opus at 32 kbps mono is transparent enough for speech and keeps a 40-second
# note under ~160 KB; MP3 at 64 kbps matches what the public API returns.
_OGG_OPUS_BITRATE = "32k"
_MP3_BITRATE = "64k"
_TELEPHONY_RATE = 8000


class AudioFormat(str, Enum):
    """Target container for a synthesis request.

    ``NATIVE`` means "whatever the engine produces" — no ffmpeg pass. The
    actual container is reported back in ``SynthesisResult.format``.
    """

    NATIVE = "native"
    MP3 = "audio/mpeg"
    OGG_OPUS = "audio/ogg"
    WAV = "audio/wav"
    PCM16_8K = "audio/pcm"


_SOURCE_SUFFIX = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/pcm": ".pcm",
}

_MAGIC = {
    AudioFormat.OGG_OPUS: b"OggS",
    AudioFormat.WAV: b"RIFF",
}


def format_for_mime(mime_type: str) -> AudioFormat:
    """Best-effort mapping of a provider's mime type to a known format."""
    if mime_type in ("audio/ogg", "audio/opus"):
        return AudioFormat.OGG_OPUS
    if mime_type in ("audio/wav", "audio/x-wav"):
        return AudioFormat.WAV
    if mime_type == "audio/pcm":
        return AudioFormat.PCM16_8K
    return AudioFormat.MP3


def _ffmpeg_args(target: AudioFormat, out_path: str) -> list[str] | None:
    if target == AudioFormat.OGG_OPUS:
        return [
            "-c:a", "libopus", "-b:a", _OGG_OPUS_BITRATE,
            "-ar", "48000", "-ac", "1", out_path,
        ]
    if target == AudioFormat.MP3:
        return ["-c:a", "libmp3lame", "-b:a", _MP3_BITRATE, out_path]
    if target == AudioFormat.WAV:
        return ["-c:a", "pcm_s16le", out_path]
    if target == AudioFormat.PCM16_8K:
        return [
            "-f", "s16le", "-ac", "1", "-ar", str(_TELEPHONY_RATE), out_path,
        ]
    return None


def _out_suffix(target: AudioFormat) -> str:
    return {
        AudioFormat.OGG_OPUS: ".ogg",
        AudioFormat.MP3: ".mp3",
        AudioFormat.WAV: ".wav",
        AudioFormat.PCM16_8K: ".pcm",
    }.get(target, ".bin")


def _atempo_filters(speed: float) -> list[str]:
    """Build an ffmpeg ``atempo`` chain for ``speed``.

    A single atempo filter only accepts 0.5–2.0, so extreme values are split
    across filters. The public API caps speed at 0.5–2.0; the chain keeps the
    helper correct for internal callers that pass something wider.
    """
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return filters


async def convert_audio(
    audio: bytes,
    source_mime: str,
    target: AudioFormat,
    *,
    speed: float = 1.0,
) -> tuple[bytes, str] | None:
    """Convert ``audio`` to ``target`` and optionally change its tempo.

    Returns ``(bytes, mime_type)`` or ``None`` when the target is unavailable
    (ffmpeg missing, conversion failed, empty output). Never raises.

    ``speed`` is applied in the same ffmpeg pass as the container conversion,
    so a channel asking for Ogg/Opus at 1.2x pays for one encode, not two.
    ``NATIVE`` with a non-default speed re-encodes in the source container.
    """
    if not audio:
        return None
    if speed <= 0:
        return None

    speed_changed = abs(speed - 1.0) > 0.01
    if target == AudioFormat.NATIVE:
        if not speed_changed:
            return audio, source_mime
        target = format_for_mime(source_mime)
    elif not speed_changed and source_mime == target.value:
        return audio, source_mime

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.info("ffmpeg unavailable — cannot convert %s to %s", source_mime, target.value)
        return None

    src_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=_SOURCE_SUFFIX.get(source_mime, ".bin"), delete=False
        ) as src:
            src.write(audio)
            src_path = src.name
        out_path = src_path.rsplit(".", 1)[0] + _out_suffix(target)

        args = _ffmpeg_args(target, out_path)
        if args is None:
            return None
        if speed_changed:
            args = ["-filter:a", ",".join(_atempo_filters(speed)), *args]
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-loglevel", "error", "-i", src_path, *args,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("ffmpeg conversion failed: %s", (stderr or b"")[:150])
            return None

        with open(out_path, "rb") as f:
            converted = f.read()
        if not converted:
            return None
        magic = _MAGIC.get(target)
        if magic and not converted.startswith(magic):
            logger.warning("ffmpeg produced %s without the expected header", target.value)
            return None
        return converted, target.value
    except Exception as e:
        logger.warning("Audio conversion failed: %s: %s", type(e).__name__, str(e)[:120])
        return None
    finally:
        for path in (src_path, out_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    logger.debug("could not remove temp audio file %s", path)
