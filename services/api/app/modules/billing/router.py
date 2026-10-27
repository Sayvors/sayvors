from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..team.context import tenant_id_of
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
    SubscriptionOut,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/budget", response_model=BudgetOut)
async def read_budget(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Workspace wallet: current plan + remaining AI credit balance.

    Employees see the owner's workspace wallet (AI spend is charged there);
    billing profile and saved cards below remain owner-scoped.
    """
    try:
        return await service.get_budget(tenant_id_of(user), db)
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


@router.get("/ledger")
async def read_ledger(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Durable AI credit ledger for the workspace: wallet, pending holds,
    and recent ledger rows. Employees see the owner's workspace ledger."""
    from ..admin.service import get_tenant_billing

    result = await get_tenant_billing(db, tenant_id_of(user))
    if result is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return result


@router.get("/plan", response_model=SubscriptionOut)
async def read_plan(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The tenant's current plan + status. Employees read the owner's."""
    from ...billing.models import TenantSubscription, Plan
    from ...billing.schemas import SubscriptionOut
    from ...core.deps import tenant_id_of

    tid = tenant_id_of(user)
    sub = (
        await db.execute(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tid)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="No subscription for this tenant.")
    plan = await db.get(Plan, sub.plan_id)
    return SubscriptionOut(
        id=sub.id, tenant_id=sub.tenant_id, plan_id=sub.plan_id,
        plan_slug=plan.slug if plan else None,
        plan_name=plan.name if plan else None,
        status=sub.status, period_start=sub.period_start, period_end=sub.period_end,
        granted_by=sub.granted_by, granted_until=sub.granted_until,
    )


@router.get("/plans")
async def list_public_plans(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    from ..billing.models import Plan

    rows = (await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order, Plan.name))).scalars().all()
    return [
        {
            "id": r.id,
            "slug": r.slug,
            "name": r.name,
            "description": r.description,
            "price_cents": r.price_cents,
            "included_credit_cents": r.included_credit_cents,
            "max_channels": r.max_channels,
            "max_messages_per_month": r.max_messages_per_month,
            "features": r.features or {},
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


@router.get("/entitlements")
async def read_entitlements(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The tenant's effective plan + entitlements (base plan + promo overrides)."""
    from ...core.deps import tenant_id_of
    from .entitlements import get_entitlements

    tid = tenant_id_of(user)
    ent = await get_entitlements(tid, db)
    return {
        "plan_slug": ent.plan_slug,
        "plan_name": ent.plan_name,
        "status": ent.status,
        "max_channels": ent.max_channels,
        "max_messages_per_month": ent.max_messages_per_month,
        "included_credit_cents": ent.included_credit_cents,
        "features": ent.features,
        "promo_active": ent.promo_active,
        "granted_by": ent.granted_by,
        "granted_until": ent.granted_until.isoformat() if ent.granted_until else None,
    }
