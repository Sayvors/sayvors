"""WhatsApp token lifecycle state, worker, and safety regression tests."""
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.channels.meta.models import MetaConnection

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
