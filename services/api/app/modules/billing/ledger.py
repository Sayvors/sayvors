"""Durable AI-credit ledger: reserve, settle, reaper, cutover, reconcile.

The wallet is ``users.ai_credit_cents``. Every mutation locks that row, so two
workers cannot spend the last cents twice. ``billing_events`` records the
movement and is the idempotency boundary:

* reserve inserts one ``ai_usage`` row with ``status=pending``;
* settle changes that same row to ``settled`` or ``released``;
* the reaper changes an abandoned row to ``expired`` and refunds the hold;
* a late settle reverses an expiry refund and charges the real cost.

PostgreSQL is the source of truth. Redis is updated only after commit, through
``budget.sync_balance``, and its failure never changes a ledger result.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .budget import RESERVE_CENTS, BudgetExhausted, BudgetUnavailable
from .models import BillingEvent

logger = logging.getLogger(__name__)

# How long a provider request may hold credit before the reaper assumes the
# process died. LLM calls have a much shorter hard deadline; this is deliberately
# generous so a slow stream is not refunded mid-flight.
HOLD_TTL_SECONDS = 15 * 60

# Reaper cadence and per-pass bound. The bound keeps one pass from holding a
# transaction open while a large crash backlog drains.
REAPER_INTERVAL_SECONDS = 60
REAPER_BATCH = 100

OPENING_KEY_PREFIX = "ledger-opening:"

# Overridable in tests (defaults to the production session factory).
_session_factory = None


def _get_session_factory():
    if _session_factory is not None:
        return _session_factory
    from ...database import async_session

    return async_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes despite DateTime(timezone=True)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Reservation:
    """One successful hold. Pass this to settle; do not rebuild it by hand."""

    id: str
    tenant_id: str
    amount_cents: int


@dataclass(frozen=True)
class SettleResult:
    """The terminal state recorded for a hold."""

    ledger_id: str
    status: str
    actual_cents: int
    balance_after_cents: int


class UnsafeLedgerBootstrap(Exception):
    """The legacy window predates retention and may overstate the wallet."""

    def __init__(self, tenant_id: str, preview: dict[str, Any]):
        self.tenant_id = tenant_id
        self.preview = preview
        super().__init__(
            preview.get("warning")
            or "Opening balance is not reliable; pass force=true to apply it."
        )


def _opening_key(tenant_id: str) -> str:
    return f"{OPENING_KEY_PREFIX}{tenant_id}"


async def _lock_user(db: AsyncSession, tenant_id: str):
    from ..users.models import User

    user = (
        await db.execute(select(User).where(User.id == tenant_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise ValueError("Tenant not found.")
    return user


async def _opening_row(db: AsyncSession, tenant_id: str) -> BillingEvent | None:
    return (
        await db.execute(
            select(BillingEvent).where(
                BillingEvent.tenant_id == tenant_id,
                BillingEvent.idempotency_key == _opening_key(tenant_id),
            )
        )
    ).scalar_one_or_none()


async def ensure_ledger_initialized(
    tenant_id: str,
    db: AsyncSession,
    *,
    allow_unreliable: bool = True,
    force: bool = False,
    _return_created: bool = False,
) -> int | tuple[int, bool]:
    """Create the one-time opening balance and return the current wallet.

    Existing tenants have grants and metered spend but no ledger holds. This
    writes one ``balance_resync`` baseline with the legacy computed balance and
    sets ``users.ai_credit_cents`` in the same transaction. The unique
    ``ledger-opening:<tenant>`` key makes a retry a no-op.

    The caller owns the commit. It must already hold (or be willing to take)
    the user row lock; taking it here is safe because it is the same row.

    ``allow_unreliable=False`` raises :class:`UnsafeLedgerBootstrap` when the
    computed window predates usage retention. The backfill script uses that to
    require an explicit ``--force``.
    """
    user = await _lock_user(db, tenant_id)
    existing = await _opening_row(db, tenant_id)
    if existing is not None:
        balance = int(user.ai_credit_cents or 0)
        return (balance, False) if _return_created else balance

    from .wallet import compute_balance

    preview = await compute_balance(tenant_id, db)
    if preview["warning"] and not allow_unreliable and not force:
        raise UnsafeLedgerBootstrap(tenant_id, preview)

    balance = max(0, int(preview["balance_cents"]))
    db.add(
        BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            kind="balance_resync",
            status="posted",
            amount_cents=0,
            balance_after_cents=balance,
            idempotency_key=_opening_key(tenant_id),
            note=(
                "Ledger opening balance (one-time cutover; grants and spend "
                "before this row are summarized here)."
            ),
            created_by="system",
        )
    )
    user.ai_credit_cents = balance
    await db.flush()
    logger.info(
        "Credit ledger opened for %s: %s cents (reliable=%s)",
        tenant_id,
        balance,
        preview["reliable"],
    )
    return (balance, True) if _return_created else balance


async def _mirror(tenant_id: str, balance: int) -> None:
    """Update the Redis mirror. Never raises and never affects the DB result."""
    from .budget import sync_balance

    await sync_balance(tenant_id, balance)


async def reserve(
    tenant_id: str,
    cents: int = RESERVE_CENTS,
    *,
    model_id: str | None = None,
    purpose: str | None = None,
    idempotency_key: str | None = None,
) -> Reservation:
    """Atomically hold ``cents`` from the durable wallet.

    Raises :class:`BudgetExhausted` when the balance cannot cover the hold and
    :class:`BudgetUnavailable` when the DB cannot be reached. A DB failure is
    fail-closed: the provider must not run unmetered.
    """
    amount = int(cents)
    if amount <= 0:
        return Reservation(id="", tenant_id=tenant_id, amount_cents=0)

    try:
        factory = _get_session_factory()
        async with factory() as db:
            user = await _lock_user(db, tenant_id)
            balance, created = await ensure_ledger_initialized(
                tenant_id, db, allow_unreliable=True, _return_created=True
            )

            if idempotency_key:
                existing = (
                    await db.execute(
                        select(BillingEvent).where(
                            BillingEvent.tenant_id == tenant_id,
                            BillingEvent.idempotency_key == idempotency_key,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    if existing.status != "pending":
                        raise ValueError(
                            "Idempotency key is already finalized for another call."
                        )
                    if created:
                        await db.commit()
                    return Reservation(
                        id=existing.id,
                        tenant_id=tenant_id,
                        amount_cents=int(existing.reserved_cents or 0),
                    )

            if balance < amount:
                # Persist a newly created opening row so the next request does
                # not redo the historical calculation, then deny the call.
                if created:
                    await db.commit()
                else:
                    await db.rollback()
                raise BudgetExhausted(tenant_id)

            new_balance = balance - amount
            hold = BillingEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                kind="ai_usage",
                status="pending",
                amount_cents=0,
                reserved_cents=amount,
                balance_after_cents=new_balance,
                model_id=model_id,
                idempotency_key=idempotency_key,
                expires_at=_now() + timedelta(seconds=HOLD_TTL_SECONDS),
                note=(purpose or "")[:500] or None,
                created_by="system",
            )
            user.ai_credit_cents = new_balance
            db.add(hold)
            await db.commit()
            reservation = Reservation(
                id=hold.id, tenant_id=tenant_id, amount_cents=amount
            )
        await _mirror(tenant_id, new_balance)
        return reservation
    except BudgetExhausted:
        raise
    except ValueError:
        raise
    except SQLAlchemyError as e:
        logger.exception("Credit reserve DB failure for %s", tenant_id)
        raise BudgetUnavailable(tenant_id, "database error") from e
    except Exception:
        logger.exception("Credit reserve failed for %s", tenant_id)
        raise


def _result_from_hold(hold: BillingEvent) -> SettleResult:
    return SettleResult(
        ledger_id=hold.id,
        status=hold.status,
        actual_cents=max(0, -int(hold.amount_cents or 0)),
        balance_after_cents=int(hold.balance_after_cents or 0),
    )


async def settle(
    reservation: Reservation | str,
    actual_cents: int,
    *,
    tenant_id: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> SettleResult | None:
    """Finalize a hold exactly once. Never raises into the provider path.

    A terminal hold returns its recorded result, so a retried settle cannot
    double-charge. An expired hold has already been refunded; a late settle
    reverses that refund and charges the real cost.
    """
    hold_id = reservation.id if isinstance(reservation, Reservation) else reservation
    if not hold_id:
        return None
    expected_tenant = reservation.tenant_id if isinstance(reservation, Reservation) else tenant_id
    actual = max(0, int(actual_cents))

    try:
        factory = _get_session_factory()
        async with factory() as db:
            hold = (
                await db.execute(
                    select(BillingEvent)
                    .where(BillingEvent.id == hold_id, BillingEvent.kind == "ai_usage")
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if hold is None:
                logger.error("Credit settle: hold %s not found", hold_id)
                return None
            if expected_tenant and hold.tenant_id != expected_tenant:
                logger.error(
                    "Credit settle: hold %s belongs to %s, not %s",
                    hold_id,
                    hold.tenant_id,
                    expected_tenant,
                )
                return None

            if hold.status in ("settled", "released"):
                return _result_from_hold(hold)
            if hold.status == "expired":
                if actual == 0:
                    return _result_from_hold(hold)
                # The reaper refunded reserved_cents; charge the real cost.
                user = await _lock_user(db, hold.tenant_id)
                new_balance = int(user.ai_credit_cents or 0) - actual
                delta = -actual
            elif hold.status == "pending":
                user = await _lock_user(db, hold.tenant_id)
                reserved = int(hold.reserved_cents or 0)
                delta = reserved - actual
                new_balance = int(user.ai_credit_cents or 0) + delta
                if actual > reserved:
                    logger.warning(
                        "Credit settle overage: tenant=%s hold=%s reserved=%s actual=%s",
                        hold.tenant_id,
                        hold.id,
                        reserved,
                        actual,
                    )
            else:
                logger.error(
                    "Credit settle: hold %s has unknown status %r", hold.id, hold.status
                )
                return None

            user.ai_credit_cents = new_balance
            hold.status = "settled" if actual > 0 else "released"
            hold.amount_cents = -actual
            hold.balance_after_cents = new_balance
            hold.prompt_tokens = max(0, int(prompt_tokens))
            hold.completion_tokens = max(0, int(completion_tokens))
            hold.settled_at = _now()
            await db.commit()
            result = SettleResult(
                ledger_id=hold.id,
                status=hold.status,
                actual_cents=actual,
                balance_after_cents=new_balance,
            )
        await _mirror(hold.tenant_id, new_balance)
        return result
    except Exception as e:
        # The usage row carries ledger_id + cost, so the reaper can recover a
        # charge whose settle call died. Never break the provider response.
        logger.exception(
            "Credit settle failed for hold %s (usage row can recover it): %s",
            hold_id,
            e,
        )
        return None


async def _expire_one(hold_id: str) -> int:
    """Expire one hold under a row lock. Returns 1 when this pass changed it."""
    try:
        factory = _get_session_factory()
        async with factory() as db:
            hold = (
                await db.execute(
                    select(BillingEvent)
                    .where(BillingEvent.id == hold_id, BillingEvent.kind == "ai_usage")
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if hold is None or hold.status != "pending":
                return 0
            if hold.expires_at is not None and _aware(hold.expires_at) > _now():
                return 0
            user = await _lock_user(db, hold.tenant_id)
            new_balance = int(user.ai_credit_cents or 0) + int(hold.reserved_cents or 0)
            user.ai_credit_cents = new_balance
            hold.status = "expired"
            hold.amount_cents = 0
            hold.balance_after_cents = new_balance
            hold.settled_at = _now()
            await db.commit()
            tenant_id = hold.tenant_id
        await _mirror(tenant_id, new_balance)
        logger.warning(
            "Credit hold expired: tenant=%s hold=%s refunded=%s",
            tenant_id,
            hold_id,
            hold.reserved_cents,
        )
        return 1
    except Exception as e:
        logger.error("Credit hold expiry failed for %s: %s", hold_id, e)
        return 0


async def reconcile_usage_holds(limit: int = REAPER_BATCH) -> int:
    """Settle holds that already have a priced usage row.

    This is the recovery path for a process that died after the provider
    returned but before ``settle`` ran. It must happen before expiry so the
    real cost is not refunded.
    """
    from ..llm.models import LLMUsageEvent

    try:
        factory = _get_session_factory()
        async with factory() as db:
            rows = (
                await db.execute(
                    select(
                        BillingEvent.id,
                        BillingEvent.tenant_id,
                        BillingEvent.reserved_cents,
                        LLMUsageEvent.cost_cents,
                    )
                    .join(LLMUsageEvent, LLMUsageEvent.ledger_id == BillingEvent.id)
                    .where(
                        BillingEvent.kind == "ai_usage",
                        BillingEvent.status == "pending",
                        LLMUsageEvent.status.in_(("ok", "cancelled")),
                        LLMUsageEvent.cost_cents > 0,
                    )
                    .order_by(BillingEvent.expires_at)
                    .limit(limit)
                )
            ).all()
    except Exception as e:
        logger.error("Credit usage-hold scan failed: %s", e)
        return 0

    settled = 0
    seen: set[str] = set()
    for hold_id, tenant_id, reserved, cost in rows:
        if hold_id in seen:
            continue
        seen.add(hold_id)
        result = await settle(
            Reservation(
                id=hold_id,
                tenant_id=tenant_id,
                amount_cents=int(reserved or 0),
            ),
            int(cost or 0),
        )
        if result is not None and result.status == "settled":
            settled += 1
    if settled:
        logger.info("Credit reaper recovered %s settled usage hold(s)", settled)
    return settled


async def _expire_stale_only(limit: int = REAPER_BATCH) -> int:
    """Refund expired holds that have no priced usage row to settle."""
    try:
        factory = _get_session_factory()
        async with factory() as db:
            ids = (
                await db.execute(
                    select(BillingEvent.id)
                    .where(
                        BillingEvent.kind == "ai_usage",
                        BillingEvent.status == "pending",
                        BillingEvent.expires_at <= _now(),
                    )
                    .order_by(BillingEvent.expires_at)
                    .limit(limit)
                )
            ).scalars().all()
    except Exception as e:
        logger.error("Credit hold expiry scan failed: %s", e)
        return 0

    expired = 0
    for hold_id in ids:
        expired += await _expire_one(hold_id)
    if expired:
        logger.warning("Credit reaper expired %s stale hold(s)", expired)
    return expired


async def expire_stale_holds(limit: int = REAPER_BATCH) -> int:
    """Recover priced holds, then refund the remaining expired holds.

    Safe to run from multiple workers concurrently: every row is re-selected
    under ``FOR UPDATE`` and a terminal status is skipped.
    """
    recovered = await reconcile_usage_holds(limit)
    expired = await _expire_stale_only(limit)
    return recovered + expired


async def reap_once() -> dict[str, int]:
    """One reaper pass. The worker loop calls this every minute."""
    recovered = await reconcile_usage_holds()
    expired = await _expire_stale_only()
    return {"recovered": recovered, "expired": expired}


async def run_hold_reaper() -> None:
    """Background loop; jitter avoids every replica firing at once."""
    interval = max(10, REAPER_INTERVAL_SECONDS)
    await asyncio.sleep(random.uniform(0, min(10, interval)))
    while True:
        try:
            result = await reap_once()
            if result["recovered"] or result["expired"]:
                logger.info("Credit reaper: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Credit reaper pass failed: %s", e)
        await asyncio.sleep(interval)


async def reconcile_wallet(
    tenant_id: str,
    db: AsyncSession,
    *,
    dry_run: bool = True,
    note: str | None = None,
    created_by: str = "admin",
) -> dict[str, Any]:
    """Compare Redis with the DB wallet and optionally repair the cache.

    The target is always the DB balance. A caller cannot supply a balance. The
    audit row is written only when the cache is missing or differs, so a second
    apply with no drift does not create noise.
    """
    from .budget import get_cached_balance, sync_balance

    if dry_run:
        from ..users.models import User

        user = await db.get(User, tenant_id)
    else:
        user = await _lock_user(db, tenant_id)
    if user is None:
        raise ValueError("Tenant not found.")

    db_balance = int(user.ai_credit_cents or 0)
    redis_balance = await get_cached_balance(tenant_id)
    drift = redis_balance is None or redis_balance != db_balance
    result: dict[str, Any] = {
        "tenant_id": tenant_id,
        "applied": False,
        "balance_cents": db_balance,
        "db_balance_cents": db_balance,
        "redis_balance_cents": redis_balance,
        "previous_balance_cents": redis_balance,
        "delta_cents": (
            db_balance - redis_balance if redis_balance is not None else None
        ),
        "redis_synced": None,
        "reliable": True,
        "warning": None,
    }
    if dry_run:
        return result

    if drift:
        db.add(
            BillingEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                kind="balance_reconcile",
                status="posted",
                amount_cents=0,
                balance_after_cents=db_balance,
                note=(note or "Redis wallet mirror reconciled to the durable DB balance")[:500],
                created_by=created_by,
            )
        )
        await db.commit()
    result["applied"] = True
    result["redis_synced"] = (
        await sync_balance(tenant_id, db_balance) if drift else True
    )
    logger.info(
        "Wallet reconcile: tenant=%s db=%s redis=%s drift=%s synced=%s by=%s",
        tenant_id,
        db_balance,
        redis_balance,
        drift,
        result["redis_synced"],
        created_by,
    )
    return result
