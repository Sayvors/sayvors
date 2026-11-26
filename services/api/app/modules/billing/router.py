"""Tenant-facing billing routes (wallet, plan, entitlements, requests)."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_current_user, get_db
from ..auth.rate_limit import rate_limit
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

logger = logging.getLogger(__name__)

# Submitting a request writes a row, opens an admin notification and can send
# the Enterprise sales emails. Ten tries a minute per workspace is generous
# for a genuine buyer and bounds a script hammering the form. Keyed by tenant,
# not IP, so a team sharing one NAT cannot multiply the budget.
REQUEST_RATE_MAX = 10
REQUEST_RATE_WINDOW_SECONDS = 60


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
async def read_ledger(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal["newest", "oldest", "cost_high", "cost_low"] = "newest",
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Durable AI credit ledger for the workspace: wallet, pending holds, and
    one page of ledger rows. Employees see the owner's workspace ledger.

    Cost sorting ranks spend (negative amounts) only; grants stay at the end.
    """
    from ..admin.service import get_tenant_billing

    result = await get_tenant_billing(
        db,
        tenant_id_of(user),
        include_model=False,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return result


@router.get("/plan", response_model=SubscriptionOut)
async def read_plan(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The tenant's current plan + status. Employees read the owner's."""
    from .models import TenantSubscription, Plan

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
            "max_locations": r.max_locations,
            "max_team_members": r.max_team_members,
            "max_regenerations_day": r.max_regenerations_day,
            "max_quick_research_month": r.max_quick_research_month,
            "max_deep_research_month": r.max_deep_research_month,
            "features": r.features or {},
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


class BillingRequestIn(BaseModel):
    kind: Literal["messages", "channels", "ai_credit", "plan"]
    amount: int | None = Field(default=None, ge=0, le=1_000_000)
    plan_slug: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)


@router.post("/requests")
async def create_purchase_request(
    body: BillingRequestIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ask an operator to top up messages, channels or AI credit, or to grant
    a sales-assisted plan. No payment is taken here."""
    from .requests import RequestError, create_request, serialize

    tenant_id = tenant_id_of(user)
    if not settings.TESTING and not await rate_limit(
        f"billing-request:{tenant_id}",
        REQUEST_RATE_MAX,
        REQUEST_RATE_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Wait a moment before submitting another.",
        )

    try:
        request, duplicate = await create_request(
            db,
            tenant_id=tenant_id,
            created_by=user.id,
            kind=body.kind,
            amount=body.amount,
            plan_slug=body.plan_slug,
            note=body.note,
        )
    except RequestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    # Tell the admin console (bell) about the new request — best effort.
    if not duplicate:
        try:
            from ...database import async_session as _async_session
            from ..admin.service import create_admin_notification

            async with _async_session() as n_db:
                await create_admin_notification(
                    n_db,
                    kind="request",
                    severity="info",
                    title=f"New {body.kind} request",
                    body=f"{user.email or body.kind} requested {body.kind}"
                    + (f" ({body.plan_slug})" if body.plan_slug else ""),
                    href="/requests",
                )
        except Exception:  # noqa: BLE001 — notifications never fail the request
            pass
    # Enterprise is sales-assisted: email the operator-configured list so a
    # human can follow up by email, phone or a meeting. Only new requests are
    # announced; the outbox idempotency key makes a retried request harmless.
    if not duplicate and request.kind == "plan" and request.plan_slug == "enterprise":
        try:
            from .plan_notifications import notify_enterprise_request

            await notify_enterprise_request(db, request=request, requested_by=user)
        except Exception as e:  # noqa: BLE001 - already committed; never fail here
            logger.warning(
                "Enterprise request %s notification failed: %s", request.id, e
            )
    return {**serialize(request), "duplicate": duplicate}


@router.get("/requests")
async def list_purchase_requests(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from .requests import list_for_tenant, serialize

    rows = await list_for_tenant(db, tenant_id_of(user), limit=limit)
    return {"items": [serialize(row) for row in rows]}


@router.get("/entitlements")
async def read_entitlements(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The tenant's effective plan + entitlements (base plan + promo overrides)."""
    from .entitlements import count_messages_this_month, get_entitlements

    tid = tenant_id_of(user)
    ent = await get_entitlements(tid, db)
    used = await count_messages_this_month(tid, db)
    remaining = None if ent.max_messages_per_month is None else max(0, ent.max_messages_per_month - used)
    return {
        "plan_slug": ent.plan_slug,
        "plan_name": ent.plan_name,
        "status": ent.status,
        "max_channels": ent.max_channels,
        "max_messages_per_month": ent.max_messages_per_month,
        "messages_used_this_month": used,
        "messages_remaining": remaining,
        "included_credit_cents": ent.included_credit_cents,
        "features": ent.features,
        "promo_active": ent.promo_active,
        "granted_by": ent.granted_by,
        "granted_until": ent.granted_until.isoformat() if ent.granted_until else None,
    }
