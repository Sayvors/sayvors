"""WA-4: quoted replies, reactions, and honest local removal.

The Cloud API supports contextual replies and reactions. It has no edit or
delete-for-everyone endpoint for business messages, so removal is local and
explicitly labelled as such.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.channels import service as channel_service
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.service import (
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)

PHONE = "+966500000040"


async def _seed(db, tenant_id):
    channel = Channel(
        id=f"chan-wa4-{uuid.uuid4().hex[:8]}", user_id=tenant_id,
        platform="whatsapp", platform_user_id="pn-wa4",
        display_name="WA4", status="active",
    )
    db.add(channel)
    await db.flush()
    target = ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel.id,
        platform_message_id=f"wamid.target.{uuid.uuid4().hex[:8]}",
        direction="inbound", content=encrypt_message_content("where is my order?"),
        content_type="text", status="delivered",
        contact_phone=encrypt_contact_phone(PHONE),
        contact_phone_hash=hash_contact_phone(PHONE),
    )
    db.add(target)
    await db.commit()
    return channel, target


def _credentials(monkeypatch):
    async def _fake(_db, _user, _channel):
        return "pn-wa4", "tok", ""

    monkeypatch.setattr(channel_service, "_whatsapp_credentials", _fake)


@pytest.mark.asyncio
async def test_text_reply_carries_the_context_wamid(monkeypatch):
    captured: dict = {}

    class _Resp:
        def json(self):
            return {"messages": [{"id": "wamid.reply"}]}

    async def _graph(self, method, path, token, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    out = await WhatsAppAdapter().send_text_message(
        "pn", "tok", "+966500000040", "It ships today",
        context_message_id="wamid.target",
    )

    assert out == "wamid.reply"
    assert captured["json"]["context"] == {"message_id": "wamid.target"}
    assert captured["json"]["type"] == "text"


@pytest.mark.asyncio
async def test_reaction_payload_is_the_documented_shape(monkeypatch):
    captured: dict = {}

    class _Resp:
        def json(self):
            return {"messages": [{"id": "wamid.reaction"}]}

    async def _graph(self, method, path, token, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    out = await WhatsAppAdapter().send_reaction(
        "pn", "tok", "+966500000040", "wamid.target", "👍"
    )

    assert out == "wamid.reaction"
    assert captured["json"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "+966500000040",
        "type": "reaction",
        "reaction": {"message_id": "wamid.target", "emoji": "👍"},
    }


@pytest.mark.asyncio
async def test_inbox_reply_quotes_a_message_in_the_same_thread(
    client, db, user_id, monkeypatch
):
    channel, target = await _seed(db, user_id)
    _credentials(monkeypatch)
    captured: dict = {}

    async def _send(self, phone_number_id, token, to, text, **kwargs):
        captured.update({"to": to, "text": text, **kwargs})
        return "wamid.sent"

    monkeypatch.setattr(WhatsAppAdapter, "send_text_message", _send)

    res = client.post("/api/v1/inbox/send", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "content": "It ships today.",
        "reply_to_message_id": target.id,
    })

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True
    assert body["message"]["reply_to_message_id"] == target.platform_message_id
    assert captured["context_message_id"] == target.platform_message_id

    row = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.id == body["message"]["id"])
        )
    ).scalar_one()
    assert row.reply_to_message_id == target.platform_message_id


@pytest.mark.asyncio
async def test_a_quote_from_another_conversation_is_refused(
    client, db, user_id, monkeypatch
):
    channel, _target = await _seed(db, user_id)
    other_channel = Channel(
        id=f"chan-other-{uuid.uuid4().hex[:8]}", user_id=user_id,
        platform="whatsapp", platform_user_id="pn-other",
        display_name="Other", status="active",
    )
    db.add(other_channel)
    await db.flush()
    foreign = ChannelMessage(
        id=str(uuid.uuid4()), channel_id=other_channel.id,
        platform_message_id="wamid.foreign", direction="inbound",
        content=encrypt_message_content("not this thread"),
        content_type="text", status="delivered",
        contact_phone=encrypt_contact_phone("+966500000041"),
        contact_phone_hash=hash_contact_phone("+966500000041"),
    )
    db.add(foreign)
    await db.commit()

    res = client.post("/api/v1/inbox/send", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "content": "hello",
        "reply_to_message_id": foreign.id,
    })
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_reaction_endpoint_persists_the_sent_reaction(
    client, db, user_id, monkeypatch
):
    channel, target = await _seed(db, user_id)
    _credentials(monkeypatch)

    async def _react(self, phone_number_id, token, to, message_id, emoji):
        assert message_id == target.platform_message_id
        assert emoji == "❤️"
        return "wamid.reaction.sent"

    monkeypatch.setattr(WhatsAppAdapter, "send_reaction", _react)

    res = client.post(
        f"/api/v1/inbox/messages/{target.id}/reaction",
        json={"emoji": "❤️"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True
    assert body["message"]["content_type"] == "reaction"
    assert body["message"]["content"] == "❤️"
    assert body["message"]["reply_to_message_id"] == target.platform_message_id


@pytest.mark.asyncio
async def test_location_and_contact_payloads(monkeypatch):
    calls: list[dict] = []

    class _Resp:
        def json(self):
            return {"messages": [{"id": f"wamid.{len(calls)}"}]}

    async def _graph(self, method, path, token, **kwargs):
        calls.append(kwargs["json"])
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    await WhatsAppAdapter().send_location(
        "pn", "tok", "+966500000040", 24.7136, 46.6753,
        name="Aster Coffee", address="Olaya, Riyadh",
    )
    assert calls[0]["type"] == "location"
    assert calls[0]["location"] == {
        "latitude": 24.7136,
        "longitude": 46.6753,
        "name": "Aster Coffee",
        "address": "Olaya, Riyadh",
    }

    await WhatsAppAdapter().send_contacts(
        "pn", "tok", "+966500000040",
        [{
            "name": {"formatted_name": "Aster"},
            "phones": [{"phone": "+966500000000", "type": "WORK"}],
        }],
    )
    assert calls[1]["type"] == "contacts"
    assert calls[1]["contacts"][0]["phones"][0]["phone"] == "+966500000000"


@pytest.mark.asyncio
async def test_send_location_endpoint_stores_a_location_message(
    client, db, user_id, monkeypatch
):
    channel, _target = await _seed(db, user_id)
    _credentials(monkeypatch)

    async def _send(self, phone_number_id, token, to, lat, lng, **kwargs):
        assert (lat, lng) == (24.7136, 46.6753)
        assert kwargs["name"] == "Aster Coffee"
        return "wamid.location.sent"

    monkeypatch.setattr(WhatsAppAdapter, "send_location", _send)

    res = client.post("/api/v1/inbox/send-location", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "latitude": 24.7136,
        "longitude": 46.6753,
        "name": "Aster Coffee",
        "address": "Olaya, Riyadh",
    })

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True
    assert body["message"]["content_type"] == "location"
    assert "https://maps.google.com/?q=24.7136,46.6753" in body["message"]["content"]


@pytest.mark.asyncio
async def test_send_contact_endpoint_stores_a_contact_card(
    client, db, user_id, monkeypatch
):
    channel, _target = await _seed(db, user_id)
    _credentials(monkeypatch)

    async def _send(self, phone_number_id, token, to, contacts):
        card = contacts[0]
        assert card["name"]["formatted_name"] == "Aster"
        assert card["phones"][0]["phone"] == "+966500000000"
        return "wamid.contact.sent"

    monkeypatch.setattr(WhatsAppAdapter, "send_contacts", _send)

    res = client.post("/api/v1/inbox/send-contact", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "name": "Aster",
        "phone": "+966500000000",
    })

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True
    assert body["message"]["content_type"] == "contact"
    assert "Aster" in body["message"]["content"]


@pytest.mark.asyncio
async def test_location_coordinates_are_validated(client, db, user_id):
    channel, _target = await _seed(db, user_id)
    res = client.post("/api/v1/inbox/send-location", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "latitude": 91,
        "longitude": 46.6753,
    })
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_rich_messages_are_whatsapp_only(client, db, user_id):
    channel = Channel(
        id=f"chan-ig-{uuid.uuid4().hex[:8]}", user_id=user_id,
        platform="instagram", platform_user_id="ig-1",
        display_name="IG", status="active",
    )
    db.add(channel)
    await db.commit()

    res = client.post("/api/v1/inbox/send-location", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "latitude": 24.7,
        "longitude": 46.6,
    })
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_remove_is_local_and_never_claims_a_retraction(
    client, db, user_id
):
    channel, _target = await _seed(db, user_id)
    outbound = ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel.id,
        platform_message_id="wamid.outbound", direction="outbound",
        content=encrypt_message_content("wrong price"),
        content_type="text", status="sent",
        contact_phone=encrypt_contact_phone(PHONE),
        contact_phone_hash=hash_contact_phone(PHONE),
        handled_by="human",
    )
    db.add(outbound)
    await db.commit()

    res = client.delete(f"/api/v1/inbox/messages/{outbound.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deleted"] is True
    assert body["content"] == ""
    assert body["deleted_at"] is not None

    await db.refresh(outbound)
    assert outbound.deleted_at is not None
    assert outbound.deleted_by == user_id

    # An inbound customer message is evidence; it cannot be removed here.
    target = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.direction == "inbound")
        )
    ).scalars().first()
    denied = client.delete(f"/api/v1/inbox/messages/{target.id}")
    assert denied.status_code == 422, denied.text


@pytest.mark.asyncio
async def test_deleted_messages_are_excluded_from_ai_history(db, user_id):
    from app.modules.channels.conversation_context import _transcript

    channel, target = await _seed(db, user_id)
    target.deleted_at = datetime.now(timezone.utc)
    db.add(target)
    normal = ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel.id,
        platform_message_id="wamid.normal", direction="inbound",
        content=encrypt_message_content("keep this"),
        content_type="text", status="delivered",
        contact_phone=encrypt_contact_phone(PHONE),
        contact_phone_hash=hash_contact_phone(PHONE),
    )
    db.add(normal)
    await db.commit()

    transcript = await _transcript(
        db, channel_id=channel.id, contact_phone=PHONE
    )
    text = " ".join(body for _speaker, body in transcript)
    assert "keep this" in text
    assert "where is my order?" not in text
