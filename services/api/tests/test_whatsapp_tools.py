"""WA-7 / WA-9: QR codes and number health for a WhatsApp number.

Both are Meta-side data: the quality rating explains a send failure, and a
short link + QR image is the zero-cost entry point for a store counter. The
adapter is the only place that talks Graph; the service re-checks tenant
ownership before any credential is used.
"""
import pytest


# ── adapter ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_number_health_reads_the_meta_fields(monkeypatch):
    from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter

    captured: dict = {}

    class _Resp:
        def json(self):
            return {
                "verified_name": "Aster Coffee",
                "display_phone_number": "+966 50 000 1111",
                "quality_rating": "GREEN",
                "messaging_limit_tier": "TIER_1K",
                "status": "CONNECTED",
                "code_verification_status": "VERIFIED",
                "account_mode": "LIVE",
                "platform_type": "CLOUD_API",
            }

    async def _graph(self, method, path, token, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    health = await WhatsAppAdapter().get_number_health("phone-1", "tok")

    assert captured["method"] == "GET"
    assert captured["path"] == "/phone-1"
    assert "quality_rating" in captured["params"]["fields"]
    assert "messaging_limit_tier" in captured["params"]["fields"]
    assert health["quality_rating"] == "GREEN"
    assert health["messaging_limit_tier"] == "TIER_1K"


@pytest.mark.asyncio
async def test_create_qr_code_payload_and_limits(monkeypatch):
    from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter

    captured: dict = {}

    class _Resp:
        def json(self):
            return {
                "code": "ABC123",
                "prefilled_message": "Hi! I'd like a table",
                "deep_link_url": "https://wa.me/message/ABC123",
                "qr_image_url": "https://scontent.example/qr.png",
            }

    async def _graph(self, method, path, token, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    out = await WhatsAppAdapter().create_qr_code(
        "phone-1", "tok", "  Hi! I'd like a table  ", image_format="png"
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/phone-1/message_qrdls"
    assert captured["json"] == {
        "prefilled_message": "Hi! I'd like a table",
        "generate_qr_image": "PNG",
    }
    assert out["code"] == "ABC123"
    assert out["deep_link_url"].endswith("ABC123")

    with pytest.raises(ValueError):
        await WhatsAppAdapter().create_qr_code("p", "t", "   ")
    with pytest.raises(ValueError):
        await WhatsAppAdapter().create_qr_code("p", "t", "x" * 141)
    with pytest.raises(ValueError):
        await WhatsAppAdapter().create_qr_code("p", "t", "hello", image_format="GIF")


@pytest.mark.asyncio
async def test_list_and_delete_qr_codes(monkeypatch):
    from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter

    calls: list[tuple] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    async def _graph(self, method, path, token, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return _Resp({"data": [{"code": "A1"}, {"code": "B2"}]})
        return _Resp({"success": True})

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    rows = await WhatsAppAdapter().list_qr_codes("phone-1", "tok")
    assert [r["code"] for r in rows] == ["A1", "B2"]

    assert await WhatsAppAdapter().delete_qr_code("phone-1", "tok", "A1") is True
    assert calls[-1][0] == "DELETE"
    assert calls[-1][1] == "/phone-1/message_qrdls/A1"


# ── API ──────────────────────────────────────────────────────────────


def test_prefilled_message_length_is_enforced_at_the_edge(client):
    res = client.post(
        "/api/v1/channels/any/whatsapp/qr-codes",
        json={"prefilled_message": "x" * 141},
    )
    assert res.status_code == 422


def test_health_on_a_non_whatsapp_channel_is_rejected(client, channel_id):
    res = client.get(f"/api/v1/channels/{channel_id}/whatsapp/health")
    assert res.status_code in (403, 422), res.text


def test_qr_list_on_a_non_whatsapp_channel_is_rejected(client, channel_id):
    res = client.get(f"/api/v1/channels/{channel_id}/whatsapp/qr-codes")
    assert res.status_code in (403, 422), res.text
