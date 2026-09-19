"""Posts API — create, read, update, delete, publish, sync.

POST   /api/v1/posts/                create (publish now | schedule | draft)
GET    /api/v1/posts/                list (?listing_id=)
GET    /api/v1/posts/{post_id}       read one
PUT    /api/v1/posts/{post_id}       update (status flips to published publish now)
DELETE /api/v1/posts/{post_id}       delete permanently
POST   /api/v1/posts/{post_id}/publish   publish a draft/scheduled/failed post now
POST   /api/v1/posts/sync            publish all due scheduled posts
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from . import service
from .schemas import PostCreate, PostOut, PostUpdate, PublishResult, SyncResult

router = APIRouter(prefix="/api/v1/posts", tags=["posts"])


def _out(result: dict) -> PostOut:
    return PostOut(**result["post"])


@router.post("/", response_model=PublishResult, status_code=201)
async def create_post(
    body: PostCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.create_post(db, user.id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return PublishResult(
        post=_out(result),
        google_published=result["google_published"],
        images_sent=result["images_sent"],
        images_skipped=result["images_skipped"],
    )


@router.get("/", response_model=list[PostOut])
async def list_posts(
    listing_id: str | None = Query(None, max_length=64),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await service.list_posts(db, user.id, listing_id)
    return [PostOut(**r) for r in rows]


@router.get("/{post_id}", response_model=PostOut)
async def get_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await service._owned_post(db, user.id, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found.")
    return PostOut(**service._serialize(post))


@router.put("/{post_id}", response_model=PublishResult)
async def update_post(
    post_id: str,
    body: PostUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.update_post(
            db, user.id, post_id,
            # exclude_unset: explicit null cancels (delete_at), absent
            # keys stay untouched.
            {k: v for k, v in body.model_dump(exclude_unset=True).items()},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return PublishResult(
        post=_out(result),
        google_published=result["google_published"],
        images_sent=result["images_sent"],
        images_skipped=result["images_skipped"],
    )


@router.delete("/{post_id}", status_code=204)
async def delete_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await service.delete_post(db, user.id, post_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{post_id}/publish", response_model=PublishResult)
async def publish_post_now(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await service.publish_post(db, user.id, post_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return PublishResult(
        post=_out(result),
        google_published=result["google_published"],
        images_sent=result["images_sent"],
        images_skipped=result["images_skipped"],
    )


@router.post("/sync", response_model=SyncResult)
async def sync_due_posts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run one worker pass on demand: publish due scheduled posts and
    delete rows whose delete_at has passed. Per-post failures are
    isolated and reported."""
    _ = user
    result = await service.publish_due(db)
    gone = await service.delete_due(db)
    result["deleted"] = gone["deleted"]
    return SyncResult(**result)
