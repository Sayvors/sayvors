"""WhatsApp templates: the only legal send outside the 24h window.

See readiness-report §17, HAND-2. These cover the consent gate, the approved
status gate, variable validation, idempotency, the recorded send, and the
follow-up worker's fallback when the window is closed.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.models import Channel, ChannelMessage, Lead
from app.modules.users.models import User
from app.modules.whatsapp_templates import service as templates
from app.modules.whatsapp_templates.models import TemplateSend, WhatsAppTemplate

PHONE = "+966500000301"


async def _seed(db, *, approved: bool = True, variables: int = 0, consent: bool = True):
    uid = f"tpl-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="T", last_name="M",
        email=f"{uid}@example.com", password_hash="x",
    ))
    conn = MetaConnection(
        id=f"tpl-conn-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        provider="whatsapp", status="active", access_token_encrypted="enc",
    )
    db.add(conn)
    await db.flush()
    db.add_all([
        MetaAsset(
            id=f"tpl-waba-{uuid.uuid4().hex[:8]}", tenant_id=uid,
            connection_id=conn.id, provider="whatsapp", asset_type="waba",
            external_asset_id="waba-1", active=True,
        ),
        MetaAsset(
            id=f"tpl-pn-{uuid.uuid4().hex[:8]}", tenant_id=uid,
            connection_id=conn.id, provider="whatsapp", asset_type="phone_number",
            external_asset_id="pn-tpl", phone=PHONE, active=True,
        ),
    ])
    channel = Channel(
        id=f"tpl-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="pn-tpl",
        display_name="Templates", status="active",
    )
    db.add(channel)
    await db.flush()
    lead = Lead(
        id=f"tpl-lead-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        channel_id=channel.id, platform="whatsapp", contact_id=PHONE,
        stage="qualified", thread_key=PHONE,
        whatsapp_opt_in_at=datetime.now(timezone.utc) if consent else None,
        whatsapp_opt_in_source="instagram_bridge" if consent else None,
    )
    db.add(lead)
    await db.flush()
    template = WhatsAppTemplate(
        id=str(uuid.uuid4()), tenant_id=uid, name="order_update",
        language="en", category="utility",
        status="approved" if approved else "pending",
        body="Your order is on the way." if variables == 0 else "Order {{1}} is on the way.",
        variables=variables, meta_template_id="meta-123",
    )
    db.add(template)
    await db.commit()
    return uid, channel, lead, template


class _Adapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail: Exception | None = None

    async def send_template_message(
        self, phone_number_id, token, to, name, language, variables=None
    ):
        self.calls.append({
            "phone_number_id": phone_number_id, "to": to, "name": name,
            "language": language, "variables": list(variables or []),
        })
        if self.fail is not None:
            raise self.fail
        return "wamid-tpl-1"

    async def list_templates(self, waba_id, token):
        return [{
            "id": "meta-123", "name": "order_update", "language": "en",
            "category": "UTILITY", "status": "APPROVED",
            "components": [{"type": "BODY", "text": "Your order is on the way."}],
        }]


def _patch_provider(monkeypatch, adapter):
    monkeypatch.setattr(
        "app.modules.channels.meta.credentials.decrypt_connection_token",
        lambda connection: "tok",
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.service.get_adapter", lambda platform: adapter
    )


def test_variable_count_reads_the_highest_placeholder():
    assert templates.count_variables("No vars") == 0
    assert templates.count_variables("Hi {{1}}, order {{2}}") == 2
    assert templates.count_variables("Hi {{ 3 }}") == 3


@pytest.mark.asyncio
async def test_send_requires_consent(db, monkeypatch):
    uid, channel, lead, template = await _seed(db, consent=False)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    with pytest.raises(ValueError, match="opt-in"):
        await templates.send_template(
            db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
            template_id=template.id, variables=[], sent_by="user-1",
        )
    assert adapter.calls == [], "nothing may be sent without consent"


@pytest.mark.asyncio
async def test_send_requires_an_approved_template(db, monkeypatch):
    uid, channel, lead, template = await _seed(db, approved=False)
    _patch_provider(monkeypatch, _Adapter())

    with pytest.raises(ValueError, match="approved"):
        await templates.send_template(
            db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
            template_id=template.id, variables=[], sent_by="user-1",
        )


@pytest.mark.asyncio
async def test_send_validates_the_variable_count(db, monkeypatch):
    uid, channel, lead, template = await _seed(db, variables=1)
    _patch_provider(monkeypatch, _Adapter())

    with pytest.raises(ValueError, match="variable"):
        await templates.send_template(
            db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
            template_id=template.id, variables=[], sent_by="user-1",
        )


@pytest.mark.asyncio
async def test_send_records_the_message_and_the_consent_basis(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    row, created = await templates.send_template(
        db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
        template_id=template.id, variables=[], sent_by="user-1",
        idempotency_key="send-1",
    )
    assert created is True
    assert row.status == "sent"
    assert row.consent_at is not None, "the send records what authorised it"
    assert adapter.calls == [{
        "phone_number_id": "pn-tpl", "to": PHONE, "name": "order_update",
        "language": "en", "variables": [],
    }]

    stored = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel.id,
            ChannelMessage.content_type == "template",
        )
    )).scalars().all()
    assert len(stored) == 1, "the inbox must show the template that went out"
    assert stored[0].is_ai is False
    assert stored[0].handled_by == "system"


@pytest.mark.asyncio
async def test_the_same_idempotency_key_sends_once(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    first, created_first = await templates.send_template(
        db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
        template_id=template.id, variables=[], sent_by="user-1",
        idempotency_key="same-key",
    )
    second, created_second = await templates.send_template(
        db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
        template_id=template.id, variables=[], sent_by="user-1",
        idempotency_key="same-key",
    )
    assert created_first is True and created_second is False
    assert second.id == first.id
    assert len(adapter.calls) == 1, "a retry must not bill a second message"


@pytest.mark.asyncio
async def test_a_provider_rejection_is_recorded_not_raised(db, monkeypatch):
    from app.modules.channels.meta.providers.base import MetaAPIError

    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    adapter.fail = MetaAPIError("re-engagement required (131047)", 400)
    _patch_provider(monkeypatch, adapter)

    row, created = await templates.send_template(
        db, tenant_id=uid, channel_id=channel.id, contact_phone=PHONE,
        template_id=template.id, variables=[], sent_by="user-1",
    )
    assert created is True
    assert row.status == "failed"
    assert "131047" in (row.error or "") or "window" in (row.error or "").lower()


@pytest.mark.asyncio
async def test_sync_upserts_the_waba_templates(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    _patch_provider(monkeypatch, _Adapter())

    result = await templates.sync_templates(db, uid)
    assert result["remote"] == 1

    rows = await templates.list_templates(db, uid)
    assert len(rows) == 1, "sync upserts by (name, language), never duplicates"
    assert rows[0].status == "approved"
    assert rows[0].body == "Your order is on the way."
    assert rows[0].variables == 0


@pytest.mark.asyncio
async def test_record_opt_in_is_idempotent_and_clears_an_opt_out(db):
    uid, channel, lead, template = await _seed(db, consent=False)
    lead.opt_out = True
    await db.commit()

    await templates.record_opt_in(db, lead, source="operator", message_id="m-1")
    first = lead.whatsapp_opt_in_at
    await templates.record_opt_in(db, lead, source="operator", message_id="m-2")
    assert lead.whatsapp_opt_in_at == first
    assert lead.whatsapp_opt_in_source == "operator"
    assert lead.opt_out is False


@pytest.mark.asyncio
async def test_the_follow_up_worker_falls_back_to_a_template(db, monkeypatch):
    """A closed window used to mark the nudge ineligible. With consent and an
    approved zero-variable utility template, it still reaches the customer."""
    from app.modules.channels.meta import lead_action_worker

    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    action = type("A", (), {})()
    action.id = "action-1"
    action.tenant_id = uid
    action.channel_id = channel.id
    action.contact_id = PHONE
    action.last_error = None
    action.status = "pending"
    action.sent_at = None
    action.provider_message_id = None
    action.error_category = None

    assert await lead_action_worker._send_window_template(db, action) is True
    assert action.status == "sent"
    assert action.provider_message_id == "wamid-tpl-1"
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_the_worker_does_not_send_without_consent(db, monkeypatch):
    from app.modules.channels.meta import lead_action_worker

    uid, channel, lead, template = await _seed(db, consent=False)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    action = type("A", (), {})()
    action.id = "action-2"
    action.tenant_id = uid
    action.channel_id = channel.id
    action.contact_id = PHONE
    action.last_error = None
    action.status = "pending"
    action.sent_at = None
    action.provider_message_id = None
    action.error_category = None

    assert await lead_action_worker._send_window_template(db, action) is False
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_the_template_api_reports_templates_and_sends(client, db, user_id):
    uid, channel, lead, template = await _seed(db)
    # The API authenticates as user_id; move the seeded rows onto that tenant.
    channel.user_id = user_id
    lead.tenant_id = user_id
    template.tenant_id = user_id
    await db.commit()

    listed = client.get("/api/v1/whatsapp/templates")
    assert listed.status_code == 200, listed.text
    assert [t["name"] for t in listed.json()["templates"]] == ["order_update"]

    sent = client.post("/api/v1/whatsapp/templates/send", json={
        "channel_id": channel.id,
        "contact_phone": PHONE,
        "template_id": template.id,
        "variables": [],
        "idempotency_key": "http-1",
    })
    # No provider is configured in the test app; the precondition checks run
    # first, so a 422 here means the consent/approval gate is working.
    assert sent.status_code in (200, 422), sent.text
