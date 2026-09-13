"""Meta webhook tests: signature, handshake, parsing, dedupe, routing."""
import hashlib
import hmac
import json
import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.channels.meta.models import MetaAsset, MetaConnection, MetaWebhookEvent
from app.modules.channels.meta.webhooks import parser as _parser
from app.modules.channels.meta.webhooks import verifier as _verifier
from app.modules.outbox.models import EventOutbox

APP_SECRET = "test-app-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _meta_env(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "test-verify-token")
    from app import config as _config

    monkeypatch.setattr(_config.settings, "META_APP_SECRET", APP_SECRET)
    monkeypatch.setattr(_config.settings, "META_WEBHOOK_VERIFY_TOKEN", "test-verify-token")


# ── verifier ─────────────────────────────────────────────


def test_verify_signature_valid():
    body = b'{"object":"page"}'
    assert _verifier.verify_signature(body, _sign(body)) is True


def test_verify_signature_invalid():
    assert _verifier.verify_signature(b"{}", "sha256=deadbeef") is False
    assert _verifier.verify_signature(b"{}", None) is False


def test_verify_signature_legacy_without_prefix():
    body = b'{"a":1}'
    raw_hex = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert _verifier.verify_signature(body, raw_hex) is True


def test_handshake_ok():
    assert _verifier.verify_handshake("subscribe", "test-verify-token", "CH") == "CH"


def test_handshake_rejected():
    assert _verifier.verify_handshake("subscribe", "wrong", "CH") is None
    assert _verifier.verify_handshake("unsubscribe", "test-verify-token", "CH") is None


# ── parser ───────────────────────────────────────────────


def test_parse_whatsapp_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "pn-1"},
                    "messages": [{
                        "id": "wamid.1", "from": "15551234567", "type": "text",
                        "text": {"body": "hello"}, "timestamp": "1757721600",
                    }],
                },
            }],
        }],
    }
    provider, events = _parser.parse(payload)
    assert provider == "whatsapp"
    assert len(events) == 1
    assert events[0]["event_type"] == "message.received"
    assert events[0]["external_asset_id"] == "pn-1"
    assert events[0]["data"]["text"] == "hello"


def test_parse_whatsapp_status():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "pn-1"},
                    "statuses": [{"id": "wamid.2", "status": "delivered",
                                  "recipient_id": "1555", "timestamp": "1757721600"}],
                },
            }],
        }],
    }
    provider, events = _parser.parse(payload)
    assert events[0]["event_type"] == "message.status"
    assert events[0]["data"]["status"] == "delivered"


def test_parse_page_comment():
    payload = {
        "object": "page",
        "entry": [{
            "id": "page-9",
            "changes": [{
                "field": "feed",
                "value": {"item": "comment", "verb": "add",
                          "comment_id": "c-1", "post_id": "p-1",
                          "message": "nice!", "from": {"id": "u-1"}},
            }],
        }],
    }
    provider, events = _parser.parse(payload)
    assert provider == "facebook"
    assert events[0]["event_type"] == "comment.received"
    assert events[0]["external_asset_id"] == "page-9"


def test_parse_instagram_comment():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "ig-7", "time": 1757721600,
            "changes": [{
                "field": "comments",
                "value": {"id": "ic-1", "text": "love it",
                          "from": {"username": "fan"}},
            }],
        }],
    }
    provider, events = _parser.parse(payload)
    assert provider == "instagram"
    assert events[0]["event_type"] == "comment.received"


def test_parse_unknown_object():
    assert _parser.parse({"object": "nope"}) == ("unknown", [])


# ── ingress ──────────────────────────────────────────────


async def _seed_asset(db, external, tenant="test-user-0000-0000-0000-000000000001"):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=tenant,
        provider="whatsapp", access_token_encrypted="x", status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=str(uuid.uuid4()), tenant_id=tenant, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=external, phone="+1555", active=True,
    ))
    await db.commit()


def _wa_body(phone_number_id, msg_id, text="hi"):
    return json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": phone_number_id},
                    "messages": [{
                        "id": msg_id, "from": "1555", "type": "text",
                        "text": {"body": text}, "timestamp": "1757721600",
                    }],
                },
            }],
        }],
    }).encode()


@pytest.mark.asyncio
async def test_ingress_handshake(client, engine):
    resp = client.get(
        "/api/v1/meta/webhooks",
        params={"hub.mode": "subscribe", "hub.challenge": "CH123",
                "hub.verify_token": "test-verify-token"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 200
    assert resp.text == "CH123"


@pytest.mark.asyncio
async def test_ingress_handshake_invalid_token(client, engine):
    resp = client.get(
        "/api/v1/meta/webhooks",
        params={"hub.mode": "subscribe", "hub.challenge": "CH456",
                "hub.verify_token": "wrong-token"},
        headers={"host": "localhost"},
    )
    assert resp.status_code == 403

    resp2 = client.get(
        "/api/v1/meta/webhooks",
        params={"hub.mode": "subscribe", "hub.challenge": "CH789",
                "hub.verify_token": "test-verify-token"},
        headers={"host": "localhost"},
    )
    assert resp2.status_code == 200
    assert resp2.text == "CH789"


@pytest.mark.asyncio
async def test_ingress_bad_signature(client, engine):
    resp = client.post(
        "/api/v1/meta/webhooks",
        content=b"{}",
        headers={"host": "localhost", "x-hub-signature-256": "sha256=bad"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ingress_message_resolves_tenant(client, engine, db):
    await _seed_asset(db, "pn-1")
    body = _wa_body("pn-1", "wamid.ingress.1")
    resp = client.post(
        "/api/v1/meta/webhooks", content=body,
        headers={"host": "localhost", "x-hub-signature-256": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["events"] == 1

    row = (await db.execute(
        select(MetaWebhookEvent).where(
            MetaWebhookEvent.external_event_id == "wamid.ingress.1"
        )
    )).scalar_one()
    assert row.tenant_id == "test-user-0000-0000-0000-000000000001"
    assert row.status == "received"


@pytest.mark.asyncio
async def test_ingress_duplicate_is_idempotent(client, engine, db):
    await _seed_asset(db, "pn-9")
    body = _wa_body("pn-9", "wamid.dupe.1", "hi again")
    headers = {"host": "localhost", "x-hub-signature-256": _sign(body)}
    assert client.post("/api/v1/meta/webhooks", content=body, headers=headers).status_code == 200
    assert client.post("/api/v1/meta/webhooks", content=body, headers=headers).status_code == 200

    rows = (await db.execute(
        select(MetaWebhookEvent).where(
            MetaWebhookEvent.external_event_id == "wamid.dupe.1"
        )
    )).scalars().all()
    assert len(rows) == 1  # single row: no double-processing


@pytest.mark.asyncio
async def test_ingress_unknown_asset_unresolved(client, engine, db):
    body = _wa_body("pn-ghost", "wamid.ghost.1", "boo")
    resp = client.post(
        "/api/v1/meta/webhooks", content=body,
        headers={"host": "localhost", "x-hub-signature-256": _sign(body)},
    )
    assert resp.status_code == 200  # accepted, parked as unresolved

    row = (await db.execute(
        select(MetaWebhookEvent).where(
            MetaWebhookEvent.external_event_id == "wamid.ghost.1"
        )
    )).scalar_one()
    assert row.status == "unresolved"
    assert row.tenant_id is None


@pytest.mark.asyncio
async def test_ingress_resolved_enqueues_outbox(client, engine, db):
    """A resolved asset must produce a normalized outbox event (Kafka path)."""
    await _seed_asset(db, "pn-outbox")
    body = _wa_body("pn-outbox", "wamid.outbox.1", "hello outbox")
    resp = client.post(
        "/api/v1/meta/webhooks", content=body,
        headers={"host": "localhost", "x-hub-signature-256": _sign(body)},
    )
    assert resp.status_code == 200

    outbox = (await db.execute(
        select(EventOutbox).where(EventOutbox.topic == "meta-events")
    )).scalar_one()
    assert outbox.event_type == "meta.message.received"
    assert outbox.payload["tenant_id"] == "test-user-0000-0000-0000-000000000001"
    assert outbox.payload["external_asset_id"] == "pn-outbox"
    assert outbox.payload["payload"]["text"] == "hello outbox"


@pytest.mark.asyncio
async def test_ingress_unresolved_no_outbox(client, engine, db):
    """Unknown assets are parked and never enqueue anything downstream."""
    body = _wa_body("pn-nobody", "wamid.nooutbox.1", "orphan")
    client.post(
        "/api/v1/meta/webhooks", content=body,
        headers={"host": "localhost", "x-hub-signature-256": _sign(body)},
    )
    rows = (await db.execute(select(EventOutbox))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingress_cross_tenant_isolation(client, engine, db):
    """Tenant B's phone never resolves to Tenant A's connection/tenant."""
    tenant_a = "test-user-0000-0000-0000-000000000001"
    tenant_b = "tenant-b-0000-0000-0000-000000000002"
    await _seed_asset(db, "pn-a", tenant=tenant_a)
    await _seed_asset(db, "pn-b", tenant=tenant_b)

    body = _wa_body("pn-b", "wamid.cross.1", "from tenant B")
    resp = client.post(
        "/api/v1/meta/webhooks", content=body,
        headers={"host": "localhost", "x-hub-signature-256": _sign(body)},
    )
    assert resp.status_code == 200

    row = (await db.execute(
        select(MetaWebhookEvent).where(
            MetaWebhookEvent.external_event_id == "wamid.cross.1"
        )
    )).scalar_one()
    assert row.tenant_id == tenant_b  # never tenant A

    outbox = (await db.execute(select(EventOutbox))).scalars().all()
    assert len(outbox) == 1
    assert outbox[0].payload["tenant_id"] == tenant_b


@pytest.mark.asyncio
async def test_ingress_fast_no_ai_sync(client, engine, db):
    """Ingress is a fast path: returns quickly and never calls the LLM."""
    await _seed_asset(db, "pn-fast")
    body = _wa_body("pn-fast", "wamid.fast.1", "timing")
    headers = {"host": "localhost", "x-hub-signature-256": _sign(body)}

    start = time.perf_counter()
    resp = client.post("/api/v1/meta/webhooks", content=body, headers=headers)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "events": 1}
    assert elapsed_ms < 2000  # far below any AI round-trip; pure DB fast path
    # The response body contains only counts — never an AI draft or secret.
    assert "draft" not in json.dumps(resp.json()).lower()


@pytest.mark.asyncio
async def test_ingress_no_secret_in_logs(client, engine, db, caplog):
    """App secret and verify token must never appear in log output."""
    import logging

    caplog.set_level(logging.INFO)
    await _seed_asset(db, "pn-secret")
    body = _wa_body("pn-secret", "wamid.secret.1", "shh")
    resp = client.post(
        "/api/v1/meta/webhooks", content=body,
        headers={"host": "localhost", "x-hub-signature-256": _sign(body)},
    )
    assert resp.status_code == 200
    # Trigger a rejected path too (403 logs a warning).
    client.post(
        "/api/v1/meta/webhooks", content=b"{}",
        headers={"host": "localhost", "x-hub-signature-256": "sha256=nope"},
    )

    log_text = "\n".join(r.message for r in caplog.records)
    assert "test-app-secret" not in log_text
    assert "test-verify-token" not in log_text
