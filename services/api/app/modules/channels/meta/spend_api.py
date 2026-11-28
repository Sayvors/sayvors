"""Frontend-contract DTOs for WhatsApp usage and approximate Meta spend."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select

from ...billing.entitlements import get_entitlements
from ...users.models import User
from .models import MetaAsset
from .spend_models import WhatsAppMonthlyUsage, WhatsAppSpendDaily


def _window(days: int):
    if days not in (30, 90, 365):
        raise ValueError("days must be 30, 90, or 365")
    end = datetime.now(timezone.utc).date()
    return end - timedelta(days=days - 1), end


def _funding(value: str | None) -> str:
    # Unknown liability is conservatively presented as client-direct so it can
    # never enter Sayvors-payable/COGS totals.
    return value if value in ("direct_client", "shared_credit_line", "platform_liable") else "direct_client"


def _availability(volume: int, unavailable: int) -> str:
    if volume <= 0:
        return "available"
    if unavailable >= volume:
        return "unavailable"
    return "partial" if unavailable else "available"


def _total(row) -> dict:
    volume = int(row.volume or 0)
    unavailable = int(row.unavailable_volume or 0)
    return {
        "funding_mode": _funding(row.funding_mode),
        "volume": volume,
        "approximate_cost": float(row.cost) if row.cost is not None else None,
        "currency": row.currency,
        "cost_availability": _availability(volume, unavailable),
        "last_meta_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
    }


def _aggregate_select():
    unavailable = case(
        (or_(
            WhatsAppSpendDaily.cost_status == "unavailable",
            WhatsAppSpendDaily.cost.is_(None),
        ), WhatsAppSpendDaily.volume),
        else_=0,
    )
    return (
        func.sum(WhatsAppSpendDaily.volume).label("volume"),
        func.sum(unavailable).label("unavailable_volume"),
        func.sum(WhatsAppSpendDaily.cost).label("cost"),
        func.max(WhatsAppSpendDaily.fetched_at).label("last_sync_at"),
    )


def _summary(totals: list[dict]) -> dict:
    if not totals:
        return {
            "approximate_cost": None, "currency": None,
            "cost_availability": "pending", "funding_mode": "direct_client",
            "last_meta_sync_at": None, "sync_status": "pending",
        }
    primary = max(totals, key=lambda row: row["volume"])
    availability = (
        "unavailable" if all(row["cost_availability"] == "unavailable" for row in totals)
        else "partial" if any(row["cost_availability"] != "available" for row in totals)
        else "available"
    )
    return {
        "approximate_cost": primary["approximate_cost"],
        "currency": primary["currency"],
        "cost_availability": availability,
        "funding_mode": primary["funding_mode"],
        "last_meta_sync_at": max(
            (row["last_meta_sync_at"] for row in totals if row["last_meta_sync_at"]),
            default=None,
        ),
        "sync_status": "synced",
    }


def _breakdown(rows, dimension: str, waba_names: dict[str, str]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for row in rows:
        value = getattr(row, dimension)
        key = (value, row.currency, row.funding_mode)
        item = grouped.setdefault(key, {
            "funding_mode": _funding(row.funding_mode), "volume": 0,
            "approximate_cost": None, "currency": row.currency,
            "unavailable": 0, "last_meta_sync_at": None,
        })
        item["volume"] += int(row.volume or 0)
        if row.cost is not None:
            item["approximate_cost"] = (item["approximate_cost"] or 0) + float(row.cost)
        if row.cost_status == "unavailable" or row.cost is None:
            item["unavailable"] += int(row.volume or 0)
        if row.fetched_at and (
            item["last_meta_sync_at"] is None or row.fetched_at > item["last_meta_sync_at"]
        ):
            item["last_meta_sync_at"] = row.fetched_at
    output = []
    for (value, _currency, _funding_mode), item in grouped.items():
        output.append({
            "funding_mode": item["funding_mode"],
            "volume": item["volume"],
            "approximate_cost": item["approximate_cost"],
            "currency": item["currency"],
            "cost_availability": _availability(item["volume"], item["unavailable"]),
            "last_meta_sync_at": item["last_meta_sync_at"].isoformat() if item["last_meta_sync_at"] else None,
            **(
                {"waba_id": value, "waba_name": waba_names.get(value)} if dimension == "waba_id"
                else {"phone": value} if dimension == "phone"
                else {"category": value}
            ),
        })
    return sorted(output, key=lambda row: row["volume"], reverse=True)[:200]


async def tenant_usage(
    db, tenant_id: str, *, days: int,
    include_phone_breakdown: bool = True,
) -> dict:
    start, end = _window(days)
    conditions = [
        WhatsAppSpendDaily.tenant_id == tenant_id,
        WhatsAppSpendDaily.spend_date.between(start, end),
    ]
    totals = (
        await db.execute(
            select(
                WhatsAppSpendDaily.currency,
                WhatsAppSpendDaily.funding_mode,
                *_aggregate_select(),
            )
            .where(*conditions)
            .group_by(WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode)
            .order_by(WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode)
        )
    ).all()
    total_dtos = [_total(row) for row in totals]
    rows = (
        await db.execute(
            select(WhatsAppSpendDaily)
            .where(*conditions)
            .order_by(WhatsAppSpendDaily.spend_date.desc(), WhatsAppSpendDaily.waba_id)
            .limit(5000)
        )
    ).scalars().all()
    waba_names = dict((await db.execute(
        select(MetaAsset.external_asset_id, MetaAsset.name).where(
            MetaAsset.tenant_id == tenant_id,
            MetaAsset.provider == "whatsapp",
            MetaAsset.asset_type == "waba",
        )
    )).all())
    month = datetime.now(timezone.utc).replace(day=1).date()
    used = int((await db.execute(
        select(WhatsAppMonthlyUsage.used_count).where(
            WhatsAppMonthlyUsage.tenant_id == tenant_id,
            WhatsAppMonthlyUsage.month == month,
        )
    )).scalar_one_or_none() or 0)
    ent = await get_entitlements(tenant_id, db)
    return {
        "used": used,
        "limit": ent.max_messages_per_month,
        "remaining": None if ent.max_messages_per_month is None else max(0, ent.max_messages_per_month - used),
        **_summary(total_dtos),
        "totals": total_dtos,
        "breakdowns": {
            "by_waba": _breakdown(rows, "waba_id", waba_names),
            "by_phone": _breakdown(rows, "phone", waba_names) if include_phone_breakdown else [],
            "by_category": _breakdown(rows, "pricing_category", waba_names),
        },
    }


async def admin_spend(
    db, *, days: int, tenant_id: str | None = None, waba_id: str | None = None,
) -> dict:
    start, end = _window(days)
    conditions = [WhatsAppSpendDaily.spend_date.between(start, end)]
    if tenant_id:
        conditions.append(WhatsAppSpendDaily.tenant_id == tenant_id)
    if waba_id:
        conditions.append(WhatsAppSpendDaily.waba_id == waba_id)
    total_rows = (
        await db.execute(
            select(
                WhatsAppSpendDaily.currency,
                WhatsAppSpendDaily.funding_mode,
                *_aggregate_select(),
            )
            .where(*conditions)
            .group_by(WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode)
            .order_by(WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode)
        )
    ).all()
    rows = (
        await db.execute(
            select(
                WhatsAppSpendDaily.tenant_id,
                User.first_name, User.last_name, User.business_name, User.email,
                WhatsAppSpendDaily.waba_id, MetaAsset.name.label("waba_name"),
                WhatsAppSpendDaily.currency, WhatsAppSpendDaily.funding_mode,
                *_aggregate_select(),
            )
            .join(User, User.id == WhatsAppSpendDaily.tenant_id)
            .outerjoin(
                MetaAsset,
                (MetaAsset.tenant_id == WhatsAppSpendDaily.tenant_id)
                & (MetaAsset.external_asset_id == WhatsAppSpendDaily.waba_id)
                & (MetaAsset.provider == "whatsapp")
                & (MetaAsset.asset_type == "waba"),
            )
            .where(*conditions)
            .group_by(
                WhatsAppSpendDaily.tenant_id, User.first_name, User.last_name,
                User.business_name, User.email, WhatsAppSpendDaily.waba_id,
                MetaAsset.name, WhatsAppSpendDaily.currency,
                WhatsAppSpendDaily.funding_mode,
            )
            .order_by(WhatsAppSpendDaily.tenant_id, WhatsAppSpendDaily.waba_id)
            .limit(1000)
        )
    ).all()
    items = []
    for row in rows:
        name = " ".join(part for part in (row.first_name, row.last_name) if part).strip()
        items.append({
            "tenant_id": row.tenant_id,
            "tenant_name": row.business_name or name or None,
            "tenant_email": row.email,
            "waba_id": row.waba_id,
            "waba_name": row.waba_name,
            "sync_status": "synced" if row.last_sync_at else "pending",
            **_total(row),
        })
    return {
        "days": days,
        "items": items,
        "total": len(items),
        "totals": [_total(row) for row in total_rows],
    }
