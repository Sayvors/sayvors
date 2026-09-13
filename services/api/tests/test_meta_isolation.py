"""Cross-tenant isolation: A can never see/use B's Meta data."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.channels.meta import oauth as _oauth
from app.modules.channels.meta import service as _service
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.base import DiscoveredAsset

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant-a-0000-0000-0000-000000000001"
TENANT_B = "tenant-b-0000-0000-0000-000000000002"
TENANT_AUTH = "test-user-0000-0000-0000-000000000001"  # default authenticated user


def _mock_adapter():
    """Return an AsyncMock shaped like WhatsAppAdapter with known WABA/phone."""
    adapter = AsyncMock()
    adapter.exchange_code.return_value = {
        "access_token": "fake-exchanged-token",
        "token_type": "bearer",
    }
    adapter.discover_assets.return_value = [
        DiscoveredAsset(
            asset_type="waba",
            external_asset_id="waba-from-session",
            name="Tenant WABA",
        ),
        DiscoveredAsset(
            asset_type="phone_number",
            external_asset_id="pn-from-session",
            phone="+1555123456",
            name="Tenant Phone",
            parent_external_id="waba-from-session",
        ),
    ]
    return adapter


async def _seed_connection(db, tenant_id, provider="whatsapp"):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=tenant_id, provider=provider,
        access_token_encrypted="x", status="active",
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def _seed_asset(db, tenant_id, conn, external="ext-1"):
    asset = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=tenant_id, connection_id=conn.id,
        provider=conn.provider, asset_type="phone_number",
        external_asset_id=external, name="Test Number",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def test_list_connections_scoped(db):
    await _seed_connection(db, TENANT_A)
    await _seed_connection(db, TENANT_B)

    rows_a = await _service.list_connections(db, TENANT_A)
    assert [c.tenant_id for c in rows_a] == [TENANT_A]


async def test_get_connection_scoped(db):
    await _seed_connection(db, TENANT_A)
    assert await _service.get_connection(db, TENANT_B, "whatsapp") is None
    assert await _service.get_connection(db, TENANT_A, "whatsapp") is not None


async def test_list_assets_scoped(db):
    conn_a = await _seed_connection(db, TENANT_A)
    conn_b = await _seed_connection(db, TENANT_B)
    await _seed_asset(db, TENANT_A, conn_a, "ext-a")
    await _seed_asset(db, TENANT_B, conn_b, "ext-b")

    rows = await _service.list_assets(db, TENANT_A, "whatsapp")
    assert [a.external_asset_id for a in rows] == ["ext-a"]


async def test_select_other_tenant_asset_rejected(db):
    conn_b = await _seed_connection(db, TENANT_B)
    asset_b = await _seed_asset(db, TENANT_B, conn_b, "ext-b")
    # Tenant A tries to activate B's asset id.
    with pytest.raises(ValueError):
        await _service.select_assets(db, TENANT_A, "whatsapp", [asset_b.id])


async def test_validate_other_tenant_rejected(db):
    await _seed_connection(db, TENANT_B)
    with pytest.raises(ValueError):
        await _service.validate_connection(db, TENANT_A, "whatsapp")


async def test_disconnect_other_tenant_noop(db):
    conn_b = await _seed_connection(db, TENANT_B)
    await _service.disconnect(db, TENANT_A, "whatsapp")
    await db.refresh(conn_b)
    assert conn_b.status == "active"  # untouched


async def test_http_connections_scoped(client, engine, db):
    """HTTP tenant sees only their own connections."""
    db.add(MetaConnection(
        id=str(uuid.uuid4()), tenant_id="test-user-0000-0000-0000-000000000001",
        provider="facebook", access_token_encrypted="x", status="active",
    ))
    db.add(MetaConnection(
        id=str(uuid.uuid4()), tenant_id="someone-else",
        provider="facebook", access_token_encrypted="x", status="active",
    ))
    await db.commit()

    resp = client.get("/api/v1/meta/connections", headers={"host": "localhost"})
    assert resp.status_code == 200
    providers = [c["provider"] for c in resp.json()["connections"]]
    assert providers == ["facebook"]


# ── WhatsApp session-level tenant binding ─────────────────


async def test_whatsapp_session_binds_correct_tenant(client, engine, db, monkeypatch):
    """Authenticated tenant's state → connection + assets stored under their tenant_id."""
    state, _ = await _oauth.create_transaction(db, TENANT_AUTH, "whatsapp")

    adapter = _mock_adapter()
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)

    resp = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state, "code": "fake-code", "waba_id": "waba-from-session"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 200, resp.text

    conn = (
        await db.execute(
            select(MetaConnection).where(
                MetaConnection.tenant_id == TENANT_AUTH,
                MetaConnection.provider == "whatsapp",
            )
        )
    ).scalar_one()
    assert conn.status == "active"

    assets = (
        await db.execute(
            select(MetaAsset).where(MetaAsset.tenant_id == TENANT_AUTH)
        )
    ).scalars().all()
    asset_ids = {a.external_asset_id for a in assets}
    assert "waba-from-session" in asset_ids
    assert "pn-from-session" in asset_ids

    # subscribe_app was called with the TENANT's WABA, not a hard-coded one.
    adapter.subscribe_app.assert_awaited_once()
    waba_arg = adapter.subscribe_app.call_args[0][0]
    assert waba_arg == "waba-from-session"

    # register_number was called with the TENANT's phone.
    adapter.register_number.assert_awaited_once()
    phone_arg = adapter.register_number.call_args[0][0]
    assert phone_arg == "pn-from-session"


async def test_whatsapp_session_rejects_other_tenant(client, engine, db, monkeypatch):
    """Tenant A's state cannot be consumed by Tenant B's authenticated session."""
    state_a, _ = await _oauth.create_transaction(db, TENANT_A, "whatsapp")

    adapter = _mock_adapter()
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)

    # Temporarily swap the authenticated user to Tenant B.
    from app.core.deps import get_current_user
    from app.modules.users.models import User as _User

    async def _tenant_b_user():
        return _User(
            id=TENANT_B, email="b@tenant.com",
            first_name="B", last_name="User",
            password_hash="x", onboarded=True,
        )

    from app.main import app as _app
    _app.dependency_overrides[get_current_user] = _tenant_b_user

    try:
        resp = client.post(
            "/api/v1/meta/whatsapp/session",
            json={"state": state_a, "code": "code", "waba_id": "waba-x"},
            headers={"host": "localhost"},
        )
        assert resp.status_code == 403
        assert "another tenant" in resp.json()["detail"].lower()

        # Nothing stored for Tenant B — adapter never reached.
        adapter.exchange_code.assert_not_awaited()
        rows = (
            await db.execute(
                select(MetaConnection).where(MetaConnection.tenant_id == TENANT_B)
            )
        ).scalars().all()
        assert rows == []
    finally:
        _app.dependency_overrides.pop(get_current_user, None)


async def test_two_tenants_separate_connections(client, engine, db, monkeypatch):
    """Tenant A and B each complete WhatsApp connect → fully separate rows."""
    state_a, _ = await _oauth.create_transaction(db, TENANT_A, "whatsapp")
    state_b, _ = await _oauth.create_transaction(db, TENANT_B, "whatsapp")

    adapter_a = _mock_adapter()
    adapter_b = _mock_adapter()
    adapter_b.discover_assets.return_value = [
        DiscoveredAsset(
            asset_type="waba",
            external_asset_id="waba-tenant-b",
            name="B WABA",
        ),
        DiscoveredAsset(
            asset_type="phone_number",
            external_asset_id="pn-tenant-b",
            phone="+15559999",
            name="B Phone",
            parent_external_id="waba-tenant-b",
        ),
    ]

    from app.core.deps import get_current_user
    from app.modules.users.models import User as _User
    from app.main import app as _app

    async def _user_a():
        return _User(
            id=TENANT_A, email="a@tenant.com",
            first_name="A", last_name="User",
            password_hash="x", onboarded=True,
        )

    async def _user_b():
        return _User(
            id=TENANT_B, email="b@tenant.com",
            first_name="B", last_name="User",
            password_hash="x", onboarded=True,
        )

    # ── Tenant A connects ──
    _app.dependency_overrides[get_current_user] = _user_a
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter_a)
    resp = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state_a, "code": "code-a", "waba_id": "waba-tenant-a"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 200, resp.text

    # ── Tenant B connects ──
    _app.dependency_overrides[get_current_user] = _user_b
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter_b)
    resp = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state_b, "code": "code-b", "waba_id": "waba-tenant-b"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 200, resp.text

    try:
        # Each tenant has exactly one connection.
        conns_a = (
            await db.execute(
                select(MetaConnection).where(MetaConnection.tenant_id == TENANT_A)
            )
        ).scalars().all()
        conns_b = (
            await db.execute(
                select(MetaConnection).where(MetaConnection.tenant_id == TENANT_B)
            )
        ).scalars().all()
        assert len(conns_a) == 1
        assert len(conns_b) == 1

        # Each tenant has exactly their own assets — no cross-contamination.
        assets_a = (
            await db.execute(
                select(MetaAsset).where(MetaAsset.tenant_id == TENANT_A)
            )
        ).scalars().all()
        assets_b = (
            await db.execute(
                select(MetaAsset).where(MetaAsset.tenant_id == TENANT_B)
            )
        ).scalars().all()
        assert {a.external_asset_id for a in assets_a} == {
            "waba-from-session", "pn-from-session"
        }
        assert {a.external_asset_id for a in assets_b} == {
            "waba-tenant-b", "pn-tenant-b"
        }

        # Each adapter got its own WABA — never swapped.
        adapter_a.subscribe_app.assert_awaited_once_with(
            "waba-from-session", "fake-exchanged-token"
        )
        adapter_b.subscribe_app.assert_awaited_once_with(
            "waba-tenant-b", "fake-exchanged-token"
        )
    finally:
        _app.dependency_overrides.pop(get_current_user, None)
