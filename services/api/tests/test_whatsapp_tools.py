"""WA-7 / WA-9: QR codes and number health for a WhatsApp number.

Number health is Meta-side data: the quality rating explains a send failure.
QR codes are generated locally from `wa.me/<number>?text=<message>` — no Meta
permission, no expiry, and the image is rendered in the browser.
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


# ── locally generated QR codes ───────────────────────────────────────


def _seed_whatsapp_qr_channel(db, user_id, *, channel_id, phone="+966 50 000 1234"):
    from app.modules.channels.meta.models import MetaAsset
    from app.modules.channels.models import Channel

    db.add(Channel(
        id=channel_id, user_id=user_id, platform="whatsapp",
        platform_user_id=f"pn-{channel_id}", display_name="QR",
        status="active",
    ))
    db.add(MetaAsset(
        id=f"asset-{channel_id}", tenant_id=user_id, connection_id="conn-qr",
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=f"pn-{channel_id}", phone=phone, active=True,
        status="connected",
    ))


@pytest.mark.asyncio
async def test_a_local_qr_code_is_created_listed_and_deleted(client, db, user_id):
    channel_id = "chan-qr-local"
    _seed_whatsapp_qr_channel(db, user_id, channel_id=channel_id)
    await db.commit()

    created = client.post(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes",
        json={"prefilled_message": "Hi! I'd like to order", "image_format": "PNG"},
    )
    assert created.status_code == 200, created.text
    code = created.json()
    assert code["prefilled_message"] == "Hi! I'd like to order"
    assert code["deep_link_url"] == (
        "https://wa.me/966500001234?text=Hi%21%20I%27d%20like%20to%20order"
    )
    assert code["qr_image_url"] is None

    # A second create with the same wording is idempotent, not a duplicate row.
    again = client.post(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes",
        json={"prefilled_message": "Hi! I'd like to order"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["code"] == code["code"]

    listed = client.get(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes"
    )
    assert listed.status_code == 200, listed.text
    assert [row["code"] for row in listed.json()] == [code["code"]]

    removed = client.delete(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes/{code['code']}"
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted"] is True
    assert client.get(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes"
    ).json() == []

    missing = client.delete(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes/{code['code']}"
    )
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_a_channel_without_a_display_phone_gets_a_clear_error(client, db, user_id):
    channel_id = "chan-qr-no-phone"
    _seed_whatsapp_qr_channel(db, user_id, channel_id=channel_id, phone="")
    await db.commit()

    res = client.post(
        f"/api/v1/channels/{channel_id}/whatsapp/qr-codes",
        json={"prefilled_message": "Hello"},
    )
    assert res.status_code == 422, res.text
    assert "display phone" in res.json()["detail"]
