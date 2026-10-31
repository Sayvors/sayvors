"""Per-tenant feature overrides — the admin "Special list" contract.

A plan defines the baseline feature set. A tenant may carry its own override
dict, which wins per key, so support can grant (or revoke) one capability for
one account without forking the plan for everybody. Tenants with at least one
override are the "Special list"; clearing the dict puts them back on plain
plan inheritance and off that list.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings
from app.modules.billing.entitlements import merge_feature_override

# bcrypt(4 rounds) of "test-admin-pass" — fast for tests, never production.
TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr("app.modules.auth.rate_limit.rate_limit", _allow)


@pytest.fixture
def admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=_HOST,
    )
    assert r.status_code == 200, r.text
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def admin_db(monkeypatch, db):
    """Point the admin router's own session factory at the in-memory DB.

    Admin routes open ``app.database.async_session`` directly instead of the
    request-scoped ``get_db`` dependency, so the dependency override alone does
    not reach them.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)
    return factory


async def _seed_tenant(db, tenant_id="tenant-override-1", email="override@example.com"):
    from app.modules.billing.models import Plan, TenantSubscription
    from app.modules.users.models import User

    db.add(User(
        id=tenant_id, email=email, first_name="Over", last_name="Ride",
        password_hash="x", email_verified=True,
    ))
    plan = Plan(
        id="plan-override-test", slug="override-test", name="Override Test",
        price_cents=0, included_credit_cents=0, max_channels=None,
        max_messages_per_month=None,
        features={"channels": True, "messaging": True, "voice": False},
        is_active=True, sort_order=50,
    )
    db.add(plan)
    db.add(TenantSubscription(
        id="sub-override-1", tenant_id=tenant_id, plan_id=plan.id, status="active",
    ))
    await db.commit()
    return tenant_id


# ── merge semantics ──────────────────────────────────────────────────


def test_override_wins_per_key():
    merged = merge_feature_override({"voice": False, "posts": True}, {"voice": True})
    assert merged == {"voice": True, "posts": True}


def test_absent_override_key_inherits_the_plan():
    merged = merge_feature_override({"voice": True, "posts": False}, {"posts": True})
    assert merged["voice"] is True
    assert merged["posts"] is True


def test_empty_override_is_pure_inheritance():
    plan = {"voice": True, "posts": False}
    assert merge_feature_override(plan, {}) == plan
    assert merge_feature_override(plan, None) == plan


def test_unknown_override_keys_cannot_inject_a_feature():
    merged = merge_feature_override({"voice": True, "legacy_key": True}, {"nonsense": True})
    # The plan keeps its own keys (nothing that already worked may vanish)...
    assert merged == {"voice": True, "legacy_key": True}


# ── API ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_special_route_is_not_shadowed_by_tenant_detail(client, admin_headers, admin_db):
    """`/tenants/special` must resolve as a literal path, not as a tenant id.

    It is declared before `/tenants/{user_id}` for exactly this reason; if the
    order regresses the request 404s looking up tenant "special".
    """
    r = client.get("/api/v1/admin/tenants/special", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_tenant_appears_on_special_list_after_override(client, db, admin_db, admin_headers):
    uid = await _seed_tenant(db)

    r = client.put(
        f"/api/v1/admin/tenants/{uid}/features",
        headers=admin_headers,
        json={"features": {"voice": True}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["features_override"] == {"voice": True}

    listed = client.get("/api/v1/admin/tenants/special", headers=admin_headers)
    assert listed.status_code == 200
    ids = [row["tenant_id"] for row in listed.json()]
    assert uid in ids


@pytest.mark.asyncio
async def test_entitlements_apply_the_override(client, db, admin_db, admin_headers):
    uid = await _seed_tenant(db)
    client.put(
        f"/api/v1/admin/tenants/{uid}/features",
        headers=admin_headers,
        json={"features": {"voice": True}},
    )

    r = client.get(f"/api/v1/admin/tenants/{uid}/entitlements", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["features"]["voice"] is True
    assert body["features_override"] == {"voice": True}


@pytest.mark.asyncio
async def test_clearing_overrides_removes_the_tenant_from_the_list(client, db, admin_db, admin_headers):
    uid = await _seed_tenant(db, tenant_id="tenant-override-2", email="override2@example.com")
    client.put(
        f"/api/v1/admin/tenants/{uid}/features",
        headers=admin_headers,
        json={"features": {"voice": True, "posts": False}},
    )
    r = client.put(
        f"/api/v1/admin/tenants/{uid}/features",
        headers=admin_headers,
        json={"features": {}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["features_override"] == {}

    listed = client.get("/api/v1/admin/tenants/special", headers=admin_headers)
    assert uid not in [row["tenant_id"] for row in listed.json()]


@pytest.mark.asyncio
async def test_unknown_feature_keys_are_ignored(client, db, admin_db, admin_headers):
    uid = await _seed_tenant(db, tenant_id="tenant-override-3", email="override3@example.com")
    r = client.put(
        f"/api/v1/admin/tenants/{uid}/features",
        headers=admin_headers,
        json={"features": {"voice": True, "definitely_not_a_feature": True}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["features_override"] == {"voice": True}


@pytest.mark.asyncio
async def test_unknown_tenant_is_a_404_not_a_subscription_row(client, db, admin_db, admin_headers):
    """A typo must not create a subscription pointing at a nonexistent user."""
    r = client.put(
        "/api/v1/admin/tenants/no-such-tenant/features",
        headers=admin_headers,
        json={"features": {"voice": True}},
    )
    assert r.status_code == 404, r.text
