"""Bounded rolling Meta spend sync, retries, and WABA attribution."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.spend_models import WhatsAppSpendDaily


async def _waba(db, suffix, **metadata):
    uid = f"spend-{suffix}-{uuid.uuid4().hex[:6]}"
    conn = MetaConnection(
        id=f"conn-{uid}", tenant_id=uid, provider="whatsapp", status="active",
        access_token_encrypted="enc",
    )
    db.add(conn)
    await db.flush()
    asset = MetaAsset(
        id=f"waba-row-{uid}", tenant_id=uid, connection_id=conn.id,
        provider="whatsapp", asset_type="waba",
        external_asset_id=f"waba-{suffix}", active=True,
        asset_metadata=metadata,
    )
    db.add(asset)
    await db.commit()
    return asset


class _Adapter:
    def __init__(self, result=None, failures=0):
        self.result = result or {"points": [], "currency": "SAR"}
        self.failures = failures
        self.calls = []

    async def get_pricing_analytics(self, waba_id, token, *, start, end):
        self.calls.append((waba_id, start, end))
        if len(self.calls) <= self.failures:
            raise RuntimeError("temporary Meta outage")
        return self.result

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_sync_uses_rolling_seven_days_and_waba_metadata(db, monkeypatch):
    from app.modules.channels.meta import spend_worker

    asset = await _waba(
        db, "one", funding_mode="platform_liable", currency="SAR",
        timezone="Asia/Riyadh", messaging_account_id="ma-current",
    )
    point = {
        "spend_date": date(2026, 11, 28), "phone": "966500000001",
        "country": "SA", "pricing_category": "UTILITY",
        "pricing_type": "REGULAR", "tier": "0:MAX",
        "volume": 4, "cost": 1.25, "cost_status": "available",
    }
    adapter = _Adapter({"points": [point]})
    monkeypatch.setattr(spend_worker, "decrypt_connection_token", lambda conn: "token")
    monkeypatch.setattr(spend_worker, "WhatsAppAdapter", lambda: adapter)
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)

    result = await spend_worker.sync_due_wabas(db, now=now, limit=10)

    assert result["synced"] == 1
    assert adapter.calls == [(
        "waba-one", date(2026, 11, 22), date(2026, 11, 29)
    )]
    row = (await db.execute(
        select(WhatsAppSpendDaily).where(WhatsAppSpendDaily.waba_id == "waba-one")
    )).scalar_one()
    assert row.tenant_id == asset.tenant_id
    assert row.funding_mode == "platform_liable"
    assert row.messaging_account_id == "ma-current"
    assert row.waba_timezone == "Asia/Riyadh"


@pytest.mark.asyncio
async def test_retry_backoff_then_upsert_is_idempotent(db, monkeypatch):
    from app.modules.channels.meta import spend_worker

    await _waba(db, "retry")
    point = {
        "spend_date": date(2026, 11, 28), "phone": "966500000001",
        "country": "SA", "pricing_category": "UTILITY",
        "pricing_type": "REGULAR", "tier": "0:MAX",
        "volume": 2, "cost": 0.5, "cost_status": "available",
    }
    adapter = _Adapter({"points": [point], "currency": "SAR"}, failures=1)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(spend_worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(spend_worker, "decrypt_connection_token", lambda conn: "token")
    monkeypatch.setattr(spend_worker, "WhatsAppAdapter", lambda: adapter)
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    await spend_worker.sync_due_wabas(db, now=now, limit=10)
    await spend_worker.sync_due_wabas(db, now=now, limit=10)

    assert sleeps == [1]
    assert len(adapter.calls) == 3
    rows = (await db.execute(select(WhatsAppSpendDaily))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_batch_limit_bounds_provider_calls(db, monkeypatch):
    from app.modules.channels.meta import spend_worker

    for index in range(3):
        await _waba(db, str(index))
    adapter = _Adapter()
    monkeypatch.setattr(spend_worker, "decrypt_connection_token", lambda conn: "token")
    monkeypatch.setattr(spend_worker, "WhatsAppAdapter", lambda: adapter)
    result = await spend_worker.sync_due_wabas(
        db, now=datetime(2026, 11, 28, tzinfo=timezone.utc), limit=2
    )
    assert result["synced"] == 2
    assert len(adapter.calls) == 2
