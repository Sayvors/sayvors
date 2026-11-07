"""Admin tenant lifecycle: suspend, export, purge, and their guards."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.admin.router import (
    PurgeTenantRequest,
    SuspendTenantRequest,
    admin_export_tenant,
    admin_purge_tenant,
    admin_reactivate_tenant,
    admin_suspend_tenant,
)
from app.modules.auth.models import RefreshToken
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.users.models import User
from app.modules.users.status import suspension_message

pytestmark = pytest.mark.asyncio


async def _seed(db, user_id: str) -> None:
    db.add(User(
        id=user_id,
        email="tenant@example.com",
        first_name="Tenant",
        last_name="Owner",
        password_hash="hashed-secret",
        onboarded=True,
        email_verified=True,
    ))
    db.add(Channel(
        id="tenant-channel-0000-0000-000000000001",
        user_id=user_id,
        platform="whatsapp",
        platform_user_id="wa-1",
        display_name="Main line",
        status="active",
    ))
    db.add(ChannelMessage(
        id="tenant-message-0000-0000-000000000001",
        channel_id="tenant-channel-0000-0000-000000000001",
        direction="inbound",
        content="hello from a customer",
    ))
    db.add(RefreshToken(
        user_id=user_id,
        token_hash="hash-1",
        fingerprint="fp",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    await db.commit()


async def _call(fn, user_id, db, **kwargs):
    return await fn(
        user_id=user_id,
        _admin={"username": "test-operator"},
        _rate_limit=None,
        db=db,
        **kwargs,
    )


async def test_suspend_blocks_members_and_revokes_sessions(db, user_id):
    await _seed(db, user_id)

    detail = await _call(admin_suspend_tenant, user_id, db, body=SuspendTenantRequest(reason="chargeback"))

    assert detail.suspended_at
    assert detail.suspension_reason == "chargeback"
    user = await db.get(User, user_id)
    await db.refresh(user)
    assert user.suspended_at is not None
    assert user.token_version == 1
    token = (await db.execute(__import__("sqlalchemy").select(RefreshToken))).scalar_one()
    assert token.revoked is True
    assert await suspension_message(db, user) == "chargeback"


async def test_reactivate_clears_the_block(db, user_id):
    await _seed(db, user_id)
    await _call(admin_suspend_tenant, user_id, db, body=SuspendTenantRequest(reason=None))

    detail = await _call(admin_reactivate_tenant, user_id, db)

    assert detail.suspended_at is None
    assert detail.suspension_reason is None
    user = await db.get(User, user_id)
    await db.refresh(user)
    assert user.suspended_at is None


async def test_member_is_suspended_through_the_owner(db, user_id, other_user_id):
    """Employees inherit the owner's suspension without their own flag."""
    await _seed(db, user_id)
    member = User(
        id=other_user_id,
        email="member@example.com",
        first_name="Team",
        last_name="Member",
        password_hash="x",
        tenant_id=user_id,
    )
    db.add(member)
    await db.commit()
    await _call(admin_suspend_tenant, user_id, db, body=SuspendTenantRequest(reason="owner suspended"))

    assert await suspension_message(db, member) == "owner suspended"


async def test_export_contains_tenant_rows_without_secrets(db, user_id):
    await _seed(db, user_id)

    response = await _call(admin_export_tenant, user_id, db)

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    bundle = __import__("json").loads(response.body)
    assert bundle["tenant"]["email"] == "tenant@example.com"
    assert bundle["counts"]["channel_messages"] == 1
    assert "hello from a customer" in str(bundle["tables"]["channel_messages"])
    # Hashes must never leave in an export.
    assert "hashed-secret" not in str(bundle)
    assert "password_hash" not in str(bundle)


async def test_purge_requires_the_exact_email(db, user_id):
    await _seed(db, user_id)

    with pytest.raises(Exception) as exc:
        await _call(admin_purge_tenant, user_id, db, body=PurgeTenantRequest(confirm="wrong@example.com"))
    assert "does not match" in str(exc.value)

    # Nothing was deleted by the refused attempt.
    assert await db.get(User, user_id) is not None


async def test_purge_removes_the_whole_tenant(db, user_id):
    from sqlalchemy import select

    await _seed(db, user_id)

    result = await _call(
        admin_purge_tenant, user_id, db, body=PurgeTenantRequest(confirm="TENANT@example.com")
    )

    assert result["total_rows"] >= 3
    assert await db.get(User, user_id) is None
    remaining_channels = (await db.execute(select(Channel))).scalars().all()
    assert remaining_channels == []
    remaining_messages = (await db.execute(select(ChannelMessage))).scalars().all()
    assert remaining_messages == []
    remaining_tokens = (await db.execute(select(RefreshToken))).scalars().all()
    assert remaining_tokens == []
