"""Wallet reconciliation for the Redis AI-credit counter.

This is the bridge until ``llm_usage_events`` is replaced by a durable DB
spend ledger. The live balance is still the Redis counter in ``budget.py``;
when that key is missing (Redis restart, eviction, or the old 24h TTL), this
module rebuilds it from:

* credit grants/adjustments in ``billing_events``
* token spend in ``llm_usage_events``, priced with ``budget.cost_cents``

A ``balance_resync`` billing event is an audit-only baseline. Balance
calculations start at the latest baseline, so re-running a resync is
idempotent and does not count the adjustment as new credit.

Known limits: usage rows are pruned after ``USAGE_EVENT_RETENTION_DAYS`` and
historical calls are priced with the current ``TOKEN_PRICES`` table. If the
calculation window starts before the retention cut-off, the result is an
upper bound because old spend is gone; callers must mark it unreliable and
require an explicit ``force`` before writing one as a baseline. A price
change also makes an old window an estimate until a new baseline is written.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BillingEvent

logger = logging.getLogger(__name__)

# Event kinds that add (or subtract, for a negative adjustment) credit.
GRANT_KINDS = ("plan_grant", "credit_topup", "credit_adjust")
# Audit-only snapshot; never included in GRANT_KINDS.
BASELINE_KIND = "balance_resync"
VOICE_PURPOSE_PREFIX = "voice."


class UnsafeWalletResync(Exception):
    """The computed balance may be too high because old usage was pruned."""

    def __init__(self, preview: dict[str, Any]):
        self.preview = preview
        super().__init__(
            preview.get("warning")
            or "Wallet resync is not reliable; pass force=true to apply it."
        )


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes despite DateTime(timezone=True)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _retention_days() -> int:
    """Import lazily so billing does not pull in the retention module at boot."""
    from ..retention import USAGE_EVENT_RETENTION_DAYS

    return int(USAGE_EVENT_RETENTION_DAYS)


def _zero(tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "balance_cents": 0,
        "opening_cents": 0,
        "credits_cents": 0,
        "spent_cents": 0,
        "calls": 0,
        "window_started_at": None,
        "reliable": True,
        "warning": None,
    }


async def compute_balance(tenant_id: str, db: AsyncSession) -> dict[str, Any]:
    """Reconstruct a tenant's wallet from the audit + metering tables.

    This is intentionally exact per call: ``cost_cents`` rounds each call up
    to at least one cent, so summing tokens first would undercount.

    The caller owns the DB session. The usage scan is streamed in chunks so a
    cold wallet repair cannot load a tenant's entire history into memory.
    """
    from ..llm.models import LLMUsageEvent
    from .budget import cost_cents

    baseline = (
        await db.execute(
            select(BillingEvent)
            .where(
                BillingEvent.tenant_id == tenant_id,
                BillingEvent.kind == BASELINE_KIND,
                BillingEvent.balance_after_cents.is_not(None),
            )
            .order_by(BillingEvent.created_at.desc(), BillingEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if baseline is not None:
        window_started_at = _aware(baseline.created_at)
        opening_cents = max(0, int(baseline.balance_after_cents or 0))
    else:
        first_grant = (
            await db.execute(
                select(func.min(BillingEvent.created_at)).where(
                    BillingEvent.tenant_id == tenant_id,
                    BillingEvent.kind.in_(GRANT_KINDS),
                )
            )
        ).scalar_one()
        if first_grant is None:
            return _zero(tenant_id)
        window_started_at = _aware(first_grant)
        opening_cents = 0

    adjustment_query = select(
        func.coalesce(func.sum(BillingEvent.amount_cents), 0)
    ).where(
        BillingEvent.tenant_id == tenant_id,
        BillingEvent.kind.in_(GRANT_KINDS),
    )
    if baseline is not None:
        adjustment_query = adjustment_query.where(
            BillingEvent.created_at > baseline.created_at
        )
    credits_cents = int((await db.execute(adjustment_query)).scalar_one() or 0)

    spent_cents = 0
    calls = 0
    usage_filters = [
        LLMUsageEvent.tenant_id == tenant_id,
        LLMUsageEvent.status.in_(("ok", "cancelled")),
        or_(
            LLMUsageEvent.purpose.is_(None),
            ~LLMUsageEvent.purpose.like(VOICE_PURPOSE_PREFIX + "%"),
        ),
    ]
    # A baseline snapshot already includes everything up to its creation.
    # Strictly-greater avoids charging a row that was counted in the snapshot
    # when the timestamps coincide.
    if baseline is not None:
        usage_filters.append(LLMUsageEvent.created_at > baseline.created_at)
    else:
        usage_filters.append(LLMUsageEvent.created_at >= window_started_at)
    usage_query = (
        select(
            LLMUsageEvent.model_id,
            LLMUsageEvent.prompt_tokens,
            LLMUsageEvent.completion_tokens,
        )
        .where(*usage_filters)
        .order_by(LLMUsageEvent.created_at, LLMUsageEvent.id)
    )
    result = await db.stream(usage_query)
    try:
        async for row in result:
            model_id, prompt_tokens, completion_tokens = row
            spent_cents += cost_cents(
                model_id, int(prompt_tokens or 0), int(completion_tokens or 0)
            )
            calls += 1
    finally:
        await result.close()

    balance_cents = max(0, opening_cents + credits_cents - spent_cents)

    # The baseline is only trustworthy while the spend rows inside its window
    # still exist. If the window predates retention, old spend has been pruned
    # and the computed balance is an upper bound.
    age_days = (
        datetime.now(timezone.utc) - window_started_at
    ).total_seconds() / 86_400
    reliable = age_days <= _retention_days()
    warning = None
    if not reliable:
        warning = (
            "Usage events older than "
            f"{_retention_days()} days have been pruned; this balance is an "
            "upper bound. Apply with force=true only after checking the tenant."
        )

    return {
        "tenant_id": tenant_id,
        "balance_cents": balance_cents,
        "opening_cents": opening_cents,
        "credits_cents": credits_cents,
        "spent_cents": spent_cents,
        "calls": calls,
        "window_started_at": window_started_at.isoformat(),
        "reliable": reliable,
        "warning": warning,
    }


async def ensure_wallet_balance(tenant_id: str, db: AsyncSession) -> int:
    """Return the live balance, rebuilding the Redis key when it is missing.

    A missing key is common after a Redis restart. Returning the DB column is
    not safe: it is a grants-only figure and would hand back already-spent
    credits. Recompute from the event tables instead.
    """
    from .budget import get_balance, seed_balance

    live = await get_balance(tenant_id)
    if live is not None:
        return live

    preview = await compute_balance(tenant_id, db)
    if preview["warning"]:
        logger.warning(
            "AI wallet %s rehydrated from an unreliable window: %s",
            tenant_id,
            preview["warning"],
        )
    # SET NX: if another worker seeded while we were computing, use its value
    # rather than overwriting it with a possibly older snapshot.
    seeded = await seed_balance(tenant_id, preview["balance_cents"])
    if seeded:
        live = await get_balance(tenant_id)
        if live is not None:
            return live
    logger.info(
        "AI wallet %s rehydrated from DB: %s¢ (grants=%s, spend=%s, calls=%s)",
        tenant_id,
        preview["balance_cents"],
        preview["credits_cents"],
        preview["spent_cents"],
        preview["calls"],
    )
    return int(preview["balance_cents"])


async def resync_wallet(
    tenant_id: str,
    db: AsyncSession,
    *,
    dry_run: bool = True,
    force: bool = False,
    note: str | None = None,
    created_by: str = "admin",
) -> dict[str, Any]:
    """Preview or apply a wallet repair.

    Applying updates ``users.ai_credit_cents`` to the computed remaining
    balance, writes a ``balance_resync`` baseline, and overwrites Redis. The
    row lock serialises this against ``grant_plan`` so a top-up cannot race
    the repair and resurrect spent credits.
    """
    from ..users.models import User
    from .budget import get_balance, sync_balance

    if dry_run:
        user = await db.get(User, tenant_id)
    else:
        user = (
            await db.execute(
                select(User).where(User.id == tenant_id).with_for_update()
            )
        ).scalar_one_or_none()
    if user is None:
        raise ValueError("Tenant not found.")

    preview = await compute_balance(tenant_id, db)
    previous = await get_balance(tenant_id)
    opening_previous = previous if previous is not None else int(user.ai_credit_cents or 0)
    preview["previous_balance_cents"] = previous
    preview["delta_cents"] = int(preview["balance_cents"]) - opening_previous
    preview["applied"] = False
    preview["redis_synced"] = None

    if not preview["reliable"] and not force:
        raise UnsafeWalletResync(preview)

    if dry_run:
        return preview

    target = int(preview["balance_cents"])
    user.ai_credit_cents = target
    audit_note = note or "Wallet resync from grants and metered usage"
    if not preview["reliable"]:
        audit_note += " (forced; usage retention gap)"
    db.add(
        BillingEvent(
            tenant_id=tenant_id,
            kind=BASELINE_KIND,
            amount_cents=int(preview["delta_cents"]),
            balance_after_cents=target,
            note=audit_note,
            created_by=created_by,
        )
    )
    await db.commit()
    synced = await sync_balance(tenant_id, target)
    preview["applied"] = True
    preview["redis_synced"] = synced

    logger.info(
        "Wallet resync: tenant=%s target=%s¢ previous=%s delta=%s redis_synced=%s by=%s",
        tenant_id,
        target,
        previous,
        preview["delta_cents"],
        synced,
        created_by,
    )
    return preview
