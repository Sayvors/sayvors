"""Platform operator management: CRUD, audit logging, and auth gating."""

import pytest
import pytest_asyncio

from app.config import settings

TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}
_CSRF = {**_HOST, "X-Requested-With": "XMLHttpRequest"}


@pytest.fixture(autouse=True)
def _admin_setup(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)

    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest_asyncio.fixture(autouse=True)
async def _patch_admin_async_session(monkeypatch, db, client):
    """Operator endpoints open their own async_session(); point it at the test DB.

    Reuse the shared fixture session to avoid SQLite StaticPool
    cross-session visibility issues (same pattern as reviews_worker).
    """
    from app.main import app
    from app.core.deps import get_db

    class _Borrowed:
        def __init__(self, real):
            self._real = real

        async def __aenter__(self):
            return self._real

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("app.database.async_session", lambda: _Borrowed(db))

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db


def _login(client):
    r = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=_HOST,
    )
    assert r.status_code == 200, r.text
    return {**_CSRF}


def test_operator_endpoints_require_admin(client):
    r = client.get("/api/v1/admin/operators", headers=_HOST)
    assert r.status_code in (401, 403)
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "x", "password": "password123", "role": "operator"},
        headers=_HOST,
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_list_and_patch_operator(client, db):
    headers = _login(client)

    # Create
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "ops1", "password": "password123", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "ops1"
    assert body["role"] == "operator"
    assert body["is_active"] is True
    assert "password_hash" not in body
    op_id = body["id"]

    # List contains bootstrap admin + new operator
    r = client.get("/api/v1/admin/operators", headers=headers)
    assert r.status_code == 200
    usernames = {op["username"] for op in r.json()}
    assert "ops1" in usernames

    # Duplicate username rejected
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "ops1", "password": "password123", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 409

    # Patch: disable, change role, reset password
    r = client.patch(
        f"/api/v1/admin/operators/{op_id}",
        json={"is_active": False, "role": "superadmin"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["role"] == "superadmin"

    r = client.patch(
        f"/api/v1/admin/operators/{op_id}",
        json={"password": "newpassword123"},
        headers=headers,
    )
    assert r.status_code == 200

    # Unknown operator
    r = client.patch(
        "/api/v1/admin/operators/no-such-id",
        json={"is_active": True},
        headers=headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_operator_create_writes_audit_log(client, db):
    headers = _login(client)
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "audited", "password": "password123", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 201

    logs = client.get("/api/v1/admin/audit-log?limit=50", headers=headers)
    assert logs.status_code == 200
    actions = [row["action"] for row in logs.json()]
    assert "operator.create" in actions


@pytest.mark.asyncio
async def test_operator_patch_writes_audit_log(client, db):
    headers = _login(client)
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "patchlog", "password": "password123", "role": "operator"},
        headers=headers,
    )
    op_id = r.json()["id"]
    r = client.patch(
        f"/api/v1/admin/operators/{op_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert r.status_code == 200

    logs = client.get("/api/v1/admin/audit-log?q=operator.update&limit=50", headers=headers)
    assert logs.status_code == 200
    assert any(row["action"] == "operator.update" for row in logs.json())


@pytest.mark.asyncio
async def test_audit_log_filters(client, db):
    headers = _login(client)
    client.post(
        "/api/v1/admin/operators",
        json={"username": "filter1", "password": "password123", "role": "operator"},
        headers=headers,
    )
    r = client.get("/api/v1/admin/audit-log?method=POST&q=operator.create&limit=20", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert rows
    assert all(row["method"] == "POST" for row in rows)
    assert all("operator.create" in row["action"] for row in rows)


def test_admin_login_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")

    async def _no_operators(*args, **kwargs):
        return False

    monkeypatch.setattr("app.modules.admin.router._has_any_operator", _no_operators)
    r = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "whatever"},
        headers=_HOST,
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_disabled_operator_cannot_login(client, db):
    headers = _login(client)
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "disabled-op", "password": "password123", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 201
    op_id = r.json()["id"]

    r = client.patch(
        f"/api/v1/admin/operators/{op_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert r.status_code == 200

    r = client.post(
        "/api/v1/admin/login",
        json={"username": "disabled-op", "password": "password123"},
        headers=_HOST,
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_operator_can_login_after_creation(client, db):
    headers = _login(client)
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "login-op", "password": "password123", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 201

    r = client.post(
        "/api/v1/admin/login",
        json={"username": "login-op", "password": "password123"},
        headers=_HOST,
    )
    assert r.status_code == 200
    body = r.json()
    assert "expires_in_minutes" in body
    # Cookie should be set
    assert settings.ADMIN_COOKIE_NAME in r.cookies


@pytest.mark.asyncio
async def test_operator_lockout_after_failed_logins(client, db, monkeypatch):
    headers = _login(client)
    monkeypatch.setattr(settings, "ADMIN_MAX_CONSECUTIVE_FAILURES", 3)

    async def _not_locked(*args, **kwargs):
        return False

    async def _register(*args, **kwargs):
        return 0

    monkeypatch.setattr("app.modules.admin.router._admin_locked_out", _not_locked)
    monkeypatch.setattr("app.modules.admin.router._register_admin_failure", _register)

    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "lockme", "password": "password123", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 201

    for _ in range(3):
        r = client.post(
            "/api/v1/admin/login",
            json={"username": "lockme", "password": "wrongpass"},
            headers=_HOST,
        )
        assert r.status_code == 401

    r = client.post(
        "/api/v1/admin/login",
        json={"username": "lockme", "password": "password123"},
        headers=_HOST,
    )
    assert r.status_code == 423


def test_operator_create_validation(client):
    headers = _login(client)
    # short password
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "shortpw", "password": "short", "role": "operator"},
        headers=headers,
    )
    assert r.status_code == 422
    # invalid role
    r = client.post(
        "/api/v1/admin/operators",
        json={"username": "badrole", "password": "password123", "role": "owner"},
        headers=headers,
    )
    assert r.status_code == 422
