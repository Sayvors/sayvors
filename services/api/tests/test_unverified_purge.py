"""Never-verified accounts are deleted after the grace period, with a trace."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.modules.admin.models import PurgedAccount
from app.modules.users.models import User
from app.modules.users.unverified_purge import purge_unverified_accounts

pytestmark = pytest.mark.asyncio


def _user(user_id: str, email: str, *, verified: bool, age_days: int) -> User:
    return User(
        id=user_id,
        email=email,
        first_name="Test",
        last_name="User",
        password_hash="x",
        email_verified=verified,
        newsletter=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


async def test_old_unverified_account_is_purged_and_archived(db, monkeypatch):
    monkeypatch.setattr(settings, "UNVERIFIED_ACCOUNT_TTL_DAYS", 7)
    db.add_all(
        [
            _user("purge-old-unverified", "old@example.com", verified=False, age_days=10),
            _user("purge-new-unverified", "new@example.com", verified=False, age_days=1),
            _user("purge-old-verified", "verified@example.com", verified=True, age_days=10),
        ]
    )
    await db.commit()

    purged = await purge_unverified_accounts(db, limit=10)

    assert purged == 1
    assert await db.get(User, "purge-old-unverified") is None
    assert await db.get(User, "purge-new-unverified") is not None
    assert await db.get(User, "purge-old-verified") is not None

    archive = await db.get(PurgedAccount, "purge-old-unverified")
    assert archive is not None
    assert archive.email == "old@example.com"
    assert archive.reason == "unverified"
    assert archive.status == "purged"
    assert archive.signed_up_at is not None
    assert archive.metadata_json["plan"]


async def test_admin_can_run_purge_and_read_the_trace(client, db, monkeypatch):
    from app.core.deps import require_admin
    from app.main import app
    from app.modules.admin.router import admin_rate_limit

    monkeypatch.setattr(settings, "UNVERIFIED_ACCOUNT_TTL_DAYS", 7)
    db.add(_user("purge-api-old", "api-old@example.com", verified=False, age_days=10))
    await db.commit()

    app.dependency_overrides[require_admin] = lambda: {
        "admin": True,
        "operator_id": "op-1",
        "username": "tester",
        "role": "superadmin",
    }
    app.dependency_overrides[admin_rate_limit] = lambda: None
    try:
        run = client.post("/api/v1/admin/purged-accounts/run")
        assert run.status_code == 200, run.text
        assert run.json()["purged"] == 1

        listing = client.get("/api/v1/admin/purged-accounts")
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 1
        assert body["items"][0]["email"] == "api-old@example.com"
        assert body["items"][0]["status"] == "purged"
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(admin_rate_limit, None)


async def test_manual_admin_purge_is_archived(client, db):
    from app.core.deps import require_admin
    from app.main import app
    from app.modules.admin.router import admin_rate_limit

    user = _user("purge-admin", "manual@example.com", verified=True, age_days=1)
    db.add(user)
    await db.commit()

    app.dependency_overrides[require_admin] = lambda: {
        "admin": True,
        "operator_id": "op-1",
        "username": "tester",
        "role": "superadmin",
    }
    app.dependency_overrides[admin_rate_limit] = lambda: None
    try:
        response = client.post(
            "/api/v1/admin/tenants/purge-admin/purge",
            json={"confirm": "manual@example.com"},
        )
        assert response.status_code == 200, response.text
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(admin_rate_limit, None)

    archive = await db.get(PurgedAccount, "purge-admin")
    assert archive is not None
    assert archive.email == "manual@example.com"
    assert archive.reason == "admin"
    assert archive.status == "purged"
    assert archive.metadata_json["purged_by"] == "tester"


async def test_verified_and_recent_accounts_are_untouched(db, monkeypatch):
    monkeypatch.setattr(settings, "UNVERIFIED_ACCOUNT_TTL_DAYS", 30)
    db.add(_user("purge-recent", "recent@example.com", verified=False, age_days=5))
    await db.commit()

    assert await purge_unverified_accounts(db, limit=10) == 0
    assert await db.get(User, "purge-recent") is not None
    assert (await db.execute(select(PurgedAccount))).scalars().all() == []
