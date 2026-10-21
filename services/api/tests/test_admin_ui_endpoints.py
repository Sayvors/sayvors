"""Regression: every admin endpoint the /admin UI calls must 200 with shape.

Covers the tenants-tuple bug class (service return form vs router form
mismatch): the UI is only as healthy as these routes.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings

# bcrypt(4 rounds) of "test-admin-pass" — fast for tests, never production.
TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Admin login is rate-limited against real Redis in dev; isolate tests."""

    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post(
        "/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST
    )
    assert r.status_code == 200
    # Session is an httpOnly cookie; the jar replays it on /api/v1/admin/*.
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


async def _tenant(db, uid="tenant-1", email="tenant1@example.com"):
    from app.modules.users.models import User

    db.add(User(
        id=uid, email=email, first_name="Tena", last_name="Nt",
        password_hash="x", email_verified=True,
    ))
    await db.commit()
    return uid


@pytest.mark.asyncio
async def test_overview_shape(client, admin_headers):
    r = client.get("/api/v1/admin/overview", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    for key in ("users_total", "reviews_total", "posts_by_status",
                "replies_by_status", "media_by_status",
                "outbox_pending", "outbox_failed", "ingest_failed"):
        assert key in body, key


@pytest.mark.asyncio
async def test_tenants_list_shape(client, db, admin_headers):
    await _tenant(db)
    r = client.get("/api/v1/admin/tenants?limit=25&offset=0", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["items"], list)
    assert body["total"] >= 1
    row = next(i for i in body["items"] if i["email"] == "tenant1@example.com")
    for key in ("id", "email", "has_connection", "reviews", "posts", "databanks"):
        assert key in row, key


@pytest.mark.asyncio
async def test_tenants_search(client, db, admin_headers):
    await _tenant(db, uid="tenant-s", email="searchme@example.com")
    r = client.get("/api/v1/admin/tenants?search=searchme", headers=admin_headers)
    assert r.status_code == 200
    assert all("searchme" in i["email"] for i in r.json()["items"])


@pytest.mark.asyncio
async def test_tenant_detail_shape_and_404(client, db, admin_headers):
    uid = await _tenant(db)
    r = client.get(f"/api/v1/admin/tenants/{uid}", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "tenant1@example.com"
    assert isinstance(body["recent_reviews"], list)
    assert isinstance(body["recent_posts"], list)
    r = client.get("/api/v1/admin/tenants/no-such-user", headers=admin_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_usage_overview_shape(client, admin_headers):
    r = client.get("/api/v1/admin/usage/overview", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "totals" in body
    assert "calls" in body["totals"] and "total_tokens" in body["totals"]


@pytest.mark.asyncio
async def test_health_shape(client, admin_headers):
    r = client.get("/api/v1/admin/health", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("ok", "degraded", "down")
    assert isinstance(body["services"], list)
    assert isinstance(body["recent_failures"], list)


@pytest.mark.asyncio
async def test_llm_list_shape(client, admin_headers):
    r = client.get("/api/v1/admin/llm", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_llm_list_reads_stored_keys_from_database(db, client, admin_headers, monkeypatch):
    """A stale boot overlay must not hide a key the database holds.

    The admin page is how an operator discovers and fixes a key problem; if
    the list trusted the in-memory overlay, a failed boot load would show
    "no keys" forever while the encrypted row sits in Postgres.
    """
    from app.core.crypto import encrypt_secret
    from app.modules.llm.models import ProviderConfig
    from app.modules.llm.providers import registry

    db.add(ProviderConfig(
        provider="openrouter",
        enabled=True,
        key_encrypted=encrypt_secret("sk-or-test-key"),
    ))
    await db.commit()
    monkeypatch.setattr(registry, "_db_overlay", None)

    r = client.get("/api/v1/admin/llm", headers=admin_headers)
    assert r.status_code == 200, r.text
    openrouter = next(p for p in r.json() if p["provider"] == "openrouter")
    assert openrouter["has_key"] is True
    assert openrouter["key_source"] == "database"


@pytest.mark.asyncio
async def test_saving_a_key_updates_this_worker(db, client, admin_headers):
    """The save response and the next generation must see the new key.

    Without a reload, the resolver keeps the overlay from boot and reports
    "no API key configured" until the process restarts.
    """
    from app.modules.llm.providers import registry

    previous = (registry._db_overlay, registry._model_overlay, registry._custom_models)
    registry.reset_provider_cache()
    try:
        r = client.put(
            "/api/v1/admin/llm/openrouter",
            headers=admin_headers,
            json={"api_key": "sk-or-saved"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["has_key"] is True
        assert registry.resolve_provider_key("openrouter") == ("sk-or-saved", "database")
    finally:
        registry._db_overlay, registry._model_overlay, registry._custom_models = previous
        registry._providers.clear()


@pytest.mark.asyncio
async def test_catalog_lists_shape(client, admin_headers):
    for url in ("/api/v1/admin/dialects", "/api/v1/admin/tones"):
        r = client.get(url, headers=admin_headers)
        assert r.status_code == 200, url
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_tenant_usage_404_unknown(client, admin_headers):
    r = client.get("/api/v1/admin/tenants/no-such-user/usage", headers=admin_headers)
    assert r.status_code == 404
