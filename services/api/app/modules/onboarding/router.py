"""Onboarding checklist persistence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from . import schemas, service


router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


@router.get("", response_model=schemas.OnboardingStateOut)
async def read_state(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    state = await service.get_state(db, user.id)
    return schemas.OnboardingStateOut(**state)


@router.put("", response_model=schemas.OnboardingStateOut)
async def write_state(
    body: schemas.OnboardingStateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        state = await service.update_state(db, user.id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return schemas.OnboardingStateOut(**state)
