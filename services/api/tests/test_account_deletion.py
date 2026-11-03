"""Thirty-day owner personal-data deletion.

The owner profile is anonymized; the workspace business records stay. The
request is cancellable by signing in, and the day-25 reminder is sent once.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import hash_password, login
from app.modules.channels.models import Channel, ChannelMessage, ReviewReply
from app.modules.channels.service import (
    decrypt_message_content,
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)
from app.modules.posts.models import LocationPost
from app.modules.users import account_deletion
from app.modules.users.models import AccountDeletionRequest, User


async def _seed_user(db, user_id):
    db.add(User(
        id=user_id,
        first_name="Ahmed",
        last_name="Khan",
        email="ahmed@example.com",
        password_hash=hash_password("Secret123!"),
        email_verified=True,
        onboarded=True,
        phone="+966500001234",
        business_name="Aster Coffee",
        business_description="Specialty coffee",
    ))
    await db.commit()


async def _seed_workspace(db, user_id):
    channel = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="whatsapp",
        platform_user_id="pn-delete-1", display_name="Aster Coffee",
        status="active",
    )
    db.add(channel)
    await db.flush()
    phone = "+966500009999"
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel.id,
        direction="outbound",
        content=encrypt_message_content("Ahmed Khan here — thanks for the order."),
        content_type="text", status="sent",
        contact_phone=encrypt_contact_phone(phone),
        contact_phone_hash=hash_contact_phone(phone),
        is_ai=False, handled_by="human",
    ))
    db.add(ReviewReply(
        id=str(uuid.uuid4()), channel_id=channel.id,
        review_id="review-1", rating=5,
        reviewer_name="Sara",
        reply_text="Thanks Sara, Ahmed Khan here.",
        status="posted",
    ))
    db.add(LocationPost(
        id=str(uuid.uuid4()), user_id=user_id, listing_id="loc-1",
        business_name="Aster Coffee", title="Ahmed Khan's offer",
        description="Ahmed Khan recommends the new roast.",
        post_type="update", status="draft",
    ))
    await db.commit()
    return channel


async def _pending(db, user_id, days=30, reminder_sent=False):
    now = datetime.now(timezone.utc)
    row = AccountDeletionRequest(
        tenant_id=user_id,
        requested_by=user_id,
        status="pending",
        requested_at=now,
        scheduled_for=now + timedelta(days=days),
    )
    if reminder_sent:
        row.reminder_sent_at = now
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_request_is_scheduled_thirty_days_out(
    client, db, user_id, monkeypatch
):
    await _seed_user(db, user_id)
    sent: list[str] = []

    async def _email(email, subject, body):
        sent.append(subject)

    monkeypatch.setattr(account_deletion, "_send_deletion_email", _email)

    res = client.post(
        "/api/v1/account/deletion", json={"confirm": "DELETE"}
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "pending"
    scheduled = datetime.fromisoformat(body["scheduled_for"])
    assert scheduled > datetime.now(timezone.utc) + timedelta(days=29)
    assert sent and "scheduled" in sent[0].lower()

    # A second request is idempotent, not a second row.
    again = client.post(
        "/api/v1/account/deletion", json={"confirm": "DELETE"}
    )
    assert again.status_code == 202
    rows = (
        await db.execute(select(AccountDeletionRequest))
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_wrong_confirmation_does_not_schedule(client, db, user_id):
    await _seed_user(db, user_id)
    res = client.post(
        "/api/v1/account/deletion", json={"confirm": "yes"}
    )
    assert res.status_code == 422
    assert (await db.execute(select(AccountDeletionRequest))).scalars().all() == []


@pytest.mark.asyncio
async def test_sign_in_cancels_the_pending_request(
    client, db, user_id, monkeypatch
):
    await _seed_user(db, user_id)
    await _pending(db, user_id)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(account_deletion, "_send_deletion_email", _noop)

    result = await login(
        LoginRequest(email="ahmed@example.com", password="Secret123!"),
        db, "pytest", "127.0.0.1",
    )
    assert result["user"]["id"] == user_id

    row = (
        await db.execute(select(AccountDeletionRequest))
    ).scalar_one()
    assert row.status == "cancelled"
    assert row.cancelled_at is not None


@pytest.mark.asyncio
async def test_day_25_reminder_is_sent_once(
    client, db, user_id, monkeypatch
):
    await _seed_user(db, user_id)
    row = await _pending(db, user_id, days=5)
    sent: list[str] = []

    async def _email(email, subject, body):
        sent.append(subject)

    monkeypatch.setattr(account_deletion, "_send_deletion_email", _email)

    assert await account_deletion.send_due_reminders(db) == 1
    await db.refresh(row)
    assert row.reminder_sent_at is not None
    assert sent == ["Your personal data will be deleted in 5 days"]

    # A second hourly tick does not send it again.
    assert await account_deletion.send_due_reminders(db) == 0


@pytest.mark.asyncio
async def test_due_deletion_anonymizes_owner_and_redacts_records(
    db, user_id, monkeypatch
):
    await _seed_user(db, user_id)
    channel = await _seed_workspace(db, user_id)
    await _pending(db, user_id, days=-1)

    completed = await account_deletion.process_due_deletions(db)
    assert completed == 1

    user = await db.get(User, user_id)
    assert user.first_name == "Deleted"
    assert user.last_name == ""
    assert user.email.startswith("deleted+")
    assert user.phone is None
    assert user.google_sub is None
    assert user.business_name == "Aster Coffee"  # business data stays
    assert user.business_description == "Specialty coffee"

    msg = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.channel_id == channel.id)
        )
    ).scalar_one()
    text = decrypt_message_content(msg.content)
    assert "Ahmed Khan" not in text
    assert "Ahmed" not in text
    assert "[deleted]" in text

    reply = (
        await db.execute(
            select(ReviewReply).where(ReviewReply.channel_id == channel.id)
        )
    ).scalar_one()
    assert "Ahmed Khan" not in reply.reply_text
    assert "[deleted]" in reply.reply_text

    post = (
        await db.execute(select(LocationPost).where(LocationPost.user_id == user_id))
    ).scalar_one()
    assert "Ahmed Khan" not in post.title
    assert "Ahmed Khan" not in post.description

    req = (
        await db.execute(select(AccountDeletionRequest))
    ).scalar_one()
    assert req.status == "completed"
    assert req.completed_at is not None
