"""WA-14: fixed AI stickers and acknowledgement reactions.

The model never draws. It picks a bundled sticker with a hidden marker, and
bare acknowledgements get a reaction instead of a paragraph — unless the last
outbound was a question, where "ok" is an answer the AI must process.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import TEST_ENGINE
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels import ai_stickers
from app.modules.channels.meta import consumer
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.service import (
    decrypt_message_content,
    encrypt_contact_phone,
    hash_contact_phone,
)
from app.modules.users.models import User

PHONE_NUMBER_ID = "PNID-STICKER"
CUSTOMER = "+966500000777"


def _session_factory():
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


class _Adapter:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.reacted: list[tuple[str, str]] = []
        self.stickers: list[str] = []
        self.fail_sticker = False

    async def send_text_message(self, phone_number_id, token, to, text, **kwargs):
        self.texts.append(text)
        return "wamid-text-1"

    async def send_typing_indicator(self, phone_number_id, token, wamid):
        return None

    async def send_reaction(self, phone_number_id, token, to, message_id, emoji):
        self.reacted.append((message_id, emoji))
        return "wamid-reaction-1"

    async def upload_media(self, phone_number_id, token, data, mime, filename="x"):
        if self.fail_sticker:
            raise RuntimeError("upload failed")
        return "media-1"

    async def send_sticker(self, phone_number_id, token, to, media_id):
        self.stickers.append(media_id)
        return "wamid-sticker-out-1"


async def _seed(db, *, last_outbound="Your order is ready."):
    uid = f"sticker-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="S", last_name="T",
        email=f"{uid}@example.com", password_hash="x",
        voice_replies="off", response_style="concise",
    ))
    conn = MetaConnection(
        id=f"sticker-conn-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        provider="whatsapp", status="active", access_token_encrypted="enc",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=f"sticker-asset-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        connection_id=conn.id, provider="whatsapp", asset_type="phone_number",
        external_asset_id=PHONE_NUMBER_ID, active=True,
        phone="+15550000777", status="connected",
    ))
    channel = Channel(
        id=f"sticker-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id=PHONE_NUMBER_ID,
        display_name="Stickers", status="active",
    )
    db.add(channel)
    await db.flush()
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel.id, direction="outbound",
        content=last_outbound, content_type="text", status="sent",
        contact_phone=encrypt_contact_phone(CUSTOMER),
        contact_phone_hash=hash_contact_phone(CUSTOMER),
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    ))
    await db.commit()
    return uid, channel


async def _patch_consumer(monkeypatch, adapter, *, generate):
    async def _noop(*args, **kwargs):
        return None

    async def _fake_classify(*args, **kwargs):
        return {
            "language": "en", "confused": False, "awaiting_user": False,
            "urgent": False,
        }

    async def _no_match(*args, **kwargs):
        return None

    monkeypatch.setattr(consumer, "async_session", _session_factory())
    monkeypatch.setattr(consumer, "_typing_indicator_enabled", _noop)
    monkeypatch.setattr(consumer, "_publish_typing", _noop)
    monkeypatch.setattr(consumer, "_publish_message_notification", _noop)
    monkeypatch.setattr(consumer, "_generate_reply", generate)
    monkeypatch.setattr(
        "app.modules.channels.meta.credentials.decrypt_connection_token",
        lambda connection: "tok",
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.service.get_adapter", lambda platform: adapter
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.thread_stats.classify_thread", _fake_classify
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.thread_state.apply_classification", _noop
    )
    monkeypatch.setattr(
        "app.modules.channels.realtime.publish_inbox_event", _noop
    )
    monkeypatch.setattr(
        "app.modules.review_engine.handoff.resolve_and_advance", _no_match
    )
    monkeypatch.setattr(
        "app.modules.review_engine.handoff.is_status_check", lambda text: False
    )


def test_marker_is_stripped_and_the_first_key_wins():
    reply, key = ai_stickers.split_sticker_marker(
        "All set!\n[[sticker:done]]\n[[sticker:ok]]"
    )
    assert reply == "All set!"
    assert key == "done"
    assert ai_stickers.split_sticker_marker("just text") == ("just text", None)


def test_bare_acknowledgements_map_to_one_reaction():
    assert ai_stickers.reaction_for_ack("thanks") == "❤️"
    assert ai_stickers.reaction_for_ack("Thank you!") == "❤️"
    assert ai_stickers.reaction_for_ack("شكرا") == "❤️"
    assert ai_stickers.reaction_for_ack("شُكْرًا") == "❤️"
    assert ai_stickers.reaction_for_ack("ok") == "👍"
    assert ai_stickers.reaction_for_ack("ٹھیک ہے") == "👍"
    assert ai_stickers.reaction_for_ack("done") == "✅"
    assert ai_stickers.reaction_for_ack("👍") == "👍"
    assert ai_stickers.reaction_for_ack("✅") == "✅"


def test_a_real_sentence_is_not_an_acknowledgement():
    assert ai_stickers.reaction_for_ack("thanks, but I need a refund") is None
    assert ai_stickers.reaction_for_ack("ok can you deliver tomorrow?") is None
    assert ai_stickers.reaction_for_ack("") is None


def test_the_pack_is_original_webp_under_metas_limit():
    for key in ("ok", "thanks", "done"):
        spec, data = ai_stickers.load_sticker(key)
        assert spec.filename.endswith(".webp")
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        assert len(data) < 100 * 1024, "Meta's static sticker limit is 100 KB"


@pytest.mark.asyncio
async def test_a_thanks_after_an_answer_gets_a_reaction_not_a_reply(db):
    _, channel = await _seed(db)
    assert await ai_stickers.should_react_instead_of_reply(
        db, channel.id, CUSTOMER
    ) is True


@pytest.mark.asyncio
async def test_ok_after_a_question_reaches_the_ai(db):
    _, channel = await _seed(db, last_outbound="Shall I book the Makkah branch?")
    assert await ai_stickers.should_react_instead_of_reply(
        db, channel.id, CUSTOMER
    ) is False


@pytest.mark.asyncio
async def test_consumer_reacts_to_a_bare_ack_and_skips_the_ai(db, monkeypatch):
    _, channel = await _seed(db)
    adapter = _Adapter()

    async def _must_not_generate(*args, **kwargs):
        raise AssertionError("a reaction must not trigger an AI reply")

    await _patch_consumer(monkeypatch, adapter, generate=_must_not_generate)

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-ack-1",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await consumer._handle_message_received(
        event, {"from": CUSTOMER, "text": "thanks", "msg_type": "text"}
    )

    assert adapter.reacted == [("wamid-ack-1", "❤️")]
    assert adapter.texts == []
    reaction = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel.id,
            ChannelMessage.content_type == "reaction",
        )
    )).scalars().one()
    assert decrypt_message_content(reaction.content) == "❤️"
    assert reaction.is_ai is True

    inbound = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.platform_message_id == "wamid-ack-1"
        )
    )).scalars().one()
    assert inbound.ai_reply_status == "skipped"


@pytest.mark.asyncio
async def test_ok_after_a_question_is_answered_by_the_ai(db, monkeypatch):
    await _seed(db, last_outbound="Shall I book the Makkah branch?")
    adapter = _Adapter()

    async def _generate(*args, **kwargs):
        return "Yes — booked for 5pm."

    await _patch_consumer(monkeypatch, adapter, generate=_generate)

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-answer-1",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await consumer._handle_message_received(
        event, {"from": CUSTOMER, "text": "ok", "msg_type": "text"}
    )

    assert adapter.reacted == []
    assert adapter.texts == ["Yes — booked for 5pm."]


@pytest.mark.asyncio
async def test_customer_reaction_is_stored_without_an_ai_reply(db, monkeypatch):
    await _seed(db)
    adapter = _Adapter()

    async def _must_not_generate(*args, **kwargs):
        raise AssertionError("a customer reaction is not a question")

    await _patch_consumer(monkeypatch, adapter, generate=_must_not_generate)

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-inbound-reaction-1",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await consumer._handle_message_received(
        event,
        {"from": CUSTOMER, "msg_type": "reaction", "reaction": {"emoji": "❤️"}},
    )

    assert adapter.texts == []
    row = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.platform_message_id == "wamid-inbound-reaction-1"
        )
    )).scalars().one()
    assert row.content_type == "reaction"
    assert row.ai_reply_status == "skipped"


@pytest.mark.asyncio
async def test_consumer_sends_the_bundled_sticker_and_strips_the_marker(
    db, monkeypatch
):
    _, channel = await _seed(db)
    adapter = _Adapter()

    async def _generate(*args, **kwargs):
        return "All set!\n[[sticker:done]]"

    await _patch_consumer(monkeypatch, adapter, generate=_generate)

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-sticker-1",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await consumer._handle_message_received(
        event, {"from": CUSTOMER, "text": "I finished the form", "msg_type": "text"}
    )

    assert adapter.texts == ["All set!"]
    assert adapter.stickers == ["media-1"]
    sticker = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel.id,
            ChannelMessage.content_type == "sticker",
        )
    )).scalars().one()
    assert sticker.media_mime_type == "image/webp"
    assert sticker.media_filename == "done.webp"
    assert sticker.is_ai is True


@pytest.mark.asyncio
async def test_a_sticker_only_reply_falls_back_to_text(db, monkeypatch):
    await _seed(db)
    adapter = _Adapter()
    adapter.fail_sticker = True

    async def _generate(*args, **kwargs):
        return "[[sticker:ok]]"

    await _patch_consumer(monkeypatch, adapter, generate=_generate)
    monkeypatch.setattr(
        "app.modules.channels.meta.credentials.decrypt_connection_token",
        lambda connection: "tok",
    )

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-sticker-fail-1",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await consumer._handle_message_received(
        event, {"from": CUSTOMER, "text": "the form is submitted", "msg_type": "text"}
    )

    assert adapter.stickers == []
    assert adapter.texts and "OK" in adapter.texts[0]
