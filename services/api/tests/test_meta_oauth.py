"""Meta OAuth transaction tests: valid/invalid/expired/reused/wrong-tenant."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.channels.meta import oauth as _oauth
from app.modules.channels.meta import service as _service
from app.modules.channels.meta.models import MetaConnection, MetaOAuthTransaction

pytestmark = pytest.mark.asyncio


async def test_create_and_consume_valid(db):
    state, row = await _oauth.create_transaction(db, "tenant-a", "whatsapp")
    assert state and row.status == "pending"

    claimed = await _oauth.consume_transaction(db, state, "whatsapp")
    assert claimed is not None
    assert claimed.tenant_id == "tenant-a"
    assert claimed.status == "completed"


async def test_consume_invalid_state(db):
    assert await _oauth.consume_transaction(db, "nope-not-real", "whatsapp") is None


async def test_consume_reused_state(db):
    state, _ = await _oauth.create_transaction(db, "tenant-a", "facebook")
    assert await _oauth.consume_transaction(db, state, "facebook") is not None
    # One-time use: second claim fails.
    assert await _oauth.consume_transaction(db, state, "facebook") is None


async def test_consume_expired_state(db):
    state, row = await _oauth.create_transaction(db, "tenant-a", "instagram")
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.add(row)
    await db.commit()

    assert await _oauth.consume_transaction(db, state, "instagram") is None
    await db.refresh(row)
    assert row.status == "expired"


async def test_consume_wrong_provider(db):
    state, _ = await _oauth.create_transaction(db, "tenant-a", "whatsapp")
    assert await _oauth.consume_transaction(db, state, "facebook") is None


async def test_state_bound_to_original_tenant(db):
    """The tenant comes from the row — a callback can never rebind it."""
    state, _ = await _oauth.create_transaction(db, "tenant-original", "whatsapp")
    claimed = await _oauth.consume_transaction(db, state, "whatsapp")
    assert claimed is not None
    assert claimed.tenant_id == "tenant-original"


async def test_create_unknown_provider(db):
    with pytest.raises(ValueError):
        await _oauth.create_transaction(db, "tenant-a", "tiktok")


async def test_callback_resolves_instagram_state_on_facebook_url(
    client, engine, db, monkeypatch
):
    """Both Login dialogs share one redirect URI (the facebook callback).

    An Instagram transaction arriving at /facebook/callback must resolve
    its provider from the state row — never be rejected as expired.
    """
    tenant = "test-user-0000-0000-0000-000000000001"
    state, _ = await _oauth.create_transaction(db, tenant, "instagram")

    class _FakeAdapter:
        async def exchange_code(self, code, redirect_uri=None):
            return {"access_token": "fake-ig-token", "token_type": "bearer"}

    monkeypatch.setattr(_service, "get_adapter", lambda _p: _FakeAdapter())

    resp = client.get(
        "/api/v1/meta/facebook/callback",
        params={"code": "fake-code", "state": state},
        headers={"host": "localhost"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert "meta_error" not in location
    # IG reuses the Facebook credentials row; frontend continues there.
    assert "meta_connected=facebook" in location

    rows = (await db.execute(select(MetaConnection))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant
    assert rows[0].provider == "facebook"


async def test_sdk_proxy_serves_and_caches(client, engine, monkeypatch):
    """GET /api/v1/meta/connect-sdk proxies the Meta SDK once, then serves cache."""
    from app.modules.channels.meta import router as _router

    calls = {"n": 0}

    class _FakeResp:
        status_code = 200
        text = "/* fake sdk */ window.FB={};"

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            calls["n"] += 1
            assert "connect.facebook.net" in url
            return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _router._sdk_cache.update(body=None, at=0.0)

    try:
        r1 = client.get("/api/v1/meta/connect-sdk", headers={"host": "localhost"})
        r2 = client.get("/api/v1/meta/connect-sdk", headers={"host": "localhost"})
    finally:
        _router._sdk_cache.update(body=None, at=0.0)

    assert r1.status_code == 200
    assert "fake sdk" in r1.text
    assert "javascript" in r1.headers["content-type"]
    assert r2.status_code == 200
    assert calls["n"] == 1  # second hit served from memory cache


async def test_sdk_proxy_failure_returns_inert_stub(client, engine, monkeypatch):
    """Upstream failure must not leak errors — frontend falls into retry."""
    from app.modules.channels.meta import router as _router

    class _FailClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            raise ConnectionError("upstream down")

    monkeypatch.setattr("httpx.AsyncClient", _FailClient)
    _router._sdk_cache.update(body=None, at=0.0)

    try:
        resp = client.get("/api/v1/meta/connect-sdk", headers={"host": "localhost"})
    finally:
        _router._sdk_cache.update(body=None, at=0.0)

    assert resp.status_code == 200
    assert "window.FB" not in resp.text


async def test_sdk_proxy_rewrites_bundle_url_to_same_origin(client, engine, monkeypatch):
    """The bootstrap's hardcoded bundle URL must point at our proxy, not facebook.net."""
    from app.modules.channels.meta import router as _router

    class _FakeResp:
        status_code = 200
        text = (
            '/* fake sdk */ ("https:\\/\\/connect.facebook.net\\/en_US\\/'
            'bundle\\/sdk.js\\/", 123, "FB", [], false);'
        )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _router._sdk_cache.update(body=None, at=0.0)

    try:
        resp = client.get(
            "/api/v1/meta/connect-sdk", headers={"host": "localhost:8000"}
        )
    finally:
        _router._sdk_cache.update(body=None, at=0.0)

    assert resp.status_code == 200
    assert (
        "http:\\/\\/localhost:8000\\/api\\/v1\\/meta\\/connect-sdk-bundle"
        in resp.text
    )
    assert "connect.facebook.net" not in resp.text


async def test_sdk_bundle_proxy_serves_and_caches(client, engine, monkeypatch):
    """GET /api/v1/meta/connect-sdk-bundle proxies the real SDK bundle."""
    from app.modules.channels.meta import router as _router

    calls = {"n": 0}

    class _FakeResp:
        status_code = 200
        text = "/* fake bundle */ window.FB_LOCAL_GLOBAL={};"

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            calls["n"] += 1
            assert "bundle/sdk.js" in url
            return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _router._bundle_cache.update(body=None, at=0.0)

    try:
        r1 = client.get("/api/v1/meta/connect-sdk-bundle", headers={"host": "localhost"})
        r2 = client.get("/api/v1/meta/connect-sdk-bundle", headers={"host": "localhost"})
    finally:
        _router._bundle_cache.update(body=None, at=0.0)

    assert r1.status_code == 200
    assert "fake bundle" in r1.text
    assert "javascript" in r1.headers["content-type"]
    assert r2.status_code == 200
    assert calls["n"] == 1  # second hit served from memory cache
