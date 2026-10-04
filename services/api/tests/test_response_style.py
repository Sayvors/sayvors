"""Tenant response style: defaults, renderer, API, and consumer sends.

"concise" must reproduce the single-message behaviour exactly; "human" may
split one logical reply into 1..N natural messages — intelligently, never
mechanically — and falls back to concise on ANY renderer failure.
"""
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels.meta import consumer as meta_consumer
from app.modules.channels.meta import response_style as rs
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.models import ChannelMessage
from conftest import TEST_ENGINE

_PHONE_ID = "pn-style-test-1"
_WAMID = "wamid.style.test.1"
_FROM = "15550001"


# ── normalize ──

def test_normalize_response_style_falls_back_to_concise():
    assert rs.normalize_response_style(None) == "concise"
    assert rs.normalize_response_style("") == "concise"
    assert rs.normalize_response_style("LOUD") == "concise"
    assert rs.normalize_response_style("concise") == "concise"
    assert rs.normalize_response_style("human") == "human"


# ── renderers ──

def test_concise_renderer_sends_exactly_one_message():
    assert rs.concise_renderer("Hello! We are open until 10.") == [
        "Hello! We are open until 10."
    ]
    assert rs.concise_renderer("   ") == []
    assert rs.concise_renderer(None) == []


@pytest.mark.asyncio
async def test_human_renderer_splits_into_natural_parts(db, user_id, monkeypatch):
    async def _fake_split(tenant_id, db_, text):
        return json.dumps(
            ["Hey! 👋", "Yes, we have that in stock.", "Want me to hold one?"]
        )

    monkeypatch.setattr(rs, "_ask_split", _fake_split)
    messages = await rs.human_renderer(
        "Hey! Yes, we have that in stock. Want me to hold one?", user_id, db
    )
    assert messages == [
        "Hey! 👋", "Yes, we have that in stock.", "Want me to hold one?"
    ]


@pytest.mark.asyncio
async def test_human_renderer_one_message_when_ai_says_so(db, user_id, monkeypatch):
    """Most replies are fine as one message — the AI may choose N=1."""
    async def _fake_split(tenant_id, db_, text):
        return '["Sure — pickup is 9 to 9."]'

    monkeypatch.setattr(rs, "_ask_split", _fake_split)
    assert await rs.human_renderer("Sure — pickup is 9 to 9.", user_id, db) == [
        "Sure — pickup is 9 to 9."
    ]


@pytest.mark.asyncio
async def test_human_renderer_falls_back_on_garbage(db, user_id, monkeypatch):
    async def _garbage(tenant_id, db_, text):
        return "the messages are: no array here"

    monkeypatch.setattr(rs, "_ask_split", _garbage)
    assert await rs.human_renderer("Real reply text.", user_id, db) == [
        "Real reply text."
    ]


@pytest.mark.asyncio
async def test_human_renderer_falls_back_on_llm_error(db, user_id, monkeypatch):
    async def _boom(tenant_id, db_, text):
        raise ValueError("No AI model is enabled by your administrator.")

    monkeypatch.setattr(rs, "_ask_split", _boom)
    assert await rs.human_renderer("Real reply text.", user_id, db) == [
        "Real reply text."
    ]


@pytest.mark.asyncio
async def test_human_renderer_caps_and_drops_empties(db, user_id, monkeypatch):
    async def _seven(tenant_id, db_, text):
        return json.dumps(["a", "", "b", "c", "d", "e", "f"])

    monkeypatch.setattr(rs, "_ask_split", _seven)
    messages = await rs.human_renderer("a b c d e f", user_id, db)
    assert len(messages) == rs._MAX_HUMAN_MESSAGES


@pytest.mark.asyncio
async def test_human_renderer_falls_back_when_split_is_lossy(db, user_id, monkeypatch):
    """A split that drops most of the text is a summary, not a repackaging."""
    async def _lossy(tenant_id, db_, text):
        return '["Sure."]'

    monkeypatch.setattr(rs, "_ask_split", _lossy)
    long_reply = "Sure — we can deliver today. " * 10
    assert await rs.human_renderer(long_reply, user_id, db) == [long_reply.strip()]


@pytest.mark.asyncio
async def test_render_response_routes_by_style(db, user_id, monkeypatch):
    async def _explode(tenant_id, db_, text):
        raise AssertionError("concise must never call the splitter")

    monkeypatch.setattr(rs, "_ask_split", _explode)
    assert await rs.render_response("concise", "one message", user_id, db) == [
        "one message"
    ]
    # NULL / unknown style column behaves as concise, never crashes.
    assert await rs.render_response(None, "one message", user_id, db) == [
        "one message"
    ]

    async def _fake_split(tenant_id, db_, text):
        return '["part one.", "part two."]'

    monkeypatch.setattr(rs, "_ask_split", _fake_split)
    assert await rs.render_response("human", "part one. part two.", user_id, db) == [
        "part one.", "part two.",
    ]


# ── API ──

async def _make_user(db, user_id, **fields):
    from app.modules.users.models import User

    user = User(
        id=user_id,
        first_name="Test",
        last_name="Owner",
        email=f"{user_id}@example.com",
        password_hash="x",
        **fields,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_response_style_endpoints(db, user_id, client):
    from app.modules.users.models import User

    await _make_user(db, user_id)

    resp = client.put(
        "/api/v1/profile/response-style", json={"response_style": "human"}
    )
    assert resp.status_code == 200
    assert resp.json()["response_style"] == "human"

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    assert user.response_style == "human"

    resp = client.get("/api/v1/profile")
    assert resp.status_code == 200
    assert resp.json()["response_style"] == "human"

    resp = client.put(
        "/api/v1/profile/response-style", json={"response_style": "loud"}
    )
    assert resp.status_code == 422


# ── consumer: style decides how many WhatsApp messages go out ──

def _test_session_factory():
    """Session factory bound to the test engine (consumer opens its own)."""
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


async def _seed_whatsapp(db, user_id, *, response_style):
    """User + MetaAsset/MetaConnection with a decryptable token."""
    from app.modules.channels.meta.credentials import encrypt_credential

    await _make_user(db, user_id, response_style=response_style)
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("tok"), status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=str(uuid.uuid4()), tenant_id=user_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=_PHONE_ID, phone="+1555", active=True,
    ))
    await db.commit()


class _FakeAdapter:
    def __init__(self, fail_on=0):
        self.sent: list[str] = []
        self._fail_on = fail_on  # 1-based index of a call that must raise

    async def send_text_message(self, phone_number_id, token, to, text):
        if len(self.sent) + 1 == self._fail_on:
            from app.modules.channels.meta.providers.base import MetaAPIError

            raise MetaAPIError("out of window", status_code=400)
        self.sent.append(text)
        return f"wamp-{len(self.sent)}"

    async def send_typing_indicator(self, phone_number_id, token, message_id):
        return True


def _wire_consumer(monkeypatch, adapter, split_return=None, logical_reply=None):
    from app.modules.channels.meta import service as meta_service

    monkeypatch.setattr(
        meta_consumer, "async_session", _test_session_factory()
    )
    monkeypatch.setattr(
        meta_consumer,
        "_generate_reply",
        lambda db, channel, tenant_id, text: _async_of(
            logical_reply or "Hey there! Yes we can help. Want pricing?"
        ),
    )
    if split_return is not None:
        async def _fake_split(tenant_id, db_, text):
            return json.dumps(split_return)

        monkeypatch.setattr(rs, "_ask_split", _fake_split)
    monkeypatch.setattr(meta_service, "get_adapter", lambda name: adapter)

    sleeps: list[float] = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(meta_consumer.asyncio, "sleep", _fake_sleep)
    return sleeps


def _async_of(value):
    async def _inner():
        return value
    return _inner()


async def _outbound_rows():
    async with _test_session_factory()() as session:
        return list(
            (
                await session.execute(
                    select(ChannelMessage)
                    .where(ChannelMessage.direction == "outbound")
                    .order_by(ChannelMessage.created_at)
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_consumer_concise_style_sends_single_message(db, user_id, monkeypatch):
    await _seed_whatsapp(db, user_id, response_style="concise")
    adapter = _FakeAdapter()
    _wire_consumer(monkeypatch, adapter)

    await meta_consumer._handle_message_received(
        {"external_asset_id": _PHONE_ID, "external_event_id": _WAMID},
        {"from": _FROM, "text": "hi", "msg_type": "text"},
    )

    assert adapter.sent == ["Hey there! Yes we can help. Want pricing?"]
    rows = await _outbound_rows()
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].platform_message_id == "wamp-1"


@pytest.mark.asyncio
async def test_consumer_human_style_sends_sequential_parts(db, user_id, monkeypatch):
    await _seed_whatsapp(db, user_id, response_style="human")
    adapter = _FakeAdapter()
    sleeps = _wire_consumer(
        monkeypatch, adapter, split_return=["Hey there! 👋", "Yes we can help.", "Want pricing?"]
    )

    await meta_consumer._handle_message_received(
        {"external_asset_id": _PHONE_ID, "external_event_id": _WAMID},
        {"from": _FROM, "text": "hi", "msg_type": "text"},
    )

    assert adapter.sent == ["Hey there! 👋", "Yes we can help.", "Want pricing?"]
    rows = await _outbound_rows()
    assert [(r.content, r.status) for r in rows] == [
        ("Hey there! 👋", "sent"),
        ("Yes we can help.", "sent"),
        ("Want pricing?", "sent"),
    ]
    assert [r.platform_message_id for r in rows] == ["wamp-1", "wamp-2", "wamp-3"]
    # Paced between parts, never before the first or after the last.
    assert sleeps == [meta_consumer._MESSAGE_GAP_SECONDS] * 2


@pytest.mark.asyncio
async def test_consumer_send_failure_stops_remaining_parts(db, user_id, monkeypatch):
    await _seed_whatsapp(db, user_id, response_style="human")
    adapter = _FakeAdapter(fail_on=2)
    _wire_consumer(
        monkeypatch, adapter, split_return=["first part", "second part"]
    )

    await meta_consumer._handle_message_received(
        {"external_asset_id": _PHONE_ID, "external_event_id": _WAMID},
        {"from": _FROM, "text": "hi", "msg_type": "text"},
    )

    assert adapter.sent == ["first part"]
    rows = await _outbound_rows()
    assert [(r.content, r.status) for r in rows] == [
        ("first part", "sent"),
        ("second part", "failed"),
    ]
