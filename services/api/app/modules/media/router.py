"""Media API — schedule photos to go live on Google, plus library CRUD.

Photos publish inside Google posts (the only photo path Localith offers);
videos are stored as library rows (provider takes image URLs, not video).

GET    /api/v1/media                list (?listing_id=)
POST   /api/v1/media                create (publish now | schedule | draft)
GET    /api/v1/media/{media_id}     read one
PUT    /api/v1/media/{media_id}     update (category/flags/schedule/delete_at)
DELETE /api/v1/media/{media_id}     delete permanently
POST   /api/v1/media/{media_id}/publish   publish a draft/scheduled/failed photo now
POST   /api/v1/media/sync           publish due + delete expired (worker pass on demand)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from . import service
from .schemas import MediaCreate, MediaOut, MediaPublishResult, MediaSyncResult, MediaUpdate

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.post("/upload")
async def upload_media_file(
    request: Request,
    file: UploadFile = File(...),
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
            user.id,
            file.filename or "upload",
            file.content_type,
            data,
            str(request.base_url),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _out(result: dict) -> MediaOut:
    return MediaOut(**result["media"])


@router.get("/", response_model=list[MediaOut])
async def list_media(
    listing_id: str | None = Query(None, max_length=64),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await service.list_media(db, user.id, listing_id)
    return [MediaOut(**r) for r in rows]


@router.post("/", response_model=MediaPublishResult, status_code=201)
async def create_media(
    body: MediaCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.create_media(db, user.id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return MediaPublishResult(
        media=_out(result),
        google_published=result["google_published"],
    )


@router.get("/{media_id}", response_model=MediaOut)
async def get_media(
    media_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await service._owned_media(db, user.id, media_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Media not found.")
    return MediaOut(**service._serialize(item))


@router.put("/{media_id}", response_model=MediaPublishResult)
async def update_media(
    media_id: str,
    body: MediaUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.update_media(
            db, user.id, media_id,
            # exclude_unset: explicit null cancels (delete_at), absent
            # keys stay untouched.
            {k: v for k, v in body.model_dump(exclude_unset=True).items()},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return MediaPublishResult(
        media=_out(result),
        google_published=result["google_published"],
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await service.delete_media(db, user.id, media_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{media_id}/publish", response_model=MediaPublishResult)
async def publish_media_now(
    media_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.publish_media(db, user.id, media_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return MediaPublishResult(
        media=_out(result),
        google_published=result["google_published"],
    )


@router.post("/sync", response_model=MediaSyncResult)
async def sync_due_media(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run one worker pass on demand: publish due photos, delete expired."""
    _ = user
    result = await service.publish_due(db)
    gone = await service.delete_due(db)
    result["deleted"] = gone["deleted"]
    return MediaSyncResult(**result)
