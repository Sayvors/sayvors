"""Tenant purchase requests with admin approval.

There is no payment gateway yet, so buying a message/channel pack, AI credit
or a sales-assisted plan records a request. An operator approves or rejects it;
approval applies the change through the same billing paths as a manual admin
grant, so the ledger and entitlements stay consistent.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BillingEvent, BillingRequest, Plan, TenantSubscription

logger = logging.getLogger(__name__)

KINDS = ("messages", "channels", "ai_credit", "plan")
MAX_MESSAGES = 100_000
MAX_CHANNELS = 1_000
MAX_CREDIT_CENTS = 1_000_000  # $10,000 per request, mirrors the admin grant cap
MAX_NOTE = 500
DEDUPE_WINDOW_HOURS = 24
# A bounded operator queue. Five lets a tenant ask for one of each kind plus
# one correction; beyond that they are spamming rather than waiting for a
# decision. The unique index caps each (kind, amount, plan) tuple to one row.
MAX_PENDING_PER_TENANT = 5


class RequestError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _pending_duplicate(
    db: AsyncSession,
    *,
    tenant_id: str,
    kind: str,
    amount: int | None,
    plan_slug: str | None,
    since: datetime | None,
) -> BillingRequest | None:
    """Find the one pending row that collides with this submission.

    ``since`` restricts the lookup to the dedupe window for the normal path;
    passing None finds a row of any age, which is what the unique-index
    conflict handler needs in order to return the row that beat us to it.
    """
    stmt = (
        select(BillingRequest)
        .where(
            BillingRequest.tenant_id == tenant_id,
            BillingRequest.kind == kind,
            BillingRequest.status == "pending",
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
    if since is not None:
        stmt = stmt.where(BillingRequest.created_at >= since)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _pending_count(db: AsyncSession, tenant_id: str) -> int:
    """Every open request, not just this window — the operator queue is the
    resource being bounded, and an old forgotten request still occupies it."""
    return int(
        (
            await db.execute(
                select(func.count(BillingRequest.id)).where(
                    BillingRequest.tenant_id == tenant_id,
                    BillingRequest.status == "pending",
                )
            )
        ).scalar_one()
    )


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
    """Create (or return the recent duplicate of) one purchase request.

    The tenant row is locked for the duration: check-then-insert is only
    atomic if submissions from the same workspace cannot interleave. The
    partial unique index is the backstop for anything that slips past the
    read (a second process, a stale replica snapshot), and its conflict is
    translated back into the same "duplicate" answer rather than a 500.
    """
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

    from ..users.models import User

    locked = (
        await db.execute(select(User.id).where(User.id == tenant_id).with_for_update())
    ).scalar_one_or_none()
    if locked is None:
        raise RequestError("Tenant not found.")

    since = _now() - timedelta(hours=DEDUPE_WINDOW_HOURS)
    existing = await _pending_duplicate(
        db, tenant_id=tenant_id, kind=kind, amount=amount,
        plan_slug=plan_slug, since=since,
    )
    if existing is not None:
        return existing, True

    if await _pending_count(db, tenant_id) >= MAX_PENDING_PER_TENANT:
        raise RequestError(
            f"You already have {MAX_PENDING_PER_TENANT} requests waiting for review. "
            "Wait for a decision before submitting another."
        )

    request = BillingRequest(
        tenant_id=tenant_id,
        kind=kind,
        amount=amount,
        plan_slug=plan_slug,
        note=note,
        created_by=created_by,
    )
    try:
        # Savepoint: a losing insert must not poison the caller's transaction.
        async with db.begin_nested():
            db.add(request)
            await db.flush()
    except IntegrityError:
        winner = await _pending_duplicate(
            db, tenant_id=tenant_id, kind=kind, amount=amount,
            plan_slug=plan_slug, since=None,
        )
        if winner is None:
            # A constraint we do not own was violated (e.g. a bad FK). Never
            # pretend it was a harmless duplicate.
            raise
        logger.info(
            "Billing request race resolved as duplicate tenant=%s kind=%s",
            tenant_id[:8], kind,
        )
        return winner, True

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


async def _apply_plan(
    db: AsyncSession,
    tenant_id: str,
    plan_slug: str,
    *,
    request_id: str,
    operator: str | None,
    note: str | None,
) -> tuple[str, int | None]:
    from .service import apply_plan_change

    try:
        result = await apply_plan_change(
            tenant_id,
            plan_slug,
            granted_until=None,
            note=note or f"Approved plan request {request_id}",
            created_by=operator or "admin",
            idempotency_key=f"billing-request-plan:{request_id}",
            db=db,
        )
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    summary = f"Plan switched to {result['plan_name']}."
    granted = int(result["granted_credit_cents"] or 0)
    if granted > 0:
        summary += f" ${granted / 100:,.2f} AI credit added."
        return summary, int(result["balance_cents"])
    return summary, None


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
    Every approval leaves an immutable ledger row, including the non-credit
    kinds, so the wallet has a dated record of what was decided and by whom.
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
    plan_grant_balance: int | None = None
    if approve:
        if request.kind == "messages":
            summary = await _apply_messages(db, request.tenant_id, int(request.amount or 0))
        elif request.kind == "channels":
            summary = await _apply_channels(db, request.tenant_id, int(request.amount or 0))
        elif request.kind == "plan":
            summary, plan_grant_balance = await _apply_plan(
                db,
                request.tenant_id,
                request.plan_slug or "",
                request_id=request.id,
                operator=operator,
                note=note,
            )
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

        # AI credit and plan changes write their own grant rows above. This
        # additional zero-amount event is the dated decision snapshot for every
        # non-credit approval; it never moves the balance.
        if request.kind != "ai_credit":
            from .ledger import ensure_ledger_initialized

            balance = int(await ensure_ledger_initialized(request.tenant_id, db))
            db.add(
                BillingEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=request.tenant_id,
                    kind="billing_request",
                    status="posted",
                    amount_cents=0,
                    reserved_cents=0,
                    balance_after_cents=balance,
                    note=f"Approved {request.kind} request {request.id}: {summary}",
                    created_by=(operator or "admin")[:36],
                    idempotency_key=f"billing-request-decision:{request.id}",
                )
            )

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

    try:
        await db.commit()
    except IntegrityError:
        # The idempotency key lost to a concurrent decision. That transaction
        # applied the purchase and set the status, so the work is done; return
        # the committed row. Anything else is a real failure and must surface.
        await db.rollback()
        committed = await db.get(BillingRequest, request_id)
        if committed is not None and committed.status == "approved":
            await db.refresh(committed)
            from ..users.models import User
            from .budget import sync_balance

            owner = await db.get(User, request.tenant_id)
            if owner is not None:
                await sync_balance(request.tenant_id, int(owner.ai_credit_cents or 0))
            return committed
        raise

    if plan_grant_balance is not None:
        from .budget import sync_balance

        synced = await sync_balance(request.tenant_id, plan_grant_balance)
        if not synced:
            logger.warning(
                "Plan request committed; Redis mirror sync failed: tenant=%s balance=%s¢",
                request.tenant_id,
                plan_grant_balance,
            )

    await db.refresh(request)

    logger.info(
        "Billing request %s %s by %s", request.id, request.status, operator or "admin"
    )
    return request
