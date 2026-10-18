"""Regression: a customer's AI history must never include another customer's.

The bug this pins (reported as "the agent replies in my friend's Arabic"):

`_generate_reply` selected history with `ChannelMessage.channel_id == ...` and
nothing else, so every customer on one WhatsApp number shared a single
10-message window. The other customer's messages AND our replies to them were
injected into the prompt, which is both a language bleed and a cross-customer
data leak.

Asserted at the provider boundary: we capture the LLMRequest the consumer
actually built and inspect its messages. That keeps the test independent of
model behaviour — no LLM, no network, and no assertion about what a model
"should" have said.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.models import Channel, ChannelMessage


class _CaptureProvider:
    """Records the request it was handed, returns a canned completion."""

    def __init__(self):
        self.requests = []

    async def complete(self, req):
        self.requests.append(req)
        return type("Resp", (), {"content": "Sure, how can I help?"})()

    def sent_text(self) -> str:
        return "\n".join(m.content for r in self.requests for m in r.messages)


async def _no_business_card(tenant_id, session):
    return None


@pytest.fixture
def prompt_env(monkeypatch, db, user_id):
    """Stub out everything `_generate_reply` needs except the DB, and hand
    back the capturing provider plus the consumer module."""
    import app.modules.llm.providers.registry as registry
    import app.modules.llm.service as llm_service
    from app.modules.channels.meta import consumer as _consumer
    from app.modules.users.models import User

    # _generate_reply does select(User).scalar_one() on the tenant id.
    db.add(User(
        id=user_id, email=f"{user_id}@example.test", password_hash="x",
        first_name="Test", last_name="Owner", onboarded=True,
    ))

    provider = _CaptureProvider()

    async def _tenant_model(session):
        return "kimi:test-model"

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _tenant_model)
    monkeypatch.setattr(llm_service, "_resolve_model",
                        lambda model: ("gpt-4o-mini", None))
    monkeypatch.setattr(registry, "get_provider_for_model", lambda model: provider)
    monkeypatch.setattr(
        "app.modules.profile.business_profile.prompt_block", _no_business_card
    )
    return provider, _consumer


async def _channel(db, channel_id):
    return (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one()


def _msg(db, channel_id, contact, content, direction="inbound", i=0):
    """One ChannelMessage row.

    Inbound rows carry the SENDER and outbound rows the RECIPIENT — the split
    that makes a single contact filter return both halves of a conversation.
    """
    db.add(ChannelMessage(
        id=f"m{i}-{direction}-{contact}-{channel_id}",
        channel_id=channel_id,
        direction=direction,
        content=content,
        status="sent",
        contact_phone=contact,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
    ))


async def test_history_is_scoped_to_the_writing_contact(prompt_env, db, channel_id, user_id):
    """The reported bug, exactly: customer A writes English on a number where
    customer B has been writing Arabic. A's prompt must contain only A."""
    provider, consumer = prompt_env
    await db.commit()

    # Two customers on ONE channel (the same WhatsApp number) — the normal case.
    _msg(db, channel_id, "friend", "مرحبا كيف حالك", i=0)
    _msg(db, channel_id, "friend", "شكرا جزيلا", i=1)
    _msg(db, channel_id, "me", "hi, do you deliver to Manchester?", i=2)
    await db.commit()

    channel = await _channel(db, channel_id)
    await consumer._generate_reply(
        db, channel, user_id, "what time do you close?", contact="me"
    )

    sent = provider.sent_text()
    assert "do you deliver to Manchester" in sent, "A must see A's own history"
    assert "مرحبا" not in sent, "LEAK: B's Arabic leaked into A's prompt"
    assert "شكرا جزيلا" not in sent, "LEAK: B's follow-up leaked too"


async def test_outbound_rows_are_threaded_under_the_same_contact(prompt_env, db, channel_id, user_id):
    """Outbound rows carry the RECIPIENT, so one filter returns both halves.
    If this breaks, the assistant forgets what it already told the customer."""
    provider, consumer = prompt_env
    await db.commit()

    _msg(db, channel_id, "me", "I want to cancel", i=0)
    _msg(db, channel_id, "me", "Sure, cancelled order 4471 for you.", i=1,
         direction="outbound")
    _msg(db, channel_id, "other", "I want to cancel", i=2)
    _msg(db, channel_id, "other", "Sure, cancelled order 9999 for you.", i=3,
         direction="outbound")
    await db.commit()

    channel = await _channel(db, channel_id)
    await consumer._generate_reply(db, channel, user_id, "hello again", contact="me")

    sent = provider.sent_text()
    assert "cancelled order 4471" in sent, "A must see what we told A"
    assert "cancelled order 9999" not in sent, "LEAK: B's order number leaked"


async def test_unknown_contact_gets_no_history_not_channel_wide(prompt_env, db, channel_id, user_id):
    """A missing contact identity must NOT fall back to the channel-wide query
    — that fallback IS the leak."""
    provider, consumer = prompt_env
    await db.commit()

    _msg(db, channel_id, "someone", "my card number is 4111 1111 1111 1111", i=0)
    await db.commit()

    channel = await _channel(db, channel_id)
    await consumer._generate_reply(db, channel, user_id, "hello?", contact=None)

    assert "4111" not in provider.sent_text(), "LEAK: channel history used as fallback"


async def test_pre_column_null_contact_rows_are_excluded(prompt_env, db, channel_id, user_id):
    """Rows written before contact_phone existed are NULL. They cannot be
    attributed to a person, so they must not enter anyone's context."""
    provider, consumer = prompt_env
    await db.commit()

    _msg(db, channel_id, None, "legacy row from before the column existed", i=0)
    _msg(db, channel_id, "me", "my own message", i=1)
    await db.commit()

    channel = await _channel(db, channel_id)
    await consumer._generate_reply(db, channel, user_id, "hi", contact="me")

    sent = provider.sent_text()
    assert "my own message" in sent
    assert "legacy row" not in sent, "LEAK: unattributable row used as context"


async def test_a_contact_with_no_prior_history_still_gets_a_prompt(prompt_env, db, channel_id, user_id):
    """First-ever message from this customer: no history is fine, but the
    request must still be built and sent (system prompt + business card)."""
    provider, consumer = prompt_env
    await db.commit()

    _msg(db, channel_id, "someone-else", "unrelated chatter", i=0)
    await db.commit()

    channel = await _channel(db, channel_id)
    reply = await consumer._generate_reply(
        db, channel, user_id, "hello, first time here", contact="brand-new"
    )

    assert reply == "Sure, how can I help?"
    assert provider.requests, "a prompt must still be built"
    assert "unrelated chatter" not in provider.sent_text()
    # The system prompt must be present even with an empty history.
    assert provider.requests[0].system_prompt