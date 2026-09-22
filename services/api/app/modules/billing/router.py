from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from . import service
from .schemas import (
    BillingProfileIn,
    BillingProfileOut,
    BudgetOut,
    GatewayChargeIn,
    GatewayChargeOut,
    GatewayTokenizeIn,
    GatewayTokenizeOut,
    PaymentMethodIn,
    PaymentMethodOut,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/budget", response_model=BudgetOut)
async def read_budget(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Tenant wallet: current plan + remaining AI credit balance."""
    try:
        return await service.get_budget(user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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


@router.post("/gateway/tokenize", response_model=GatewayTokenizeOut)
async def gateway_tokenize(body: GatewayTokenizeIn, user=Depends(get_current_user)):
    """Stub-gateway tokenize: card metadata in, opaque token out.

    Never accepts a full PAN or CVC (see providers.py / models.py).
    """
    from datetime import datetime, timezone

    from .providers import get_payment_provider

    now = datetime.now(timezone.utc)
    if (body.exp_year, body.exp_month) < (now.year, now.month):
        raise HTTPException(status_code=400, detail="Card is already expired.")
    gw = get_payment_provider("stub")
    return gw.tokenize(
        brand=body.brand,
        last4=body.last4,
        exp_month=body.exp_month,
        exp_year=body.exp_year,
        holder_name=body.holder_name,
    )


@router.post("/gateway/charge", response_model=GatewayChargeOut)
async def gateway_charge(body: GatewayChargeIn, user=Depends(get_current_user)):
    """Stub-gateway charge: always succeeds for a valid stub token.

    Pure stub — no money moves and no credits are granted yet; real
    processor + top-up wiring lands with gateway keys.
    """
    from .providers import get_payment_provider

    gw = get_payment_provider("stub")
    try:
        return gw.charge(
            token=body.token,
            amount_cents=body.amount_cents,
            currency=body.currency,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
