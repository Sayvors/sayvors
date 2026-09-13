"""Meta OAuth transaction tests: valid/invalid/expired/reused/wrong-tenant."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.modules.channels.meta import oauth as _oauth
from app.modules.channels.meta.models import MetaOAuthTransaction

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
