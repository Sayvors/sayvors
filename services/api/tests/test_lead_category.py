"""HAND-5: one canonical lead label across every surface.

The old `intent` field could not express wholesale, `qualified` meant "the AI
stored a sentence", and each screen invented its own wording. These tests pin
the taxonomy, the qualification rule, and the three surfaces a human reads.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.modules.channels.meta import lead_engine as le
from app.modules.channels.meta.lead_digest import compose_digest
from app.modules.channels.meta.lead_escalation import _lead_label
from app.modules.channels.models import ChannelMessage, Lead
from app.modules.channels.service import hash_contact_phone
from app.modules.users.models import User

CUSTOMER = "+966500000010"


@pytest.mark.parametrize(
    "text,intent,expected",
    [
        ("I need 500 units for my shop", None, "wholesale"),
        ("Do you sell wholesale?", None, "wholesale"),
        ("بالجملة من فضلك", None, "wholesale"),
        ("I want to book a table for four", None, "booking"),
        ("أريد حجز موعد", None, "booking"),
        ("How much for one piece?", None, "retail"),
        ("I want to buy one for myself", "buying", "retail"),
        ("How much is it?", None, "quote"),
        ("What are your opening hours?", None, "info"),
        ("It arrived broken and damaged", None, "support"),
        ("أريد شراء موقع إلكتروني", "buying", "retail"),
    ],
)
def test_detect_category_returns_one_canonical_label(text, intent, expected):
    assert le.detect_category(text, intent) == expected


def test_lead_delta_accepts_only_canonical_categories():
    text, delta = le.split_reply_and_lead(
        'Sure.\nLEAD: {"category": "Wholesale", "intent": "buying", '
        '"request": "500 units", "confidence": 0.9}'
    )
    assert text == "Sure."
    assert delta is not None
    assert delta["category"] == "wholesale"

    _, dropped = le.split_reply_and_lead(
        'Sure.\nLEAD: {"category": "enterprise", "request": "500 units", '
        '"confidence": 0.9}'
    )
    assert dropped is not None
    assert "category" not in dropped


@pytest.mark.asyncio
async def test_capture_labels_and_qualifies_a_wholesale_lead(
    db, channel_id, user_id
):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-wholesale", message_id="m-cat-1",
        inbound_text="I need 500 units, wholesale price",
        delta={"request": "500 units", "confidence": 0.9},
    )
    assert lead is not None
    assert lead.category == "wholesale"
    assert lead.stage == "qualified"
    assert lead.field_provenance["category"]["source_message_id"] == "m-cat-1"


@pytest.mark.asyncio
async def test_an_information_lead_is_labelled_but_stays_new(
    db, channel_id, user_id
):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-info", message_id="m-cat-2",
        inbound_text="What are your opening hours?",
        delta={"request": "opening hours", "confidence": 0.9},
    )
    assert lead is not None
    assert lead.category == "info"
    assert lead.stage == "new", "a question is not a sales-qualified lead"


@pytest.mark.asyncio
async def test_a_complaint_is_tracked_as_support_not_qualified(
    db, channel_id, user_id
):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-support", message_id="m-cat-3",
        inbound_text="It arrived broken and damaged",
        require_intent=True,
    )
    assert lead is not None
    assert lead.category == "support"
    assert lead.stage == "new"


@pytest.mark.asyncio
async def test_the_tenant_stage_rule_decides_qualification(
    db, channel_id, user_id
):
    db.add(User(
        id=user_id, first_name="Rule", last_name="Owner",
        email="lead-rules@example.com", password_hash="x",
        lead_settings={"qualified_categories": ["wholesale"]},
    ))
    await db.flush()

    retail = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-rule-retail", message_id="m-rule-1",
        inbound_text="I want to buy one for myself",
        delta={"intent": "buying", "request": "one", "confidence": 0.9},
    )
    assert retail.category == "retail"
    assert retail.stage == "new", "retail is not in this tenant's rule"

    wholesale = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-rule-wholesale", message_id="m-rule-2",
        inbound_text="I need 500 units wholesale",
        delta={"request": "500 units", "confidence": 0.9},
    )
    assert wholesale.category == "wholesale"
    assert wholesale.stage == "qualified"


@pytest.mark.asyncio
async def test_manual_category_correction_survives_the_next_extraction(
    client, db, channel_id, user_id
):
    lead = Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id="cat-manual", stage="new",
        language="en", opt_out=False, category="info",
        thread_key="cat-manual",
    )
    db.add(lead)
    await db.commit()

    r = client.patch(
        f"/api/v1/leads/{lead.id}", json={"category": "wholesale"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "wholesale"

    # A later model extraction at 0.9 must not undo the human's 1.0 label.
    await db.refresh(lead)
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-manual", message_id="m-manual-2",
        inbound_text="How much is it?",
        delta={"category": "info", "confidence": 0.9},
    )
    await db.refresh(lead)
    assert lead.category == "wholesale"

    bad = client.patch(
        f"/api/v1/leads/{lead.id}", json={"category": "enterprise"}
    )
    assert bad.status_code == 422, bad.text

    # Even a more specific engine signal cannot override a human's label.
    r = client.patch(
        f"/api/v1/leads/{lead.id}", json={"category": "support"}
    )
    assert r.status_code == 200, r.text
    await db.refresh(lead)
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="cat-manual", message_id="m-manual-3",
        inbound_text="I need 500 units wholesale",
        delta={"request": "500 units", "confidence": 0.95},
    )
    await db.refresh(lead)
    assert lead.category == "support", "a manual correction is final"


@pytest.mark.asyncio
async def test_the_leads_api_filters_and_returns_the_category(
    client, db, channel_id, user_id
):
    for idx, category in enumerate(("wholesale", "retail")):
        db.add(Lead(
            id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
            platform="whatsapp", contact_id=f"cat-list-{idx}",
            stage="qualified", language="en", opt_out=False,
            category=category, thread_key=f"cat-list-{idx}",
        ))
    await db.commit()

    r = client.get("/api/v1/leads?category=wholesale")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["leads"][0]["category"] == "wholesale"


@pytest.mark.asyncio
async def test_the_inbox_carries_the_same_lead_label(
    client, db, channel_id, user_id
):
    db.add(Lead(
        id=str(uuid.uuid4()), tenant_id=user_id, channel_id=channel_id,
        platform="whatsapp", contact_id=CUSTOMER, stage="qualified",
        language="en", opt_out=False, category="wholesale",
        thread_key=CUSTOMER,
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="500 units please", content_type="text", status="delivered",
        contact_phone=CUSTOMER,
        contact_phone_hash=hash_contact_phone(CUSTOMER),
    ))
    await db.commit()

    rows = client.get("/api/v1/inbox/threads").json()["threads"]
    row = next(t for t in rows if t["channel_id"] == channel_id)
    assert row["lead_category"] == "wholesale"


def test_digest_and_escalation_email_show_the_same_label():
    lead = SimpleNamespace(
        contact_name="Sara", contact_username=None, contact_id="+15550000001",
        platform="whatsapp", category="wholesale", priority="normal",
        request="500 units", last_message_at=None, created_at=None,
    )
    _, body = compose_digest([lead], datetime.now(timezone.utc))
    assert "Sara [Wholesale]" in body
    assert _lead_label(lead) == "Sara (Wholesale)"


def test_qualified_categories_are_validated_and_never_empty():
    settings = le.normalize_lead_settings({
        "qualified_categories": ["WHOLESALE", "bogus", "retail", "retail"],
    })
    assert settings["qualified_categories"] == ["wholesale", "retail"]

    # An empty list is a misconfiguration, not "qualify nothing": falling
    # back keeps one bad save from silently disabling the lead pipeline.
    empty = le.normalize_lead_settings({"qualified_categories": []})
    assert empty["qualified_categories"] == list(le.DEFAULT_QUALIFIED_CATEGORIES)
