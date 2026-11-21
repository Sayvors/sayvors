"""Media API — schedule photos to go live on Google, plus library CRUD.

Photos publish as a Google local post, into the location gallery, or as the
profile photo; videos are stored as library rows (the publisher takes image
URLs, not video).

GET    /api/v1/media                list (?listing_id=)
POST   /api/v1/media                create (publish now | schedule | draft)
GET    /api/v1/media/{media_id}     read one
PUT    /api/v1/media/{media_id}     update (category/flags/schedule/delete_at)
DELETE /api/v1/media/{media_id}     delete permanently
POST   /api/v1/media/{media_id}/publish   publish a draft/scheduled/failed photo now
POST   /api/v1/media/sync           publish due + delete expired (admin/ops only)
"""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings

logger = logging.getLogger(__name__)
from ...core.deps import get_current_user, get_db, require_admin
from ...core.storage import public_media_base
from ...core.upstream_errors import upstream_http_error
from ..users.models import User
from . import image_check, service
from .schemas import MediaCreate, MediaOut, MediaPublishResult, MediaSyncResult, MediaUpdate
from ..team.context import tenant_id_of, require_perm, TenantContext

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.post("/upload")
async def upload_media_file(
    request: Request,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a photo/video from the owner's computer.

    Returns a public URL the provider can fetch at publish time. Files live
    on a persistent volume; nothing is published yet — call POST / with the
    returned image_url (or schedule it) afterwards.
    """
    _ = db
    try:
        data = await file.read()
        return await service.save_upload(
            tenant_id_of(user),
            file.filename or "upload",
            file.content_type,
            data,
            public_media_base(str(request.base_url)),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/convert")
async def convert_media_for_browser(
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
):
    """Re-encode a photo the browser cannot decode (CMYK JPEG, huge scans).

    Returns the raw converted bytes (image/jpeg or image/png). The composer
    swaps them in for preview, crop and publish, so an undecodable original
    never becomes an empty crop frame or an uncropped publish. The model id
    and storage details stay server-side; only pixels travel back.
    """
    _ = ctx, user
    data = await file.read()
    try:
        out, mime, width, height = service.reencode_for_browser(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(
        content=out,
        media_type=mime,
        headers={"X-Image-Size": f"{width}x{height}"},
    )


@router.post("/crop")
async def crop_media_server_side(
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    x: int = Form(...),
    y: int = Form(...),
    w: int = Form(...),
    h: int = Form(...),
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
):
    """Crop with Pillow when the browser cannot (canvas taint, CORS, exotic codecs).

    Accepts an uploaded file or an http(s) media URL (SSRF-guarded, pinned-DNS
    fetch). The rect is in DISPLAYED pixel coordinates — the browser applies
    EXIF orientation before drawing, so the server transposes first. Returns
    raw cropped bytes; the composer uploads them like any other file, so the
    merchant's framing survives even when their browser could not bake it.
    """
    _ = ctx, user
    if file is not None and (file.filename or file.content_type):
        data = await file.read()
    elif url:
        if not (url.startswith("https://") or url.startswith("http://")):
            raise HTTPException(status_code=400, detail="Only http(s) URLs.")
        from ...core.pinned_http import fetch_pinned_bytes

        try:
            data = await fetch_pinned_bytes(url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not fetch that image: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide a file or a url.")
    try:
        out, mime = service.crop_for_browser(data, x=x, y=y, w=w, h=h)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=out, media_type=mime)


@router.post("/analyze-banner")
async def analyze_banner(
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("media.view")),
    db: AsyncSession = Depends(get_db),
):
    """Score an uploaded image as a Google banner/promotion photo.

    Deterministic rules (format, size, aspect, sharpness, exposure) always
    run. If the admin has configured a vision model, a multimodal AI verdict
    is appended — the model id itself is never returned to the tenant, only
    the verdict. The result is advice; it never blocks publishing.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    max_bytes = max(1, settings.MEDIA_MAX_MB) * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=400, detail="File is too big.")
    result = image_check.analyze_banner_image(
        data, filename=file.filename or "", content_type=file.content_type
    )

    from ..admin.service import get_platform_config

    config = await get_platform_config(db)
    model = (config.banner_vision_model or "").strip() or settings.BANNER_VISION_MODEL
    if model:
        result["ai_verdict"] = await _vision_verdict(data, model)

    # Optional plain-text decision model: it reads the measurements (and the
    # vision observations, when present) and writes the final call. Any
    # enabled model qualifies — no vision capability needed. Best-effort:
    # when it is unset or fails, the deterministic score stands.
    decision_model = (config.banner_decision_model or "").strip()
    if decision_model:
        decision = await _decision_verdict(result, decision_model)
        if decision:
            result["decision"] = decision
            result["suitable"] = decision["suitable"]
            result["confidence"] = decision["confidence"]
            if decision["summary"]:
                result["summary"] = decision["summary"]
    return result


async def _decision_verdict(result: dict, model: str) -> dict | None:
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


async def _vision_verdict(data: bytes, model: str) -> dict | None:
    """Multimodal verdict from the configured vision model, best-effort."""
    try:
        import json

        from ..llm.gateway import complete
        from ..llm.providers.base import LLMMessage

        response = await complete(
            model=model,
            messages=[LLMMessage(
                role="user",
                content=(
                    "Analyse this photo as a Google Business Profile banner "
                    "(cover) image. Answer ONLY with JSON: {\"suitable\": "
                    "\"yes\"|\"maybe\"|\"no\", \"confidence\": 0-100, "
                    "\"reasons\": [\"...\"]}."
                ),
            )],
            images=[("image/jpeg", data)],
            purpose="media.banner_verdict",
            temperature=0.2,
            max_tokens=300,
        )
        text = (response.content or "").strip()
        # Tolerate a code fence the model may add.
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        verdict = json.loads(text)
        return {
            "suitable": str(verdict.get("suitable", "maybe")),
            "confidence": int(verdict.get("confidence", 0)),
            "reasons": [str(r) for r in (verdict.get("reasons") or [])][:6],
        }
    except Exception:
        logger.exception("Banner vision verdict failed")
        return None


def _out(result: dict) -> MediaOut:
    return MediaOut(**result["media"])


@router.get("", response_model=list[MediaOut])
async def list_media(
    listing_id: str | None = Query(None, max_length=64),
    ctx: TenantContext = Depends(require_perm("media.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await service.list_media(db, tenant_id_of(user), listing_id)
    return [MediaOut(**r) for r in rows]


@router.post("", response_model=MediaPublishResult, status_code=201)
@router.post("/", response_model=MediaPublishResult, status_code=201)
async def create_media(
    body: MediaCreate,
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.create_media(db, tenant_id_of(user), body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise upstream_http_error(e, context="Media provider failed") from None
    return MediaPublishResult(
        media=_out(result),
        google_published=result["google_published"],
    )


@router.get("/{media_id}", response_model=MediaOut)
async def get_media(
    media_id: str,
    ctx: TenantContext = Depends(require_perm("media.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await service._owned_media(db, tenant_id_of(user), media_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Media not found.")
    return MediaOut(**service._serialize(item))


@router.put("/{media_id}", response_model=MediaPublishResult)
async def update_media(
    media_id: str,
    body: MediaUpdate,
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.update_media(
            db, tenant_id_of(user), media_id,
            # exclude_unset: explicit null cancels (delete_at), absent
            # keys stay untouched.
            {k: v for k, v in body.model_dump(exclude_unset=True).items()},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise upstream_http_error(e, context="Media provider failed") from None
    return MediaPublishResult(
        media=_out(result),
        google_published=result["google_published"],
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: str,
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await service.delete_media(db, tenant_id_of(user), media_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{media_id}/publish", response_model=MediaPublishResult)
async def publish_media_now(
    media_id: str,
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.publish_media(db, tenant_id_of(user), media_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise upstream_http_error(e, context="Media provider failed") from None
    return MediaPublishResult(
        media=_out(result),
        google_published=result["google_published"],
    )


@router.post("/sync", response_model=MediaSyncResult)
async def sync_due_media(
    request: Request,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run one worker pass on demand (admin/ops only — any authenticated
    tenant must not be able to trigger a GLOBAL publish/delete pass).
    Rate limited to 6/hour per IP."""
    from ..auth.rate_limit import rate_limit

    ip = request.client.host if request.client else "unknown"
    if not await rate_limit(f"media-sync:{ip}", 6, 3600):
        raise HTTPException(status_code=429, detail="Sync rate limit exceeded. Try again later.")
    result = await service.publish_due(db)
    gone = await service.delete_due(db)
    result["deleted"] = gone["deleted"]
    return MediaSyncResult(**result)
