"""Bounded, lease-based WhatsApp token maintenance worker tests."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.modules.admin.models import AdminNotification
from app.modules.channels.meta.credentials import decrypt_credential, encrypt_credential
from app.modules.channels.meta.models import MetaConnection
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.token_rotation import (
    ROTATION_BATCH_SIZE,
    TokenInfo,
    claim_connection,
    persist_rotation_success,
    record_transient_failure,
    run_rotation_pass,
    select_due_connection_ids,
)
from app.modules.notifications.models import Notification
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@asynccontextmanager
async def _borrowed(db):
    yield db


async def _seed(db, connection_id, *, kind="USER", expires_at=NOW + timedelta(days=2),
                data_access_expires_at=None, last_rotated_at=NOW - timedelta(days=50),
                status="active", provider="whatsapp", lease_until=None, next_attempt_at=None):
    conn = MetaConnection(
        id=connection_id, tenant_id=f"tenant-{connection_id}", provider=provider,
        access_token_encrypted=encrypt_credential(f"token-{connection_id}"),
        token_kind=kind, token_expires_at=expires_at,
        data_access_expires_at=data_access_expires_at,
        token_last_rotated_at=last_rotated_at, status=status,
        token_rotation_lease_until=lease_until,
        token_rotation_next_attempt_at=next_attempt_at,
    )
    db.add(conn)
    await db.commit()
    return conn


async def test_due_selection_is_bounded_and_skips_healthy_system_tokens(db):
    for index in range(ROTATION_BATCH_SIZE + 1):
        await _seed(db, f"due-{index}")
    await _seed(db, "healthy-business", kind="BUSINESS_INTEGRATION_SYSTEM_USER",
                expires_at=None, last_rotated_at=None)
    await _seed(db, "healthy-user", expires_at=NOW + timedelta(days=30))
    await _seed(db, "other-provider", provider="facebook")
    await _seed(db, "reauth", status="needs_reauth")
    await _seed(db, "leased", lease_until=NOW + timedelta(minutes=5))
    await _seed(db, "backoff", next_attempt_at=NOW + timedelta(minutes=5))

    ids = await select_due_connection_ids(db, now=NOW)
    assert len(ids) == ROTATION_BATCH_SIZE
    assert "healthy-business" not in ids
    assert "healthy-user" not in ids
    assert "other-provider" not in ids
    assert "reauth" not in ids
    assert "leased" not in ids
    assert "backoff" not in ids


async def test_claim_is_single_use_and_clears_backoff(db):
    conn = await _seed(db, "claim-me", next_attempt_at=NOW - timedelta(minutes=1))
    claim = await claim_connection(db, conn.id, now=NOW)
    assert claim is not None
    assert claim.token_rotation_lease_until is not None
    await db.commit()
    assert await claim_connection(db, conn.id, now=NOW) is None
    reclaimed = await claim_connection(db, conn.id, now=NOW + timedelta(minutes=11))
    assert reclaimed is not None
    await db.rollback()


async def test_due_selection_uses_earlier_data_access_deadline(db):
    await _seed(db, "data-access-due", expires_at=NOW + timedelta(days=30),
                data_access_expires_at=NOW + timedelta(days=2))
    await _seed(db, "data-access-healthy", expires_at=NOW + timedelta(days=30),
                data_access_expires_at=NOW + timedelta(days=20))
    ids = await select_due_connection_ids(db, now=NOW)
    assert ids == ["data-access-due"]


async def test_unknown_expiry_is_due_for_non_system_but_not_system_tokens(db):
    await _seed(db, "page-unknown-expiry", kind="PAGE", expires_at=None,
                last_rotated_at=None)
    await _seed(db, "system-unknown-expiry", kind="SYSTEM_USER", expires_at=None,
                last_rotated_at=None)
    ids = await select_due_connection_ids(db, now=NOW)
    assert ids == ["page-unknown-expiry"]


async def test_successful_rotation_encrypts_token_and_clears_error(db):
    conn = await _seed(db, "rotate-me")
    conn.token_rotation_error = "exchange_transient"
    conn.token_rotation_attempts = 3
    await db.commit()
    ciphertext = conn.access_token_encrypted
    claim = await claim_connection(db, conn.id, now=NOW)
    await db.commit()
    info = TokenInfo(token_kind="USER", expires_at=NOW + timedelta(days=60), is_valid=True)
    assert await persist_rotation_success(
        db, claim, token="new-plaintext-token", info=info, rotated_at=NOW,
        expected_ciphertext=ciphertext, expected_lease_until=claim.token_rotation_lease_until,
    ) is True
    await db.commit()
    await db.refresh(conn)
    assert decrypt_credential(conn.access_token_encrypted) == "new-plaintext-token"
    assert conn.access_token_encrypted != ciphertext
    assert _utc(conn.token_expires_at) == NOW + timedelta(days=60)
    assert _utc(conn.token_last_rotated_at) == NOW
    assert conn.token_rotation_attempts == 0
    assert conn.token_rotation_error is None
    assert conn.token_rotation_lease_until is None
    assert conn.status == "active"


async def test_stale_compare_and_swap_cannot_overwrite_reconnect(db):
    conn = await _seed(db, "stale-cas")
    ciphertext = conn.access_token_encrypted
    claim = await claim_connection(db, conn.id, now=NOW)
    await db.commit()
    conn.access_token_encrypted = encrypt_credential("reconnected-token")
    await db.commit()
    assert await persist_rotation_success(
        db, claim, token="stale-token", info=TokenInfo(token_kind="USER", is_valid=True),
        rotated_at=NOW, expected_ciphertext=ciphertext,
        expected_lease_until=claim.token_rotation_lease_until,
    ) is False
    await db.commit()
    await db.refresh(conn)
    assert decrypt_credential(conn.access_token_encrypted) == "reconnected-token"


async def test_transient_failure_retains_token_and_schedules_backoff(db):
    conn = await _seed(db, "transient")
    ciphertext = conn.access_token_encrypted
    claim = await claim_connection(db, conn.id, now=NOW)
    await db.commit()
    assert await record_transient_failure(
        db, claim, code="exchange_transient", now=NOW,
        expected_ciphertext=ciphertext,
        expected_lease_until=claim.token_rotation_lease_until,
    ) is True
    await db.commit()
    await db.refresh(conn)
    assert conn.access_token_encrypted == ciphertext
    assert conn.status == "error"
    assert conn.token_rotation_attempts == 1
    assert conn.token_rotation_error == "exchange_transient"
    assert _utc(conn.token_rotation_next_attempt_at) == NOW + timedelta(minutes=15)


async def test_pass_rotates_due_user_once_and_skips_non_expiring_business(db):
    user = await _seed(db, "run-user")
    await _seed(db, "run-business", kind="BUSINESS_INTEGRATION_SYSTEM_USER",
                expires_at=None, last_rotated_at=None)
    adapter = AsyncMock()
    adapter.exchange_long_lived_token.return_value = {
        "access_token": "rotated-plaintext", "expires_in": 5184000,
    }
    processed = await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    )
    assert processed == 1
    await db.refresh(user)
    assert decrypt_credential(user.access_token_encrypted) == "rotated-plaintext"
    assert _utc(user.token_expires_at) == NOW + timedelta(days=60)
    adapter.exchange_long_lived_token.assert_awaited_once_with("token-run-user")
    adapter.inspect_token.assert_not_awaited()

    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 0
    adapter.exchange_long_lived_token.assert_awaited_once()


async def test_unknown_token_is_inspected_and_business_token_is_enrolled_without_exchange(db):
    conn = await _seed(db, "unknown-business", kind=None, expires_at=None,
                       last_rotated_at=None)
    adapter = AsyncMock()
    adapter.inspect_token.return_value = TokenInfo(
        token_kind="BUSINESS_INTEGRATION_SYSTEM_USER", is_valid=True,
    )
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 1
    await db.refresh(conn)
    assert conn.token_kind == "BUSINESS_INTEGRATION_SYSTEM_USER"
    assert conn.token_expires_at is None
    assert conn.token_last_rotated_at is None
    assert conn.status == "active"
    adapter.inspect_token.assert_awaited_once_with("token-unknown-business")
    adapter.exchange_long_lived_token.assert_not_awaited()


async def test_enrolled_user_with_unknown_expiry_is_inspected_not_blindly_rotated(db):
    conn = await _seed(db, "user-unknown-expiry", expires_at=None)
    adapter = AsyncMock()
    adapter.inspect_token.return_value = TokenInfo(
        token_kind="USER", is_valid=True, expires_at=NOW + timedelta(days=60),
    )
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 1
    await db.refresh(conn)
    assert _utc(conn.token_expires_at) == NOW + timedelta(days=60)
    adapter.inspect_token.assert_awaited_once_with("token-user-unknown-expiry")
    adapter.exchange_long_lived_token.assert_not_awaited()


async def test_permanent_rotation_failure_marks_reauth_and_alerts_once(db, user_id, caplog):
    db.add(User(
        id=user_id, first_name="Test", last_name="Tenant",
        email=f"{user_id}@example.com", password_hash="x",
    ))
    conn = await _seed(db, "permanent")
    conn.tenant_id = user_id
    await db.commit()
    adapter = AsyncMock()
    adapter.exchange_long_lived_token.side_effect = MetaAPIError(
        "provider echoed do-not-leak-token", 401,
    )
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 1
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 0
    await db.refresh(conn)
    assert conn.status == "needs_reauth"
    assert conn.token_rotation_error == "rotation_rejected"
    assert decrypt_credential(conn.access_token_encrypted) == "token-permanent"
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(AdminNotification))).scalar_one() == 1
    assert "do-not-leak-token" not in caplog.text


async def test_transient_pass_failure_retries_only_after_backoff(db):
    conn = await _seed(db, "run-transient")
    adapter = AsyncMock()
    adapter.exchange_long_lived_token.side_effect = MetaAPIError("unavailable", 503)
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 1
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 0
    await db.refresh(conn)
    assert conn.status == "error"
    assert conn.token_rotation_error == "exchange_transient"
    assert conn.token_rotation_attempts == 1
    assert decrypt_credential(conn.access_token_encrypted) == "token-run-transient"

    adapter.exchange_long_lived_token.side_effect = None
    adapter.exchange_long_lived_token.return_value = {
        "access_token": "recovered-token", "expires_in": 5184000,
    }
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter,
        now=NOW + timedelta(minutes=16), concurrency=1,
    ) == 1
    await db.refresh(conn)
    assert conn.status == "active"
    assert decrypt_credential(conn.access_token_encrypted) == "recovered-token"


async def test_unsupported_expiring_token_alerts_without_exchange(db, user_id):
    db.add(User(
        id=user_id, first_name="Test", last_name="Tenant",
        email=f"{user_id}@example.com", password_hash="x",
    ))
    conn = await _seed(db, "unsupported", kind="PAGE", expires_at=NOW + timedelta(days=2),
                       last_rotated_at=None)
    conn.tenant_id = user_id
    await db.commit()
    adapter = AsyncMock()
    adapter.inspect_token.return_value = TokenInfo(
        token_kind="PAGE", is_valid=True, expires_at=NOW + timedelta(days=2),
    )
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter, now=NOW, concurrency=1,
    ) == 1
    assert await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=adapter,
        now=NOW + timedelta(hours=25), concurrency=1,
    ) == 1
    await db.refresh(conn)
    assert conn.status == "error"
    assert conn.token_rotation_error == "rotation_unsupported"
    assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(AdminNotification))).scalar_one() == 1
    adapter.exchange_long_lived_token.assert_not_awaited()


async def test_worker_caps_concurrent_meta_calls(db, monkeypatch):
    for index in range(12):
        await _seed(db, f"concurrent-{index}")
    active = 0
    peak = 0

    async def fake_process(connection_id, *, adapter, now, semaphore, session_factory):
        nonlocal active, peak
        async with semaphore:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
        return True

    monkeypatch.setattr(
        "app.modules.channels.meta.token_rotation._process_connection", fake_process,
    )
    processed = await run_rotation_pass(
        session_factory=lambda: _borrowed(db), adapter=AsyncMock(), now=NOW, concurrency=5,
    )
    assert processed == 12
    assert peak == 5
