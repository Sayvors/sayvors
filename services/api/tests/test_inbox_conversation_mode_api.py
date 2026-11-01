"""Conversation mode over HTTP.

The switch is only real if the endpoints that drive it work: PATCH mode,
POST resolve, and the thread payload the inbox reads on open.
"""
import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.models import Channel, ChannelMessage, Lead
from app.modules.channels.service import hash_contact_phone

CUSTOMER = "+966500000003"


async def _seed(db, user_id, *, channel_id):
    db.add(Channel(
        id=channel_id, user_id=user_id, platform="whatsapp",
        platform_user_id="pn-mode", display_name="Mode", status="active",
    ))
    await db.flush()
    db.add(Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=CUSTOMER, stage="qualified",
        language="en", opt_out=False, thread_key=CUSTOMER,
        priority="important", ai_miss_count=3,
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="hello", content_type="text", status="delivered",
        contact_phone=CUSTOMER,
        contact_phone_hash=hash_contact_phone(CUSTOMER),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_switch_to_human_then_resolve(client, db, user_id):
    await _seed(db, user_id, channel_id="chan-mode-http")

    r = client.patch(
        "/api/v1/inbox/threads/chan-mode-http/%2B966500000003/mode",
        json={"mode": "human"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "human"
    assert body["mode_changed_by"] == user_id

    # The inbox list and the thread-open payload must both carry it.
    listed = client.get("/api/v1/inbox/threads").json()["threads"]
    row = next(t for t in listed if t["channel_id"] == "chan-mode-http")
    assert row["mode"] == "human"

    opened = client.get(
        "/api/v1/inbox/threads/chan-mode-http/%2B966500000003"
    ).json()
    assert opened["thread"]["mode"] == "human"

    r = client.post(
        "/api/v1/inbox/threads/chan-mode-http/%2B966500000003/resolve"
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "ai"


@pytest.mark.asyncio
async def test_resolve_returns_the_thread_with_a_clean_counter(client, db, user_id):
    await _seed(db, user_id, channel_id="chan-mode-resolve")
    client.patch(
        "/api/v1/inbox/threads/chan-mode-resolve/%2B966500000003/mode",
        json={"mode": "human"},
    )

    client.post("/api/v1/inbox/threads/chan-mode-resolve/%2B966500000003/resolve")

    from sqlalchemy import select

    lead = (await db.execute(
        select(Lead).where(Lead.channel_id == "chan-mode-resolve")
    )).scalar_one()
    await db.refresh(lead)
    assert lead.priority == "normal"
    assert lead.ai_miss_count == 0


@pytest.mark.asyncio
async def test_switching_another_tenants_thread_is_refused(client, db, other_user_id):
    await _seed(db, other_user_id, channel_id="chan-mode-theirs")

    r = client.patch(
        "/api/v1/inbox/threads/chan-mode-theirs/%2B966500000003/mode",
        json={"mode": "human"},
    )
    assert r.status_code in (403, 404), r.text


@pytest.mark.asyncio
async def test_an_unattributed_thread_cannot_be_switched(client, db, user_id):
    db.add(Channel(
        id="chan-mode-unknown", user_id=user_id, platform="whatsapp",
        platform_user_id="pn-unknown", display_name="Mode", status="active",
    ))
    await db.commit()

    r = client.patch(
        "/api/v1/inbox/threads/chan-mode-unknown/unknown/mode",
        json={"mode": "human"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_an_invalid_mode_is_rejected(client, db, user_id):
    await _seed(db, user_id, channel_id="chan-mode-invalid")

    r = client.patch(
        "/api/v1/inbox/threads/chan-mode-invalid/%2B966500000003/mode",
        json={"mode": "robot"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_a_whatsapp_channel_defaults_to_auto_reply_on(client, db, user_id):
    """Merely opening the settings screen must not silence a working number."""
    await _seed(db, user_id, channel_id="chan-autoreply-default")

    r = client.get("/api/v1/channels/chan-autoreply-default/autoreply")
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_thread_state_exposes_the_escalation_clock(client, db, user_id):
    """BUG-4: an auto-escalated thread must say why the AI stopped, whether
    the humans were told, and when the sweep hands it back."""
    from datetime import datetime, timedelta, timezone

    channel_id = "chan-mode-clock"
    since = datetime.now(timezone.utc) - timedelta(hours=6)
    db.add(Channel(
        id=channel_id, user_id=user_id, platform="whatsapp",
        platform_user_id="pn-clock", display_name="Clock", status="active",
    ))
    await db.flush()
    db.add(Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=CUSTOMER, stage="qualified",
        language="en", opt_out=False, thread_key=CUSTOMER,
        priority="important", ai_miss_count=3,
        category="wholesale",
        priority_since=since, escalated_at=since, handover_sent_at=since,
        # NULL reminder + a sent escalation = the reminder already fired.
        escalation_reminder_at=None,
    ))
    await db.commit()

    opened = client.get(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000003"
    ).json()["thread"]

    assert opened["priority"] == "important"
    assert opened["ai_miss_count"] == 3
    assert opened["lead_category"] == "wholesale"
    assert opened["escalated_at"] is not None
    assert opened["handover_sent_at"] is not None
    assert opened["escalation_reminder_at"] is None
    assert opened["escalation_resume_hours"] == 24
    assert opened["resume_at"] is not None

    resumed = datetime.fromisoformat(opened["resume_at"])
    started = datetime.fromisoformat(opened["priority_since"])
    assert resumed - started == timedelta(hours=24)


@pytest.mark.asyncio
async def test_thread_state_uses_the_tenant_resume_window(client, db, user_id):
    """The countdown must match the sweep's arithmetic, not a hardcoded 24h."""
    from datetime import datetime, timedelta, timezone

    from app.modules.users.models import User

    db.add(User(
        id=user_id, first_name="Test", last_name="Owner",
        email="clock-owner@example.com", password_hash="x",
        lead_settings={"escalation_resume_hours": 6},
    ))
    channel_id = "chan-mode-clock-window"
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(Channel(
        id=channel_id, user_id=user_id, platform="whatsapp",
        platform_user_id="pn-clock-window", display_name="Clock",
        status="active",
    ))
    await db.flush()
    db.add(Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=CUSTOMER, stage="qualified",
        language="en", opt_out=False, thread_key=CUSTOMER,
        priority="important", ai_miss_count=1, priority_since=since,
    ))
    await db.commit()

    opened = client.get(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000003"
    ).json()["thread"]

    assert opened["escalation_resume_hours"] == 6
    resumed = datetime.fromisoformat(opened["resume_at"])
    started = datetime.fromisoformat(opened["priority_since"])
    assert resumed - started == timedelta(hours=6)


@pytest.mark.asyncio
async def test_thread_state_has_no_clock_when_the_lead_is_normal(client, db, user_id):
    """No escalation means no countdown — the strip is not permanent UI."""
    channel_id = "chan-mode-normal"
    db.add(Channel(
        id=channel_id, user_id=user_id, platform="whatsapp",
        platform_user_id="pn-normal", display_name="Normal", status="active",
    ))
    await db.flush()
    db.add(Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=CUSTOMER, stage="qualified",
        language="en", opt_out=False, thread_key=CUSTOMER,
        priority="normal", ai_miss_count=0,
    ))
    await db.commit()

    opened = client.get(
        f"/api/v1/inbox/threads/{channel_id}/%2B966500000003"
    ).json()["thread"]

    assert opened["priority"] == "normal"
    assert opened["ai_miss_count"] == 0
    assert opened["priority_since"] is None
    assert opened["resume_at"] is None


@pytest.mark.asyncio
async def test_deleting_a_thread_removes_its_stored_context(client, db, user_id):
    """A deleted conversation must not leave a summary of it behind."""
    from sqlalchemy import select

    from app.modules.channels.models import ConversationContext
    from app.modules.channels.service import encrypt_message_content

    await _seed(db, user_id, channel_id="chan-mode-delete")
    db.add(ConversationContext(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id="chan-mode-delete",
        contact_phone=CUSTOMER,
        contact_phone_hash=hash_contact_phone(CUSTOMER),
        summary=encrypt_message_content("Customer wants a refund."),
        message_count=4, reason="resolve",
    ))
    await db.commit()

    r = client.delete(
        "/api/v1/inbox/threads/chan-mode-delete/%2B966500000003"
    )
    assert r.status_code == 204, r.text

    left = (await db.execute(
        select(ConversationContext).where(
            ConversationContext.channel_id == "chan-mode-delete"
        )
    )).scalars().all()
    assert left == [], "the summary is PII and must go with the thread"
