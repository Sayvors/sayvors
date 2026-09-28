from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...core.deps import get_current_user, require_admin
from ..users.models import User
from . import service as feedback_service
from .schemas import FeedbackCreate, FeedbackList, FeedbackOut

router = APIRouter(prefix="/api/v1", tags=["feedback"])


@router.get("/feedback/status")
async def feedback_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await feedback_service.get_feedback_status(current_user.id, db)


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await feedback_service.create_feedback(current_user.id, body, db)
    except feedback_service.FeedbackCooldownError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))


@router.get("/admin/feedback", response_model=FeedbackList)
async def list_all_feedback(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    items, total = await feedback_service.list_feedback(db, limit, offset)
    return FeedbackList(items=items, total=total)
