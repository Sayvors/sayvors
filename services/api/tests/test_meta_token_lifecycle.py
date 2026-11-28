"""Meta token classification: never blindly exchange business/system tokens."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from urllib.parse import parse_qs

from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter
from app.modules.channels.meta.token_rotation import (
    TokenMetadataError,
    classify_token,
    parse_debug_token,
    parse_exchange_payload,
)

NOW = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)


def test_parse_code_exchange_preserves_fields_and_expiry():
    payload = {
        "access_token": "opaque", "token_type": "bearer", "expires_in": 3600,
        "data_access_expires_at": int((NOW + timedelta(days=30)).timestamp()),
        "vendor_extension": {"kept": True},
    }
    info = parse_exchange_payload(payload, now=NOW)
    assert info.expires_at == NOW + timedelta(hours=1)
    assert info.data_access_expires_at == NOW + timedelta(days=30)
    assert info.effective_expires_at == NOW + timedelta(hours=1)
    assert info.expiry_source == "reported"


def test_missing_user_exchange_expiry_uses_documented_fallback():
    info = parse_exchange_payload(
        {"access_token": "opaque", "token_kind": "USER"},
        now=NOW, allow_user_fallback=True,
    )
    assert info.expires_at == NOW + timedelta(days=60)
    assert info.expiry_source == "user_exchange_fallback_60d"


def test_missing_business_expiry_never_gets_a_fake_deadline():
    info = parse_debug_token({"data": {
        "type": "BUSINESS_INTEGRATION_SYSTEM_USER", "is_valid": True,
        "app_id": "app-1",
    }}, now=NOW)
    assert info.expires_at is None
    assert info.data_access_expires_at is None
    assert info.effective_expires_at is None
    assert classify_token(info) == "non_expiring"


def test_system_user_with_reported_expiry_is_validate_only():
    info = parse_debug_token({"data": {
        "type": "SYSTEM_USER", "is_valid": True,
        "expires_at": int((NOW + timedelta(days=20)).timestamp()),
    }}, now=NOW)
    assert classify_token(info) == "validate_only"


def test_only_user_tokens_are_exchange_eligible():
    user = parse_debug_token({"data": {"type": "USER", "is_valid": True}}, now=NOW)
    business = parse_debug_token({"data": {
        "type": "BUSINESS_INTEGRATION_SYSTEM_USER", "is_valid": True,
    }}, now=NOW)
    assert classify_token(user) == "exchange_user"
    assert classify_token(business) == "non_expiring"


def test_invalid_or_malformed_expiry_is_not_silently_accepted():
    invalid = parse_debug_token({"data": {"type": "USER", "is_valid": False}}, now=NOW)
    assert classify_token(invalid) == "reauth"
    with pytest.raises(TokenMetadataError):
        parse_exchange_payload({"access_token": "opaque", "expires_in": "later"}, now=NOW)


class _Response(httpx.Response):
    def __init__(self, payload, status_code=200):
        super().__init__(status_code, json=payload)


@pytest.mark.asyncio
async def test_code_exchange_returns_complete_payload(monkeypatch):
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_SECRET", "secret-1")
    payload = {"access_token": "opaque", "expires_in": 60, "extension": {"x": 1}}
    requests = []

    def handle(request):
        requests.append(request)
        return _Response(payload)

    adapter = WhatsAppAdapter()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        assert await adapter.exchange_code("code-1") == payload
        assert len(requests) == 1
        assert not requests[0].url.query
        form = parse_qs(requests[0].content.decode())
        assert form["client_secret"] == ["secret-1"]
        assert form["code"] == ["code-1"]
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_inspection_uses_app_token_not_business_token(monkeypatch):
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_SECRET", "secret-1")
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/oauth/access_token"):
            assert not request.url.query
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["client_credentials"]
            assert form["client_secret"] == ["secret-1"]
            return _Response({"access_token": "app-access-token"})
        assert request.url.path.endswith("/debug_token")
        assert request.headers["Authorization"] == "Bearer app-access-token"
        assert request.url.params["input_token"] == "business-token"
        return _Response({"data": {"type": "USER", "is_valid": True}})

    adapter = WhatsAppAdapter()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        info = await adapter.inspect_token("business-token")
        assert info.token_kind == "USER"
        assert len(calls) == 2
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_long_lived_exchange_uses_fb_exchange_token(monkeypatch):
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_SECRET", "secret-1")
    seen = {}

    def handle(request):
        assert not request.url.query
        seen.update(parse_qs(request.content.decode()))
        return _Response({"access_token": "long-lived", "expires_in": 5184000})

    adapter = WhatsAppAdapter()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        result = await adapter.exchange_long_lived_token("short-lived")
        assert result["access_token"] == "long-lived"
        assert seen["grant_type"] == ["fb_exchange_token"]
        assert seen["fb_exchange_token"] == ["short-lived"]
        assert seen["client_id"] == ["app-1"]
        assert seen["client_secret"] == ["secret-1"]
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_connect_business_token_is_not_exchanged_or_given_fake_expiry(
    client, db, user_id, monkeypatch,
):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.modules.channels.meta import oauth, service
    from app.modules.channels.meta.models import MetaConnection
    from app.modules.channels.meta.token_rotation import TokenInfo

    state, _ = await oauth.create_transaction(db, user_id, "whatsapp")
    adapter = AsyncMock()
    adapter.exchange_code.return_value = {
        "access_token": "business-token", "token_type": "bearer",
        "expires_in": 3600, "extension": {"preserved": True},
    }
    adapter.inspect_token.return_value = TokenInfo(
        token_kind="BUSINESS_INTEGRATION_SYSTEM_USER", is_valid=True, app_id="app-1",
    )
    adapter.discover_assets.return_value = []
    monkeypatch.setattr(service, "get_adapter", lambda _provider: adapter)
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")

    response = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state, "code": "code-1", "waba_id": "waba-1"},
        headers={"host": "localhost"},
    )
    assert response.status_code == 200, response.text
    conn = (await db.execute(select(MetaConnection))).scalar_one()
    assert conn.token_kind == "BUSINESS_INTEGRATION_SYSTEM_USER"
    assert conn.token_expires_at is None
    assert conn.data_access_expires_at is None
    assert conn.token_last_rotated_at is None
    assert conn.status == "active"
    assert conn.connection_metadata["token_type"] == "bearer"
    assert conn.connection_metadata["extension"] == {"preserved": True}
    adapter.exchange_long_lived_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_user_token_rotates_immediately(client, db, user_id, monkeypatch):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.modules.channels.meta import oauth, service
    from app.modules.channels.meta.credentials import decrypt_credential
    from app.modules.channels.meta.models import MetaConnection
    from app.modules.channels.meta.token_rotation import TokenInfo

    state, _ = await oauth.create_transaction(db, user_id, "whatsapp")
    adapter = AsyncMock()
    adapter.exchange_code.return_value = {"access_token": "short-user-token"}
    adapter.inspect_token.return_value = TokenInfo(token_kind="USER", is_valid=True, app_id="app-1")
    adapter.exchange_long_lived_token.return_value = {
        "access_token": "long-user-token", "expires_in": 5184000,
    }
    adapter.discover_assets.return_value = []
    monkeypatch.setattr(service, "get_adapter", lambda _provider: adapter)
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")

    response = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state, "code": "code-1", "waba_id": "waba-1"},
        headers={"host": "localhost"},
    )
    assert response.status_code == 200, response.text
    conn = (await db.execute(select(MetaConnection))).scalar_one()
    assert decrypt_credential(conn.access_token_encrypted) == "long-user-token"
    assert conn.token_kind == "USER"
    assert conn.token_expires_at is not None
    assert conn.token_last_rotated_at is not None
    assert conn.token_rotation_attempts == 0
    adapter.exchange_long_lived_token.assert_awaited_once_with("short-user-token")


@pytest.mark.asyncio
async def test_connect_transient_rotation_keeps_original_token_recoverable(
    client, db, user_id, monkeypatch,
):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.modules.channels.meta import oauth, service
    from app.modules.channels.meta.credentials import decrypt_credential
    from app.modules.channels.meta.models import MetaConnection
    from app.modules.channels.meta.providers.base import MetaAPIError
    from app.modules.channels.meta.token_rotation import TokenInfo

    state, _ = await oauth.create_transaction(db, user_id, "whatsapp")
    adapter = AsyncMock()
    adapter.exchange_code.return_value = {"access_token": "short-user-token", "expires_in": 3600}
    adapter.inspect_token.return_value = TokenInfo(token_kind="USER", is_valid=True, app_id="app-1")
    adapter.exchange_long_lived_token.side_effect = MetaAPIError("safe transient", 503)
    adapter.discover_assets.return_value = []
    monkeypatch.setattr(service, "get_adapter", lambda _provider: adapter)
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")

    response = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state, "code": "code-1", "waba_id": "waba-1"},
        headers={"host": "localhost"},
    )
    assert response.status_code == 200, response.text
    conn = (await db.execute(select(MetaConnection))).scalar_one()
    assert decrypt_credential(conn.access_token_encrypted) == "short-user-token"
    assert conn.status == "error"
    assert conn.token_rotation_error == "exchange_transient"
    assert conn.token_expires_at is not None


@pytest.mark.asyncio
async def test_malformed_inspection_metadata_keeps_connect_recoverable():
    from unittest.mock import AsyncMock
    from app.modules.channels.meta.token_rotation import (
        TokenMetadataError, prepare_whatsapp_credentials,
    )

    adapter = AsyncMock()
    adapter.inspect_token.side_effect = TokenMetadataError("invalid expires_at")
    prepared = await prepare_whatsapp_credentials(
        adapter, {"access_token": "original-token", "expires_in": 3600}, now=NOW,
    )
    assert prepared["access_token"] == "original-token"
    assert prepared["_token_status"] == "error"
    assert prepared["token_rotation_error"] == "invalid_token_metadata"
    assert prepared["token_expires_at"] == NOW + timedelta(hours=1)
    adapter.exchange_long_lived_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_store_connection_never_persists_plaintext_nested_tokens(db):
    from app.modules.channels.meta import service
    from app.modules.channels.meta.credentials import decrypt_credential

    conn = await service.store_connection(
        db, "metadata-tenant", "whatsapp",
        {
            "access_token": "top-secret-token",
            "authorization": "Bearer header-secret",
            "extension": {
                "access_token": "nested-secret-token",
                "safe_value": "preserved",
                "deeper": {"client_secret": "nested-app-secret"},
            },
        },
    )
    metadata = repr(conn.connection_metadata)
    assert "top-secret-token" not in metadata
    assert "header-secret" not in metadata
    assert "nested-secret-token" not in metadata
    assert "nested-app-secret" not in metadata
    assert conn.connection_metadata["extension"]["safe_value"] == "preserved"
    assert decrypt_credential(conn.access_token_encrypted) == "top-secret-token"


@pytest.mark.asyncio
async def test_connect_user_exchange_without_expiry_uses_user_only_fallback(
    client, db, user_id, monkeypatch,
):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.modules.channels.meta import oauth, service
    from app.modules.channels.meta.models import MetaConnection
    from app.modules.channels.meta.token_rotation import TokenInfo

    state, _ = await oauth.create_transaction(db, user_id, "whatsapp")
    adapter = AsyncMock()
    adapter.exchange_code.return_value = {"access_token": "short-user-token"}
    adapter.inspect_token.return_value = TokenInfo(token_kind="USER", is_valid=True, app_id="app-1")
    adapter.exchange_long_lived_token.return_value = {"access_token": "long-user-token"}
    adapter.discover_assets.return_value = []
    monkeypatch.setattr(service, "get_adapter", lambda _provider: adapter)
    monkeypatch.setattr("app.modules.channels.meta.providers.whatsapp.settings.META_APP_ID", "app-1")
    before = datetime.now(timezone.utc)
    response = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state, "code": "code-1", "waba_id": "waba-1"},
        headers={"host": "localhost"},
    )
    assert response.status_code == 200, response.text
    conn = (await db.execute(select(MetaConnection))).scalar_one()
    assert conn.token_expires_at is not None
    assert 59 <= (conn.token_expires_at.replace(tzinfo=timezone.utc) - before).days <= 60
    assert conn.connection_metadata["token_expiry_source"] == "user_exchange_fallback_60d"


@pytest.mark.asyncio
async def test_whatsapp_session_without_code_cannot_reset_connection_or_alert_dedupe(
    client, db, user_id, monkeypatch,
):
    from unittest.mock import AsyncMock
    from sqlalchemy import func, select
    from app.modules.admin.models import AdminNotification
    from app.modules.channels.meta import oauth, service
    from app.modules.channels.meta.credentials import encrypt_credential
    from app.modules.channels.meta.models import MetaConnection
    from app.modules.channels.meta.reauth import mark_token_expiring
    from app.modules.notifications.models import Notification
    from app.modules.users.models import User

    db.add(User(
        id=user_id, first_name="Test", last_name="Tenant",
        email=f"{user_id}@example.com", password_hash="x",
    ))
    conn = MetaConnection(
        id="code-less-existing", tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("existing-token"),
        token_kind="USER", status="error", token_rotation_error=None,
    )
    db.add(conn)
    await db.commit()
    ciphertext = conn.access_token_encrypted
    assert await mark_token_expiring(
        db, conn, "rotation_unsupported", expected_ciphertext=ciphertext,
    ) is True
    await db.commit()
    state, _ = await oauth.create_transaction(db, user_id, "whatsapp")
    adapter = AsyncMock()
    adapter.discover_assets.return_value = []
    monkeypatch.setattr(service, "get_adapter", lambda _provider: adapter)

    response = client.post(
        "/api/v1/meta/whatsapp/session",
        json={"state": state, "waba_id": "replacement-waba"},
        headers={"host": "localhost"},
    )

    assert response.status_code == 422, response.text
    await db.refresh(conn)
    assert conn.access_token_encrypted == ciphertext
    assert conn.status == "error"
    assert conn.token_rotation_error == "rotation_unsupported"
    adapter.exchange_code.assert_not_awaited()
    assert await mark_token_expiring(
        db, conn, "rotation_unsupported", expected_ciphertext=ciphertext,
    ) is False
    await db.commit()
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(AdminNotification))).scalar_one() == 1


@pytest.mark.asyncio
async def test_store_whatsapp_connection_without_token_fails_closed(db):
    from app.modules.channels.meta import service
    from app.modules.channels.meta.credentials import decrypt_credential

    conn = await service.store_connection(
        db, "tokenless-upsert", "whatsapp", {"access_token": "existing-token"},
    )
    ciphertext = conn.access_token_encrypted
    conn.status = "error"
    conn.token_rotation_error = "rotation_unsupported"
    await db.commit()

    with pytest.raises(ValueError, match="access token"):
        await service.store_connection(
            db, "tokenless-upsert", "whatsapp", {"business_id": "replacement-business"},
        )

    await db.refresh(conn)
    assert conn.access_token_encrypted == ciphertext
    assert decrypt_credential(conn.access_token_encrypted) == "existing-token"
    assert conn.status == "error"
    assert conn.token_rotation_error == "rotation_unsupported"
    assert conn.meta_business_id is None


@pytest.mark.asyncio
async def test_store_whatsapp_connection_without_token_cannot_create_row(db):
    from sqlalchemy import func, select
    from app.modules.channels.meta import service
    from app.modules.channels.meta.models import MetaConnection

    with pytest.raises(ValueError, match="access token"):
        await service.store_connection(
            db, "tokenless-insert", "whatsapp", {"waba_id": "waba-only"},
        )
    assert (await db.execute(select(func.count()).select_from(MetaConnection))).scalar_one() == 0


@pytest.mark.asyncio
async def test_connect_exchange_preserves_prior_data_access_deadline():
    from unittest.mock import AsyncMock
    from app.modules.channels.meta.token_rotation import TokenInfo, prepare_whatsapp_credentials

    adapter = AsyncMock()
    adapter.inspect_token.return_value = TokenInfo(token_kind="USER", is_valid=True)
    adapter.exchange_long_lived_token.return_value = {
        "access_token": "long-user-token", "expires_in": 5184000,
    }
    prepared = await prepare_whatsapp_credentials(
        adapter,
        {
            "access_token": "short-user-token",
            "data_access_expires_at": int((NOW + timedelta(days=1)).timestamp()),
        },
        now=NOW,
    )

    assert prepared["access_token"] == "long-user-token"
    assert prepared["data_access_expires_at"] == NOW + timedelta(days=1)
