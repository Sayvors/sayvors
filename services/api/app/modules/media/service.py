"""Media service: scheduled photos that go live on Google.

One row is one photo. Publish either creates a Google local post carrying the
photo, adds it to the location gallery, or replaces the profile/cover image —
all through the native Business Profile media API. Same robustness contract
as posts: per-item advisory locks (double publish impossible), retry-then-park,
delete-due.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..notifications.service import notify
from ..scheduling import (
    MAX_PUBLISH_ATTEMPTS,
    provider_post_id as _google_post_id,
    release_lock,
    retry_delay as _retry_delay,
    take_lock,
)
from . import image_check
from .models import BannerCheck, LocationMedia

logger = logging.getLogger(__name__)

PUBLISHABLE_FROM = ("draft", "scheduled", "failed")
MAX_PER_PASS = 50

# Per-item advisory locks: publishing is NOT idempotent, so the same photo
# never publishes twice at once. Different photos proceed in parallel.
# Implementation lives in app.modules.scheduling (single copy).
_MEDIA_LOCK_PREFIX = "sayvors:media-publish:"


async def _acquire_media_lock(db: AsyncSession, media_id: str) -> bool:
    return await take_lock(db, True, _MEDIA_LOCK_PREFIX, media_id)


async def _try_media_lock(db: AsyncSession, media_id: str) -> bool:
    return await take_lock(db, False, _MEDIA_LOCK_PREFIX, media_id)


async def _release_media_lock(db: AsyncSession, media_id: str) -> None:
    await release_lock(db, _MEDIA_LOCK_PREFIX, media_id)


# File uploads from the owner's computer. Stored in shared storage: GCS
# public bucket when configured, otherwise local disk served publicly at
# <api-origin>/media-files/... The provider fetches the photo from that
# URL at publish time, which is why it must be public, not just on disk.
UPLOAD_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov")
VIDEO_EXTENSIONS = (".mp4", ".mov")

# Content type is DERIVED from the validated extension, never from the
# client's Content-Type header: that header is attacker-controlled, and
# storing e.g. text/html under a public URL is stored XSS.
_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
    ".mp4": "video/mp4", ".mov": "video/quicktime",
}

_MAGIC_SIGNATURES = {
    ".jpg": (b"\xff\xd8",),   # JPEG SOI marker
    ".jpeg": (b"\xff\xd8",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
}


def detect_media_type(filename: str, content_type: str | None) -> str:
    name = (filename or "").lower()
    if name.endswith(VIDEO_EXTENSIONS) or (content_type or "").startswith("video/"):
        return "VIDEO"
    return "PHOTO"


def _magic_matches(ext: str, data: bytes) -> bool:
    """Verify the file's leading bytes match its declared extension."""
    if ext in (".mp4", ".mov"):
        # ISO base media: 'ftyp' box at offset 4 (covers both MP4 and MOV/QT).
        return len(data) >= 12 and data[4:8] == b"ftyp"
    sigs = _MAGIC_SIGNATURES.get(ext)
    if not sigs:
        return False
    return any(data.startswith(s) for s in sigs)


def _sniff_extension(data: bytes) -> str | None:
    """The real container format from leading bytes, or None when unknown.

    Downloads routinely lie about their extension (a JPEG saved as .png by a
    messenger, a WebP named .jpg by a browser). The bytes are what matter, so
    the upload path repairs the name instead of rejecting a good photo.
    """
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF8"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        return ".mov" if brand.startswith(b"qt") else ".mp4"
    return None


async def save_upload(
    user_id: str, filename: str, content_type: str | None, data: bytes, base_url: str
) -> dict:
    """Store one uploaded file and return its public URL + detected type."""
    from ...core.storage import local_media_url, put_media

    max_bytes = max(1, settings.MEDIA_MAX_MB) * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"File is too big — max {settings.MEDIA_MAX_MB}MB.")
    if not data:
        raise ValueError("Empty file.")
    ext = Path(filename or "").suffix.lower()
    ctype = content_type or ""
    if ctype and not (ctype.startswith("image/") or ctype.startswith("video/")):
        raise ValueError("Only image or video files.")
    # Content must match the extension (polyglot guard), and the stored
    # content type is always derived from the extension, never the header.
    # A LYING extension is repaired from the bytes rather than rejected: a
    # JPEG downloaded as .png is a good photo with a bad name, and bouncing
    # it costs the merchant a publish for nothing. Unknown bytes still fail.
    if ext not in UPLOAD_EXTENSIONS or not _magic_matches(ext, data):
        sniffed = _sniff_extension(data)
        if sniffed is None or sniffed not in UPLOAD_EXTENSIONS:
            raise ValueError("File content doesn't look like the file type it claims.")
        logger.warning(
            "upload name repaired: %r bytes are %s (was %r)",
            (filename or "")[:80], sniffed, ext,
        )
        ext = sniffed
    expected_type = _CONTENT_TYPES[ext]
    # The stored name must carry the REPAIRED extension: the public URL is
    # what Google and browsers fetch, and a .png URL serving JPEG bytes
    # breaks clients that trust the suffix.
    stored_name = f"{Path(filename or 'upload').stem or 'upload'}{ext}"
    storage_key, _provider_url = put_media(user_id, stored_name, data, expected_type)
    # Always hand out our own public origin, even when the bytes live in S3 or
    # GCS. The raw object URL is often private, and Google's localPosts API
    # fetches `sourceUrl` itself — a 403 there is a generic INVALID_ARGUMENT.
    # `/media-files` streams the object from whichever backend holds it.
    public_url = local_media_url(base_url, user_id, storage_key)
    object_key = storage_key
    if object_key.startswith(f"media/{user_id}/"):
        object_key = object_key[len("media/"):]
    elif not object_key.startswith(f"{user_id}/"):
        object_key = f"{user_id}/{Path(object_key).name}"
    return {
        "key": object_key,
        "image_url": public_url,
        "type": detect_media_type(filename, expected_type),
        "size": len(data),
        "content_type": expected_type,
    }


async def vision_verdict(
    data: bytes, model: str, checks: list[dict] | None = None
) -> dict | None:
    """One AI verdict: the model looks at the photo and judges it as a Google
    Business Profile cover/banner. The deterministic measurements are passed as
    facts so the model can be concrete; the model still has to look at the
    actual image. Best-effort — a failure degrades to the rule result."""
    try:
        import json

        from ..llm.gateway import complete
        from ..llm.providers.base import LLMMessage

        facts = [
            {"check": c.get("label"), "pass": bool(c.get("pass")), "note": c.get("note")}
            for c in (checks or [])
        ]
        prompt = (
            "You check whether a photo is good enough to be a Google Business Profile "
            "cover/banner image. Look at the photo and use these measurements as facts:\n"
            f"{json.dumps(facts)}\n"
            "Google prefers a wide photo (around 16:9), bright, sharp, and showing the "
            "real business. Text-heavy, blurry, dark, tiny, or stock-looking photos "
            "perform poorly and Google may replace them.\n"
            "Answer ONLY with JSON: {\"suitable\": \"yes\"|\"maybe\"|\"no\", "
            "\"confidence\": 0-100, \"summary\": \"one plain sentence for the business owner\", "
            "\"reasons\": [\"short plain reason\"]}. Give at most 5 reasons. "
            "Do not repeat the same point twice."
        )
        response = await complete(
            model=model,
            messages=[LLMMessage(role="user", content=prompt)],
            images=[(_mime_for_bytes(data), data)],
            purpose="media.banner_verdict",
            temperature=0.2,
            max_tokens=350,
        )
        text = (response.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        verdict = json.loads(text)
        suitable = str(verdict.get("suitable", "maybe")).lower()
        if suitable not in ("yes", "maybe", "no"):
            suitable = "maybe"
        try:
            confidence = max(0, min(100, int(verdict.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0
        reasons = []
        seen = set()
        for r in verdict.get("reasons") or []:
            s = str(r).strip()
            key = s.lower()
            if s and key not in seen:
                seen.add(key)
                reasons.append(s[:180])
            if len(reasons) >= 5:
                break
        return {
            "suitable": suitable,
            "confidence": confidence,
            "summary": str(verdict.get("summary") or "").strip()[:300],
            "reasons": reasons,
        }
    except Exception:
        logger.exception("Banner vision verdict failed")
        return None


def _mime_for_bytes(data: bytes) -> str:
    """The real MIME for the vision call — providers validate it.

    Labeling PNG bytes as image/jpeg made strict providers (Gemini) reject
    the part, which silently degraded the verdict to rules-only.
    """
    ext = _sniff_extension(data)
    return {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext or "", "image/jpeg")


async def decision_verdict(
    result: dict, model: str, images: list[tuple[str, bytes]] | None = None
) -> dict | None:
    """Plain-language suitability call from a text model, best-effort.

    The rule layer supplies facts and the vision layer (when configured)
    supplies observations; this model weighs them the way a human reviewer
    would and answers in the merchant's language. A failure here must never
    break the check — the deterministic summary simply stands.
    """
    try:
        import json

        from ..llm.gateway import complete
        from ..llm.providers.base import LLMMessage

        checks = [
            {"check": c["label"], "pass": bool(c["pass"]), "note": c["note"]}
            for c in result.get("checks", [])
        ]
        vision_reasons = ((result.get("ai_verdict") or {}).get("reasons")) or []
        prompt = (
            "You decide whether a photo is good enough to serve as a Google "
            "Business Profile banner (cover) image.\n"
            f"Automated measurements: {json.dumps(checks)}\n"
            f"Vision model observations: {json.dumps(vision_reasons)}\n"
            "Google prefers wide (around 16:9), bright, sharp photos that show "
            "the real business; text-heavy, blurry or stock-looking images "
            "perform poorly and Google may replace them.\n"
            "Answer ONLY with JSON: {\"suitable\": \"yes\"|\"maybe\"|\"no\", "
            "\"confidence\": 0-100, \"summary\": \"one plain sentence for the "
            "business owner\", \"reasons\": [\"short plain reason\"]}."
        )
        response = await complete(
            model=model,
            messages=[LLMMessage(role="user", content=prompt)],
            images=images or None,
            purpose="media.banner_decision",
            temperature=0.1,
            max_tokens=300,
        )
        text = (response.content or "").strip()
        # Tolerate a code fence the model may add.
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        verdict = json.loads(text)
        suitable = str(verdict.get("suitable", "maybe")).lower()
        if suitable not in ("yes", "maybe", "no"):
            suitable = "maybe"
        try:
            confidence = max(0, min(100, int(verdict.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0
        return {
            "suitable": suitable,
            "confidence": confidence,
            "summary": str(verdict.get("summary") or "").strip()[:300],
            "reasons": [str(r) for r in (verdict.get("reasons") or [])][:6],
        }
    except Exception:
        logger.exception("Banner decision verdict failed")
        return None


async def full_banner_analysis(
    db, data: bytes, *, vision_verdict_fn=None, decision_verdict_fn=None
) -> dict:
    """Check whether a photo is worth using as a Google Business Profile cover.

    Rules always run (size, shape, sharpness, brightness). If an admin-configured
    AI model is available, it looks at the actual photo and gives the final
    plain-language verdict. One verdict, one reason list — no internal layers
    leak into the tenant payload. `decision_verdict_fn` is accepted for backward
    compatibility and ignored.
    """
    result = image_check.analyze_banner_image(data)

    from ..admin.service import get_platform_config

    config = await get_platform_config(db)
    vision_fn = vision_verdict_fn or vision_verdict

    model = (config.banner_vision_model or "").strip() or settings.BANNER_VISION_MODEL
    ai = None
    if model:
        try:
            try:
                ai = await vision_fn(data, model, result.get("checks") or [])
            except TypeError:
                # Back-compat: older/fake verdict fns accept (data, model) only.
                ai = await vision_fn(data, model)
        except Exception:
            logger.exception("Banner vision verdict failed")
            ai = None

    if ai:
        result["ai_verdict"] = ai
        result["suitable"] = ai.get("suitable") or result.get("suitable")
        result["confidence"] = int(ai.get("confidence") or result.get("confidence") or 0)
        if ai.get("summary"):
            result["summary"] = ai["summary"]
        result["reasons"] = list(ai.get("reasons") or [])
    else:
        # Rule-only: surface failed checks as plain reasons, no repetition.
        result["ai_verdict"] = None
        reasons = []
        for c in result.get("checks") or []:
            if c.get("pass"):
                continue
            note = str(c.get("note") or "").strip()
            label = str(c.get("label") or "").strip()
            if note and note.lower() not in {label.lower()}:
                reasons.append(f"{label}: {note}" if label else note)
            elif label:
                reasons.append(label)
        result["reasons"] = reasons[:5]
    return result


async def enqueue_banner_check(
    db, *, user_id: str, filename: str, content_type: str | None,
    data: bytes, base_url: str,
) -> "BannerCheck":
    """Store the photo, create a queued check row, and submit the realtime job.

    The row id doubles as the job's idempotency key, so a double-clicked
    button cannot queue two analyses for the same upload.
    """
    upload = await save_upload(user_id, filename, content_type, data, base_url)
    row = BannerCheck(
        tenant_id=user_id,
        media_key=upload.get("key"),
        media_url=upload["image_url"],
    )
    db.add(row)
    await db.flush()

    from ..jobs.service import submit_job

    await submit_job(
        db,
        tenant_id=user_id,
        job_type="media.banner_check",
        payload={"check_id": row.id},
        subject_type="banner_check",
        subject_id=row.id,
        idempotency_key=f"banner_check:{row.id}",
    )
    await db.commit()
    await db.refresh(row)
    return row


async def run_banner_check(db, *, check_id: str, tenant_id: str) -> dict:
    """Execute one queued check (the realtime-lane handler core).

    Analysis failures are terminal and stored on the row — a bad image must
    not spin the retry machinery; the merchant simply runs the check again.
    """
    import json

    row = (
        await db.execute(
            select(BannerCheck).where(
                BannerCheck.id == check_id,
                BannerCheck.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"skipped": "check not found", "check_id": check_id}
    if row.status == "done":
        return {"check_id": row.id, "status": "done"}

    row.status = "running"
    await db.commit()
    try:
        from ...core.storage import media_bytes_from_url

        data, _ct = media_bytes_from_url(tenant_id, row.media_url or "")
        result = await full_banner_analysis(db, data)
        row.suitable = result.get("suitable")
        row.confidence = result.get("confidence")
        row.summary = result.get("summary")
        row.checks_json = json.dumps(result.get("checks") or [])
        row.ai_verdict_json = (
            json.dumps(result["ai_verdict"]) if result.get("ai_verdict") is not None else None
        )
        row.decision_json = (
            json.dumps(result["decision"]) if result.get("decision") is not None else None
        )
        row.error = None
        row.status = "done"
    except Exception as e:  # noqa: BLE001 - stored, never silent
        row.status = "failed"
        row.error = str(e)[:300]
        await db.commit()
        return {"check_id": row.id, "status": "failed", "error": row.error}
    await db.commit()
    await db.refresh(row)
    return {"check_id": row.id, "status": row.status}


def _load_json(value: str | None) -> Any | None:
    import json

    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _reasons_from_check(checks: list, ai_verdict: dict | None) -> list[str]:
    if ai_verdict and ai_verdict.get("reasons"):
        return [str(r) for r in ai_verdict["reasons"]][:5]
    reasons = []
    for c in checks or []:
        if c.get("pass"):
            continue
        note = str(c.get("note") or "").strip()
        label = str(c.get("label") or "").strip()
        if note and note.lower() not in {label.lower()}:
            reasons.append(f"{label}: {note}" if label else note)
        elif label:
            reasons.append(label)
    return reasons[:5]


def serialize_banner_check(row: "BannerCheck") -> dict:
    """Same shape as the synchronous /analyze-banner payload, plus status."""
    checks = _load_json(row.checks_json) or []
    ai_verdict = _load_json(row.ai_verdict_json)
    return {
        "id": row.id,
        "status": row.status,
        "suitable": row.suitable,
        "confidence": row.confidence,
        "summary": row.summary,
        "checks": checks,
        "ai_verdict": ai_verdict,
        "decision": _load_json(row.decision_json),
        "reasons": _reasons_from_check(checks, ai_verdict),
        "error": row.error,
    }


# Browsers refuse to decode some perfectly valid photos — CMYK JPEGs from
# print shops, oversized scans, exotic codecs. The composer's crop editor and
# the publish-time rasteriser both run in the browser, so such a file shows an
# empty frame and then publishes uncropped. Pillow decodes what browsers
# cannot, so the conversion happens here and the composer swaps the bytes in.
MAX_BROWSER_EDGE = 4096


def reencode_for_browser(data: bytes) -> tuple[bytes, str, int, int]:
    """Re-encode any readable image into a browser-friendly sRGB JPEG/PNG.

    Returns (bytes, mime, width, height). Raises ValueError with a
    merchant-facing reason when the file is empty, oversized or not an image.
    """
    import io

    from PIL import Image

    if not data:
        raise ValueError("Empty file.")
    max_bytes = max(1, settings.MEDIA_MAX_MB) * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"File is too big — max {settings.MEDIA_MAX_MB}MB.")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise ValueError("That file is not a readable image.")

    # Palette/alpha modes keep PNG (logos with transparency); everything
    # else flattens to sRGB JPEG, which is what photos should ship as.
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        image = image.convert("RGBA")
        mime = "image/png"
    else:
        image = image.convert("RGB")
        mime = "image/jpeg"

    longest = max(image.size)
    if longest > MAX_BROWSER_EDGE:
        scale = MAX_BROWSER_EDGE / longest
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )

    buf = io.BytesIO()
    if mime == "image/png":
        image.save(buf, format="PNG", optimize=True)
    else:
        image.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), mime, image.width, image.height


# Matches lib/crop-image.ts MAX_EXPORT_EDGE: the client bake caps exports at
# this edge, so the server fallback must produce the same envelope.
MAX_CROP_EDGE = 2048


def crop_for_browser(data: bytes, *, x: int, y: int, w: int, h: int) -> tuple[bytes, str]:
    """Crop an image with Pillow when the browser cannot rasterise it.

    The rect arrives in DISPLAYED pixel coordinates — browsers apply EXIF
    orientation before drawing, so the transposition is applied here too or
    the crop lands in the wrong place on rotated photos. A rect that drifts
    outside the image (dims probed before a re-encode) is clamped to a sane
    crop rather than failing: an imperfect crop still beats an uncropped one.
    """
    import io

    from PIL import Image, ImageOps

    if not data:
        raise ValueError("Empty file.")
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except Exception:
        raise ValueError("That file is not a readable image.")

    x = max(0, min(int(x), image.width - 1))
    y = max(0, min(int(y), image.height - 1))
    w = max(1, min(int(w), image.width - x))
    h = max(1, min(int(h), image.height - y))
    region = image.crop((x, y, x + w, y + h))

    has_alpha = region.mode in ("RGBA", "LA", "PA") or (
        region.mode == "P" and "transparency" in region.info
    )
    if has_alpha:
        region = region.convert("RGBA")
        mime = "image/png"
    else:
        region = region.convert("RGB")
        mime = "image/jpeg"
    longest = max(region.size)
    if longest > MAX_CROP_EDGE:
        scale = MAX_CROP_EDGE / longest
        region = region.resize(
            (
                max(1, round(region.width * scale)),
                max(1, round(region.height * scale)),
            ),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    if mime == "image/png":
        region.save(buf, format="PNG", optimize=True)
    else:
        region.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), mime


def _serialize(m: LocationMedia) -> dict:
    return {
        "id": m.id,
        "listing_id": m.listing_id,
        "image_url": m.image_url,
        "type": m.type,
        "category": m.category,
        "caption": m.caption or "",
        "status": m.status,
        "scheduled_on": m.scheduled_on.isoformat() if m.scheduled_on else None,
        "published_at": m.published_at.isoformat() if m.published_at else None,
        "delete_at": m.delete_at.isoformat() if m.delete_at else None,
        "publish_method": m.publish_method or "post",
        "google_post_id": m.google_post_id,
        "is_profile": bool(m.is_profile),
        "is_cover": bool(m.is_cover),
        "error": m.error,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _owned_media(db: AsyncSession, user_id: str, media_id: str) -> LocationMedia | None:
    result = await db.execute(
        select(LocationMedia).where(
            LocationMedia.id == media_id,
            LocationMedia.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Bad datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_delete_at(delete_at: datetime | None, scheduled_on: datetime | None) -> None:
    if delete_at is None:
        return
    if delete_at <= datetime.now(timezone.utc):
        raise ValueError("delete_at must be in the future.")
    if scheduled_on is not None and delete_at <= scheduled_on:
        raise ValueError("delete_at must be after the scheduled publish time.")


def _require_http_url(url: str) -> str:
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("image_url must be a hosted http(s) URL.")
    return url


def _check_method_publishable(method: str | None, action: str) -> None:
    """Native Google accepts post, gallery, profile (logo) and banner (cover)."""
    if action in ("publish", "schedule") and (method or "post") not in (
        "post", "gallery", "profile", "banner",
    ):
        raise ValueError(
            "publish_method must be 'post', 'gallery', 'profile' or 'banner'."
        )


def _content_type_for(url: str) -> str:
    """Best-effort image content type for a stored media URL."""
    ext = Path(url.split("?", 1)[0]).suffix.lower()
    return _CONTENT_TYPES.get(ext, "image/jpeg")


async def list_media(
    db: AsyncSession, user_id: str, listing_id: str | None = None
) -> list[dict]:
    from ..locations.service import disconnected_listing_ids

    filters = [LocationMedia.user_id == user_id]
    hidden = await disconnected_listing_ids(db, user_id)
    if hidden:
        filters.append(LocationMedia.listing_id.notin_(hidden))
    if listing_id:
        filters.append(LocationMedia.listing_id == listing_id)
    rows = (
        await db.execute(
            select(LocationMedia).where(*filters).order_by(LocationMedia.created_at.desc()).limit(200)
        )
    ).scalars().all()
    return [_serialize(m) for m in rows]


async def create_media(db: AsyncSession, user_id: str, data: dict) -> dict:
    action = data.get("action", "publish")
    scheduled_on = _parse_dt(data.get("scheduled_on"))
    if action == "schedule" and scheduled_on is None:
        raise ValueError("scheduled_on is required to schedule media.")
    if action == "schedule" and scheduled_on <= datetime.now(timezone.utc):  # type: ignore[operator]
        raise ValueError("scheduled_on must be in the future.")
    delete_at = _parse_dt(data.get("delete_at"))
    _validate_delete_at(delete_at, scheduled_on)
    image_url = _require_http_url(data.get("image_url") or "")
    media_type = data.get("type", "PHOTO")
    if media_type not in ("PHOTO", "VIDEO"):
        raise ValueError("type must be PHOTO or VIDEO.")
    publish_method = data.get("publish_method") or "post"
    if publish_method not in ("post", "gallery", "profile", "banner"):
        raise ValueError("publish_method must be post, gallery, profile or banner.")
    _check_method_publishable(publish_method, action)

    item = LocationMedia(
        id=str(uuid.uuid4()),
        user_id=user_id,
        listing_id=data["listing_id"],
        image_url=image_url,
        type=media_type,
        category=(data.get("category") or "EXTERIOR")[:32],
        caption=(data.get("caption") or "")[:500],
        status="scheduled" if action == "schedule" else "draft",
        scheduled_on=scheduled_on,
        delete_at=delete_at,
        publish_method=publish_method,
    )
    db.add(item)
    await db.flush()

    if action == "publish":
        return await publish_media(db, user_id, item.id)
    if action == "schedule":
        when = scheduled_on.strftime("%b %d, %H:%M") if scheduled_on else "soon"
        await notify(
            db, user_id, "media_scheduled",
            f"Photo scheduled — {item.caption or item.category.replace('_', ' ').title()}",
            f"Publishes {when}.",
            data={"media_id": item.id, "listing_id": item.listing_id},
            href="/dashboard/posts-media?tab=media",
        )
    await db.commit()
    await db.refresh(item)
    return {"media": _serialize(item), "google_published": False}


async def update_media(
    db: AsyncSession, user_id: str, media_id: str, data: dict
) -> dict:
    item = await _owned_media(db, user_id, media_id)
    if item is None:
        raise ValueError("Media not found.")
    if item.status == "published":
        raise ValueError("Published photos live on Google now — archive the post instead of editing.")
    for field in ("category", "caption"):
        if data.get(field) is not None:
            setattr(item, field, data[field])
    for field in ("is_profile", "is_cover"):
        if field in data and data[field] is not None:
            setattr(item, field, bool(data[field]))
    # delete_at: explicit null cancels, absent key leaves untouched
    # (router passes exclude_unset).
    if "delete_at" in data:
        item.delete_at = _parse_dt(data.get("delete_at"))

    # Re-targeting a draft/scheduled photo is allowed; a published one is
    # already on Google and cannot change surface.
    if "publish_method" in data and data["publish_method"] is not None:
        pm = data["publish_method"]
        if pm not in ("post", "gallery", "profile", "banner"):
            raise ValueError("publish_method must be 'post', 'gallery', 'profile' or 'banner'.")
        if item.status == "published":
            raise ValueError("Published photos live on Google now — archive the post instead of editing.")
        item.publish_method = pm

    new_status = data.get("status")
    if new_status is not None and new_status != item.status:
        if new_status == "published" and item.status in PUBLISHABLE_FROM:
            await db.flush()
            return await publish_media(db, user_id, item.id)
        if new_status == "published":
            item.status = "published"
        elif new_status in ("draft", "scheduled", "archived"):
            item.status = new_status
            if new_status == "scheduled":
                item.scheduled_on = _parse_dt(data.get("scheduled_on")) or item.scheduled_on
                if item.scheduled_on is None:
                    raise ValueError("scheduled_on is required to schedule media.")
        else:
            raise ValueError(f"Cannot transition to {new_status}.")
    if "delete_at" in data or "scheduled_on" in data:
        _validate_delete_at(item.delete_at, item.scheduled_on)
    item.error = None
    await db.commit()
    await db.refresh(item)
    return {"media": _serialize(item), "google_published": False}


async def delete_media(db: AsyncSession, user_id: str, media_id: str) -> None:
    item = await _owned_media(db, user_id, media_id)
    if item is None:
        raise ValueError("Media not found.")
    await db.delete(item)
    await db.commit()


async def publish_media(
    db: AsyncSession, user_id: str, media_id: str, notify_user: bool = True
) -> dict:
    """Publish one photo to Google right now.

    Destination comes from `publish_method`: a local post, the location
    gallery, or the profile/cover image. Held under the item's advisory lock:
    a double publish would post the photo twice on Google. Videos are
    library-only. notify_user=False lets batch callers (worker) emit one
    summary instead of a row per photo.
    """
    locked = await _acquire_media_lock(db, media_id)
    try:
        return await _publish_media_inner(db, user_id, media_id, notify_user)
    finally:
        if locked:
            await _release_media_lock(db, media_id)


async def _publish_media_inner(
    db: AsyncSession, user_id: str, media_id: str, notify_user: bool = True
) -> dict:
    from ..channels.meta.providers.google_publish import GoogleBusinessPublisher
    from ..channels.service import decrypt_token, encrypt_token
    from ..locations.service import channel_for_listing, listing_id_of

    item = await _owned_media(db, user_id, media_id)
    if item is None:
        raise ValueError("Media not found.")
    if item.status not in PUBLISHABLE_FROM:
        raise ValueError(f"Cannot publish {item.status} media.")
    if item.type != "PHOTO":
        raise ValueError("Video auto-publishing is not supported by the provider yet — photos only.")
    channel = await channel_for_listing(
        db, user_id, item.listing_id, statuses=("active", "expired")
    )
    if channel is None:
        raise ValueError(
            "Connect that Google location in Channels before publishing media."
        )
    if channel.status != "active":
        raise ValueError(
            "Google connection expired — reconnect Google before publishing."
        )

    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        raise ValueError("Reconnect Google in Channels before publishing media.")

    publisher = GoogleBusinessPublisher(access or "", refresh)
    publisher.set_known_expiry(channel.token_expires_at)

    async def _persist(new_access: str, new_expires) -> None:
        channel.access_token = encrypt_token(new_access)
        channel.token_expires_at = new_expires
        await db.commit()

    publisher.set_token_persister(_persist)
    method = item.publish_method or "post"
    caption = item.caption or item.category.replace("_", " ").title()
    try:
        if method == "post":
            response = await publisher.publish_post(
                "",
                listing_id_of(channel),
                "update",
                item.image_url,
                "image",
                caption,
                caption,
                None,
                account_id=channel.platform_user_id,
                media_urls=[item.image_url],
                tenant_id=user_id,
            )
        else:
            # Location media (gallery / logo / banner): upload the bytes
            # straight to Google. Google never fetches a URL, so no public
            # bucket is needed for these surfaces.
            from ...core.storage import media_bytes_from_url

            media_data, media_content_type = media_bytes_from_url(user_id, item.image_url)
            response = await publisher.set_location_image(
                "",
                listing_id_of(channel),
                method,
                item.image_url,
                account_id=channel.platform_user_id,
                category_override=item.category if method == "gallery" else None,
                media_data=media_data,
                content_type=media_content_type or _content_type_for(item.image_url),
            )
    except Exception as e:
        _register_publish_failure(item, str(e)[:500])
        if notify_user and item.status == "failed":
            # Parked (not merely retrying): this needs the human.
            await notify(
                db, user_id, "media_failed",
                f"Photo failed to publish — {item.caption or item.category.replace('_', ' ').title()}",
                (item.error or "")[:160],
                data={"media_id": item.id, "listing_id": item.listing_id},
                href="/dashboard/posts-media?tab=media",
            )
        await db.commit()
        raise RuntimeError(f"Google media publish failed: {e}")
    finally:
        await publisher.close()

    item.status = "published"
    item.published_at = datetime.now(timezone.utc)
    item.error = None
    item.attempts = 0
    item.next_retry_at = None
    item.google_response = response
    google_id = _google_post_id(response)
    if google_id:
        item.google_post_id = google_id
    if notify_user:
        await notify(
            db, user_id, "media_published",
            f"Photo published to Google — {item.caption or item.category.replace('_', ' ').title()}",
            None,
            data={"media_id": item.id, "listing_id": item.listing_id},
            href="/dashboard/posts-media?tab=media",
        )
    await db.commit()
    await db.refresh(item)
    return {"media": _serialize(item), "google_published": True}


def _register_publish_failure(item: LocationMedia, error: str) -> None:
    """Retry-then-park, same policy as posts."""
    item.error = error
    item.attempts = (item.attempts or 0) + 1
    if item.status == "scheduled" and item.attempts < MAX_PUBLISH_ATTEMPTS:
        item.next_retry_at = datetime.now(timezone.utc) + _retry_delay(item.attempts)
    else:
        item.status = "failed"
        item.next_retry_at = None


async def publish_due(db: AsyncSession) -> dict:
    """Publish due scheduled photos across all users. Returns counts."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LocationMedia)
            .where(
                LocationMedia.status == "scheduled",
                LocationMedia.scheduled_on.is_not(None),
                LocationMedia.scheduled_on <= now,
                (LocationMedia.next_retry_at.is_(None))
                | (LocationMedia.next_retry_at <= now),
            )
            .order_by(LocationMedia.scheduled_on)
            .limit(MAX_PER_PASS)
        )
    ).scalars().all()
    totals = {
        "checked": len(rows), "published": 0, "failed": 0,
        "retried": 0, "skipped": 0, "errors": [],
    }
    per_user: dict[str, dict[str, int]] = {}
    for item in rows:
        media_id, user_id = item.id, item.user_id
        held = await _try_media_lock(db, media_id)
        if not held:
            totals["skipped"] += 1
            continue
        try:
            await publish_media(db, user_id, media_id, notify_user=False)
            totals["published"] += 1
            per_user.setdefault(user_id, {"published": 0, "failed": 0})
            per_user[user_id]["published"] += 1
        except Exception as e:
            fresh = await _owned_media(db, user_id, media_id)
            if fresh is not None and fresh.status == "scheduled":
                totals["retried"] += 1
            else:
                totals["failed"] += 1
                per_user.setdefault(user_id, {"published": 0, "failed": 0})
                per_user[user_id]["failed"] += 1
            totals["errors"].append(f"{media_id[:8]}: {str(e)[:120]}")
            try:
                await db.rollback()
            except Exception:
                pass
        finally:
            await _release_media_lock(db, media_id)
    # One summary row per active user per pass — never a row per photo.
    for uid, counts in per_user.items():
        parts = []
        if counts["published"]:
            parts.append(f"published {counts['published']}")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        await notify(
            db, uid,
            "media_published" if counts["published"] else "media_failed",
            f"Scheduled photos: {', '.join(parts)}",
            None,
            data={"published": counts["published"], "failed": counts["failed"]},
            href="/dashboard/posts-media?tab=media",
        )
    try:
        await db.commit()
    except Exception:
        pass
    return totals


async def delete_due(db: AsyncSession) -> dict:
    """Delete rows whose delete_at has passed. Local rows only."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LocationMedia).where(
                LocationMedia.delete_at.is_not(None),
                LocationMedia.delete_at <= now,
            )
        )
    ).scalars().all()
    totals = {"checked": len(rows), "deleted": 0}
    for item in rows:
        try:
            await db.delete(item)
            await db.flush()
            totals["deleted"] += 1
        except Exception as e:
            logger.warning("Scheduled media deletion failed for %s: %s", item.id, e)
            try:
                await db.rollback()
            except Exception:
                pass
    try:
        await db.commit()
    except Exception:
        pass
    return totals
