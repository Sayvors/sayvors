"""Inbox threading and real WhatsApp sending.

Threads are derived from (channel, contact_phone). These tests cover the three
behaviours the dashboard depends on: grouping, the Unknown catch-all for
pre-migration rows, and that a rejected send is recorded as failed rather than
silently reported as sent.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels import service as channels
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.meta.models import MetaAsset, MetaConnection


def _user(user_id):
    """The service only reads `user.id`, so a stub avoids entangling the User
    model's full column set with these tests."""
    return SimpleNamespace(id=user_id)


def _channel(db, user_id, cid="chan-1", name="WhatsApp"):
    ch = Channel(
        id=cid, user_id=user_id, platform="whatsapp",
        platform_user_id="pn-1", display_name=name, status="active",
    )
    db.add(ch)
    await_commit = db.commit()
    return ch, await_commit


async def _msg(db, channel_id, *, phone=None, direction="inbound", content="hi",
               minutes_ago=0, status="delivered", name=None, mid=None):
    row = ChannelMessage(
        id=f"m-{abs(hash((channel_id, phone, content, minutes_ago))) % 10**12}",
        channel_id=channel_id,
        platform_message_id=mid,
        direction=direction,
        content=content,
        content_type="text",
        status=status,
        contact_phone=phone,
        contact_name=name,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    return row


@pytest.mark.asyncio
async def test_threads_group_by_contact(db, user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="first", minutes_ago=30)
    await _msg(db, ch.id, phone="966500000001", content="second", minutes_ago=5)
    await _msg(db, ch.id, phone="966500000002", content="other", minutes_ago=10)
    await db.commit()

    threads = await channels.list_inbox_threads(db=db, user=_user(user_id))
    by_phone = {t["contact_phone"]: t for t in threads}
    assert set(by_phone) == {"966500000001", "966500000002"}
    # Newest activity first.
    assert [t["contact_phone"] for t in threads] == ["966500000001", "966500000002"]
    assert by_phone["966500000001"]["message_count"] == 2
    assert by_phone["966500000001"]["last_message"] == "second"


@pytest.mark.asyncio
async def test_disconnected_channel_hidden_from_inbox(db, user_id):
    """Disconnecting a number takes its threads out of the list. The messages
    stay (business data) and reappear when the channel reconnects."""
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="before disconnect", minutes_ago=10)
    await db.commit()
    assert len(await channels.list_inbox_threads(db=db, user=_user(user_id))) == 1

    ch.status = "disconnected"
    await db.commit()
    assert await channels.list_inbox_threads(db=db, user=_user(user_id)) == []

    # Reconnect of the same number: threads come back.
    ch.status = "active"
    await db.commit()
    assert len(await channels.list_inbox_threads(db=db, user=_user(user_id))) == 1


@pytest.mark.asyncio
async def test_channel_with_inactive_asset_hidden_from_inbox(db, user_id):
    """Channels disconnected before status marking existed carry no
    "disconnected" flag — but their Meta asset was deactivated, which is the
    second signal the inbox reads. Covers tenants who disconnected on old
    code; deploying alone must already hide their threads."""
    ch, _ = _channel(db, user_id)  # status still "active"
    db.add(MetaAsset(
        id="asset-1", tenant_id=user_id, connection_id="seed-conn",
        provider="whatsapp", asset_type="phone_number",
        external_asset_id="pn-1", active=False,
    ))
    await _msg(db, ch.id, phone="966500000001", content="legacy disconnect", minutes_ago=5)
    await db.commit()

    assert await channels.list_inbox_threads(db=db, user=_user(user_id)) == []


@pytest.mark.asyncio
async def test_pre_migration_rows_group_as_unknown(db, user_id):
    """Rows written before contact_phone existed have no sender. They must land
    in one catch-all thread, keeping their text, not be dropped."""
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone=None, content="legacy one", minutes_ago=40)
    await _msg(db, ch.id, phone=None, content="legacy two", minutes_ago=20)
    await _msg(db, ch.id, phone="966500000001", content="real", minutes_ago=5)
    await db.commit()

    threads = await channels.list_inbox_threads(db=db, user=_user(user_id))
    unknown = [t for t in threads if t["is_unknown"]]
    assert len(unknown) == 1
    assert unknown[0]["key"] == "unknown"
    assert unknown[0]["contact_phone"] is None
    assert unknown[0]["message_count"] == 2
    assert unknown[0]["last_message"] == "legacy two"
    # Unattributed history is not a customer waiting on a reply.
    assert unknown[0]["unread"] == 0


@pytest.mark.asyncio
async def test_thread_messages_ordered_oldest_first(db, user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="one", minutes_ago=30)
    await _msg(db, ch.id, phone="966500000001", content="two", minutes_ago=10)
    await _msg(db, ch.id, phone="966500000001", content="three", minutes_ago=1)
    await _msg(db, ch.id, phone="966500000009", content="other contact")
    await db.commit()

    msgs = await channels.list_thread_messages(_user(user_id), db, ch.id, "966500000001")
    assert [m.content for m in msgs] == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_thread_messages_unknown_bucket(db, user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone=None, content="legacy")
    await _msg(db, ch.id, phone="966500000001", content="real")
    await db.commit()
    msgs = await channels.list_thread_messages(_user(user_id), db, ch.id, None)
    assert [m.content for m in msgs] == ["legacy"]


@pytest.mark.asyncio
async def test_unread_counts_inbound_after_last_outbound(db, user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="q1", minutes_ago=50)
    await _msg(db, ch.id, phone="966500000001", content="a1", minutes_ago=45,
               direction="outbound", status="read")
    await _msg(db, ch.id, phone="966500000001", content="q2", minutes_ago=10)
    await _msg(db, ch.id, phone="966500000001", content="q3", minutes_ago=5)
    await db.commit()

    threads = await channels.list_inbox_threads(db=db, user=_user(user_id))
    t = next(x for x in threads if x["contact_phone"] == "966500000001")
    # q2 and q3 arrived after the reply; q1/a1 are a completed exchange.
    assert t["unread"] == 2


@pytest.mark.asyncio
async def test_unread_counts_all_when_never_answered(db, user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="q1", minutes_ago=9)
    await _msg(db, ch.id, phone="966500000001", content="q2", minutes_ago=5)
    await db.commit()
    threads = await channels.list_inbox_threads(db=db, user=_user(user_id))
    t = next(x for x in threads if x["contact_phone"] == "966500000001")
    assert t["unread"] == 2


@pytest.mark.asyncio
async def test_search_filters_threads_by_message_text(db, user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="my order is late", minutes_ago=9)
    await _msg(db, ch.id, phone="966500000002", content="what are your hours", minutes_ago=5)
    await db.commit()

    u = _user(user_id)
    hits = await channels.list_inbox_threads(u, db, search="order")
    assert [t["contact_phone"] for t in hits] == ["966500000001"]
    # A thread is narrowed to matching threads, not to matching messages only.
    assert hits[0]["message_count"] == 1
    assert await channels.list_inbox_threads(u, db, search="zzzz") == []


@pytest.mark.asyncio
async def test_threads_are_scoped_to_owner(db, user_id, other_user_id):
    ch, _ = _channel(db, user_id)
    await _msg(db, ch.id, phone="966500000001", content="mine")
    await db.commit()
    assert await channels.list_inbox_threads(_user(other_user_id), db) == []


@pytest.mark.asyncio
async def test_send_requires_recipient(db, user_id):
    ch, _ = _channel(db, user_id)
    await db.commit()
    from app.modules.channels.schemas import ChannelMessageSend

    with pytest.raises(ValueError, match="recipient phone number"):
        await channels.send_message(
            ch.id,
            ChannelMessageSend(content="hi", contact_phone="  "),
            _user(user_id),
            db,
        )


def _seed_asset(db, tenant_id, phone_number_id="pn-1", active=True, with_token=True):
    from app.modules.channels.meta.credentials import encrypt_credential

    conn = MetaConnection(
        id=f"conn-{phone_number_id}", tenant_id=tenant_id, provider="whatsapp",
        status="active",
        # Real ciphertext, not a placeholder: the send path decrypts this, and a
        # bogus value would fail decryption and mask the behaviour under test.
        access_token_encrypted=encrypt_credential("test-token") if with_token else None,
    )
    db.add(conn)
    db.add(MetaAsset(
        id=f"asset-{phone_number_id}", tenant_id=tenant_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=phone_number_id, name="Business", active=active,
    ))
    return conn


@pytest.mark.asyncio
async def test_send_records_provider_message_id(db, user_id, monkeypatch):
    ch, _ = _channel(db, user_id)
    _seed_asset(db, user_id)
    await db.commit()

    from app.modules.channels.meta.providers import whatsapp as wa

    adapter = AsyncMock()
    adapter.send_text_message = AsyncMock(return_value="wamid.PROVIDER1")
    monkeypatch.setattr(wa.WhatsAppAdapter, "send_text_message", adapter.send_text_message)

    from app.modules.channels.schemas import ChannelMessageSend

    msg = await channels.send_message(
        ch.id,
        ChannelMessageSend(content="hello there", contact_phone="966500000001"),
        _user(user_id),
        db,
    )
    assert msg.status == "sent"
    assert msg.platform_message_id == "wamid.PROVIDER1"
    assert msg.contact_phone == "966500000001"
    # The send went to the resolved phone number, not the channel's own.
    adapter.send_text_message.assert_awaited_once()
    args = adapter.send_text_message.await_args
    assert args.args[2] == "966500000001"
    assert args.args[3] == "hello there"


@pytest.mark.asyncio
async def test_send_failure_is_recorded_not_raised(db, user_id, monkeypatch):
    """A rejected send must land as a failed row carrying the reason, so the
    thread never shows a message that never arrived as 'sent'."""
    ch, _ = _channel(db, user_id)
    _seed_asset(db, user_id)
    await db.commit()

    from app.modules.channels.meta.providers import whatsapp as wa
    from app.modules.channels.meta.providers.base import MetaAPIError

    adapter = AsyncMock()
    adapter.send_text_message = AsyncMock(
        side_effect=MetaAPIError("Message failed to send because more than 24 hours", 400)
    )
    monkeypatch.setattr(wa.WhatsAppAdapter, "send_text_message", adapter.send_text_message)

    from app.modules.channels.schemas import ChannelMessageSend

    msg = await channels.send_message(
        ch.id,
        ChannelMessageSend(content="late reply", contact_phone="966500000001"),
        _user(user_id),
        db,
    )
    assert msg.status == "failed"
    assert "24 hours" in msg.error
    assert msg.platform_message_id is None


@pytest.mark.asyncio
async def test_send_without_connection_fails_with_reason(db, user_id):
    ch, _ = _channel(db, user_id)
    await db.commit()
    from app.modules.channels.schemas import ChannelMessageSend

    msg = await channels.send_message(
        ch.id,
        ChannelMessageSend(content="hi", contact_phone="966500000001"),
        _user(user_id),
        db,
    )
    assert msg.status == "failed"
    assert "No WhatsApp account is connected" in msg.error


@pytest.mark.asyncio
async def test_send_cannot_borrow_another_tenants_credentials(db, user_id, other_user_id, monkeypatch):
    """The asset lookup is scoped to the sender's tenant, so a channel whose
    number belongs to someone else cannot send with their token."""
    ch, _ = _channel(db, user_id, cid="chan-theirs", name="Theirs")
    _seed_asset(db, other_user_id, phone_number_id="pn-theirs")
    # Point the user's own channel at a number owned by the other tenant.
    ch.platform_user_id = "pn-theirs"
    await db.commit()

    from app.modules.channels.meta.providers import whatsapp as wa

    called = AsyncMock()
    monkeypatch.setattr(wa.WhatsAppAdapter, "send_text_message", called)

    from app.modules.channels.schemas import ChannelMessageSend

    msg = await channels.send_message(
        ch.id,
        ChannelMessageSend(content="hi", contact_phone="966500000001"),
        _user(user_id),
        db,
    )
    assert msg.status == "failed"
    called.assert_not_awaited()
