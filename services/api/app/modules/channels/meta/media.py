"""Download a WhatsApp media object (voice notes, audio) for transcription.

The Cloud API exposes media in two steps: `GET /{media_id}` returns a
short-lived URL plus the mime type, and that URL itself requires the same
access token. Both calls are made here, with the same bounded streaming the
STT provider uses — a customer supplies the bytes, so their size must never
be trusted.

This module deliberately does not store the audio: a voice note is
transcribed once, inline, and the transcript is what the inbox and the
assistant keep.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Same ceiling as the STT provider. WhatsApp voice notes are well under 16 MB.
MAX_MEDIA_BYTES = 25 * 1024 * 1024


class MediaDownloadError(RuntimeError):
    """The media could not be resolved or downloaded."""


def _graph_base() -> str:
    from .providers.whatsapp import graph_base

    return graph_base()


async def download_whatsapp_media(
    media_id: str,
    token: str,
    *,
    max_bytes: int = MAX_MEDIA_BYTES,
    timeout_seconds: float = 45.0,
) -> tuple[bytes, str]:
    """Return (audio bytes, mime type) for a WhatsApp media id.

    Raises MediaDownloadError on any failure; the caller decides whether the
    customer gets a "couldn't hear that" reply. No token or URL is logged.
    """
    if not media_id or not token:
        raise MediaDownloadError("media id or access token missing")

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            meta_resp = await client.get(
                f"{_graph_base()}/{media_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise MediaDownloadError(f"media lookup failed: {type(e).__name__}") from e
        if meta_resp.status_code >= 400:
            raise MediaDownloadError(
                f"media lookup rejected ({meta_resp.status_code}): "
                f"{meta_resp.text[:160]}"
            )
        try:
            meta = meta_resp.json()
        except ValueError as e:
            raise MediaDownloadError("media lookup returned non-JSON") from e

        url = meta.get("url")
        mime = meta.get("mime_type") or "audio/ogg"
        if not url:
            raise MediaDownloadError("media lookup returned no URL")

        declared = meta.get("file_size")
        if isinstance(declared, int) and declared > max_bytes:
            raise MediaDownloadError(f"media too large: {declared} bytes")

        chunks: list[bytes] = []
        total = 0
        try:
            async with client.stream(
                "GET", url, headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True,
            ) as resp:
                if resp.status_code >= 400:
                    raise MediaDownloadError(
                        f"media download rejected ({resp.status_code})"
                    )
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaDownloadError(
                            f"media exceeded {max_bytes} bytes while streaming"
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as e:
            raise MediaDownloadError(f"media download failed: {type(e).__name__}") from e

    audio = b"".join(chunks)
    if not audio:
        raise MediaDownloadError("media download returned no bytes")
    logger.info(
        "WhatsApp media downloaded: bytes=%d mime=%s", len(audio), mime[:60]
    )
    return audio, mime
