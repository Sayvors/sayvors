"""WA-2 / WA-3: inbound attachments and outbound documents/stickers.

Inbound images, documents and stickers are downloaded once and stored in the
private document store; the inbox reads them through an authenticated route.
Outbound documents and stickers are uploaded to Meta and mirrored privately so
the thread shows exactly what the customer received. Video is deliberately out
of scope.
"""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.modules.channels import service as channel_service
from app.modules.channels.meta import consumer
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter
from app.modules.channels.meta.webhooks import parser
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.service import (
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)

PHONE = "+966500000040"


def _local_docs(monkeypatch, tmp_path):
    """Force the private document store onto a temp directory."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "")


async def _seed_channel(db, tenant_id, *, platform="whatsapp"):
    channel = Channel(
        id=f"chan-media-{uuid.uuid4().hex[:8]}", user_id=tenant_id,
        platform=platform, platform_user_id="pn-media",
        display_name="Media", status="active",
    )
    db.add(channel)
    await db.commit()
    return channel


def _credentials(monkeypatch):
    async def _fake(_db, _user, _channel):
        return "pn-media", "tok", ""

    monkeypatch.setattr(channel_service, "_whatsapp_credentials", _fake)


def test_parser_hoists_an_image_caption_into_text():
    _provider, events = parser.parse({
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-1"},
                    "messages": [{
                        "id": "wamid-image-1",
                        "from": "966500001111",
                        "timestamp": "1700000000",
                        "type": "image",
                        "image": {
                            "id": "media-image-1",
                            "mime_type": "image/jpeg",
                            "caption": "This receipt is wrong",
                        },
                    }],
                },
            }],
        }],
    })

    data = events[0]["data"]
    assert data["msg_type"] == "image"
    assert data["text"] == "This receipt is wrong"
    assert data["media"]["id"] == "media-image-1"


@pytest.mark.asyncio
async def test_inbound_document_is_stored_privately(monkeypatch, tmp_path):
    _local_docs(monkeypatch, tmp_path)

    async def _download(media_id, token, **kwargs):
        assert media_id == "media-doc-1"
        assert token == "tok"
        assert kwargs["max_bytes"] == consumer.INBOUND_MEDIA_MAX_BYTES
        return b"%PDF-1.4 fake invoice", "application/pdf"

    monkeypatch.setattr(
        "app.modules.channels.meta.media.download_whatsapp_media", _download
    )

    row = SimpleNamespace(
        id="msg-doc-1", content_type="document",
        media_key=None, media_mime_type=None, media_filename=None,
    )
    stored = await consumer._store_inbound_media(
        row,
        tenant_id="tenant-1",
        data={"media": {
            "id": "media-doc-1",
            "mime_type": "application/pdf",
            "filename": "invoice.pdf",
        }},
        token="tok",
        wamid="wamid-doc-1",
    )

    assert stored is True
    assert row.media_key == "msg-doc-1.pdf"
    assert row.media_mime_type == "application/pdf"
    assert row.media_filename == "invoice.pdf"
    path = tmp_path / "inbox-tenant-1" / "msg-doc-1.pdf"
    assert path.read_bytes() == b"%PDF-1.4 fake invoice"


@pytest.mark.asyncio
async def test_inbound_media_never_uses_the_customer_filename_as_a_path(
    monkeypatch, tmp_path
):
    _local_docs(monkeypatch, tmp_path)

    async def _download(media_id, token, **kwargs):
        return b"fake", "application/pdf"

    monkeypatch.setattr(
        "app.modules.channels.meta.media.download_whatsapp_media", _download
    )

    row = SimpleNamespace(
        id="msg-safe-1", content_type="document",
        media_key=None, media_mime_type=None, media_filename=None,
    )
    assert await consumer._store_inbound_media(
        row,
        tenant_id="tenant-1",
        data={"media": {
            "id": "media-safe-1",
            "mime_type": "application/pdf",
            "filename": "..\\..\\secrets.pdf",
        }},
        token="tok",
        wamid="wamid-safe-1",
    )
    assert row.media_key == "msg-safe-1.pdf"
    assert row.media_filename == "secrets.pdf"
    assert not (tmp_path / "secrets.pdf").exists()


@pytest.mark.asyncio
async def test_inbound_media_failure_keeps_the_message_usable(
    monkeypatch, tmp_path
):
    _local_docs(monkeypatch, tmp_path)

    from app.modules.channels.meta.media import MediaDownloadError

    async def _download(media_id, token, **kwargs):
        raise MediaDownloadError("expired media url")

    monkeypatch.setattr(
        "app.modules.channels.meta.media.download_whatsapp_media", _download
    )

    row = SimpleNamespace(
        id="msg-fail-1", content_type="image",
        media_key=None, media_mime_type=None, media_filename=None,
    )
    assert await consumer._store_inbound_media(
        row,
        tenant_id="tenant-1",
        data={"media": {"id": "media-fail-1", "mime_type": "image/jpeg"}},
        token="tok",
        wamid="wamid-fail-1",
    ) is False
    assert row.media_key is None


@pytest.mark.asyncio
async def test_attachment_without_caption_gets_an_honest_line(db, channel_id):
    sent: list[str] = []

    class _Adapter:
        async def send_text_message(self, phone_number_id, token, to, text):
            sent.append(text)
            return "wamid-out-media"

    await consumer._reply_attachment_needs_context(
        db, _Adapter(), "phone-1", "tok", PHONE, channel_id,
        "tenant-1", "en", unreadable=False,
    )

    assert sent == [consumer.ATTACHMENT_NEEDS_CONTEXT_TEXT["en"]]

    row = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.direction == "outbound")
        )
    ).scalars().one()
    assert row.handled_by == "system"
    assert row.is_ai is False
    assert (
        channel_service.decrypt_message_content(row.content)
        == consumer.ATTACHMENT_NEEDS_CONTEXT_TEXT["en"]
    )


@pytest.mark.asyncio
async def test_unreadable_attachment_says_so(db, channel_id):
    sent: list[str] = []

    class _Adapter:
        async def send_text_message(self, phone_number_id, token, to, text):
            sent.append(text)
            return "wamid-out-media"

    await consumer._reply_attachment_needs_context(
        db, _Adapter(), "phone-1", "tok", PHONE, channel_id,
        "tenant-1", "ar", unreadable=True,
    )
    assert sent == [consumer.ATTACHMENT_UNREADABLE_TEXT["ar"]]


@pytest.mark.asyncio
async def test_document_and_sticker_payloads(monkeypatch):
    calls: list[dict] = []

    class _Resp:
        def json(self):
            return {"messages": [{"id": f"wamid.{len(calls)}"}]}

    async def _graph(self, method, path, token, **kwargs):
        calls.append(kwargs["json"])
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    await WhatsAppAdapter().send_document(
        "pn", "tok", PHONE, "media-doc-1",
        filename="invoice.pdf", caption="Your invoice",
    )
    assert calls[0] == {
        "messaging_product": "whatsapp",
        "to": PHONE,
        "type": "document",
        "document": {
            "id": "media-doc-1",
            "filename": "invoice.pdf",
            "caption": "Your invoice",
        },
    }

    await WhatsAppAdapter().send_sticker("pn", "tok", PHONE, "media-sticker-1")
    assert calls[1] == {
        "messaging_product": "whatsapp",
        "to": PHONE,
        "type": "sticker",
        "sticker": {"id": "media-sticker-1"},
    }


@pytest.mark.asyncio
async def test_send_document_endpoint_stores_and_sends(
    client, db, user_id, monkeypatch, tmp_path
):
    _local_docs(monkeypatch, tmp_path)
    channel = await _seed_channel(db, user_id)
    _credentials(monkeypatch)

    captured: dict = {}

    async def _upload(self, phone_number_id, token, data, mime_type, filename="media"):
        captured["upload"] = (data, mime_type, filename)
        return "media-doc-uploaded"

    async def _send(self, phone_number_id, token, to, media_id, **kwargs):
        captured["send"] = (media_id, kwargs)
        return "wamid.document.sent"

    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)
    monkeypatch.setattr(WhatsAppAdapter, "send_document", _send)

    res = client.post(
        "/api/v1/inbox/send-document",
        data={
            "channel_id": channel.id,
            "contact_phone": PHONE,
            "caption": "Your invoice",
        },
        files={"file": ("invoice.pdf", b"%PDF-1.4 invoice", "application/pdf")},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True
    message = body["message"]
    assert message["content_type"] == "document"
    assert message["media_filename"] == "invoice.pdf"
    assert message["media_mime_type"] == "application/pdf"
    assert message["media_url"] == f"/api/v1/inbox/media/{message['id']}"
    assert captured["upload"] == (b"%PDF-1.4 invoice", "application/pdf", "invoice.pdf")
    assert captured["send"][0] == "media-doc-uploaded"
    assert captured["send"][1]["caption"] == "Your invoice"

    stored = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.id == message["id"])
        )
    ).scalar_one()
    assert stored.media_key
    assert (tmp_path / f"inbox-{user_id}" / stored.media_key).read_bytes() == (
        b"%PDF-1.4 invoice"
    )


@pytest.mark.asyncio
async def test_send_sticker_endpoint_accepts_webp(
    client, db, user_id, monkeypatch, tmp_path
):
    _local_docs(monkeypatch, tmp_path)
    channel = await _seed_channel(db, user_id)
    _credentials(monkeypatch)

    async def _upload(self, phone_number_id, token, data, mime_type, filename="media"):
        assert mime_type == "image/webp"
        return "media-sticker-uploaded"

    async def _send(self, phone_number_id, token, to, media_id):
        assert media_id == "media-sticker-uploaded"
        return "wamid.sticker.sent"

    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)
    monkeypatch.setattr(WhatsAppAdapter, "send_sticker", _send)

    res = client.post(
        "/api/v1/inbox/send-sticker",
        data={"channel_id": channel.id, "contact_phone": PHONE},
        files={"file": ("party.webp", b"RIFFfake-webp", "image/webp")},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True
    assert body["message"]["content_type"] == "sticker"
    assert body["message"]["media_url"]


@pytest.mark.asyncio
async def test_send_sticker_rejects_non_webp(client, db, user_id, monkeypatch, tmp_path):
    _local_docs(monkeypatch, tmp_path)
    channel = await _seed_channel(db, user_id)
    _credentials(monkeypatch)

    res = client.post(
        "/api/v1/inbox/send-sticker",
        data={"channel_id": channel.id, "contact_phone": PHONE},
        files={"file": ("party.png", b"\x89PNG fake", "image/png")},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_inbox_media_route_serves_a_stored_attachment(
    client, db, user_id, monkeypatch, tmp_path
):
    _local_docs(monkeypatch, tmp_path)
    channel = await _seed_channel(db, user_id)
    key = "msg-media-route.pdf"
    docs = tmp_path / f"inbox-{user_id}"
    docs.mkdir(parents=True)
    (docs / key).write_bytes(b"%PDF-1.4 served")

    message = ChannelMessage(
        id="msg-media-route",
        channel_id=channel.id,
        direction="inbound",
        content=encrypt_message_content("[document message]"),
        content_type="document",
        status="delivered",
        contact_phone=encrypt_contact_phone(PHONE),
        contact_phone_hash=hash_contact_phone(PHONE),
        media_key=key,
        media_mime_type="application/pdf",
        media_filename="invoice.pdf",
    )
    db.add(message)
    await db.commit()

    res = client.get(f"/api/v1/inbox/media/{message.id}")
    assert res.status_code == 200, res.text
    assert res.content == b"%PDF-1.4 served"
    # Documents download as octet-stream; only raster images are inline.
    assert res.headers["content-type"] == "application/octet-stream"
    assert "attachment" in res.headers["content-disposition"]
    assert res.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_inbox_media_route_hides_deleted_and_foreign_messages(
    client, db, user_id, other_user_id, monkeypatch, tmp_path
):
    _local_docs(monkeypatch, tmp_path)
    channel = await _seed_channel(db, user_id)
    key = "msg-hidden.pdf"
    docs = tmp_path / f"inbox-{user_id}"
    docs.mkdir(parents=True)
    (docs / key).write_bytes(b"private")

    deleted = ChannelMessage(
        id="msg-media-deleted",
        channel_id=channel.id,
        direction="inbound",
        content=encrypt_message_content("[document message]"),
        content_type="document",
        status="delivered",
        contact_phone=encrypt_contact_phone(PHONE),
        contact_phone_hash=hash_contact_phone(PHONE),
        media_key=key,
        media_mime_type="application/pdf",
        media_filename="invoice.pdf",
        deleted_at=channel.created_at,
    )
    foreign_channel = Channel(
        id="chan-media-foreign", user_id=other_user_id,
        platform="whatsapp", platform_user_id="pn-other",
        display_name="Other", status="active",
    )
    foreign = ChannelMessage(
        id="msg-media-foreign",
        channel_id=foreign_channel.id,
        direction="inbound",
        content=encrypt_message_content("[document message]"),
        content_type="document",
        status="delivered",
        contact_phone=encrypt_contact_phone(PHONE),
        contact_phone_hash=hash_contact_phone(PHONE),
        media_key=key,
        media_mime_type="application/pdf",
        media_filename="invoice.pdf",
    )
    db.add_all([deleted, foreign_channel, foreign])
    await db.commit()

    assert client.get(f"/api/v1/inbox/media/{deleted.id}").status_code == 404
    assert client.get(f"/api/v1/inbox/media/{foreign.id}").status_code == 404
    assert client.get("/api/v1/inbox/media/does-not-exist").status_code == 404
