"""Download and store the photos a reviewer attached to a Google review.

Google returns these as `reviewMediaItems[].thumbnailUrl`, which is a FIFE
link: it resolves for a few hours and then 403s. Storing the URL would give
us a review card with a broken image a day later, so the bytes are fetched
once and kept in our own storage, served from /media-files.

Design notes:
  * Idempotent. A photo is only downloaded when its `source_url` is not
    already recorded, so a re-sync costs nothing and never duplicates.
  * Failures are non-fatal. A photo that will not download is skipped; the
    review itself still syncs. Google media is best-effort garnish, not
    something that should fail a merchant's whole sync.
  * Content is validated by magic bytes and served as image/* only, so a
    hostile "thumbnail" cannot land renderable HTML/SVG on a public URL.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from ...config import settings
from ...core.storage import media_configured, put_media

logger = logging.getLogger(__name__)

# Google's thumbnails are small; anything larger is not a review photo.
MAX_MEDIA_BYTES = 8 * 1024 * 1024
DOWNLOAD_TIMEOUT = 15.0
# A review can carry several photos; cap the work per review.
MAX_ITEMS_PER_REVIEW = 10

_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def _sniff_image(data: bytes) -> str | None:
    """Return a safe image extension if the bytes really are a raster image.

    WEBP ("RIFF....WEBP") is checked too. Anything else — including SVG and
    HTML — is rejected rather than stored on a public URL.
    """
    for signature, ext in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _public_path(user_id: str, storage_key: str) -> str:
    """Relative public path for a locally stored file.

    Deliberately relative: the frontend prefixes it with the API origin it
    already uses for every other call, so this keeps working behind any host
    or proxy without the worker needing to know its own public URL.
    """
    return f"{settings.MEDIA_PUBLIC_PATH.rstrip('/')}/{user_id}/{storage_key}"


async def _download(url: str) -> tuple[bytes, str] | None:
    try:
        async with httpx.AsyncClient(
            timeout=DOWNLOAD_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.debug("review media download %s -> %s", url[:80], resp.status_code)
                return None
            data = resp.content
    except Exception as e:  # network/DNS/timeout — never fail the sync
        logger.debug("review media download failed %s: %s", url[:80], e)
        return None
    if not data or len(data) > MAX_MEDIA_BYTES:
        return None
    ext = _sniff_image(data)
    if ext is None:
        return None
    return data, ext


async def sync_review_media(
    user_id: str, media: list[dict], stored: list[dict] | None
) -> list[dict]:
    """Reconcile a review's stored photos with what Google currently reports.

    `media` is the freshly parsed `reviewMediaItems`; `stored` is what we
    already have on the insight. Returns the list to persist.

    Existing entries are kept when their `source_url` is unchanged, so this is
    a no-op on a steady-state sync. A changed source URL re-downloads, and
    media Google no longer reports is dropped from our copy of the list (the
    stored files are left alone rather than deleted — a review can be
    re-synced at any time and we would only re-download).
    """
    if not media:
        return list(stored or [])

    previous = {
        entry.get("source_url"): entry
        for entry in (stored or [])
        if isinstance(entry, dict) and entry.get("source_url")
    }

    out: list[dict] = []
    for item in media[:MAX_ITEMS_PER_REVIEW]:
        if not isinstance(item, dict):
            continue
        source = item.get("thumbnail_url") or item.get("video_url")
        if not source:
            continue
        existing = previous.get(source)
        if existing:
            out.append(existing)
            continue

        if item.get("kind") == "video":
            # Videos are not downloaded: they are large, we have no transcode
            # step, and the still image is enough to represent the review.
            out.append({
                "url": None,
                "kind": "video",
                "label": item.get("label"),
                "source_url": source,
            })
            continue

        got = await _download(source)
        if got is None:
            # Keep a marker so we retry on a later sync rather than
            # re-downloading on every single one.
            out.append({
                "url": None,
                "kind": "image",
                "label": item.get("label"),
                "source_url": source,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            })
            continue
        data, ext = got
        try:
            storage_key, public = put_media(
                user_id, f"review{ext}", data, f"image/{ext.lstrip('.')}"
            )
        except Exception as e:
            logger.warning("review media store failed: %s", e)
            continue
        out.append({
            # GCS hands back an absolute public URL; local disk needs the
            # relative path the frontend resolves against the API origin.
            "url": public or _public_path(user_id, storage_key),
            "storage_key": storage_key,
            "kind": "image",
            "label": item.get("label"),
            "source_url": source,
        })

    return out
