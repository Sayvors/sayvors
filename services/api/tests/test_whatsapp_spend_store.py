"""Daily WhatsApp spend facts are dimension-complete and rolling-upserted."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select


def _point(**changes):
    point = {
        "spend_date": date(2026, 11, 1), "phone": "966500000001",
        "country": "SA", "pricing_category": "UTILITY",
        "pricing_type": "REGULAR", "tier": "0:750000",
        "volume": 2, "cost": Decimal("4.60"), "cost_status": "available",
    }
    point.update(changes)
    return point


def _result(*points, **changes):
    result = {
        "points": list(points), "currency": "SAR",
        "funding_mode": "direct_client", "waba_timezone": "Asia/Riyadh",
        "messaging_account_id": "ma-1",
    }
    result.update(changes)
    return result


@pytest.mark.asyncio
async def test_upsert_replaces_rolling_adjustments_without_duplicates(db):
    from app.modules.channels.meta.spend_models import WhatsAppSpendDaily
    from app.modules.channels.meta.spend_store import upsert_spend_result

    await upsert_spend_result(db, "tenant-1", "waba-1", _result(_point()))
    await upsert_spend_result(
        db, "tenant-1", "waba-1",
        _result(_point(volume=3, cost=Decimal("6.90"))),
    )
    rows = (await db.execute(select(WhatsAppSpendDaily))).scalars().all()
    assert len(rows) == 1
    assert rows[0].volume == 3
    assert rows[0].cost == Decimal("6.900000")
    assert rows[0].currency == "SAR"
    assert rows[0].funding_mode == "direct_client"
    assert rows[0].waba_timezone == "Asia/Riyadh"
    assert rows[0].messaging_account_id == "ma-1"


@pytest.mark.asyncio
async def test_each_pricing_dimension_is_part_of_fact_identity(db):
    from app.modules.channels.meta.spend_models import WhatsAppSpendDaily
    from app.modules.channels.meta.spend_store import attribution_hash, upsert_spend_result

    points = [
        _point(),
        _point(tier="750001:MAX"),
        _point(phone="966500000002"),
        _point(country="AE"),
        _point(pricing_category="MARKETING"),
        _point(pricing_type="FREE_CUSTOMER_SERVICE"),
    ]
    hashes = {attribution_hash("waba-1", p) for p in points}
    assert len(hashes) == len(points)
    await upsert_spend_result(db, "tenant-1", "waba-1", _result(*points))
    rows = (await db.execute(select(WhatsAppSpendDaily))).scalars().all()
    assert len(rows) == len(points)


@pytest.mark.asyncio
async def test_unavailable_cost_clears_previous_cost_and_is_not_zero(db):
    from app.modules.channels.meta.spend_models import WhatsAppSpendDaily
    from app.modules.channels.meta.spend_store import upsert_spend_result

    await upsert_spend_result(db, "tenant-1", "waba-1", _result(_point()))
    await upsert_spend_result(
        db, "tenant-1", "waba-1",
        _result(_point(cost=None, cost_status="unavailable"), funding_mode="shared_credit_line"),
    )
    row = (await db.execute(select(WhatsAppSpendDaily))).scalar_one()
    assert row.cost is None
    assert row.cost_status == "unavailable"
    assert row.funding_mode == "shared_credit_line"
