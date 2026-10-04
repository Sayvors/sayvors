from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from . import business_profile, service
from .schemas import (
    BusinessProfileResponse,
    BusinessProfileUpdateRequest,
    FeedbackRequest,
    PreferencesUpdateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    ResponseStyleUpdateRequest,
    UsageResponse,
    VoiceRepliesUpdateRequest,
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


@router.put("/response-style", response_model=ProfileResponse)
async def put_response_style(
    body: ResponseStyleUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the tenant's WhatsApp response style. Takes effect for messages
    sent after the save — the consumer reads it per incoming message."""
    try:
        return await service.update_response_style(
            user.id, body.response_style, db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/voice-replies", response_model=ProfileResponse)
async def put_voice_replies(
    body: VoiceRepliesUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the tenant's WhatsApp voice replies tier ("off" | "simple" |
    "advanced"). Which engine serves each tier is admin-managed."""
    try:
        return await service.update_voice_replies(
            user.id, body.voice_replies, db
        )
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
        feedback = await service.submit_feedback(user.id, body.emoji_rating, body.message, db)
        return {"feedback": feedback}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/business", response_model=BusinessProfileResponse)
async def read_business_profile(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The AI business card (or null until first generation)."""
    row = await business_profile.get_business_profile_row(user.id, db)
    return {
        "profile": business_profile.serialize_profile(row) if row else None
    }


@router.put("/business", response_model=BusinessProfileResponse)
async def write_business_profile(
    body: BusinessProfileUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save card edits — user text wins over any later regeneration."""
    try:
        profile = await business_profile.save_business_profile(
            user.id, body.model_dump(), db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"profile": profile}


@router.post("/business/regenerate", response_model=BusinessProfileResponse)
async def regenerate_business_profile(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Force a regeneration from the databank. An edited card keeps its
    text — only empty fields get filled."""
    try:
        profile = await business_profile.generate_business_profile(
            user.id, db, force=True
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"profile": profile}
