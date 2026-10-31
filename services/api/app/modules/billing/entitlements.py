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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Plan, TenantSubscription

logger = logging.getLogger(__name__)

# Overridable in tests (defaults to the production session factory).
_session_factory = None


def _get_session_factory():
    if _session_factory is not None:
        return _session_factory
    from ...database import async_session

    return async_session


class EntitlementDenied(Exception):
    """Raised when a tenant's effective plan lacks a required feature or quota.

    Carries the feature key (or "quota") so the API layer can attach a
    machine-readable header — the dashboard shows an upgrade prompt instead
    of a bare 403.
    """

    def __init__(self, message: str, feature: str | None = None):
        super().__init__(message)
        self.feature = feature


#: Response header marking a 403/429 as a plan-limit denial rather than a
#: permission or auth failure. Value is the feature key, or "quota".
ENTITLEMENT_DENIED_HEADER = "X-Entitlement-Denied"


def entitlement_403(detail: str, feature: str | None = None):
    """Build a 403 that the dashboard renders as an upgrade prompt.

    Use this (instead of a bare HTTPException) for every plan/feature gate
    so tenants always get the same "this is premium" path.
    """
    from fastapi import HTTPException

    return HTTPException(
        status_code=403,
        detail=detail,
        headers={ENTITLEMENT_DENIED_HEADER: feature or "plan"},
    )


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
    # The plan's raw baseline before the tenant override is applied.
    plan_features: dict[str, bool] = field(default_factory=dict)
    # The per-tenant override keys that produced `features` (empty = inherit).
    features_override: dict[str, bool] = field(default_factory=dict)
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


def merge_feature_override(
    plan_features: dict | None, override: dict | None
) -> dict[str, bool]:
    """Merge per-tenant overrides over the plan baseline.

    Override keys win per key (True forces a feature on, False forces it
    off); absent keys inherit the plan. Only override keys are checked
    against the catalog: a typo can then never enable something unknown,
    while a pre-catalog key already stored on a plan keeps working exactly
    as it did before overrides existed.
    """
    from .features import FEATURE_KEYS

    merged: dict[str, bool] = {k: bool(v) for k, v in (plan_features or {}).items()}
    for k, v in (override or {}).items():
        if k in FEATURE_KEYS:
            merged[k] = bool(v)
    return merged


async def get_effective_plan(tenant_id: str, db: AsyncSession) -> tuple[Plan, str, str | None, datetime | None, dict]:
    """Resolve (plan, status, granted_by, granted_until, features_override).

    Falls back to the free-trial plan if no subscription exists (override is
    then empty — there is no row to carry one).
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
                return plan, status, granted_by, granted_until, dict(sub.features_override or {})
        # Otherwise use the base plan.
        plan = await db.get(Plan, sub.plan_id)
        if plan is not None and plan.is_active:
            return plan, status, granted_by, granted_until, dict(sub.features_override or {})

    # Fallback: free-trial plan.
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial", Plan.is_active.is_(True)))
    ).scalar_one_or_none()
    if plan is None:
        plan = (await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))).scalar_one_or_none()
    if plan is None:
        raise RuntimeError("No active plan found — seed the plans table.")
    return plan, "active", None, None, {}


async def get_entitlements(tenant_id: str, db: AsyncSession) -> Entitlements:
    plan, status, granted_by, granted_until, override = await get_effective_plan(tenant_id, db)
    now = datetime.now(timezone.utc)
    promo_active = granted_until is not None and granted_until > now
    return Entitlements(
        plan_slug=plan.slug,
        plan_name=plan.name,
        status=status,
        max_channels=plan.max_channels,
        max_messages_per_month=plan.max_messages_per_month,
        included_credit_cents=plan.included_credit_cents,
        features=merge_feature_override(plan.features, override),
        plan_features={k: bool(v) for k, v in (plan.features or {}).items()},
        features_override=override,
        granted_by=granted_by,
        granted_until=granted_until,
        promo_active=promo_active,
    )


async def count_messages_this_month(tenant_id: str, db: AsyncSession) -> int:
    """Count outbound messages sent by this tenant in the current calendar month."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from ..channels.models import Channel, ChannelMessage

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
    factory = _get_session_factory()
    async with factory() as db:
        ent = await get_entitlements(tenant_id, db)
        if not ent.has_feature(feature):
            raise EntitlementDenied(
                f"Feature '{feature}' is not included in plan '{ent.plan_slug}'.",
                feature=feature,
            )
