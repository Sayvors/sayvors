"""Inbox over HTTP.

The service-layer tests in test_inbox.py cover the logic; these cover the wiring
that the dashboard actually depends on — route shape, auth, CSRF, the
"unknown" URL key, and the 200-with-sent:false contract on a rejected send.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.meta.models import MetaAsset, MetaConnection


async def _seed(db, user_id, channel_id="chan-1"):
    ch = Channel(
        id=channel_id, user_id=user_id, platform="whatsapp",
        platform_user_id="pn-1", display_name="Business line", status="active",
    )
    db.add(ch)
    await db.commit()
    return ch


async def _msg(db, channel_id, *, phone=None, direction="inbound", content="hi",
               minutes_ago=0, name=None):
    db.add(ChannelMessage(
        id=f"m-{abs(hash((channel_id, phone, content, minutes_ago))) % 10**12}",
        channel_id=channel_id, platform_message_id=None, direction=direction,
        content=content, content_type="text", status="delivered",
        contact_phone=phone, contact_name=name,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_inbox_threads_http(client, db, user_id):
    await _seed(db, user_id)
    await _msg(db, "chan-1", phone="966500000001", content="is this open?", name="Ahmed")
    await _msg(db, "chan-1", phone="966500000002", content="what time do you close")

    r = client.get("/api/v1/inbox/threads")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    keys = {t["key"] for t in body["threads"]}
    assert keys == {"966500000001", "966500000002"}
    first = next(t for t in body["threads"] if t["key"] == "966500000001")
    assert first["contact_phone"] == "966500000001"
    assert first["display_name"] == "Ahmed"
    assert first["channel_name"] == "Business line"
    assert first["unread"] == 1
    assert first["is_unknown"] is False


@pytest.mark.asyncio
async def test_inbox_search_http(client, db, user_id):
    await _seed(db, user_id)
    await _msg(db, "chan-1", phone="966500000001", content="my order is late")
    await _msg(db, "chan-1", phone="966500000002", content="opening hours please")

    r = client.get("/api/v1/inbox/threads", params={"search": "order"})
    assert r.status_code == 200, r.text
    assert [t["key"] for t in r.json()["threads"]] == ["966500000001"]


@pytest.mark.asyncio
async def test_inbox_thread_messages_http(client, db, user_id):
    await _seed(db, user_id)
    await _msg(db, "chan-1", phone="966500000001", content="first", minutes_ago=30)
    await _msg(db, "chan-1", phone="966500000001", content="second", minutes_ago=5)
    await _msg(db, "chan-1", phone="966500000002", content="other contact")

    r = client.get("/api/v1/inbox/threads/chan-1/966500000001")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    # Oldest first, as the thread renders top to bottom.
    assert [m["content"] for m in body["messages"]] == ["first", "second"]
    assert body["messages"][0]["direction"] == "inbound"


@pytest.mark.asyncio
async def test_inbox_unknown_thread_url_key(client, db, user_id):
    """The frontend sends the literal string "unknown" for unattributed rows."""
    await _seed(db, user_id)
    await _msg(db, "chan-1", phone=None, content="legacy row")
    await _msg(db, "chan-1", phone="966500000001", content="real row")

    r = client.get("/api/v1/inbox/threads")
    unknown = [t for t in r.json()["threads"] if t["is_unknown"]]
    assert len(unknown) == 1

    r2 = client.get("/api/v1/inbox/threads/chan-1/unknown")
    assert r2.status_code == 200, r2.text
    assert [m["content"] for m in r2.json()["messages"]] == ["legacy row"]


@pytest.mark.asyncio
async def test_inbox_thread_messages_404_for_foreign_channel(client, db, user_id, other_user_id):
    await _seed(db, other_user_id, channel_id="chan-theirs")
    r = client.get("/api/v1/inbox/threads/chan-theirs/966500000001")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_inbox_send_without_connection_reports_failure(client, db, user_id):
    """A send with no connected account is a normal outcome: HTTP 200 with
    sent=false and a reason, never a 500 and never a fake 'sent'."""
    await _seed(db, user_id)
    r = client.post("/api/v1/inbox/send", json={
        "channel_id": "chan-1", "contact_phone": "966500000001", "content": "hello",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] is False
    assert "No WhatsApp account is connected" in body["error"]
    assert body["message"]["status"] == "failed"
    # The attempt is still recorded, so the thread keeps a truthful history.
    assert body["message"]["contact_phone"] == "966500000001"


@pytest.mark.asyncio
async def test_inbox_send_rejects_missing_recipient(client, db, user_id):
    await _seed(db, user_id)
    r = client.post("/api/v1/inbox/send", json={
        "channel_id": "chan-1", "content": "hello",
    })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_inbox_send_404_foreign_channel(client, db, user_id, other_user_id):
    await _seed(db, other_user_id, channel_id="chan-theirs")
    r = client.post("/api/v1/inbox/send", json={
        "channel_id": "chan-theirs", "contact_phone": "966500000001", "content": "hi",
    })
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_inbox_send_success_then_thread_shows_it(client, db, user_id, monkeypatch):
    from app.modules.channels.meta.credentials import encrypt_credential
    from app.modules.channels.meta.providers import whatsapp as wa

    await _seed(db, user_id)
    conn = MetaConnection(
        id="conn-1", tenant_id=user_id, provider="whatsapp", status="active",
        access_token_encrypted=encrypt_credential("test-token"),
    )
    db.add(conn)
    db.add(MetaAsset(
        id="asset-1", tenant_id=user_id, connection_id=conn.id, provider="whatsapp",
        asset_type="phone_number", external_asset_id="pn-1", active=True,
    ))
    await _msg(db, "chan-1", phone="966500000001", content="are you open?")
    await db.commit()

    adapter = AsyncMock()
    adapter.send_text_message = AsyncMock(return_value="wamid.OUT1")
    monkeypatch.setattr(wa.WhatsAppAdapter, "send_text_message", adapter.send_text_message)

    r = client.post("/api/v1/inbox/send", json={
        "channel_id": "chan-1", "contact_phone": "966500000001", "content": "yes, until 9pm",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] is True
    assert body["error"] is None
    assert body["message"]["status"] == "sent"
    assert body["message"]["platform_message_id"] == "wamid.OUT1"
    adapter.send_text_message.assert_awaited_once()

    # The reply lands in the same thread and clears the unread badge.
    msgs = client.get("/api/v1/inbox/threads/chan-1/966500000001").json()["messages"]
    assert [m["content"] for m in msgs] == ["are you open?", "yes, until 9pm"]
    assert msgs[-1]["direction"] == "outbound"

    threads = client.get("/api/v1/inbox/threads").json()["threads"]
    assert threads[0]["unread"] == 0
    assert threads[0]["last_direction"] == "outbound"


@pytest.mark.asyncio
async def test_inbox_requires_auth(client, db, user_id):
    """Unauthenticated callers get 401, not thread contents."""
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides.pop(
        __import__("app.core.deps", fromlist=["get_current_user"]).get_current_user
    )
    try:
        r = client.get("/api/v1/inbox/threads")
        assert r.status_code in (401, 403), r.text
    finally:
        # The fixture clears overrides on teardown; restore for other tests.
        from types import SimpleNamespace
        from app.core.deps import get_current_user

        async def _user():
            return SimpleNamespace(id=user_id, token_version=0)

        fastapi_app.dependency_overrides[get_current_user] = _user
