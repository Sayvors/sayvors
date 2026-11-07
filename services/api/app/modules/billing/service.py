"""Billing service: profiles + card-on-file records (tenant-scoped)."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    BillingEvent,
    BillingProfile,
    PaymentMethod,
    Plan,
    TenantSubscription,
)
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
    provider = (body.provider or _MANUAL_PROVIDER).strip().lower()
    provider_pm_id: str | None = None
    if provider == _MANUAL_PROVIDER:
        verified = False
    elif provider == "stub":
        from .providers import get_payment_provider

        gw = get_payment_provider("stub")
        if body.provider_token:
            gw.verify_token(body.provider_token)
            provider_pm_id = body.provider_token
        else:
            tok = gw.tokenize(
                brand=body.brand,
                last4=body.last4,
                exp_month=body.exp_month,
                exp_year=body.exp_year,
                holder_name=body.holder_name,
            )
            provider_pm_id = tok["token"]
        verified = True
    else:
        # Real gateway ids fail loudly until keys are configured
        # (see providers.py) — never persisted for an unverifiable claim.
        from .providers import get_payment_provider

        get_payment_provider(provider)
        verified = False
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
        provider=provider,
        provider_payment_method_id=provider_pm_id,
        verified=verified,
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

async def get_budget(tenant_id: str, db: AsyncSession) -> dict:
    """Tenant-facing wallet: plan + durable available balance.

    The DB wallet is authoritative. A tenant that predates the ledger gets its
    one-time opening baseline on first read; after that this is a plain row
    read. Redis is never consulted for the number.
    """
    from ..users.models import User
    from .ledger import OPENING_KEY_PREFIX, ensure_ledger_initialized
    from .models import BillingEvent

    user = await db.get(User, tenant_id)
    if user is None:
        raise ValueError("Tenant not found.")
    fallback = int(user.ai_credit_cents or 0)
    plan = user.plan or "free"
    try:
        from .entitlements import get_effective_plan

        effective, _status, _by, _until, _override = await get_effective_plan(
            tenant_id, db
        )
        plan = effective.slug
    except Exception as e:
        logger.warning(
            "Could not resolve effective plan for %s; using user.plan: %s",
            tenant_id,
            e,
        )
    try:
        # Fast path: after cutover the opening row exists, so a dashboard read
        # is a plain row read with no wallet lock. Only a tenant that still
        # predates the ledger pays for the one-time reconstruction.
        opening = (
            await db.execute(
                select(BillingEvent.id).where(
                    BillingEvent.tenant_id == tenant_id,
                    BillingEvent.idempotency_key == f"{OPENING_KEY_PREFIX}{tenant_id}",
                )
            )
        ).scalar_one_or_none()
        if opening is not None:
            balance = fallback
        else:
            balance = int(await ensure_ledger_initialized(tenant_id, db))
            await db.commit()
    except Exception as e:
        logger.exception(
            "Wallet read failed for %s; showing the last committed DB balance: %s",
            tenant_id,
            e,
        )
        await db.rollback()
        balance = fallback
    from . import pricing

    await pricing.ensure_fresh(db)
    per_usd = pricing.sc_per_usd()
    return {
        "plan": plan,
        "balance_cents": balance,
        "balance_dollars": round(balance / 100, 2),
        "currency": "usd",
        # Credits are the customer-facing unit; cents remain the ledger's
        # storage unit for compatibility with existing holds and grants.
        "credits_per_usd": per_usd,
        "balance_credits": round((balance / 100) * per_usd, 2),
    }


async def grant_trial_credit(user, db: AsyncSession) -> bool:
    """Give a new tenant the one-time free-trial AI credit.

    Runs inside the signup transaction, after the user row has an id. The
    ledger key is the idempotency boundary: a retried signup, a duplicate
    social callback or a backfill run cannot grant the same tenant twice.
    The wallet, ledger event and subscription move together; a failure here
    rolls the signup back instead of silently creating a zero-credit account.
    """
    from ...config import settings

    key = f"trial:{user.id}"
    existing = (
        await db.execute(
            select(BillingEvent.id).where(
                BillingEvent.tenant_id == user.id,
                BillingEvent.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    amount = max(0, int(settings.TRIAL_CREDIT_CENTS))
    if amount == 0:
        return False

    plan = (
        await db.execute(
            select(Plan).where(Plan.slug == "free-trial", Plan.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if plan is not None:
        sub = (
            await db.execute(
                select(TenantSubscription).where(
                    TenantSubscription.tenant_id == user.id
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            db.add(
                TenantSubscription(
                    tenant_id=user.id,
                    plan_id=plan.id,
                    status="active",
                    granted_by="signup",
                )
            )
        elif (user.plan or "free") == "free":
            sub.plan_id = plan.id
            sub.status = "active"
            sub.granted_by = "signup"

    balance = int(user.ai_credit_cents or 0) + amount
    user.ai_credit_cents = balance
    if (user.plan or "free") == "free":
        user.plan = "free-trial"
    db.add(
        BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=user.id,
            kind="plan_grant",
            status="posted",
            amount_cents=amount,
            reserved_cents=0,
            balance_after_cents=balance,
            idempotency_key=key,
            note=f"Free trial credit (${amount / 100:.2f})",
            created_by="signup",
        )
    )
    await db.flush()
    return True


async def grant_plan(user_id: str, plan: str, add_credit_cents: int,
                     note: str | None, created_by: str | None,
                     db: AsyncSession) -> dict:
    """Admin purchase flow: set the plan, add credits, ledger it, sync Redis.

    The plan's own ``included_credit_cents`` is bundled on a plan change, so
    the wallet matches the card the tenant saw. The grant adds to the locked
    durable wallet; it never recomputes a balance from grants, so a top-up
    cannot re-grant credit the tenant already spent. The subscription row is
    updated here as well so entitlement checks and the wallet cannot disagree.
    """
    from ..users.models import User
    from .budget import PLAN_INCLUDED_CENTS, sync_balance
    from .ledger import ensure_ledger_initialized

    if plan not in ("free", "pro"):
        raise ValueError("Unknown plan.")
    plan_row = (
        await db.execute(select(Plan).where(Plan.slug == plan))
    ).scalar_one_or_none()
    # Serialise grants so two admins cannot lose one top-up to a
    # read-modify-write race.
    user = (
        await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise ValueError("Tenant not found.")
    old_plan = user.plan or "free"
    plan_changed = old_plan != plan
    if plan_changed:
        bundled = (
            plan_row.included_credit_cents
            if plan_row is not None
            else PLAN_INCLUDED_CENTS.get(plan, 0)
        )
    else:
        bundled = 0
    total_add = (add_credit_cents or 0) + bundled

    sub = (
        await db.execute(
            select(TenantSubscription).where(TenantSubscription.tenant_id == user_id)
        )
    ).scalar_one_or_none()
    if plan_row is not None and plan_changed:
        if sub is None:
            db.add(
                TenantSubscription(
                    tenant_id=user_id,
                    plan_id=plan_row.id,
                    status="active",
                    granted_by=created_by or "admin",
                )
            )
        else:
            sub.plan_id = plan_row.id
            sub.status = "active"
            sub.granted_by = created_by or "admin"
            sub.granted_until = None

    before = int(await ensure_ledger_initialized(user_id, db))
    new_balance = before + total_add
    user.plan = plan
    user.ai_credit_cents = new_balance
    db.add(BillingEvent(
        id=str(uuid.uuid4()),
        tenant_id=user_id,
        kind="plan_grant" if plan_changed else "credit_topup",
        status="posted",
        amount_cents=total_add,
        reserved_cents=0,
        balance_after_cents=new_balance,
        note=note,
        created_by=created_by,
    ))
    await db.commit()
    synced = await sync_balance(user_id, new_balance)
    if not synced:
        logger.warning(
            "Plan grant committed; Redis mirror sync failed: tenant=%s balance=%s¢",
            user_id,
            new_balance,
        )
    logger.info("Plan grant: tenant=%s plan=%s +%s¢ (by=%s)", user_id, plan, total_add, created_by)
    return {
        "plan": plan,
        "balance_cents": new_balance,
        "balance_dollars": round(new_balance / 100, 2),
        "currency": "usd",
    }


async def grant_credit(
    user_id: str,
    amount_cents: int,
    note: str | None,
    created_by: str | None,
    db: AsyncSession,
    *,
    idempotency_key: str | None = None,
) -> dict:
    """Add AI credit without changing the tenant's plan.

    Unlike the legacy ``grant_plan`` flow this works for free-trial and
    enterprise tenants too. The wallet row is locked, the ledger row and the
    balance move in one transaction, and an optional idempotency key makes a
    double-click or a retried request harmless.
    """
    from ..users.models import User
    from .budget import sync_balance
    from .ledger import ensure_ledger_initialized

    amount = int(amount_cents or 0)
    if amount <= 0:
        raise ValueError("Credit amount must be greater than zero.")
    if amount > 1_000_000:
        raise ValueError("Credit amount exceeds the per-grant limit.")

    if idempotency_key:
        existing = (
            await db.execute(
                select(BillingEvent).where(
                    BillingEvent.tenant_id == user_id,
                    BillingEvent.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            user = await db.get(User, user_id)
            if user is None:
                raise ValueError("Tenant not found.")
            return {
                "plan": user.plan or "free",
                "balance_cents": int(user.ai_credit_cents or 0),
                "balance_dollars": round(int(user.ai_credit_cents or 0) / 100, 2),
                "currency": "usd",
                "granted_cents": 0,
                "duplicate": True,
            }

    user = (
        await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise ValueError("Tenant not found.")

    before = int(await ensure_ledger_initialized(user_id, db))
    new_balance = before + amount
    user.ai_credit_cents = new_balance
    db.add(
        BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=user_id,
            kind="credit_topup",
            status="posted",
            amount_cents=amount,
            reserved_cents=0,
            balance_after_cents=new_balance,
            note=note,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request with the same idempotency key won the unique
        # index. The grant already exists; report the current wallet.
        await db.rollback()
        user = await db.get(User, user_id)
        if user is None:
            raise ValueError("Tenant not found.")
        return {
            "plan": user.plan or "free",
            "balance_cents": int(user.ai_credit_cents or 0),
            "balance_dollars": round(int(user.ai_credit_cents or 0) / 100, 2),
            "currency": "usd",
            "granted_cents": 0,
            "duplicate": True,
        }

    synced = await sync_balance(user_id, new_balance)
    if not synced:
        logger.warning(
            "Credit top-up committed; Redis mirror sync failed: tenant=%s balance=%s¢",
            user_id,
            new_balance,
        )
    logger.info("Credit top-up: tenant=%s +%s¢ (by=%s)", user_id, amount, created_by)
    return {
        "plan": user.plan or "free",
        "balance_cents": new_balance,
        "balance_dollars": round(new_balance / 100, 2),
        "currency": "usd",
        "granted_cents": amount,
        "duplicate": False,
    }
