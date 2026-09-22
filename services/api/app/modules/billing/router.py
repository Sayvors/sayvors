from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from . import service
from .schemas import (
    BillingProfileIn,
    BillingProfileOut,
    PaymentMethodIn,
    PaymentMethodOut,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/profile", response_model=BillingProfileOut | None)
async def read_profile(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_profile(user.id, db)


@router.put("/profile", response_model=BillingProfileOut)
async def write_profile(
    body: BillingProfileIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.save_profile(user.id, body, db)


@router.get("/methods", response_model=list[PaymentMethodOut])
async def read_methods(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.list_methods(user.id, db)


@router.post("/methods", response_model=PaymentMethodOut)
async def create_method(
    body: PaymentMethodIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.add_method(user.id, body, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/methods/{method_id}/default", response_model=PaymentMethodOut)
async def make_default(
    method_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.set_default(method_id, user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/methods/{method_id}")
async def delete_method(
    method_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await service.remove_method(method_id, user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}
