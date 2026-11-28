"""WhatsApp token lifecycle state, worker, and safety regression tests."""
from datetime import datetime, timedelta, timezone

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.modules.admin.models import AdminNotification
from app.modules.channels.meta.credentials import decrypt_connection_token, encrypt_credential
from app.modules.channels.meta.models import MetaConnection
from app.modules.channels.meta.reauth import handle_meta_auth_failure, mark_needs_reauth
from app.modules.channels.meta.token_rotation import token_health
from app.modules.notifications.models import Notification
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def test_meta_connection_has_token_lifecycle_fields_and_due_index(db):
    conn = MetaConnection(
        id="rotation-state", tenant_id="tenant-rotation", provider="whatsapp",
        access_token_encrypted="ciphertext", token_kind="USER",
        token_expires_at=datetime.now(timezone.utc) + timedelta(days=2),
        data_access_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        token_last_rotated_at=datetime.now(timezone.utc),
        token_rotation_attempts=2, token_rotation_error="exchange_transient",
        token_rotation_next_attempt_at=datetime.now(timezone.utc) + timedelta(hours=1),
        token_rotation_lease_until=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    assert conn.token_kind == "USER"
    assert conn.token_rotation_attempts == 2
    assert conn.token_rotation_error == "exchange_transient"
    assert conn.token_rotation_lease_until is not None

    indexes = {
        idx.name: [column.name for column in idx.columns]
        for idx in MetaConnection.__table__.indexes
    }
    assert indexes["ix_meta_connections_token_rotation_due"] == [
        "provider", "status", "token_expires_at",
    ]


@pytest.mark.parametrize("status", ["expired", "revoked", "needs_reauth"])
async def test_guard_rejects_unusable_whatsapp_statuses(status):
    conn = SimpleNamespace(
        provider="whatsapp", status=status,
        access_token_encrypted=encrypt_credential("secret-token"),
        token_expires_at=None, data_access_expires_at=None,
    )
    assert decrypt_connection_token(conn) is None


async def test_guard_rejects_expired_token_or_data_access_and_allows_leweway():
    now = datetime.now(timezone.utc)
    base = dict(
        provider="whatsapp", status="active",
        access_token_encrypted=encrypt_credential("secret-token"),
    )
    assert decrypt_connection_token(SimpleNamespace(
        **base, token_expires_at=now - timedelta(seconds=1), data_access_expires_at=None,
    )) is None
    assert decrypt_connection_token(SimpleNamespace(
        **base, token_expires_at=None, data_access_expires_at=now,
    )) is None
    assert decrypt_connection_token(SimpleNamespace(
        **base, token_expires_at=now + timedelta(days=1), data_access_expires_at=None,
    )) == "secret-token"


async def test_guard_does_not_change_facebook_behavior():
    conn = SimpleNamespace(
        provider="facebook", status="expired",
        access_token_encrypted=encrypt_credential("facebook-token"),
        token_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        data_access_expires_at=None,
    )
    assert decrypt_connection_token(conn) == "facebook-token"


async def test_coarse_token_health():
    now = datetime.now(timezone.utc)
    assert token_health(SimpleNamespace(provider="whatsapp", status="needs_reauth")) == "reauth_required"
    assert token_health(SimpleNamespace(
        provider="whatsapp", status="active", token_kind="USER",
        token_expires_at=now + timedelta(days=30), data_access_expires_at=None,
        token_last_rotated_at=now, token_rotation_lease_until=None,
    )) == "healthy"
    assert token_health(SimpleNamespace(
        provider="whatsapp", status="active", token_kind="USER",
        token_expires_at=now + timedelta(days=2), data_access_expires_at=None,
        token_last_rotated_at=now, token_rotation_lease_until=None,
    )) == "rotating"
    assert token_health(SimpleNamespace(
        provider="whatsapp", status="active", token_kind="BUSINESS_INTEGRATION_SYSTEM_USER",
        token_expires_at=None, data_access_expires_at=None,
        token_last_rotated_at=None, token_rotation_lease_until=None,
    )) == "healthy"


async def _seed_reauth_connection(db, user_id):
    db.add(User(
        id=user_id, first_name="Test", last_name="Tenant",
        email=f"{user_id}@example.com", password_hash="x",
    ))
    conn = MetaConnection(
        id="reauth-connection", tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("do-not-leak-token"),
        token_kind="USER", status="active",
    )
    db.add(conn)
    await db.commit()
    return conn


async def test_reauth_marker_alerts_once_and_never_leaks_token(db, user_id, caplog):
    conn = await _seed_reauth_connection(db, user_id)
    assert await mark_needs_reauth(db, conn, "auth_rejected") is True
    await db.commit()
    assert await mark_needs_reauth(db, conn, "auth_rejected") is False
    await db.commit()

    assert conn.status == "needs_reauth"
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(AdminNotification))).scalar_one() == 1
    notification = (await db.execute(select(Notification))).scalar_one()
    admin = (await db.execute(select(AdminNotification))).scalar_one()
    assert notification.title == "WhatsApp needs reconnection"
    assert notification.href == "/dashboard/channels"
    assert admin.severity == "warning"
    assert "auth_rejected" in admin.body
    assert "do-not-leak-token" not in repr(notification.__dict__)
    assert "do-not-leak-token" not in repr(admin.__dict__)
    assert "do-not-leak-token" not in caplog.text


async def test_validation_permanent_auth_marks_and_alerts_but_transient_does_not(
    db, user_id, monkeypatch,
):
    from app.modules.channels.meta import service

    conn = await _seed_reauth_connection(db, user_id)
    conn.meta_business_id = "business-1"
    await db.commit()
    adapter = AsyncMock()
    adapter.validate_connection.return_value = (False, "auth_rejected")
    monkeypatch.setattr(service, "get_adapter", lambda _provider: adapter)
    status, _ = await service.validate_connection(db, user_id, "whatsapp")
    assert status == "needs_reauth"
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1

    conn.status = "active"
    conn.token_rotation_error = None
    await db.commit()
    adapter.validate_connection.return_value = (False, "transient_error")
    status, _ = await service.validate_connection(db, user_id, "whatsapp")
    assert status == "error"
    assert conn.token_rotation_error == "validation_transient"
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1


async def test_connection_api_exposes_coarse_health_without_credentials(client, db, user_id):
    db.add(User(
        id=user_id, first_name="Test", last_name="Tenant",
        email=f"{user_id}@example.com", password_hash="x",
    ))
    db.add(MetaConnection(
        id="api-health", tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("api-secret-token"),
        token_kind="USER", status="active",
        token_expires_at=datetime.now(timezone.utc) + timedelta(days=2),
        token_last_rotated_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    response = client.get("/api/v1/meta/connections", headers={"host": "localhost"})
    assert response.status_code == 200
    payload = response.json()["connections"][0]
    assert payload["token_health"] == "rotating"
    assert payload["token_expires_at"] is not None
    assert payload["token_last_rotated_at"] is not None
    assert "access_token" not in payload
    assert "api-secret-token" not in response.text


async def test_send_auth_failure_marks_but_rate_limit_does_not(db, user_id, caplog):
    from app.modules.channels.meta.providers.base import MetaAPIError

    conn = await _seed_reauth_connection(db, user_id)
    assert await handle_meta_auth_failure(
        db, conn, MetaAPIError("provider echoed do-not-leak-token", 401),
    ) is True
    await db.commit()
    assert conn.status == "needs_reauth"
    assert "do-not-leak-token" not in caplog.text

    conn.status = "active"
    conn.token_rotation_error = None
    await db.commit()
    assert await handle_meta_auth_failure(
        db, conn, MetaAPIError("rate limited", 429),
    ) is False
    await db.commit()
    assert conn.status == "active"
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1
