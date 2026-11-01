"""Ticket identity on the WhatsApp lead row.

The lead row IS the ticket: ticket_number/status/kind are the work object, and
`stage` is only the sales qualification inside it.
"""
import uuid

import pytest

from app.modules.channels.meta import lead_engine as le
from app.modules.channels.models import Channel, Lead
from app.modules.channels.tickets import (
    apply_ticket_stage,
    prompt_block,
    split_ticket_request,
    ticket_kind_for,
    ticket_status_for_stage,
)


async def _seed_channel(db, user_id):
    channel = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="whatsapp",
        platform_user_id="pn-ticket-1", display_name="Tickets",
        status="active",
    )
    db.add(channel)
    await db.commit()
    return channel


def test_ticket_lifecycle_maps_from_the_sales_stage():
    assert ticket_status_for_stage("new") == "new"
    assert ticket_status_for_stage("qualified") == "open"
    assert ticket_status_for_stage("follow_up") == "in_progress"
    assert ticket_status_for_stage("converted") == "resolved"
    assert ticket_status_for_stage("lost") == "closed"

    lead = Lead(
        id="l1", tenant_id="t1", channel_id="c1", platform="whatsapp",
        contact_id="p1", stage="converted", ticket_status="open",
    )
    apply_ticket_stage(lead)
    assert lead.ticket_status == "resolved"
    assert lead.resolved_at is not None

    lead.stage = "qualified"
    apply_ticket_stage(lead)
    assert lead.ticket_status == "open"
    assert lead.resolved_at is None


def test_ticket_kind_follows_the_category():
    assert ticket_kind_for("support") == "whatsapp_support"
    assert ticket_kind_for("quote") == "whatsapp_sales"
    assert ticket_kind_for("wholesale") == "whatsapp_sales"
    assert ticket_kind_for("info") == "whatsapp_info"
    assert ticket_kind_for(None, "booking") == "whatsapp_sales"
    assert ticket_kind_for(None) == "whatsapp_general"


def test_ticket_marker_is_stripped():
    text, opened = split_ticket_request("Done — I've opened it.\nOPEN_TICKET")
    assert opened is True
    assert text == "Done — I've opened it."

    text, opened = split_ticket_request("Just an answer")
    assert opened is False
    assert text == "Just an answer"


def test_prompt_block_is_explicit_about_no_ticket():
    assert "LATEST TICKET: none" in prompt_block(None)
    lead = Lead(
        id="l1", tenant_id="t1", channel_id="c1", platform="whatsapp",
        contact_id="p1", stage="qualified", ticket_number="WA-ABC123",
        ticket_status="open", ticket_kind="whatsapp_sales",
        summary="Website with payments",
    )
    block = prompt_block(lead)
    assert "WA-ABC123" in block
    assert "Status: open" in block
    assert "Lead stage: qualified" in block
    assert "Never use the word lead with the customer" in block


@pytest.mark.asyncio
async def test_capture_assigns_a_ticket_number_and_kind(db, user_id):
    channel = await _seed_channel(db, user_id)
    lead = await le.capture_lead(
        db,
        tenant_id=user_id,
        channel_id=channel.id,
        platform="whatsapp",
        contact_id="+966500007777",
        contact_name="Sara",
        message_id="wamid-ticket-1",
        inbound_text="how much for 50 boxes?",
        delta={"intent": "quote", "request": "50 boxes", "confidence": 0.9},
    )
    assert lead is not None
    assert lead.ticket_number.startswith("WA-")
    assert lead.ticket_kind == "whatsapp_sales"
    assert lead.ticket_status == "open"  # quote -> qualified -> open
    assert lead.stage == "qualified"


@pytest.mark.asyncio
async def test_patch_stage_updates_the_ticket_status(
    client, db, user_id
):
    channel = await _seed_channel(db, user_id)
    lead = await le.capture_lead(
        db,
        tenant_id=user_id,
        channel_id=channel.id,
        platform="whatsapp",
        contact_id="+966500007778",
        message_id="wamid-ticket-2",
        inbound_text="the order arrived damaged",
        delta={"category": "support", "request": "damaged order", "confidence": 0.9},
    )
    assert lead is not None
    assert lead.ticket_kind == "whatsapp_support"

    res = client.patch(
        f"/api/v1/leads/{lead.id}", json={"stage": "converted"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticket_status"] == "resolved"
    assert body["resolved_at"]

    await db.refresh(lead)
    assert lead.ticket_status == "resolved"
    assert lead.resolved_at is not None
