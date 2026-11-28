"""Tenant/admin read models for WhatsApp usage and approximate Meta spend."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import case, func, or_, select

from ...billing.entitlements import get_entitlements
from .spend_models import WhatsAppMonthlyUsage, WhatsAppSpendDaily


def validate_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("end must be on or after start")
    if (end - start).days > 365:
        raise ValueError("date range cannot exceed 366 days")


def _filters(start: date, end: date, tenant_id: str | None = None, waba_id: str | None = None):
    conditions = [WhatsAppSpendDaily.spend_date.between(start, end)]
    if tenant_id:
        conditions.append(WhatsAppSpendDaily.tenant_id == tenant_id)
    if waba_id:
        conditions.append(WhatsAppSpendDaily.waba_id == waba_id)
    return conditions


def _total(row) -> dict:
    return {
        "currency": row.currency,
        "funding_mode": row.funding_mode,
        "approx_cost": float(row.cost) if row.cost is not None else None,
        "volume": int(row.volume or 0),
        "unavailable_volume": int(row.unavailable_volume or 0),
    }


async def tenant_usage(db, tenant_id: str, *, start: date, end: date) -> dict:
    validate_range(start, end)
    conditions = _filters(start, end, tenant_id=tenant_id)
    totals = (
        await db.execute(
            select(
                WhatsAppSpendDaily.currency,
                WhatsAppSpendDaily.funding_mode,
                func.sum(WhatsAppSpendDaily.volume).label("volume"),
                func.sum(case(
                    (or_(
                        WhatsAppSpendDaily.cost_status == "unavailable",
                        WhatsAppSpendDaily.cost.is_(None),
                    ), WhatsAppSpendDaily.volume),
                    else_=0,
                )).label("unavailable_volume"),
                func.sum(WhatsAppSpendDaily.cost).label("cost"),
                func.max(WhatsAppSpendDaily.fetched_at).label("last_sync_at"),
            )
            .where(*conditions)
            .group_by(WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode)
            .order_by(WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode)
        )
    ).all()
    breakdown_rows = (
        await db.execute(
            select(WhatsAppSpendDaily)
            .where(*conditions)
            .order_by(WhatsAppSpendDaily.spend_date.desc(), WhatsAppSpendDaily.waba_id)
            .limit(200)
        )
    ).scalars().all()
    breakdowns = [{
        "tenant_id": row.tenant_id,
        "date": row.spend_date.isoformat(),
        "waba_id": row.waba_id,
        "messaging_account_id": row.messaging_account_id,
        "phone": row.phone,
        "country": row.country,
        "pricing_category": row.pricing_category,
        "pricing_type": row.pricing_type,
        "tier": row.tier,
        "volume": row.volume,
        "approx_cost": float(row.cost) if row.cost is not None else None,
        "currency": row.currency,
        "cost_status": row.cost_status,
        "funding_mode": row.funding_mode,
        "waba_timezone": row.waba_timezone,
    } for row in breakdown_rows]
    month = datetime.now(timezone.utc).replace(day=1).date()
    usage = (
        await db.execute(
            select(WhatsAppMonthlyUsage.used_count).where(
                WhatsAppMonthlyUsage.tenant_id == tenant_id,
                WhatsAppMonthlyUsage.month == month,
            )
        )
    ).scalar_one_or_none()
    ent = await get_entitlements(tenant_id, db)
    used = int(usage or 0)
    return {
        "channel": "whatsapp",
        "month": month.isoformat(),
        "used": used,
        "limit": ent.max_messages_per_month,
        "remaining": None if ent.max_messages_per_month is None else max(0, ent.max_messages_per_month - used),
        "last_sync_at": max((row.last_sync_at for row in totals), default=None),
        "totals": [_total(row) for row in totals],
        "breakdowns": breakdowns,
    }


async def admin_spend(
    db, *, start: date, end: date,
    tenant_id: str | None = None, waba_id: str | None = None,
) -> dict:
    validate_range(start, end)
    conditions = _filters(start, end, tenant_id=tenant_id, waba_id=waba_id)
    rows = (
        await db.execute(
            select(
                WhatsAppSpendDaily.tenant_id,
                WhatsAppSpendDaily.waba_id,
                WhatsAppSpendDaily.messaging_account_id,
                WhatsAppSpendDaily.currency,
                WhatsAppSpendDaily.funding_mode,
                func.sum(WhatsAppSpendDaily.volume).label("volume"),
                func.sum(case(
                    (or_(
                        WhatsAppSpendDaily.cost_status == "unavailable",
                        WhatsAppSpendDaily.cost.is_(None),
                    ), WhatsAppSpendDaily.volume),
                    else_=0,
                )).label("unavailable_volume"),
                func.sum(WhatsAppSpendDaily.cost).label("cost"),
                func.max(WhatsAppSpendDaily.fetched_at).label("last_sync_at"),
            )
            .where(*conditions)
            .group_by(
                WhatsAppSpendDaily.tenant_id, WhatsAppSpendDaily.waba_id,
                WhatsAppSpendDaily.messaging_account_id,
                WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode,
            )
            .order_by(WhatsAppSpendDaily.tenant_id, WhatsAppSpendDaily.waba_id)
            .limit(1000)
        )
    ).all()
    items = []
    cogs: dict[str, dict] = {}
    for row in rows:
        total = _total(row)
        items.append({
            "tenant_id": row.tenant_id,
            "waba_id": row.waba_id,
            "messaging_account_id": row.messaging_account_id,
            "last_sync_at": row.last_sync_at,
            **total,
        })
        if row.funding_mode == "platform_liable":
            current = cogs.setdefault(row.currency, {
                "currency": row.currency, "approx_cost": 0.0, "volume": 0,
            })
            current["approx_cost"] += total["approx_cost"] or 0.0
            current["volume"] += total["volume"]
    return {
        "items": items,
        # Client-direct and shared-credit-line spend is never Sayvors COGS.
        "cogs": [cogs[key] for key in sorted(cogs)],
    }
