from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from . import service
from .schemas import (
    FeedbackRequest,
    PreferencesUpdateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    UsageResponse,
)

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def read_profile(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await service.get_profile(user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("", response_model=ProfileResponse)
async def patch_profile(
    body: ProfileUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.update_profile(
            user.id, body.model_dump(exclude_unset=True), db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/preferences", response_model=ProfileResponse)
async def patch_preferences(
    body: PreferencesUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.update_preferences(user.id, body.theme, body.language, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/usage", response_model=UsageResponse)
async def read_usage(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_usage(user.id, db)


@router.get("/feedback")
async def read_feedback(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"feedback": await service.list_feedback(user.id, db)}


@router.post("/feedback")
async def write_feedback(
    body: FeedbackRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        feedback = await service.submit_feedback(user.id, body.category, body.stars, db)
        return {"feedback": feedback}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
