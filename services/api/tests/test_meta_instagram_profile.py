"""Instagram business profile: read-only, with a stale-snapshot fallback.

Meta's IG User reference states updating is not supported, so this asserts the
read path works and that nothing invents a write. The fallback matters more than
the happy path: a Graph outage must show the last known profile marked stale,
not an empty page that looks like a deleted account.
"""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

TENANT = "test-user-0000-0000-0000-000000000001"  # conftest's authenticated user
IG = "17841405822304914"

_PROFILE = {
    "id": IG,
    "username": "sayvors",
    "name": "Sayvors",
    "biography": "AI reviews and replies for your business.",
    "website": "https://sayvors.com",
    "profile_picture_url": "https://scontent.cdninstagram.com/pic.jpg",
    "followers_count": 12400,
    "follows_count": 845,
    "media_count": 234,
}


def _fake_graph(payload, seen):
    async def _inner(self, method, path, token, **kwargs):
        seen["method"] = method
        seen["path"] = path
        seen["params"] = kwargs.get("params", {})
        seen["token"] = token
        return httpx.Response(200, json=payload)

    return _inner


async def _seed(db, *, with_token=True, metadata=None):
    conn = MetaConnection(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        provider="instagram",
        access_token_encrypted=encrypt_credential("page-token") if with_token else None,
        status="active",
    )
    db.add(conn)
    await db.flush()
    asset = MetaAsset(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        connection_id=conn.id,
        provider="instagram",
        asset_type="ig_account",
        external_asset_id=IG,
        name="sayvors",
        username="sayvors",
        active=True,
        asset_metadata=metadata or {},
    )
    db.add(asset)
    await db.commit()
    return asset


# ── adapter ───────────────────────────────────────────────────────────


async def test_adapter_requests_the_readable_fields(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(InstagramAdapter, "_graph", _fake_graph(_PROFILE, seen))

    out = await InstagramAdapter().get_business_profile(IG, "page-token")

    assert seen["method"] == "GET"
    assert seen["path"] == f"/{IG}"
    assert seen["token"] == "page-token"
    fields = seen["params"]["fields"]
    for f in ("username", "name", "biography", "website", "followers_count"):
        assert f in fields
    assert out["username"] == "sayvors"
    assert out["followers_count"] == 12400


async def test_adapter_normalises_missing_counters(monkeypatch):
    seen: dict = {}
    # Meta omits counters rather than sending null.
    monkeypatch.setattr(
        InstagramAdapter,
        "_graph",
        _fake_graph({"id": IG, "username": "sayvors", "name": "Sayvors"}, seen),
    )

    out = await InstagramAdapter().get_business_profile(IG, "t")

    assert out["followers_count"] == 0
    assert out["follows_count"] == 0
    assert out["media_count"] == 0


async def test_instagram_has_no_profile_write_surface():
    """Guard rail: Meta does not support profile updates, so neither do we."""
    from app.modules.channels.meta.capabilities import CAPABILITIES

    adapter = InstagramAdapter()
    assert hasattr(adapter, "get_business_profile")
    assert not hasattr(adapter, "set_business_profile")
    assert "manage_profile" not in CAPABILITIES["instagram"]
    assert "read_profile" in CAPABILITIES["instagram"]


# ── endpoint ──────────────────────────────────────────────────────────


async def test_profile_endpoint_returns_live_data(client, db, monkeypatch):
    await _seed(db)
    monkeypatch.setattr(InstagramAdapter, "_graph", _fake_graph(_PROFILE, {}))

    res = client.get(f"/api/v1/meta/instagram/{IG}/profile")

    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "sayvors"
    assert body["name"] == "Sayvors"
    assert body["website"] == "https://sayvors.com"
    assert body["followers_count"] == 12400
    assert body["media_count"] == 234
    assert body["status"]
    assert body["stale"] is False
    assert body["synced_at"]


async def test_profile_endpoint_persists_a_snapshot(client, db, monkeypatch):
    from sqlalchemy import select

    asset = await _seed(db)
    asset_id = asset.id
    monkeypatch.setattr(InstagramAdapter, "_graph", _fake_graph(_PROFILE, {}))

    client.get(f"/api/v1/meta/instagram/{IG}/profile")

    # The endpoint committed through its own session; drop this session's
    # cached copy before reading back what it wrote.
    db.expire_all()
    stored = (
        await db.execute(select(MetaAsset).where(MetaAsset.id == asset_id))
    ).scalar_one()
    assert stored.asset_metadata["business_profile"]["username"] == "sayvors"
    assert stored.asset_metadata["business_profile_synced_at"]


async def test_profile_falls_back_to_snapshot_when_graph_fails(client, db, monkeypatch):
    from app.modules.channels.meta.providers.base import MetaAPIError

    await _seed(
        db,
        metadata={
            "business_profile": dict(_PROFILE, followers_count=11000),
            "business_profile_synced_at": "2026-01-01T00:00:00+00:00",
        },
    )

    async def _boom(self, method, path, token, **kwargs):
        raise MetaAPIError("upstream 503", 503)

    monkeypatch.setattr(InstagramAdapter, "_graph", _boom)

    res = client.get(f"/api/v1/meta/instagram/{IG}/profile")

    assert res.status_code == 200
    body = res.json()
    # The point of the fallback: last known data, clearly marked as not live.
    assert body["followers_count"] == 11000
    assert body["stale"] is True
    assert body["synced_at"] == "2026-01-01T00:00:00+00:00"


async def test_profile_graph_failure_without_snapshot_surfaces(client, db, monkeypatch):
    from app.modules.channels.meta.providers.base import MetaAPIError

    await _seed(db)

    async def _boom(self, method, path, token, **kwargs):
        raise MetaAPIError("upstream 500", 500)

    monkeypatch.setattr(InstagramAdapter, "_graph", _boom)

    res = client.get(f"/api/v1/meta/instagram/{IG}/profile")
    assert res.status_code == 500


async def test_profile_unknown_account_is_404(client, db):
    res = client.get("/api/v1/meta/instagram/does-not-exist/profile")
    assert res.status_code == 404


async def test_profile_missing_token_without_snapshot_is_409(client, db):
    await _seed(db, with_token=False)
    res = client.get(f"/api/v1/meta/instagram/{IG}/profile")
    assert res.status_code == 409
    assert "reconnect" in res.json()["detail"].lower()


async def test_profile_ignores_an_asset_from_another_provider(client, db):
    """Same external id, different provider: must not answer the IG profile."""
    conn = MetaConnection(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        provider="whatsapp",
        access_token_encrypted=encrypt_credential("wa-token"),
        status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(
        MetaAsset(
            id=str(uuid.uuid4()),
            tenant_id=TENANT,
            connection_id=conn.id,
            provider="whatsapp",
            asset_type="phone_number",
            external_asset_id=IG,
            active=True,
        )
    )
    await db.commit()

    assert client.get(f"/api/v1/meta/instagram/{IG}/profile").status_code == 404


async def test_profile_is_not_writable(client, db):
    """No PATCH: Meta rejects profile updates, so the API must not pretend."""
    await _seed(db)
    res = client.patch(
        f"/api/v1/meta/instagram/{IG}/profile", json={"biography": "hacked"}
    )
    assert res.status_code in (404, 405)