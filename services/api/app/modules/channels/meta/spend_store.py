"""Idempotent storage and aggregation for WhatsApp spend attribution."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .spend_models import WhatsAppSpendDaily


def attribution_hash(waba_id: str, point: dict) -> str:
    """Hash every identity dimension, including nullable phone/tier values."""
    identity = [
        waba_id,
        point.get("messaging_account_id"),
        point.get("spend_date"),
        point.get("phone"),
        point.get("country"),
        point.get("pricing_category"),
        point.get("pricing_type"),
        point.get("tier"),
    ]
    canonical = json.dumps(identity, ensure_ascii=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def upsert_spend_result(db, tenant_id: str, waba_id: str, result: dict) -> int:
    """Replace rolling Meta facts in place; retries never add duplicate spend."""
    written = 0
    for point in result.get("points") or []:
        values = {
            **point,
            "messaging_account_id": point.get("messaging_account_id") or result.get("messaging_account_id"),
            "currency": result.get("currency"),
            "funding_mode": result.get("funding_mode") or "unknown",
            "waba_timezone": result.get("waba_timezone"),
            "source": "pricing_analytics",
        }
        values["attribution_hash"] = attribution_hash(waba_id, values)
        values["cost"] = Decimal(str(values["cost"])) if values.get("cost") is not None else None
        try:
            async with db.begin_nested():
                existing = (
                    await db.execute(
                        select(WhatsAppSpendDaily).where(
                            WhatsAppSpendDaily.tenant_id == tenant_id,
                            WhatsAppSpendDaily.waba_id == waba_id,
                            WhatsAppSpendDaily.spend_date == values["spend_date"],
                            WhatsAppSpendDaily.attribution_hash == values["attribution_hash"],
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    db.add(WhatsAppSpendDaily(tenant_id=tenant_id, waba_id=waba_id, **values))
                else:
                    for key, value in values.items():
                        setattr(existing, key, value)
                await db.flush()
        except IntegrityError:
            # Another worker won the same fact insert. Its committed row is the
            # update target; the savepoint rollback kept this batch usable.
            existing = (
                await db.execute(
                    select(WhatsAppSpendDaily).where(
                        WhatsAppSpendDaily.tenant_id == tenant_id,
                        WhatsAppSpendDaily.waba_id == waba_id,
                        WhatsAppSpendDaily.spend_date == values["spend_date"],
                        WhatsAppSpendDaily.attribution_hash == values["attribution_hash"],
                    )
                )
            ).scalar_one()
            for key, value in values.items():
                setattr(existing, key, value)
        written += 1
    await db.commit()
    return written
