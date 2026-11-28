"""Every Messages API send crosses the durable quota reservation choke point."""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.billing.models import Plan, TenantSubscription
from app.modules.channels.meta import quota
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.base import (
    MetaAPIError, MetaProviderAdapter, MetaTransportError,
)
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter
from app.modules.channels.meta.spend_models import (
    WhatsAppMonthlyUsage, WhatsAppQuotaReservation,
)
from app.modules.users.models import User


async def _seed(db, monkeypatch):
    uid = f"adapter-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="Adapter", last_name="Test",
        email=f"{uid}@example.com", password_hash="x",
    ))
    plan = Plan(
        id=f"plan-{uid}", slug=f"plan-{uid}", name="Adapter Plan",
        max_messages_per_month=10, features={"messaging": True},
    )
    db.add(plan)
    await db.flush()
    db.add(TenantSubscription(tenant_id=uid, plan_id=plan.id))
    conn = MetaConnection(
        id=f"conn-{uid}", tenant_id=uid, provider="whatsapp", status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=f"asset-{uid}", tenant_id=uid, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id="pn-adapter", active=True,
    ))
    await db.commit()
    monkeypatch.setattr(quota, "_session_factory", lambda: _Borrowed(db))
    return uid


class _Borrowed:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return False


def _response():
    return SimpleNamespace(json=lambda: {"messages": [{"id": "wamid-out"}]})


@pytest.mark.asyncio
async def test_send_reserves_before_provider_and_consumes(db, monkeypatch):
    uid = await _seed(db, monkeypatch)
    observed = []

    async def fake_graph(self, method, path, token, **kwargs):
        used = (await db.execute(
            select(WhatsAppMonthlyUsage.used_count).where(
                WhatsAppMonthlyUsage.tenant_id == uid
            )
        )).scalar_one()
        observed.append(used)
        return _response()

    monkeypatch.setattr(MetaProviderAdapter, "_graph", fake_graph)
    adapter = WhatsAppAdapter()
    try:
        result = await adapter.send_text_message("pn-adapter", "token", "1555", "hello")
    finally:
        await adapter.close()
    assert result == "wamid-out"
    assert observed == [1]
    reservation = (await db.execute(select(WhatsAppQuotaReservation))).scalar_one()
    assert reservation.status == "consumed"
    assert reservation.provider_message_id == "wamid-out"


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected_used,expected_status", [
    (MetaAPIError("rejected", 400), 1, "consumed"),
    (MetaTransportError("connect failed"), 0, "released"),
])
async def test_failure_policy_only_releases_proven_pre_send(
    db, monkeypatch, error, expected_used, expected_status
):
    uid = await _seed(db, monkeypatch)

    async def fake_graph(self, method, path, token, **kwargs):
        raise error

    monkeypatch.setattr(MetaProviderAdapter, "_graph", fake_graph)
    adapter = WhatsAppAdapter()
    try:
        with pytest.raises(type(error)):
            await adapter.send_text_message("pn-adapter", "token", "1555", "hello")
    finally:
        await adapter.close()
    usage = (await db.execute(
        select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
    )).scalar_one()
    reservation = (await db.execute(select(WhatsAppQuotaReservation))).scalar_one()
    assert usage.used_count == expected_used
    assert reservation.status == expected_status


@pytest.mark.asyncio
async def test_duplicate_idempotency_scope_counts_once(db, monkeypatch):
    uid = await _seed(db, monkeypatch)

    async def fake_graph(self, method, path, token, **kwargs):
        return _response()

    monkeypatch.setattr(MetaProviderAdapter, "_graph", fake_graph)
    adapter = WhatsAppAdapter()
    try:
        for _ in range(2):
            with quota.whatsapp_send_key("template:send-1"):
                await adapter.send_template_message(
                    "pn-adapter", "token", "1555", "order_update", "en", []
                )
    finally:
        await adapter.close()
    usage = (await db.execute(
        select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
    )).scalar_one()
    assert usage.used_count == 1


@pytest.mark.asyncio
async def test_typing_indicator_never_reserves_quota(db, monkeypatch):
    await _seed(db, monkeypatch)

    async def fake_graph(self, method, path, token, **kwargs):
        return _response()

    monkeypatch.setattr(MetaProviderAdapter, "_graph", fake_graph)
    adapter = WhatsAppAdapter()
    try:
        assert await adapter.send_typing_indicator("pn-adapter", "token", "wamid-in")
    finally:
        await adapter.close()
    assert (await db.execute(select(WhatsAppMonthlyUsage))).scalars().all() == []
