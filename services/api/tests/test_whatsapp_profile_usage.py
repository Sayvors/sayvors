"""WhatsApp hub backend: profile persistence + stale fallback, Sayvors
messaging quota, PIN-registration rate limiting.

The profile endpoints used to fetch Graph live and throw the data away —
the editor had no DB copy to fall back on. These tests pin the new
contract: every successful read/write persists a snapshot on the asset
(merging, never clobbering pin_encrypted), a Graph outage serves the
stored copy flagged stale, and usage/rate-limit behavior matches the
Sayvors-quota policy (outbound only, plan-keyed, never Meta's tier).
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import settings
from app.modules.channels.meta import router as meta_router
from app.modules.channels.meta import service as _service
from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.models import Channel, ChannelMessage

pytestmark = pytest.mark.asyncio

TENANT = "test-user-0000-0000-0000-000000000001"  # the default client user
OTHER = "other-tenant-0000-0000-0000-000000000002"
PN = "pn-profile-1"

PROFILE = {
    "about": "Handmade ceramics",
    "address": "12 Maadi Rd",
    "description": "Small-batch pottery",
    "email": "hi@shop.com",
    "websites": ["https://shop.com"],
    "vertical": "RETAIL",
    "profile_picture_url": None,
}


async def _seed_number(db, tenant_id=TENANT, external=PN, with_token=True):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=tenant_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("tok") if with_token else None,
        status="active", connection_type="oauth",
    )
    asset = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=tenant_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=external, name="Shop Number", active=True,
        asset_metadata={},
    )
    db.add_all([conn, asset])
    await db.commit()
    await db.refresh(asset)
    return conn, asset


def _mock_adapter(get_profile=PROFILE):
    """Graph is mocked at the adapter seam; set echoes the update like the
    real re-read after a successful POST would."""

    async def _set(pid, token, fields):
        return {**PROFILE, **fields}

    adapter = AsyncMock()
    adapter.get_business_profile = AsyncMock(return_value=dict(get_profile))
    adapter.set_business_profile = AsyncMock(side_effect=_set)
    return adapter


async def _get_profile(client, phone_id=PN):
    return client.get(
        f"/api/v1/meta/whatsapp/{phone_id}/profile",
        headers={"host": "localhost"},
    )


async def test_profile_get_persists_snapshot(client, db, monkeypatch):
    _conn, asset = await _seed_number(db)
    adapter = _mock_adapter()
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)

    resp = await _get_profile(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["about"] == "Handmade ceramics"
    assert body["stale"] is False
    assert body["synced_at"]

    await db.refresh(asset)
    stored = asset.asset_metadata["business_profile"]
    assert stored["about"] == "Handmade ceramics"
    assert asset.asset_metadata["business_profile_synced_at"] == body["synced_at"]


async def test_profile_get_stale_fallback(client, db, monkeypatch):
    """Graph down + stored copy → 200 stale; nothing stored → error passes."""
    _conn, asset = await _seed_number(db)
    asset.asset_metadata = {
        "pin_encrypted": encrypt_credential("123456"),
        "business_profile": dict(PROFILE),
        "business_profile_synced_at": "2026-10-01T00:00:00+00:00",
    }
    await db.commit()
    adapter = _mock_adapter()
    adapter.get_business_profile = AsyncMock(
        side_effect=MetaAPIError("graph down", 500)
    )
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)

    resp = await _get_profile(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stale"] is True
    assert body["synced_at"] == "2026-10-01T00:00:00+00:00"
    assert body["about"] == "Handmade ceramics"

    # Nothing stored → the Graph error passes through untouched.
    bare = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=TENANT, connection_id=_conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id="pn-bare", name="Bare", active=True,
        asset_metadata={},
    )
    db.add(bare)
    await db.commit()
    resp = await _get_profile(client, phone_id="pn-bare")
    assert resp.status_code == 500
    # The merge path must never clobber the PIN sibling key.
    await db.refresh(asset)
    assert asset.asset_metadata["pin_encrypted"]


async def test_profile_patch_persists(client, db, monkeypatch):
    _conn, asset = await _seed_number(db)
    adapter = _mock_adapter()
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)

    resp = client.patch(
        f"/api/v1/meta/whatsapp/{PN}/profile",
        json={"about": "New about", "websites": ["shop.com"]},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stale"] is False
    assert body["synced_at"]

    await db.refresh(asset)
    assert asset.asset_metadata["business_profile"]["about"] == "New about"


async def test_profile_endpoints_tenant_scoped(client, db, monkeypatch):
    """Another tenant's number is invisible — adapter never reached."""
    await _seed_number(db, tenant_id=OTHER)
    adapter = _mock_adapter()
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)

    resp = await _get_profile(client)
    assert resp.status_code == 404
    resp = client.patch(
        f"/api/v1/meta/whatsapp/{PN}/profile",
        json={"about": "hijack"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 404
    adapter.get_business_profile.assert_not_awaited()
    adapter.set_business_profile.assert_not_awaited()


async def test_register_rate_limited(client, db, monkeypatch):
    """6th registration attempt inside the window → 429."""
    _conn, _asset = await _seed_number(db)
    monkeypatch.setattr(settings, "TESTING", False)
    # Graph stays mocked — the rate limiter is the thing under test.
    adapter = AsyncMock()
    adapter.register_number = AsyncMock(return_value="wamid-mock")
    monkeypatch.setattr(_service, "get_adapter", lambda _p: adapter)
    calls = {"n": 0}

    async def fake_rate_limit(key, max_requests, window_seconds, **kwargs):
        calls["n"] += 1
        return calls["n"] <= max_requests

    monkeypatch.setattr(meta_router, "rate_limit", fake_rate_limit)

    for _ in range(5):
        resp = client.post(
            f"/api/v1/meta/whatsapp/{PN}/register",
            json={"pin": "000000"},
            headers={"host": "localhost"},
        )
        assert resp.status_code in (200, 400)  # not rate limited yet
    resp = client.post(
        f"/api/v1/meta/whatsapp/{PN}/register",
        json={"pin": "000000"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 429


async def _seed_channel_with_messages(db, tenant_id=TENANT, external="pn-usage"):
    channel = Channel(
        id=str(uuid.uuid4()), user_id=tenant_id, platform="whatsapp",
        platform_user_id=external, display_name="Shop", status="active",
    )
    db.add(channel)
    await db.flush()
    now = datetime.now(timezone.utc)
    rows = [
        # 2 outbound this month count (sent + failed both cost).
        ChannelMessage(id=str(uuid.uuid4()), channel_id=channel.id,
                       direction="outbound", content="a", content_type="text",
                       status="sent", created_at=now - timedelta(days=1)),
        ChannelMessage(id=str(uuid.uuid4()), channel_id=channel.id,
                       direction="outbound", content="b", content_type="text",
                       status="failed", created_at=now - timedelta(days=2)),
        # Inbound never counts.
        ChannelMessage(id=str(uuid.uuid4()), channel_id=channel.id,
                       direction="inbound", content="c", content_type="text",
                       status="delivered", created_at=now - timedelta(days=1)),
        # Last month's outbound does not count.
        ChannelMessage(id=str(uuid.uuid4()), channel_id=channel.id,
                       direction="outbound", content="d", content_type="text",
                       status="sent", created_at=now - timedelta(days=40)),
    ]
    db.add_all(rows)
    await db.commit()
    return channel


async def test_usage_counts_outbound_this_month(client, db):
    await _seed_channel_with_messages(db)
    resp = client.get("/api/v1/meta/whatsapp/usage", headers={"host": "localhost"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_this_month"] == 2
    assert body["plan"] == "free"  # conftest user carries no plan column value
    assert body["monthly_limit"] == settings.PLAN_MESSAGE_LIMITS["free"]


async def test_usage_plan_limits(client, engine, db):
    from app.core.deps import get_current_user
    from app.main import app as _app
    from app.modules.users.models import User as _User

    async def _pro_user():
        return _User(
            id=TENANT, email="pro@sayvors.com", first_name="Pro",
            last_name="User", password_hash="x", onboarded=True, plan="pro",
        )

    _app.dependency_overrides[get_current_user] = _pro_user
    try:
        resp = client.get("/api/v1/meta/whatsapp/usage", headers={"host": "localhost"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "pro"
        assert body["monthly_limit"] == settings.PLAN_MESSAGE_LIMITS["pro"]
    finally:
        _app.dependency_overrides.pop(get_current_user, None)


async def test_usage_tenant_scoped(client, db):
    """Another tenant's whatsapp traffic never lands in this tenant's quota."""
    await _seed_channel_with_messages(db, tenant_id=OTHER)
    resp = client.get("/api/v1/meta/whatsapp/usage", headers={"host": "localhost"})
    assert resp.status_code == 200
    assert resp.json()["used_this_month"] == 0
