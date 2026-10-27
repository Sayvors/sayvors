"""Plan entitlements — resolves a tenant's effective plan and enforces limits.

The wallet (billing/ledger.py) is the source of truth for *credit balance*.
This module is the source of truth for *what a tenant is allowed to do*:
which features are enabled and which numeric caps apply.

Effective plan = base subscription plan + any active admin/promo override
(granted_until in the future). When an override expires, the tenant
silently drops to the base plan's limits — no code deploy required. This
is what makes time-limited promos (e.g. "free Pro for early adopters")
safe to run and to revoke.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Plan, TenantSubscription

logger = logging.getLogger(__name__)


class EntitlementDenied(Exception):
    """Raised when a tenant's effective plan lacks a required feature or quota."""


@dataclass
class Entitlements:
    plan_slug: str
    plan_name: str
    status: str
    # Numeric caps (None = unlimited).
    max_channels: int | None
    max_messages_per_month: int | None
    included_credit_cents: int
    # Feature flags.
    features: dict[str, bool] = field(default_factory=dict)
    # Promo override state.
    granted_by: str | None = None
    granted_until: datetime | None = None
    promo_active: bool = False

    def has_feature(self, key: str) -> bool:
        return bool(self.features.get(key, False))

    def channel_quota_ok(self, current_count: int) -> bool:
        if self.max_channels is None:
            return True
        return current_count < self.max_channels

    def message_quota_ok(self, used_this_month: int) -> bool:
        if self.max_messages_per_month is None:
            return True
        return used_this_month < self.max_messages_per_month


async def get_effective_plan(tenant_id: str, db: AsyncSession) -> tuple[Plan, str, str | None, datetime | None]:
    """Resolve (plan, status, granted_by, granted_until) for a tenant.

    Falls back to the free-trial plan if no subscription exists.
    """
    sub = (
        await db.execute(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    granted_by = None
    granted_until = None
    status = "active"

    if sub is not None:
        status = sub.status
        granted_by = sub.granted_by
        granted_until = sub.granted_until
        # Promo override: if granted_until is in the future, use the granted plan.
        if granted_until is not None and granted_until > now:
            plan = await db.get(Plan, sub.plan_id)
            if plan is not None and plan.is_active:
                return plan, status, granted_by, granted_until
        # Otherwise use the base plan.
        plan = await db.get(Plan, sub.plan_id)
        if plan is not None and plan.is_active:
            return plan, status, granted_by, granted_until

    # Fallback: free-trial plan.
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial", Plan.is_active.is_(True)))
    ).scalar_one_or_none()
    if plan is None:
        plan = (await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))).scalar_one_or_none()
    if plan is None:
        raise RuntimeError("No active plan found — seed the plans table.")
    return plan, "active", None, None


async def get_entitlements(tenant_id: str, db: AsyncSession) -> Entitlements:
    plan, status, granted_by, granted_until = await get_effective_plan(tenant_id, db)
    now = datetime.now(timezone.utc)
    promo_active = granted_until is not None and granted_until > now
    return Entitlements(
        plan_slug=plan.slug,
        plan_name=plan.name,
        status=status,
        max_channels=plan.max_channels,
        max_messages_per_month=plan.max_messages_per_month,
        included_credit_cents=plan.included_credit_cents,
        features=plan.features or {},
        granted_by=granted_by,
        granted_until=granted_until,
        promo_active=promo_active,
    )


async def count_messages_this_month(tenant_id: str, db: AsyncSession) -> int:
    """Count outbound messages sent by this tenant in the current calendar month."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from ...channels.models import Channel, ChannelMessage

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    channel_ids = (
        await db.execute(select(Channel.id).where(Channel.user_id == tenant_id))
    ).scalars().all()
    if not channel_ids:
        return 0
    result = await db.execute(
        select(func.count()).select_from(ChannelMessage).where(
            ChannelMessage.channel_id.in_(channel_ids),
            ChannelMessage.direction == "outbound",
            ChannelMessage.created_at >= month_start,
        )
    )
    return int(result.scalar() or 0)


async def check_feature(tenant_id: str, feature: str) -> None:
    """Raise EntitlementDenied if the tenant's effective plan lacks `feature`.

    Opens its own DB session so callers (e.g. the LLM gateway) don't need
    to thread one through. Fail-closed: a DB error denies rather than
    allowing free usage.
    """
    from ...database import async_session

    async with async_session() as db:
        ent = await get_entitlements(tenant_id, db)
        if not ent.has_feature(feature):
            raise EntitlementDenied(
                f"Feature '{feature}' is not included in plan '{ent.plan_slug}'."
            )
