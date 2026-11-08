"""Tenant purchase requests with admin approval.

There is no payment gateway yet, so buying a message/channel pack, AI credit
or a sales-assisted plan records a request. An operator approves or rejects it;
approval applies the change through the same billing paths as a manual admin
grant, so the ledger and entitlements stay consistent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BillingRequest, Plan, TenantSubscription

logger = logging.getLogger(__name__)

KINDS = ("messages", "channels", "ai_credit", "plan")
MAX_MESSAGES = 100_000
MAX_CHANNELS = 1_000
MAX_CREDIT_CENTS = 1_000_000  # $10,000 per request, mirrors the admin grant cap
MAX_NOTE = 500
DEDUPE_WINDOW_HOURS = 24


class RequestError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_request(
    db: AsyncSession,
    *,
    tenant_id: str,
    created_by: str | None,
    kind: str,
    amount: int | None = None,
    plan_slug: str | None = None,
    note: str | None = None,
) -> tuple[BillingRequest, bool]:
    """Create (or return the recent duplicate of) one purchase request."""
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise RequestError("Unknown request type.")
    note = (note or "").strip()[:MAX_NOTE] or None
    amount = None if amount is None else int(amount)

    if kind in ("messages", "channels"):
        cap = MAX_MESSAGES if kind == "messages" else MAX_CHANNELS
        if amount is None or amount < 1 or amount > cap:
            raise RequestError(f"Enter a quantity between 1 and {cap:,}.")
    elif kind == "ai_credit":
        if amount is None or amount < 100 or amount > MAX_CREDIT_CENTS:
            raise RequestError("Enter an amount between $1 and $10,000.")
        plan_slug = None
    elif kind == "plan":
        plan_slug = (plan_slug or "").strip()[:40] or None
        if not plan_slug:
            raise RequestError("Choose a plan.")
        plan = (
            await db.execute(select(Plan).where(Plan.slug == plan_slug))
        ).scalar_one_or_none()
        if plan is None or not plan.is_active:
            raise RequestError("That plan is not available.")
        amount = None

    since = _now() - timedelta(hours=DEDUPE_WINDOW_HOURS)
    existing = (
        await db.execute(
            select(BillingRequest)
            .where(
                BillingRequest.tenant_id == tenant_id,
                BillingRequest.kind == kind,
                BillingRequest.status == "pending",
                BillingRequest.created_at >= since,
                BillingRequest.amount.is_(None)
                if amount is None
                else BillingRequest.amount == amount,
                BillingRequest.plan_slug.is_(None)
                if plan_slug is None
                else BillingRequest.plan_slug == plan_slug,
            )
            .order_by(BillingRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    request = BillingRequest(
        tenant_id=tenant_id,
        kind=kind,
        amount=amount,
        plan_slug=plan_slug,
        note=note,
        created_by=created_by,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    logger.info(
        "Billing request created tenant=%s kind=%s amount=%s plan=%s",
        tenant_id[:8], kind, amount, plan_slug,
    )
    return request, False


def serialize(request: BillingRequest, email: str | None = None) -> dict:
    return {
        "id": request.id,
        "tenant_id": request.tenant_id,
        "email": email,
        "kind": request.kind,
        "amount": request.amount,
        "plan_slug": request.plan_slug,
        "note": request.note,
        "status": request.status,
        "created_by": request.created_by,
        "reviewed_by": request.reviewed_by,
        "reviewed_at": request.reviewed_at.isoformat() if request.reviewed_at else None,
        "decision_note": request.decision_note,
        "created_at": request.created_at.isoformat() if request.created_at else None,
    }


async def list_for_tenant(db: AsyncSession, tenant_id: str, limit: int = 50) -> list[BillingRequest]:
    return list(
        (
            await db.execute(
                select(BillingRequest)
                .where(BillingRequest.tenant_id == tenant_id)
                .order_by(BillingRequest.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


async def list_all(
    db: AsyncSession, status: str | None = None, limit: int = 100
) -> list[tuple[BillingRequest, str | None]]:
    from ..users.models import User

    stmt = (
        select(BillingRequest, User.email)
        .join(User, User.id == BillingRequest.tenant_id, isouter=True)
        .order_by(BillingRequest.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(BillingRequest.status == status)
    return [(row[0], row[1]) for row in (await db.execute(stmt)).all()]


async def _apply_messages(db: AsyncSession, tenant_id: str, amount: int) -> str:
    sub, plan = await _subscription(db, tenant_id)
    if sub is None:
        raise RequestError("Tenant has no subscription row.")
    if plan.max_messages_per_month is None:
        return "Plan already has unlimited WhatsApp messages; nothing to add."
    # Additive bonus, not an absolute override: a later plan change still
    # determines the base and this amount rides on top of it.
    sub.message_bonus = max(0, sub.message_bonus or 0) + amount
    await db.flush()
    try:
        from .quotas import invalidate_message_usage

        await invalidate_message_usage(tenant_id)
    except Exception:
        pass
    effective = plan.max_messages_per_month + sub.message_bonus
    return f"WhatsApp allowance is now {effective:,}/month."


async def _apply_channels(db: AsyncSession, tenant_id: str, amount: int) -> str:
    sub, plan = await _subscription(db, tenant_id)
    if sub is None:
        raise RequestError("Tenant has no subscription row.")
    if plan.max_channels is None:
        return "Plan already has unlimited channels; nothing to add."
    sub.channels_bonus = max(0, sub.channels_bonus or 0) + amount
    await db.flush()
    effective = plan.max_channels + sub.channels_bonus
    return f"Channel allowance is now {effective:,}."


async def _apply_plan(db: AsyncSession, tenant_id: str, plan_slug: str) -> str:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == plan_slug))
    ).scalar_one_or_none()
    if plan is None or not plan.is_active:
        raise RequestError("That plan is no longer available.")
    sub, _current = await _subscription(db, tenant_id)
    if sub is None:
        sub = TenantSubscription(tenant_id=tenant_id, plan_id=plan.id, status="active")
        db.add(sub)
    else:
        sub.plan_id = plan.id
        sub.status = "active"
        sub.granted_until = None
    # message_bonus/channels_bonus are deliberately untouched: they are the
    # additive top-ups the tenant bought and must stack on the new plan.
    await db.flush()
    return f"Plan switched to {plan.name}."


async def _subscription(db: AsyncSession, tenant_id: str) -> tuple[TenantSubscription | None, Plan]:
    sub = (
        await db.execute(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if sub is not None:
        plan = await db.get(Plan, sub.plan_id)
        if plan is not None:
            return sub, plan
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one_or_none()
    if plan is None:
        plan = (
            await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))
        ).scalars().first()
    if plan is None:
        raise RequestError("No active plan exists to attach this request to.")
    if sub is None:
        sub = TenantSubscription(tenant_id=tenant_id, plan_id=plan.id, status="active")
        db.add(sub)
        await db.flush()
    return sub, plan


async def decide_request(
    db: AsyncSession,
    request_id: str,
    *,
    approve: bool,
    operator: str | None,
    note: str | None = None,
) -> BillingRequest:
    """Approve (applying the purchase) or reject one request.

    The row is locked so two operators cannot apply the same request twice; AI
    credit additionally uses an idempotency key derived from the request id.
    """
    request = (
        await db.execute(
            select(BillingRequest)
            .where(BillingRequest.id == request_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise RequestError("Request not found.")
    if request.status != "pending":
        raise RequestError("This request was already reviewed.")

    summary = "Rejected."
    if approve:
        if request.kind == "messages":
            summary = await _apply_messages(db, request.tenant_id, int(request.amount or 0))
        elif request.kind == "channels":
            summary = await _apply_channels(db, request.tenant_id, int(request.amount or 0))
        elif request.kind == "plan":
            summary = await _apply_plan(db, request.tenant_id, request.plan_slug or "")
        elif request.kind == "ai_credit":
            from .service import grant_credit

            await grant_credit(
                request.tenant_id,
                int(request.amount or 0),
                f"Top-up request {request.id}" + (f": {note}" if note else ""),
                operator or "admin",
                db,
                idempotency_key=f"billing-request:{request.id}",
            )
            summary = f"${(request.amount or 0) / 100:,.2f} AI credit added."

    request.status = "approved" if approve else "rejected"
    request.reviewed_by = (operator or "admin")[:64]
    request.reviewed_at = _now()
    request.decision_note = (note or "").strip()[:MAX_NOTE] or summary

    # Tell the tenant in the bell, in the same transaction. `notify` flushes
    # only; the commit below persists it. Its own failure is swallowed so an
    # applied purchase is never rolled back by a notification problem.
    try:
        from ..notifications.service import notify

        await notify(
            db,
            request.tenant_id,
            "billing_request_approved" if approve else "billing_request_rejected",
            "Top-up request approved" if approve else "Top-up request rejected",
            summary,
            data={"request_id": request.id, "kind": request.kind},
            href="/dashboard/billing/topup",
        )
    except Exception as e:  # pragma: no cover - notification is best effort
        logger.warning("Billing request notification failed: %s", e)

    # Email the decision to the owner. Enqueued, never sent inline.
    try:
        from ..email.service import send_notification_email
        from ..users.models import User

        owner = await db.get(User, request.tenant_id)
        if owner is not None and owner.email:
            await send_notification_email(
                owner.email,
                "Your top-up request was approved" if approve else "Your top-up request was rejected",
                f"{summary}\n\nRequest: {request.kind}"
                + (f" · {request.amount}" if request.amount else "")
                + (f"\nNote: {request.decision_note}" if request.decision_note else ""),
                "/dashboard/billing/topup",
            )
    except Exception as e:  # pragma: no cover - email is best effort
        logger.warning("Billing request email failed: %s", e)

    await db.commit()
    await db.refresh(request)

    logger.info(
        "Billing request %s %s by %s", request.id, request.status, operator or "admin"
    )
    return request
