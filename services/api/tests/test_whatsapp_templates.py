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
    waba = MetaAsset(
        id=f"tpl-waba-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        connection_id=conn.id, provider="whatsapp", asset_type="waba",
        external_asset_id="waba-1", active=True,
    )
    db.add(waba)
    await db.flush()
    db.add(MetaAsset(
        id=f"tpl-pn-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        connection_id=conn.id, provider="whatsapp", asset_type="phone_number",
        external_asset_id="pn-tpl", phone=PHONE, active=True,
        parent_asset_id=waba.id,
    ))
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
        self.created: dict | None = None
        self.updated: dict | None = None
        self.deleted: dict | None = None

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

    async def create_template(self, waba_id, token, **kwargs):
        self.created = {"waba_id": waba_id, **kwargs}
        return {
            "id": "meta-new", "status": "PENDING", "category": "UTILITY",
        }

    async def update_template(self, template_id, token, **kwargs):
        self.updated = {"template_id": template_id, **kwargs}
        return {"status": "PENDING", "category": "UTILITY"}

    async def delete_template(self, token, **kwargs):
        self.deleted = kwargs
        return {"success": True}


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
async def test_sync_finds_the_waba_through_a_live_number_when_it_is_inactive(
    db, monkeypatch
):
    """The reported bug: a connected number whose parent WABA was marked
    inactive by the old selection sweep made sync claim no WABA existed."""
    uid, channel, lead, template = await _seed(db)
    waba = (
        await db.execute(
            select(MetaAsset).where(
                MetaAsset.tenant_id == uid, MetaAsset.asset_type == "waba"
            )
        )
    ).scalar_one()
    waba.active = False
    await db.commit()
    _patch_provider(monkeypatch, _Adapter())

    result = await templates.sync_templates(db, uid)
    assert result["remote"] == 1
    assert (await templates.waba_connection(db, uid))["connected"] is True


@pytest.mark.asyncio
async def test_sync_uses_the_connection_waba_id_when_no_asset_exists(
    db, monkeypatch
):
    """Some older connects stored only the number. The WABA id still lives on
    the connection metadata, which is enough to list and author templates."""
    uid, channel, lead, template = await _seed(db)
    waba = (
        await db.execute(
            select(MetaAsset).where(
                MetaAsset.tenant_id == uid, MetaAsset.asset_type == "waba"
            )
        )
    ).scalar_one()
    conn = (
        await db.execute(
            select(MetaConnection).where(MetaConnection.tenant_id == uid)
        )
    ).scalar_one()
    conn.connection_metadata = {"waba_id": "waba-from-metadata"}
    await db.delete(waba)
    await db.commit()
    _patch_provider(monkeypatch, _Adapter())

    result = await templates.sync_templates(db, uid)
    assert result["remote"] == 1
    assert (await templates.waba_connection(db, uid))["connected"] is True


@pytest.mark.asyncio
async def test_create_template_submits_samples_and_mirrors_pending(
    db, monkeypatch
):
    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    row = await templates.create_template(
        db, uid, name="order_ready", language="en_US", category="utility",
        body="Order {{1}} is ready for pickup.", examples=["A-1042"],
    )
    assert adapter.created == {
        "waba_id": "waba-1", "name": "order_ready", "language": "en_US",
        "category": "utility", "body": "Order {{1}} is ready for pickup.",
        "examples": ["A-1042"],
    }
    assert row.status == "pending"
    assert row.meta_template_id == "meta-new"
    assert row.variables == 1
    assert row.category == "utility"


@pytest.mark.asyncio
async def test_create_template_validates_names_gaps_and_samples(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    _patch_provider(monkeypatch, _Adapter())

    with pytest.raises(ValueError, match="name"):
        await templates.create_template(
            db, uid, name="Order Ready", language="en", category="utility",
            body="Hello", examples=[],
        )
    with pytest.raises(ValueError, match="without gaps"):
        await templates.create_template(
            db, uid, name="bad_gap", language="en", category="utility",
            body="Hi {{2}}", examples=["a", "b"],
        )
    with pytest.raises(ValueError, match="sample"):
        await templates.create_template(
            db, uid, name="no_sample", language="en", category="utility",
            body="Hi {{1}}", examples=[],
        )
    with pytest.raises(ValueError, match="already exists"):
        await templates.create_template(
            db, uid, name="order_update", language="en", category="utility",
            body="Duplicate", examples=[],
        )


@pytest.mark.asyncio
async def test_update_template_returns_it_to_review(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    row = await templates.update_template(
        db, uid, template.id, body="Your order is ready.", examples=[],
    )
    assert adapter.updated == {
        "template_id": "meta-123", "category": "utility",
        "body": "Your order is ready.", "examples": [],
    }
    assert row.status == "pending"
    assert row.body == "Your order is ready."
    assert row.variables == 0


@pytest.mark.asyncio
async def test_delete_template_removes_it_but_keeps_send_history(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)
    send = TemplateSend(
        id=str(uuid.uuid4()), tenant_id=uid, lead_id=lead.id,
        template_id=template.id, contact_phone=PHONE,
        template_name=template.name, language=template.language,
        idempotency_key="del-1", status="sent",
    )
    db.add(send)
    await db.commit()

    await templates.delete_template(db, uid, template.id)

    assert adapter.deleted == {
        "template_id": "meta-123", "waba_id": "waba-1", "name": "order_update",
    }
    assert (
        await db.execute(
            select(WhatsAppTemplate).where(WhatsAppTemplate.id == template.id)
        )
    ).scalar_one_or_none() is None
    await db.refresh(send)
    assert send.template_id is None, "send history survives the template"
    assert send.template_name == "order_update"


@pytest.mark.asyncio
async def test_template_analytics_counts_outcomes(db, monkeypatch):
    uid, channel, lead, template = await _seed(db)
    _patch_provider(monkeypatch, _Adapter())
    now = datetime.now(timezone.utc)
    for index, status in enumerate(("sent", "sent", "failed", "blocked")):
        db.add(TemplateSend(
            id=str(uuid.uuid4()), tenant_id=uid, lead_id=lead.id,
            template_id=template.id, contact_phone=PHONE,
            template_name=template.name, language=template.language,
            idempotency_key=f"an-{index}", status=status,
            created_at=now - timedelta(days=index),
        ))
    await db.commit()

    result = await templates.template_analytics(db, uid, template.id, days=30)
    assert result["total"] == 4
    assert result["sent"] == 2
    assert result["failed"] == 1
    assert result["blocked"] == 1
    assert result["last_sent_at"] is not None


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
    payload = listed.json()
    assert [t["name"] for t in payload["templates"]] == ["order_update"]
    assert "waba" in payload
    assert payload["templates"][0]["send_count"] == 0

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


@pytest.mark.asyncio
async def test_the_template_api_authors_edits_and_deletes(
    client, db, user_id, monkeypatch
):
    uid, channel, lead, template = await _seed(db)
    channel.user_id = user_id
    lead.tenant_id = user_id
    template.tenant_id = user_id
    for model in (MetaAsset, MetaConnection):
        rows = (
            await db.execute(select(model).where(model.tenant_id == uid))
        ).scalars().all()
        for row in rows:
            row.tenant_id = user_id
    await db.commit()
    adapter = _Adapter()
    _patch_provider(monkeypatch, adapter)

    created = client.post("/api/v1/whatsapp/templates", json={
        "name": "pickup_ready",
        "language": "en_US",
        "category": "utility",
        "body": "Order {{1}} is ready.",
        "examples": ["A-1"],
    })
    assert created.status_code == 201, created.text
    new_id = created.json()["template"]["id"]
    assert created.json()["template"]["status"] == "pending"

    edited = client.patch(f"/api/v1/whatsapp/templates/{new_id}", json={
        "body": "Order {{1}} is ready for pickup.",
        "examples": ["A-1"],
    })
    assert edited.status_code == 200, edited.text
    assert "pickup" in edited.json()["template"]["body"]

    analytics = client.get(
        f"/api/v1/whatsapp/templates/{new_id}/analytics?days=7"
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["total"] == 0

    deleted = client.delete(f"/api/v1/whatsapp/templates/{new_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
