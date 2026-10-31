"""First-contact language picker: English / العربية / اردو.

The choice is stored per thread and then enforced for text and voice. The
prompt is a one-time gate, never a blocker: a customer who ignores it gets a
normal answer on their next message.
"""
import pytest

from app.modules.channels.meta.language_gate import (
    CONFIRMATION,
    LANGUAGE_OPTIONS,
    PROMPT_BODY,
    language_block,
    language_from_label,
    prompt_once,
)


def test_three_buttons_in_the_expected_order():
    assert [label for label, _ in LANGUAGE_OPTIONS] == ["English", "العربية", "اردو"]
    assert [code for _, code in LANGUAGE_OPTIONS] == ["en", "ar", "ur"]
    assert len(PROMPT_BODY) <= 1024


@pytest.mark.parametrize(
    "text,expected",
    [
        ("English", "en"),
        ("english.", "en"),
        ("EN", "en"),
        ("العربية", "ar"),
        ("عربي", "ar"),
        ("اردو", "ur"),
        ("Urdu", "ur"),
        ("what are your hours?", None),
        ("", None),
        (None, None),
    ],
)
def test_label_aliases(text, expected):
    assert language_from_label(text) == expected


def test_language_block_pins_the_reply_language():
    block = language_block("ar")
    assert "Arabic" in block
    assert "EVERY reply" in block
    assert language_block(None) == ""
    assert language_block("xx") == ""


@pytest.mark.asyncio
async def test_prompt_once_is_true_only_before_any_outbound(db, channel_id):
    from app.modules.channels.models import ChannelMessage
    from app.modules.channels.service import encrypt_contact_phone, hash_contact_phone

    contact = "+966500002222"
    assert await prompt_once(db, channel_id, contact) is True

    db.add(ChannelMessage(
        id="lang-out-1",
        channel_id=channel_id,
        direction="outbound",
        content="hi",
        status="sent",
        contact_phone=encrypt_contact_phone(contact),
        contact_phone_hash=hash_contact_phone(contact),
    ))
    await db.commit()

    assert await prompt_once(db, channel_id, contact) is False


@pytest.mark.asyncio
async def test_choice_is_persisted_on_the_thread(db, channel_id):
    from app.modules.channels.meta.thread_state import (
        get_thread_state,
        set_preferred_language,
    )

    contact = "+966500003333"
    await set_preferred_language(db, channel_id, contact, "ur")
    await db.commit()

    state = await get_thread_state(db, channel_id, contact)
    assert state is not None
    assert state.preferred_language == "ur"


@pytest.mark.asyncio
async def test_prompt_sends_buttons_and_records_the_row(db, channel_id):
    from sqlalchemy import select

    from app.modules.channels.meta import consumer
    from app.modules.channels.models import ChannelMessage
    from app.modules.channels.service import decrypt_message_content

    sent: dict = {}

    class _Adapter:
        async def send_interactive_buttons(
            self, phone_number_id, token, to, body, titles
        ):
            sent.update({"to": to, "body": body, "titles": titles})
            return "wamid-lang-1"

        async def send_text_message(self, *a, **k):  # pragma: no cover
            raise AssertionError("buttons should not fall back here")

    await consumer._send_language_prompt(
        db, _Adapter(),
        channel_id=channel_id, tenant_id="tenant-1",
        phone_number_id="phone-1", token="tok", contact="+966500004444",
    )

    assert sent["titles"] == ["English", "العربية", "اردو"]
    assert sent["body"] == PROMPT_BODY

    row = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.direction == "outbound")
    )).scalars().one()
    assert row.content_type == "interactive"
    assert row.handled_by == "system"
    assert row.is_ai is False
    assert decrypt_message_content(row.content) == PROMPT_BODY


@pytest.mark.asyncio
async def test_prompt_falls_back_to_text_when_buttons_are_rejected(db, channel_id):
    from sqlalchemy import select

    from app.modules.channels.meta import consumer
    from app.modules.channels.models import ChannelMessage

    class _Adapter:
        async def send_interactive_buttons(self, *a, **k):
            raise RuntimeError("Meta rejected the payload")

        async def send_text_message(self, phone_number_id, token, to, text):
            return "wamid-lang-2"

    await consumer._send_language_prompt(
        db, _Adapter(),
        channel_id=channel_id, tenant_id="tenant-1",
        phone_number_id="phone-1", token="tok", contact="+966500005555",
    )

    row = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.direction == "outbound")
    )).scalars().one()
    assert row.content_type == "text"
    assert row.platform_message_id == "wamid-lang-2"


@pytest.mark.asyncio
async def test_confirmation_uses_the_chosen_language(db, channel_id):
    from sqlalchemy import select

    from app.modules.channels.meta import consumer
    from app.modules.channels.models import ChannelMessage
    from app.modules.channels.service import decrypt_message_content

    class _Adapter:
        async def send_text_message(self, phone_number_id, token, to, text):
            return "wamid-confirm"

    await consumer._send_language_confirmation(
        db, _Adapter(),
        channel_id=channel_id, tenant_id="tenant-1",
        phone_number_id="phone-1", token="tok",
        contact="+966500006666", language="ar",
    )

    row = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.direction == "outbound")
    )).scalars().one()
    assert decrypt_message_content(row.content) == CONFIRMATION["ar"]
