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
    # Same pipeline the queued job runs; the verdict functions are module
    # aliases so tests (and callers) can substitute them in one place.
    return await service.full_banner_analysis(
        db, data, vision_verdict_fn=_vision_verdict, decision_verdict_fn=_decision_verdict,
    )


async def _vision_verdict(data: bytes, model: str) -> dict | None:
    """Alias kept for the publish composer's test seams; body lives in service."""
    return await service.vision_verdict(data, model)


async def _decision_verdict(result: dict, model: str) -> dict | None:
    return await service.decision_verdict(result, model)


@router.post("/banner-checks")
async def enqueue_banner_check(
    request: Request,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    ctx: TenantContext = Depends(require_perm("media.manage")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue the AI photo check on the realtime lane (publication waits on it).

    Accepts an uploaded file, or a media URL when the photo lives in the
    library (no local File in the browser) — the server resolves the bytes
    through its own storage / the SSRF-guarded fetcher. Returns the check id
    for polling. The photo is stored through the same validation as
    /upload, so a lying-extension file is rejected here with the same
    message the picker already showed.
    """
    _ = ctx
    if file is not None and (file.filename or file.content_type):
        data = await file.read()
        filename = file.filename or "banner.png"
        content_type = file.content_type
    elif url:
        from ...core.storage import media_bytes_from_url

        try:
            data, content_type = media_bytes_from_url(tenant_id_of(user), url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read that image: {e}")
        # The stored content type is authoritative (it was derived from a
        # validated upload); derive the name so the magic check passes.
        ext = {
            "image/jpeg": "banner.jpg",
            "image/png": "banner.png",
            "image/webp": "banner.webp",
            "image/gif": "banner.gif",
        }.get((content_type or "").split(";")[0].strip().lower(), "banner.png")
        filename = ext
    else:
        raise HTTPException(status_code=400, detail="Provide a file or a url.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    max_bytes = max(1, settings.MEDIA_MAX_MB) * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=400, detail="File is too big.")
    try:
        row = await service.enqueue_banner_check(
            db,
            user_id=tenant_id_of(user),
            filename=filename,
            content_type=content_type,
            data=data,
            base_url=public_media_base(str(request.base_url)),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": row.id, "status": row.status}


@router.get("/banner-checks/{check_id}")
async def get_banner_check(
    check_id: str,
    ctx: TenantContext = Depends(require_perm("media.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll one queued check. Payload shape matches /analyze-banner."""
    from sqlalchemy import select as _select

    from .models import BannerCheck

    row = (
        await db.execute(
            _select(BannerCheck).where(
                BannerCheck.id == check_id,
                BannerCheck.tenant_id == tenant_id_of(user),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    return service.serialize_banner_check(row)


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
