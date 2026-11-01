"""WA-8: WhatsApp number lifecycle.

Verify -> request code -> verify code -> register, plus deregistration and the
two-step PIN. Meta owns the state; the adapter payloads and the asset status
the UI reads back are pinned here.
"""
import uuid

import pytest
from sqlalchemy import select

from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter

TENANT = "test-user-0000-0000-0000-000000000001"
PN = "pn-lifecycle-1"


async def _seed(db, tenant_id=TENANT, external=PN):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=tenant_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("tok"), status="active",
    )
    db.add(conn)
    await db.flush()
    asset = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=tenant_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=external, name="Shop Number", active=True,
        asset_metadata={},
    )
    db.add(asset)
    await db.commit()
    return asset


async def _asset(db, phone_id=PN):
    return (
        await db.execute(
            select(MetaAsset).where(MetaAsset.external_asset_id == phone_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_adapter_lifecycle_payloads(monkeypatch):
    calls: list[dict] = []

    class _Resp:
        def json(self):
            return {"success": True}

    async def _graph(self, method, path, token, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)
    adapter = WhatsAppAdapter()

    assert await adapter.request_verification_code(
        "pn", "tok", code_method="VOICE", language="ar_SA"
    )
    assert calls[-1]["path"] == "/pn/request_code"
    assert calls[-1]["params"] == {"code_method": "VOICE", "language": "ar_SA"}

    assert await adapter.verify_number_code("pn", "tok", "123456")
    assert calls[-1]["path"] == "/pn/verify_code"
    assert calls[-1]["json"] == {"code": "123456"}

    assert await adapter.deregister_number("pn", "tok")
    assert calls[-1]["path"] == "/pn/deregister"
    assert calls[-1]["json"] == {"messaging_product": "whatsapp"}

    assert await adapter.set_two_step_pin("pn", "tok", "654321")
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["path"] == "/pn"
    assert calls[-1]["json"] == {"pin": "654321"}


@pytest.mark.asyncio
async def test_request_code_endpoint(client, db, monkeypatch):
    await _seed(db)
    seen: dict = {}

    async def _request(self, phone_number_id, token, **kwargs):
        seen.update({"phone": phone_number_id, "token": token, **kwargs})
        return True

    monkeypatch.setattr(WhatsAppAdapter, "request_verification_code", _request)

    res = client.post(
        f"/api/v1/meta/whatsapp/{PN}/request-code",
        json={"code_method": "VOICE", "language": "ar_SA"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["sent"] is True
    assert seen == {
        "phone": PN, "token": "tok",
        "code_method": "VOICE", "language": "ar_SA",
    }


@pytest.mark.asyncio
async def test_verify_code_updates_the_asset(client, db, monkeypatch):
    await _seed(db)

    async def _verify(self, phone_number_id, token, code):
        assert code == "123456"
        return True

    monkeypatch.setattr(WhatsAppAdapter, "verify_number_code", _verify)

    res = client.post(
        f"/api/v1/meta/whatsapp/{PN}/verify-code", json={"code": "123456"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["verified"] is True
    assert (await _asset(db)).status == "verified"


@pytest.mark.asyncio
async def test_deregister_updates_the_asset(client, db, monkeypatch):
    await _seed(db)

    async def _deregister(self, phone_number_id, token):
        return True

    monkeypatch.setattr(WhatsAppAdapter, "deregister_number", _deregister)

    res = client.post(f"/api/v1/meta/whatsapp/{PN}/deregister")
    assert res.status_code == 200, res.text
    assert res.json()["deregistered"] is True
    asset = await _asset(db)
    assert asset.status == "deregistered"
    assert asset.active is False


@pytest.mark.asyncio
async def test_two_step_pin_is_encrypted_and_never_returned(
    client, db, monkeypatch
):
    await _seed(db)

    async def _pin(self, phone_number_id, token, pin):
        assert pin == "654321"
        return True

    monkeypatch.setattr(WhatsAppAdapter, "set_two_step_pin", _pin)

    res = client.post(
        f"/api/v1/meta/whatsapp/{PN}/two-step", json={"pin": "654321"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["updated"] is True
    assert "654321" not in res.text

    asset = await _asset(db)
    stored = (asset.asset_metadata or {}).get("pin_encrypted")
    assert stored
    assert stored != "654321"


@pytest.mark.asyncio
async def test_lifecycle_rejects_a_short_code_and_foreign_number(
    client, db, monkeypatch
):
    await _seed(db)
    assert client.post(
        f"/api/v1/meta/whatsapp/{PN}/verify-code", json={"code": "12"}
    ).status_code == 422
    assert client.post(
        "/api/v1/meta/whatsapp/pn-not-mine/request-code",
        json={"code_method": "SMS", "language": "en_US"},
    ).status_code == 404
