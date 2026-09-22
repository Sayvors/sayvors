"""Platform admin auth: separate password, token gate (no network, no DB writes)."""
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
def _clean_llm_overlay():
    """The provider overlay is process-global; isolate tests from each other."""
    from app.modules.llm.providers import registry

    registry.reset_provider_cache()
    yield
    registry.reset_provider_cache()


@pytest.fixture(autouse=True)
def _clean_llm_overlay():
    """The provider overlay is process-global; isolate tests from each other."""
    from app.modules.llm.providers import registry

    registry.reset_provider_cache()
    yield
    registry.reset_provider_cache()


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Admin login is rate-limited against real Redis in dev; isolate tests."""

    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.mark.asyncio
async def test_admin_disabled_without_hash(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")
    r = client.post("/api/v1/admin/login", json={"password": "x"}, headers=_HOST)
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_admin_wrong_password(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post("/api/v1/admin/login", json={"password": "nope"}, headers=_HOST)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_and_me(client, monkeypatch):
    from app.security import decode_token

    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post(
        "/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST
    )
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in_minutes"] == settings.ADMIN_SESSION_MINUTES
    payload = decode_token(body["access_token"])
    assert payload["type"] == "admin"
    assert payload["sub"] == "admin"

    me = client.get(
        "/api/v1/admin/me",
        headers={**_HOST, "Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json() == {"admin": True}


@pytest.mark.asyncio
async def test_admin_gate_rejects_user_token(client, user_id):
    from app.security import create_access_token

    user_token = create_access_token(user_id)
    r = client.get(
        "/api/v1/admin/me",
        headers={**_HOST, "Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_gate_rejects_anonymous(client):
    r = client.get("/api/v1/admin/me", headers=_HOST)
    assert r.status_code in (401, 403)


def test_every_admin_route_is_gated_except_login():
    """Regression guard: no future admin endpoint ships without the gate."""
    from app.core.deps import require_admin
    from app.modules.admin.router import router as admin_router

    assert admin_router.prefix == "/api/v1/admin"
    for route in admin_router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path == "/api/v1/admin/login" and methods == {"POST"}:
            continue
        dependant = getattr(route, "dependant", None)
        calls = [getattr(d, "call", None) for d in (dependant.dependencies if dependant else [])]
        assert require_admin in calls, f"{path} missing require_admin"


def test_admin_prefix_belongs_only_to_admin_router():
    """No tenant router may mount under /api/v1/admin (either direction)."""
    import app.main as main_module

    routers = {
        name: obj
        for name, obj in vars(main_module).items()
        if name.endswith("_router") and hasattr(obj, "prefix")
    }
    assert routers, "expected mounted routers"
    for name, router in routers.items():
        if name == "admin_router":
            assert router.prefix == "/api/v1/admin"
        else:
            assert not str(router.prefix).startswith("/api/v1/admin"), name


@pytest.mark.asyncio
async def test_user_token_rejected_on_all_admin_gets(client, user_id):
    from app.security import create_access_token

    headers = {**_HOST, "Authorization": f"Bearer {create_access_token(user_id)}"}
    for path in (
        "/api/v1/admin/me",
        "/api/v1/admin/overview",
        "/api/v1/admin/tenants",
        "/api/v1/admin/tenants/abc",
    ):
        r = client.get(path, headers=headers)
        assert r.status_code in (401, 403, 404), (path, r.status_code)


@pytest.mark.asyncio
async def test_admin_token_rejected_on_tenant_routes(client, monkeypatch):
    # NOTE: the client fixture overrides get_current_user with a fake user,
    # which would mask real token validation. Drop that override here so the
    # real dependency runs (DB override stays, so no live database needed).
    from app import main as main_module
    from app.core import deps as core_deps

    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST
    )
    assert login.status_code == 200
    headers = {**_HOST, "Authorization": f"Bearer {login.json()['access_token']}"}

    key = core_deps.get_current_user
    saved = main_module.app.dependency_overrides.pop(key, None)
    try:
        for path in (
            "/api/v1/analytics/overview?days=30",
            "/api/v1/analytics/reviews/insights",
            "/api/v1/channels/?limit=100",
            "/api/v1/integrations/localith/connection",
        ):
            r = client.get(path, headers=headers)
            assert r.status_code == 401, (path, r.status_code, r.text[:120])
    finally:
        if saved is not None:
            main_module.app.dependency_overrides[key] = saved


@pytest.mark.asyncio
async def test_admin_overview_counts(db, user_id, channel_id):
    from datetime import datetime, timezone

    from app.modules.analytics.models import ReviewInsight
    from app.modules.admin import service as admin_service
    from app.modules.localith.models import LocalithConnection
    from app.modules.users.models import User

    db.add(User(
        id=user_id, email="test@sayvors.com", first_name="Test",
        last_name="User", password_hash="x", onboarded=True,
    ))
    db.add(LocalithConnection(
        id="conn-admin-1", user_id=user_id, listing_id="loc-1",
        listing_name="T", listing_google_id="g",
    ))
    db.add(ReviewInsight(
        id="ins-admin-1", user_id=user_id, channel_id=channel_id,
        review_id="r1", rating=5, review_text="Great!", reviewer_name="A",
        sentiment="positive", sentiment_score=0.9, topics=[], products=[],
        problems=[], enrichment_status="done", replied=False,
        review_updated_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    ov = await admin_service.get_overview(db)
    assert ov["users_total"] >= 1
    assert ov["connections"] >= 1
    assert ov["reviews_total"] >= 1

    items, total = await admin_service.list_tenants(db, None, 50, 0)
    assert total >= 1
    mine = next(t for t in items if t["id"] == user_id)
    assert mine["has_connection"] is True
    assert mine["reviews"] >= 1

    detail = await admin_service.get_tenant(db, user_id)
    assert detail is not None
    assert detail["listing_name"] == "T"
    assert len(detail["recent_reviews"]) >= 1

    assert await admin_service.get_tenant(db, "no-such-user") is None


@pytest.mark.asyncio
async def test_admin_overview_http(client, monkeypatch):
    from app.modules.admin import service as admin_service

    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST
    )
    token = login.json()["access_token"]
    r = client.get(
        "/api/v1/admin/overview",
        headers={**_HOST, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "users_total" in body
    assert "outbox_pending" in body


@pytest.mark.asyncio
async def test_admin_health_structure(db):
    from app.modules.admin import service as admin_service

    health = await admin_service.get_health(db, probe=False)
    assert health["status"] in ("ok", "degraded", "down")
    names = [s["name"] for s in health["services"]]
    assert "Database" in names
    assert "Redis" in names
    assert "Kafka" in names
    assert "Localith" in names
    assert any(n.startswith("AI:") for n in names)
    db_svc = next(s for s in health["services"] if s["name"] == "Database")
    assert db_svc["ok"] is True
    assert isinstance(health["recent_failures"], list)


@pytest.mark.asyncio
async def test_admin_health_http(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST
    )
    token = login.json()["access_token"]
    for url in ("/api/v1/admin/health", "/api/v1/admin/health?probe=false"):
        r = client.get(
            url,
            headers={**_HOST, "Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, url
        body = r.json()
        assert body["probe"] is False
        assert any(s["name"] == "Database" and s["ok"] for s in body["services"])


def _admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    login = client.post(
        "/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST
    )
    assert login.status_code == 200
    return {**_HOST, "Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_llm_list_and_set_round_trip(client, monkeypatch):
    headers = _admin_headers(client, monkeypatch)

    r = client.get("/api/v1/admin/llm", headers=headers)
    assert r.status_code == 200
    providers = {p["provider"]: p for p in r.json()}
    assert "groq" in providers
    assert "gsk" not in r.text  # key material never leaks

    # Unknown provider rejected.
    r = client.put("/api/v1/admin/llm/nope", json={"enabled": True}, headers=headers)
    assert r.status_code == 404

    # Store a key -> source becomes database, still no leak.
    r = client.put(
        "/api/v1/admin/llm/groq", json={"api_key": "gsk_test_123"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["key_source"] == "database"
    assert r.json()["enabled"] is True
    assert "gsk_test_123" not in r.text

    r = client.get("/api/v1/admin/llm", headers=headers)
    groq = next(p for p in r.json() if p["provider"] == "groq")
    assert groq["key_source"] == "database"
    assert groq["has_key"] is True

    # Kill-switch off -> disabled.
    r = client.put("/api/v1/admin/llm/groq", json={"enabled": False}, headers=headers)
    assert r.json()["key_source"] == "disabled"

    # Clear the key -> falls back to env (none in tests).
    r = client.put("/api/v1/admin/llm/groq", json={"api_key": "", "enabled": True}, headers=headers)
    assert r.json()["key_source"] in ("env", "none")


@pytest.mark.asyncio
async def test_admin_llm_test_endpoint(client, monkeypatch):
    import app.modules.admin.service as admin_service

    headers = _admin_headers(client, monkeypatch)
    # Store a key first (test endpoint needs one configured).
    put = client.put(
        "/api/v1/admin/llm/groq", json={"api_key": "gsk_test_123"}, headers=headers
    )
    assert put.status_code == 200

    async def _fake_probe(name, url, timeout=10):
        return "reachable (M models listed)"

    monkeypatch.setattr(admin_service, "_probe_ai_provider", _fake_probe)
    r = client.post("/api/v1/admin/llm/groq/test", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "groq"

    r = client.post("/api/v1/admin/llm/nope/test", headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_custom_model_crud(client, monkeypatch):
    headers = _admin_headers(client, monkeypatch)
    # Tenant calls need the provider keyed, otherwise nothing is visible.
    put = client.put(
        "/api/v1/admin/llm/groq", json={"api_key": "gsk_test_123"}, headers=headers
    )
    assert put.status_code == 200
    payload = {
        "id": "groq:test-custom-1", "name": "Test Custom",
        "provider": "groq", "api_model": "test-custom-1",
        "context_window": 8000, "max_output": 1000, "supports_stream": False,
    }
    # Unknown provider rejected.
    r = client.post("/api/v1/admin/llm/models", json={**payload, "provider": "nope"}, headers=headers)
    assert r.status_code == 404
    # Bad id shape rejected.
    r = client.post("/api/v1/admin/llm/models", json={**payload, "id": "nocolon"}, headers=headers)
    assert r.status_code == 422
    # A catalog id can be saved as an explicit override row.
    override = {**payload, "id": "groq:oss-120b", "name": "OSS 120B", "api_model": "oss-120b"}
    r = client.post("/api/v1/admin/llm/models", json=override, headers=headers)
    assert r.status_code == 201, r.text[:200]
    # Same id again -> duplicate row rejected.
    r = client.post("/api/v1/admin/llm/models", json=override, headers=headers)
    assert r.status_code == 409
    # Override row deletes cleanly (it is admin-saved).
    r = client.delete("/api/v1/admin/llm/groq/models/groq:oss-120b", headers=headers)
    assert r.status_code == 204
    # Create custom works.
    r = client.post("/api/v1/admin/llm/models", json=payload, headers=headers)
    assert r.status_code == 201, r.text[:200]
    body = r.json()
    assert body["custom"] is True
    assert body["name"] == "Test Custom"
    # Shows up flagged custom in the list.
    r = client.get("/api/v1/admin/llm", headers=headers)
    groq = next(p for p in r.json() if p["provider"] == "groq")
    custom = next(m for m in groq["models"] if m["id"] == "groq:test-custom-1")
    assert custom["custom"] is True
    # Duplicate create rejected.
    r = client.post("/api/v1/admin/llm/models", json=payload, headers=headers)
    assert r.status_code == 409
    # Tenant catalog sees it too � and nothing else unsaved.
    r = client.get("/api/v1/llm/models", headers=_user_headers(client))
    ids = [m["id"] for m in r.json()["models"]]
    assert "groq:test-custom-1" in ids
    assert "groq:oss-120b" not in ids  # override deleted; catalog stays hidden
    # Catalog models can't be deleted (no row left).
    r = client.delete("/api/v1/admin/llm/groq/models/groq:oss-120b", headers=headers)
    assert r.status_code == 400
    # Custom one deletes cleanly.
    r = client.delete("/api/v1/admin/llm/groq/models/groq:test-custom-1", headers=headers)
    assert r.status_code == 204
    r = client.get("/api/v1/llm/models", headers=_user_headers(client))
    assert "groq:test-custom-1" not in [m["id"] for m in r.json()["models"]]


def _user_headers(client):
    # Any authenticated tenant token works for the catalog endpoint; reuse
    # the client fixture's fake user via a scratch login is overkill, so use
    # the dependency override path the fixture already installed: hit the
    # endpoint with a dummy bearer (override ignores it).
    return {**_HOST, "Authorization": "Bearer test-fake-token"}


@pytest.mark.asyncio
async def test_tenant_models_mirror_admin_saved_rows(client, monkeypatch):
    """Tenants see exactly the admin's saved+enabled rows — never the catalog."""
    headers = _admin_headers(client, monkeypatch)
    tenant = _user_headers(client)

    # Fresh database: nothing saved -> tenants see nothing.
    r = client.get("/api/v1/llm/models", headers=tenant)
    assert r.status_code == 200
    assert r.json()["models"] == []

    # A provider key alone changes nothing — models need explicit rows.
    put = client.put(
        "/api/v1/admin/llm/groq", json={"api_key": "gsk_test_123"}, headers=headers
    )
    assert put.status_code == 200
    r = client.get("/api/v1/llm/models", headers=tenant)
    assert r.json()["models"] == []

    # Admin opts a catalog model in -> tenant sees exactly that one, usable.
    t = client.put(
        "/api/v1/admin/llm/groq/models/groq:oss-120b",
        json={"enabled": True},
        headers=headers,
    )
    assert t.status_code == 200
    r = client.get("/api/v1/llm/models", headers=tenant)
    models = r.json()["models"]
    assert [m["id"] for m in models] == ["groq:oss-120b"]
    assert models[0]["available"] is True

    # Admin switches it off -> gone again.
    t = client.put(
        "/api/v1/admin/llm/groq/models/groq:oss-120b",
        json={"enabled": False},
        headers=headers,
    )
    assert t.status_code == 200
    r = client.get("/api/v1/llm/models", headers=tenant)
    assert r.json()["models"] == []


@pytest.mark.asyncio
async def test_admin_models_list(client, monkeypatch):
    headers = _admin_headers(client, monkeypatch)
    r = client.get("/api/v1/admin/models", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_admin_remote_models_unknown_provider(client, monkeypatch):
    headers = _admin_headers(client, monkeypatch)
    r = client.get("/api/v1/admin/llm/nope/remote-models", headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_remote_models_needs_key(client, monkeypatch):
    from app.modules.llm.providers import registry

    headers = _admin_headers(client, monkeypatch)
    monkeypatch.setattr(registry, "_db_overlay", {})
    r = client.get("/api/v1/admin/llm/openai/remote-models", headers=headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_remote_models_parses_shapes(client, monkeypatch):
    import httpx
    from app.modules.llm.providers import registry

    headers = _admin_headers(client, monkeypatch)
    monkeypatch.setattr(
        registry, "_db_overlay",
        {"groq": {"key_encrypted": None, "enabled": True}},
        raising=False,
    )
    # Give groq a fake key through the overlay is impossible without encrypt;
    # instead patch resolve to hand back a dummy key.
    monkeypatch.setattr(
        registry, "resolve_provider_key", lambda p: ("dummy", "database")
    )

    class _FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())
    r = client.get("/api/v1/admin/llm/groq/remote-models", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {"id": "groq:model-a", "name": "model-a"},
        {"id": "groq:model-b", "name": "model-b"},
    ]


# ── G1 access-token revocation ─────────────────────────────

def _real_auth_client(client):
    """Drop the fake-user override so the real get_current_user runs."""
    from app import main as main_module
    from app.core import deps as core_deps

    key = core_deps.get_current_user
    saved = main_module.app.dependency_overrides.pop(key, None)
    return key, saved


@pytest.mark.asyncio
async def test_access_token_blacklist_rejected(client, db, user_id):
    """A blacklisted access jti must 401 even before expiry (G1)."""
    from app import main as main_module
    from app.modules.auth.rate_limit import blacklist_token
    from app.modules.users.models import User
    from app.security import create_access_token, decode_token

    db.add(User(id=user_id, email="g1@sayvors.com", first_name="G",
                last_name="One", password_hash="x", onboarded=True))
    await db.commit()

    key, saved = _real_auth_client(client)
    try:
        token = create_access_token(user_id, 0)
        headers = {**_HOST, "Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/review-engine/strategies", headers=headers).status_code == 200

        jti = decode_token(token)["jti"]
        await blacklist_token(jti, 60)
        r = client.get("/api/v1/review-engine/strategies", headers=headers)
        assert r.status_code == 401
    finally:
        if saved is not None:
            main_module.app.dependency_overrides[key] = saved


@pytest.mark.asyncio
async def test_access_token_stale_version_rejected(client, db, user_id):
    """Bumping token_version (password change / logout-all) kills old tokens (G1)."""
    from app import main as main_module
    from app.modules.users.models import User
    from app.security import create_access_token

    db.add(User(id=user_id, email="g1v@sayvors.com", first_name="G",
                last_name="One", password_hash="x", onboarded=True))
    await db.commit()

    key, saved = _real_auth_client(client)
    try:
        old = create_access_token(user_id, 0)
        headers = {**_HOST, "Authorization": f"Bearer {old}"}
        assert client.get("/api/v1/review-engine/strategies", headers=headers).status_code == 200

        from sqlalchemy import update
        await db.execute(update(User).where(User.id == user_id).values(token_version=1))
        await db.commit()

        assert client.get("/api/v1/review-engine/strategies", headers=headers).status_code == 401
        fresh = create_access_token(user_id, 1)
        fresh_headers = {**_HOST, "Authorization": f"Bearer {fresh}"}
        assert client.get("/api/v1/review-engine/strategies", headers=fresh_headers).status_code == 200
    finally:
        if saved is not None:
            main_module.app.dependency_overrides[key] = saved


@pytest.mark.asyncio
async def test_logout_kills_presented_access_token(client, db, user_id):
    """Logout blacklists the presented access token; logout-all bumps version (G1)."""
    from app import main as main_module
    from app.modules.users.models import User
    from app.security import create_access_token

    db.add(User(id=user_id, email="g1l@sayvors.com", first_name="G",
                last_name="One", password_hash="x", onboarded=True))
    await db.commit()

    key, saved = _real_auth_client(client)
    try:
        token = create_access_token(user_id, 0)
        headers = {**_HOST, "Authorization": f"Bearer {token}"}
        r = client.post("/api/v1/auth/logout", json={}, headers=headers)
        assert r.status_code == 200
        # Same access token is now dead.
        assert client.get("/api/v1/review-engine/strategies", headers=headers).status_code == 401

        token2 = create_access_token(user_id, 0)
        headers2 = {**_HOST, "Authorization": f"Bearer {token2}"}
        r2 = client.post("/api/v1/auth/logout", json={"all_devices": True}, headers=headers2)
        assert r2.status_code == 200
        # Version bumped → even a freshly minted ver-0 token is rejected.
        assert client.get("/api/v1/review-engine/strategies", headers=headers2).status_code == 401
    finally:
        if saved is not None:
            main_module.app.dependency_overrides[key] = saved
