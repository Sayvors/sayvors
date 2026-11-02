"""WhatsApp status media: SSRF guard, MIME selection, and error hygiene."""
import pytest

from app.core.http import UnsafeUrlError
from app.modules.channels.meta.providers import whatsapp as wa
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.whatsapp import (
    MAX_STATUS_IMAGE_BYTES,
    MAX_STATUS_VIDEO_BYTES,
    WhatsAppAdapter,
)


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _publish(adapter: WhatsAppAdapter, **overrides):
    kwargs = {
        "token": "tok",
        "asset_id": "pn-1",
        "media_url": "https://cdn.example.com/status.png",
        "media_type": "image",
        "caption": "Hello",
        "method": "status",
        "description": "",
        "scheduled_at": None,
    }
    kwargs.update(overrides)
    return adapter.publish_post(**kwargs)


@pytest.mark.asyncio
async def test_status_media_fetches_pinned_and_uploads_real_mime(monkeypatch):
    adapter = WhatsAppAdapter()
    captured: dict = {}

    def _fetch(url, **kwargs):
        captured["fetch"] = (url, kwargs)
        return b"png-bytes", "image/png"

    async def _upload(self, phone_number_id, token, data, mime_type, filename="media"):
        captured["upload"] = (phone_number_id, data, mime_type)
        return "media-1"

    async def _graph(self, method, path, token, **kwargs):
        captured["graph"] = (method, path, kwargs)
        return _Resp({"messages": [{"id": "wamid.status"}]})

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)
    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)
    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    try:
        result = await _publish(adapter)
    finally:
        await adapter.close()

    url, fetch_kwargs = captured["fetch"]
    assert url == "https://cdn.example.com/status.png"
    assert fetch_kwargs["max_bytes"] == MAX_STATUS_IMAGE_BYTES
    assert fetch_kwargs["user_agent"] == "SayvorsMedia/1.0"
    assert captured["upload"] == ("pn-1", b"png-bytes", "image/png")

    method, path, graph_kwargs = captured["graph"]
    assert (method, path) == ("POST", "/pn-1/messages")
    body = graph_kwargs["json"]
    assert body["type"] == "image"
    assert body["image"] == {"id": "media-1", "caption": "Hello"}
    assert result == {
        "provider": "whatsapp",
        "message_id": "wamid.status",
        "method": "status",
        "asset_id": "pn-1",
    }


@pytest.mark.asyncio
async def test_status_video_uses_video_kind_and_mime(monkeypatch):
    adapter = WhatsAppAdapter()
    captured: dict = {}

    def _fetch(url, **kwargs):
        captured["fetch_max_bytes"] = kwargs["max_bytes"]
        return b"mp4-bytes", "video/mp4"

    async def _upload(self, phone_number_id, token, data, mime_type, filename="media"):
        captured["mime"] = mime_type
        return "media-video"

    async def _graph(self, method, path, token, **kwargs):
        captured["body"] = kwargs["json"]
        return _Resp({"messages": [{"id": "wamid.video"}]})

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)
    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)
    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    try:
        await _publish(adapter, media_type="video", media_url="https://cdn.example.com/v.mp4")
    finally:
        await adapter.close()

    assert captured["mime"] == "video/mp4"
    assert captured["fetch_max_bytes"] == MAX_STATUS_VIDEO_BYTES
    assert captured["body"]["type"] == "video"
    assert captured["body"]["video"] == {"id": "media-video", "caption": "Hello"}


@pytest.mark.asyncio
async def test_status_media_falls_back_when_content_type_is_not_media(monkeypatch):
    adapter = WhatsAppAdapter()
    captured: dict = {}

    def _fetch(url, **kwargs):
        return b"bytes", "text/html"

    async def _upload(self, phone_number_id, token, data, mime_type, filename="media"):
        captured["mime"] = mime_type
        return "media-1"

    async def _graph(self, method, path, token, **kwargs):
        return _Resp({"messages": [{"id": "wamid.status"}]})

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)
    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)
    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    try:
        await _publish(adapter)
    finally:
        await adapter.close()

    assert captured["mime"] == "image/jpeg"


@pytest.mark.asyncio
async def test_status_media_content_type_must_match_kind(monkeypatch):
    adapter = WhatsAppAdapter()
    captured: dict = {}

    def _fetch(url, **kwargs):
        return b"bytes", "video/mp4"

    async def _upload(self, phone_number_id, token, data, mime_type, filename="media"):
        captured["mime"] = mime_type
        return "media-1"

    async def _graph(self, method, path, token, **kwargs):
        return _Resp({"messages": [{"id": "wamid.status"}]})

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)
    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)
    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    try:
        await _publish(adapter, media_type="image")
    finally:
        await adapter.close()

    assert captured["mime"] == "image/jpeg"


@pytest.mark.asyncio
async def test_status_media_empty_body_is_rejected(monkeypatch):
    adapter = WhatsAppAdapter()

    def _fetch(url, **kwargs):
        return b"", "image/jpeg"

    async def _upload(self, *args, **kwargs):
        raise AssertionError("empty media must never be uploaded")

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)
    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)

    try:
        with pytest.raises(MetaAPIError) as exc:
            await _publish(adapter)
    finally:
        await adapter.close()

    assert exc.value.status_code == 502
    assert "empty" in str(exc.value)


@pytest.mark.asyncio
async def test_status_media_unsafe_url_is_400_and_does_not_echo_it(monkeypatch):
    adapter = WhatsAppAdapter()

    def _fetch(url, **kwargs):
        raise UnsafeUrlError("host '10.0.0.5' is not public")

    async def _upload(self, *args, **kwargs):
        raise AssertionError("unsafe media must never be uploaded")

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)
    monkeypatch.setattr(WhatsAppAdapter, "upload_media", _upload)

    try:
        with pytest.raises(MetaAPIError) as exc:
            await _publish(
                adapter, media_url="http://169.254.169.254/latest/meta-data/"
            )
    finally:
        await adapter.close()

    assert exc.value.status_code == 400
    message = str(exc.value)
    assert "169.254.169.254" not in message
    assert "10.0.0.5" not in message
    assert "http://" not in message


@pytest.mark.asyncio
async def test_status_media_fetch_failure_is_generic_502(monkeypatch):
    adapter = WhatsAppAdapter()

    def _fetch(url, **kwargs):
        raise ValueError("response exceeds size limit")

    monkeypatch.setattr(wa, "fetch_pinned_media", _fetch)

    try:
        with pytest.raises(MetaAPIError) as exc:
            await _publish(adapter)
    finally:
        await adapter.close()

    assert exc.value.status_code == 502
    message = str(exc.value)
    assert "https://cdn.example.com" not in message
    assert "size limit" not in message
