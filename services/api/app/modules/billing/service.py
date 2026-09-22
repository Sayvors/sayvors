"""Billing service: profiles + card-on-file records (tenant-scoped)."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BillingEvent, BillingProfile, PaymentMethod
from .schemas import BillingProfileIn, PaymentMethodIn

logger = logging.getLogger(__name__)

_MANUAL_PROVIDER = "manual"


def _expired(month: int, year: int) -> bool:
    now = datetime.now(timezone.utc)
    return (year, month) < (now.year, now.month)


def _serialize_method(row: PaymentMethod) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "brand": row.brand,
        "last4": row.last4,
        "exp_month": row.exp_month,
        "exp_year": row.exp_year,
        "holder_name": row.holder_name,
        "is_default": row.is_default,
        "provider": row.provider,
        "verified": row.verified,
        "expired": _expired(row.exp_month, row.exp_year),
    }


async def get_profile(user_id: str, db: AsyncSession) -> dict | None:
    row = (
        await db.execute(
            select(BillingProfile).where(BillingProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "user_id": row.user_id,
        "full_name": row.full_name,
        "email": row.email,
        "phone": row.phone,
        "address_line1": row.address_line1,
        "address_line2": row.address_line2,
        "city": row.city,
        "region": row.region,
        "postal_code": row.postal_code,
        "country": row.country,
        "tax_id": row.tax_id,
    }


async def save_profile(user_id: str, body: BillingProfileIn, db: AsyncSession) -> dict:
    row = (
        await db.execute(
            select(BillingProfile).where(BillingProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = BillingProfile(id=str(uuid.uuid4()), user_id=user_id)
        db.add(row)
    for field in ("full_name", "email", "phone", "address_line1",
                  "address_line2", "city", "region", "postal_code",
                  "country", "tax_id"):
        setattr(row, field, getattr(body, field))
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    result = await get_profile(user_id, db)
    assert result is not None
    return result


async def list_methods(user_id: str, db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(PaymentMethod)
            .where(PaymentMethod.user_id == user_id)
            .order_by(PaymentMethod.is_default.desc(),
                      PaymentMethod.created_at.desc())
        )
    ).scalars().all()
    return [_serialize_method(r) for r in rows]


async def _unset_others_default(user_id: str, db: AsyncSession, keep_id: str) -> None:
    rows = (
        await db.execute(
            select(PaymentMethod).where(
                PaymentMethod.user_id == user_id,
                PaymentMethod.is_default.is_(True),
                PaymentMethod.id != keep_id,
            )
        )
    ).scalars().all()
    for r in rows:
        r.is_default = False
        db.add(r)


async def add_method(user_id: str, body: PaymentMethodIn, db: AsyncSession) -> dict:
    if body.provider != _MANUAL_PROVIDER:
        # No gateway wired yet (see providers.py) — loud rejection, and the
        # provider id is never persisted for an unverifiable claim.
        from .providers import get_payment_provider

        get_payment_provider()
    if _expired(body.exp_month, body.exp_year):
        raise ValueError("Card is already expired.")
    existing = await list_methods(user_id, db)
    row = PaymentMethod(
        id=str(uuid.uuid4()),
        user_id=user_id,
        brand=body.brand.strip().lower()[:20],
        last4=body.last4,
        exp_month=body.exp_month,
        exp_year=body.exp_year,
        holder_name=(body.holder_name or "").strip() or None,
        # First card becomes the default automatically.
        is_default=body.is_default or not existing,
        provider=_MANUAL_PROVIDER,
        provider_payment_method_id=None,
        verified=False,
    )
    db.add(row)
    await db.flush()
    if row.is_default:
        await _unset_others_default(user_id, db, row.id)
    await db.commit()
    await db.refresh(row)
    return _serialize_method(row)


async def _owned_method(method_id: str, user_id: str, db: AsyncSession):
    row = (
        await db.execute(
            select(PaymentMethod).where(
                PaymentMethod.id == method_id,
                PaymentMethod.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Payment method not found.")
    return row


async def remove_method(method_id: str, user_id: str, db: AsyncSession) -> None:
    row = await _owned_method(method_id, user_id, db)
    was_default = row.is_default
    await db.delete(row)
    await db.flush()
    if was_default:
        # Promote the newest remaining card so the account keeps a default.
        nxt = (
            await db.execute(
                select(PaymentMethod)
                .where(PaymentMethod.user_id == user_id)
                .order_by(PaymentMethod.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if nxt is not None:
            nxt.is_default = True
            db.add(nxt)
    await db.commit()


async def set_default(method_id: str, user_id: str, db: AsyncSession) -> dict:
    row = await _owned_method(method_id, user_id, db)
    row.is_default = True
    db.add(row)
    await db.flush()
    await _unset_others_default(user_id, db, row.id)
    await db.commit()
    await db.refresh(row)
    return _serialize_method(row)


# ── Plan + AI credits (D1) ─────────────────────────────────

async def get_budget(user_id: str, db: AsyncSession) -> dict:
    """Tenant-facing wallet: plan + live balance.

    The live balance is Redis when available, else the DB column (top-up
    source of truth — may lag spend made since the last grant).
    """
    from ..users.models import User
    from .budget import get_balance

    user = await db.get(User, user_id)
    if user is None:
        raise ValueError("Tenant not found.")
    live = await get_balance(user_id)
    balance = live if live is not None else (user.ai_credit_cents or 0)
    return {
        "plan": user.plan or "free",
        "balance_cents": balance,
        "balance_dollars": round(balance / 100, 2),
        "currency": "usd",
    }


async def grant_plan(user_id: str, plan: str, add_credit_cents: int,
                     note: str | None, created_by: str | None,
                     db: AsyncSession) -> dict:
    """Admin purchase flow: set the plan, add credits, ledger it, sync Redis.

    A Pro purchase grants PLAN_INCLUDED_CENTS bundled credits on top of any
    explicit top-up — the DB is updated as a pro user with a $20 AI budget.
    """
    from ..users.models import User
    from .budget import PLAN_INCLUDED_CENTS, sync_balance

    if plan not in ("free", "pro"):
        raise ValueError("Unknown plan.")
    user = await db.get(User, user_id)
    if user is None:
        raise ValueError("Tenant not found.")
    old_plan = user.plan or "free"
    plan_changed = old_plan != plan
    bundled = PLAN_INCLUDED_CENTS.get(plan, 0) if plan_changed else 0
    total_add = (add_credit_cents or 0) + bundled
    user.plan = plan
    user.ai_credit_cents = (user.ai_credit_cents or 0) + total_add
    db.add(BillingEvent(
        id=str(uuid.uuid4()),
        tenant_id=user_id,
        kind="plan_grant" if plan_changed else "credit_topup",
        amount_cents=total_add,
        balance_after_cents=user.ai_credit_cents,
        note=note,
        created_by=created_by,
    ))
    await db.commit()
    await sync_balance(user_id, user.ai_credit_cents)
    logger.info("Plan grant: tenant=%s plan=%s +%s¢ (by=%s)", user_id, plan, total_add, created_by)
    return {
        "plan": user.plan,
        "balance_cents": user.ai_credit_cents,
        "balance_dollars": round(user.ai_credit_cents / 100, 2),
        "currency": "usd",
    }
