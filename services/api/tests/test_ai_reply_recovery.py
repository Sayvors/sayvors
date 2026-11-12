"""LAUNCH-B2: a pending AI reply survives a crash and is re-driven.

The inbound row commits before the AI reply. Deduping purely by
`platform_message_id` made a retry after that commit a no-op reported as
success, so a lost reply stayed lost. These tests pin the reply state machine:

* an LLM/send failure leaves the row `pending` and raises to the worker;
* the retry re-enters the same row and sends exactly once;
* a successful send that crashed before bookkeeping is not sent twice;
* a permanent provider rejection is terminal, not an infinite retry.
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels.meta import consumer
from app.modules.channels.meta import service as meta_service
from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.base import (
    MetaAmbiguousError,
    MetaAPIError,
    MetaTransportError,
)
from app.modules.channels.meta.native_cards import (
    coordinates_from_maps_url,
    split_native_card_request,
)
from app.modules.channels.models import (
    Channel,
    ChannelMessage,
    Lead,
    WhatsAppThreadState,
)
from app.modules.channels.service import (
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)
from app.modules.users.models import User
from conftest import TEST_ENGINE

PHONE_ID = "pn-reply-recovery"
WAMID = "wamid-reply-recovery-1"
CUSTOMER = "+966500009999"
TEXT = "hello there"


def _session_factory():
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


class _Adapter:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.typing: list[str] = []
        self.contexts: list[str | None] = []
        self.locations: list[tuple] = []
        self.contacts: list[list[dict]] = []
        self.fail_with: Exception | None = None
        self.fail_times = 0

    async def send_text_message(self, phone_number_id, token, to, text, **kwargs):
        if self.fail_with is not None and self.fail_times != 0:
            self.fail_times -= 1
            raise self.fail_with
        self.contexts.append(kwargs.get("context_message_id"))
        self.sent.append(text)
        return f"wamid.out.{len(self.sent)}"

    async def send_typing_indicator(self, phone_number_id, token, wamid):
        self.typing.append(wamid)

    async def send_location(
        self, phone_number_id, token, to, latitude, longitude,
        name=None, address=None, **kwargs,
    ):
        self.locations.append((latitude, longitude, name, address))
        return "wamid.location"

    async def send_contacts(
        self, phone_number_id, token, to, contacts, **kwargs,
    ):
        self.contacts.append(contacts)
        return "wamid.contact"


async def _seed(db, user_id, *, preferred_language: str | None = "en"):
    db.add(User(
        id=user_id, first_name="Test", last_name="Owner",
        email=f"{user_id}@example.com", password_hash="x",
        response_style="concise", voice_replies="off",
        lead_settings={"quiet_start_hour": 0, "quiet_end_hour": 0},
    ))
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("tok"), status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=str(uuid.uuid4()), tenant_id=user_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=PHONE_ID, phone="+1555", active=True,
    ))
    channel = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="whatsapp",
        platform_user_id=PHONE_ID, display_name="Recovery", status="active",
    )
    db.add(channel)
    await db.flush()
    db.add(WhatsAppThreadState(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        contact_phone=encrypt_contact_phone(CUSTOMER),
        contact_phone_hash=hash_contact_phone(CUSTOMER),
        language="en",
        preferred_language=preferred_language,
    ))
    db.add(Channel(
        id=str(uuid.uuid4()),
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="acct-ai-card",
        display_name="Aster Coffee",
        status="active",
        metadata_json='{"address": "Olaya St, Riyadh", "phone": "+966500000000", "maps_url": "https://www.google.com/maps/@24.7136,46.6753,17z"}',
    ))
    await db.commit()
    return channel


def _event():
    return (
        {
            "external_asset_id": PHONE_ID,
            "external_event_id": WAMID,
            "event_type": "message.received",
            "occurred_at": None,
        },
        {"from": CUSTOMER, "text": TEXT, "msg_type": "text"},
    )


def _wire(monkeypatch, adapter, *, auto_reply=True):
    from app.modules.channels.meta import thread_stats as stats_mod

    monkeypatch.setattr(consumer, "async_session", _session_factory())
    monkeypatch.setattr(meta_service, "get_adapter", lambda name: adapter)

    async def _enabled(_db, _channel_id):
        return auto_reply

    monkeypatch.setattr(consumer, "_auto_reply_enabled", _enabled)

    async def _typing(_tenant_id):
        return False

    monkeypatch.setattr(consumer, "_typing_indicator_enabled", _typing)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(consumer, "_publish_typing", _noop)

    async def _stats(_db, _channel_id, _contact):
        return {"language": "en", "confused": False, "awaiting_user": False}

    monkeypatch.setattr(stats_mod, "classify_thread", _stats)


async def _stored_row():
    async with _session_factory()() as session:
        return (
            await session.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == WAMID,
                )
            )
        ).scalar_one()


async def _outbound():
    async with _session_factory()() as session:
        return (
            await session.execute(
                select(ChannelMessage).where(
                    ChannelMessage.direction == "outbound",
                )
            )
        ).scalars().all()


@pytest.mark.asyncio
async def test_llm_failure_leaves_pending_and_the_retry_sends_once(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    _wire(monkeypatch, adapter)

    calls = {"n": 0}

    async def _gen(_db, _channel, _tenant_id, _text, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("LLM is down")
        return "Thanks for waiting — I'm back."  # linter converts em dash

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    with pytest.raises(RuntimeError, match="LLM is down"):
        await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "pending"
    assert row.ai_reply_attempts == 1
    assert "LLM is down" in (row.ai_reply_error or "")
    assert await _outbound() == []

    await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "sent"
    assert row.ai_reply_attempts >= 2
    assert adapter.sent == ["Thanks for waiting, I'm back."]
    assert adapter.contexts == [WAMID]
    outbound = await _outbound()
    assert len(outbound) == 1
    assert outbound[0].status == "sent"
    assert outbound[0].reply_to_message_id == WAMID


@pytest.mark.asyncio
async def test_a_reply_sent_before_the_crash_is_not_sent_again(
    db, user_id, monkeypatch
):
    channel = await _seed(db, user_id)
    adapter = _Adapter()
    _wire(monkeypatch, adapter)

    inbound = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        platform_message_id=WAMID,
        direction="inbound",
        content=encrypt_message_content(TEXT),
        content_type="text",
        status="delivered",
        contact_phone=encrypt_contact_phone(CUSTOMER),
        contact_phone_hash=hash_contact_phone(CUSTOMER),
        ai_reply_status="pending",
        ai_reply_attempts=1,
    )
    db.add(inbound)
    await db.flush()
    # The previous attempt delivered this and crashed before closing the row.
    db.add(ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        platform_message_id="wamid.already.sent",
        direction="outbound",
        content=encrypt_message_content("The answer you already got"),
        content_type="text",
        status="sent",
        contact_phone=encrypt_contact_phone(CUSTOMER),
        contact_phone_hash=hash_contact_phone(CUSTOMER),
        is_ai=True,
        handled_by="ai",
    ))
    await db.commit()

    generated = {"called": False}

    async def _gen(*a, **k):
        generated["called"] = True
        return "A duplicate answer"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    await consumer._handle_message_received(event, data)

    assert generated["called"] is False
    assert adapter.sent == []
    row = await _stored_row()
    assert row.ai_reply_status == "sent"


@pytest.mark.asyncio
async def test_transient_send_failure_is_retried(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    adapter.fail_with = MetaAPIError("graph timeout", 503)
    adapter.fail_times = 1
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "Delivered on the retry"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    with pytest.raises(MetaAPIError):
        await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "pending"
    assert "graph timeout" in (row.ai_reply_error or "")

    await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "sent"
    assert adapter.sent == ["Delivered on the retry"]


@pytest.mark.asyncio
async def test_transport_unreachable_is_transient_like_a_5xx(
    db, user_id, monkeypatch
):
    """LAUNCH-B3: an unreachable Meta raises MetaTransportError (a 503
    MetaAPIError subclass) and takes the existing transient path — pending
    row, raise to the worker, send lands on the retry."""
    await _seed(db, user_id)
    adapter = _Adapter()
    adapter.fail_with = MetaTransportError("Meta unreachable after 3 attempts", 503)
    adapter.fail_times = 1
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "Sent once Meta came back"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    with pytest.raises(MetaAPIError):
        await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "pending"
    assert "unreachable" in (row.ai_reply_error or "")

    await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "sent"
    assert adapter.sent == ["Sent once Meta came back"]


@pytest.mark.asyncio
async def test_mid_flight_send_failure_is_ambiguous_never_retried(
    db, user_id, monkeypatch
):
    """LAUNCH-B3: a read timeout means the send may have landed. The row
    stays pending and the handler raises MetaAmbiguousError so the events
    worker files the event ambiguous (terminal) — no retry that could
    double-message, no failed-row lie, no text fallback."""
    await _seed(db, user_id)
    adapter = _Adapter()
    adapter.fail_with = MetaAmbiguousError(
        "Meta Graph POST /messages failed mid-flight: ReadTimeout"
    )
    adapter.fail_times = 1
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "Maybe delivered, maybe not"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    with pytest.raises(MetaAmbiguousError):
        await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "pending"
    assert "mid-flight" in (row.ai_reply_error or "")
    assert await _outbound() == []

    # The re-drive must stay honest: the reply is still owed, and a resume
    # with no delivered outbound may send — but the event itself is
    # terminal in the worker (pinned in test_meta_events_worker.py), so in
    # production nothing re-enters automatically.
    await consumer._handle_message_received(event, data)
    row = await _stored_row()
    assert adapter.sent == ["Maybe delivered, maybe not"]


@pytest.mark.asyncio
async def test_permanent_send_failure_is_terminal(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    adapter.fail_with = MetaAPIError("outside the 24h window", 400)
    adapter.fail_times = 10
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "Too late"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "failed"
    assert "24h" in (row.ai_reply_error or "")
    outbound = await _outbound()
    assert len(outbound) == 1
    assert outbound[0].status == "failed"


@pytest.mark.asyncio
async def test_auto_reply_off_closes_the_row_as_skipped(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    _wire(monkeypatch, adapter, auto_reply=False)

    event, data = _event()
    await consumer._handle_message_received(event, data)

    row = await _stored_row()
    assert row.ai_reply_status == "skipped"
    assert adapter.sent == []


def test_native_card_marker_is_stripped_from_the_reply():
    text, kind = split_native_card_request("We're on Olaya St.\nSEND_LOCATION")
    assert kind == "location"
    assert text == "We're on Olaya St."

    text, kind = split_native_card_request("Call us.\nSEND_CONTACT")
    assert kind == "contact"
    assert text == "Call us."

    text, kind = split_native_card_request("No marker here")
    assert kind is None
    assert text == "No marker here"


def test_maps_coordinates_parse_common_google_shapes():
    assert coordinates_from_maps_url(
        "https://www.google.com/maps/@24.7136,46.6753,17z"
    ) == (24.7136, 46.6753)
    assert coordinates_from_maps_url(
        "https://maps.google.com/?q=24.7136,46.6753"
    ) == (24.7136, 46.6753)
    assert coordinates_from_maps_url(
        "https://maps.google.com/place/!3d24.7136!4d46.6753"
    ) == (24.7136, 46.6753)
    assert coordinates_from_maps_url("https://maps.google.com/?cid=123") is None


@pytest.mark.asyncio
async def test_ai_location_marker_sends_a_native_card(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "We're on Olaya St.\nSEND_LOCATION"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    await consumer._handle_message_received(event, data)

    assert adapter.locations == [
        (24.7136, 46.6753, "Aster Coffee", "Olaya St, Riyadh")
    ]
    outbound = await _outbound()
    assert {row.content_type for row in outbound} == {"text", "location"}
    assert all(row.reply_to_message_id == WAMID for row in outbound)


@pytest.mark.asyncio
async def test_ai_contact_marker_sends_a_native_card(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "You can save our number.\nSEND_CONTACT"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    await consumer._handle_message_received(event, data)

    assert adapter.contacts == [[{
        "name": {"formatted_name": "Aster Coffee"},
        "phones": [{"phone": "+966500000000", "type": "WORK"}],
    }]]
    outbound = await _outbound()
    assert {row.content_type for row in outbound} == {"text", "contact"}


@pytest.mark.asyncio
async def test_open_ticket_marker_creates_a_ticket(
    db, user_id, monkeypatch
):
    await _seed(db, user_id)
    adapter = _Adapter()
    _wire(monkeypatch, adapter)

    async def _gen(*a, **k):
        return "Done — I've opened a ticket.\nOPEN_TICKET"  # linter converts em dash

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    await consumer._handle_message_received(event, data)

    lead = (
        await db.execute(
            select(Lead).where(Lead.contact_id == CUSTOMER)
        )
    ).scalar_one()
    assert lead.ticket_number.startswith("WA-")
    assert lead.ticket_status == "open"
    assert lead.ticket_kind in ("whatsapp_info", "whatsapp_general")
    assert adapter.sent == ["Done, I've opened a ticket."]


@pytest.mark.asyncio
async def test_language_button_reply_is_answered_immediately(
    db, user_id, monkeypatch
):
    """A tapped language button is text, not a silent [interactive message]."""
    from app.modules.channels.meta.language_gate import CONFIRMATION

    await _seed(db, user_id, preferred_language=None)
    adapter = _Adapter()
    _wire(monkeypatch, adapter)

    generated = {"called": False}

    async def _gen(*a, **k):
        generated["called"] = True
        return "Should not be called"

    monkeypatch.setattr(consumer, "_generate_reply", _gen)

    event, data = _event()
    data = {**data, "msg_type": "interactive", "text": "English"}
    await consumer._handle_message_received(event, data)

    assert generated["called"] is False
    assert adapter.sent == [CONFIRMATION["en"]]

    state = (
        await db.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.contact_phone_hash
                == hash_contact_phone(CUSTOMER)
            )
        )
    ).scalar_one()
    await db.refresh(state)
    assert state.preferred_language == "en"
