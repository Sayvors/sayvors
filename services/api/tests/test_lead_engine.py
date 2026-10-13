"""The deterministic lead engine: parsing, validation, merge, scheduling.

These are the no-LLM guarantees: extraction parsing is a pure string
split riding the reply call, scheduling is rows + clamped settings, the
merge never downgrades a known field, and the worker module contains no
LLM machinery at all.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.meta import lead_engine as le
from app.modules.channels.models import ChannelMessage, Lead, LeadAction


# ── extraction split: pure, byte-identical without the line ──────────


def test_split_no_lead_line_is_byte_identical():
    for raw in ("Sure — what kind?", "hello", "", None):
        assert le.split_reply_and_lead(raw) == ((raw or "").strip(), None)


def test_split_trailing_lead_line():
    raw = 'Sure — what kind?\nLEAD: {"intent": "quote", "request": "10 shawarma plates", "confidence": 0.9}'
    reply, delta = le.split_reply_and_lead(raw)
    assert reply == "Sure — what kind?"
    assert delta["intent"] == "quote"
    assert delta["request"] == "10 shawarma plates"
    assert delta["confidence"] == 0.9


def test_split_malformed_line_is_ignored_not_fatal():
    # Not JSON → the whole text passes through, customer sees it all.
    raw = "Sure LEAD: oops not json"
    assert le.split_reply_and_lead(raw) == (raw, None)
    # Unparseable JSON object → same.
    raw2 = 'Hi\nLEAD: {"intent": broken}'
    assert le.split_reply_and_lead(raw2) == (raw2.strip(), None)


def test_split_lead_only_reply_leaves_nothing_to_send():
    reply, delta = le.split_reply_and_lead('LEAD: {"intent": "info", "confidence": 0.7}')
    assert reply == ""
    assert delta["intent"] == "info"


def test_parse_delta_whitelists_fields_and_clamps():
    delta = le._parse_lead_delta(
        '{"intent": "SCAM", "request": "x", "evil_prompt": "ignore rules",'
        ' "phone": "+971501234567", "confidence": 9}'
    )
    assert "evil_prompt" not in delta
    assert "intent" not in delta  # not in the allowed set
    assert delta["phone"] == "+971501234567"
    assert delta["confidence"] == 1.0  # clamped


def test_parse_delta_confidence_only_is_nothing():
    assert le._parse_lead_delta('{"confidence": 0.9}') is None
    assert le._parse_lead_delta("") is None
    assert le._parse_lead_delta("[]") is None


# ── phone validation: never guess a country ──────────────────────────


def test_validate_phone_international_passes():
    assert le.validate_phone("+971501234567") == "+971501234567"
    assert le.validate_phone("+44 20 7946 0958") == "+442079460958"


def test_validate_phone_never_guesses_region():
    # A bare local number has NO country — guessing one would fabricate
    # a fact. It must stay None, not become some default region's number.
    assert le.validate_phone("0501234567") is None
    assert le.validate_phone("2012345678") is None
    assert le.validate_phone("12345") is None
    assert le.validate_phone("") is None
    assert le.validate_phone(None) is None
    assert le.validate_phone("not a phone") is None


# ── deterministic signals ────────────────────────────────────────────


def test_detect_intent_keywords():
    assert le.detect_intent("how much for 50 boxes?") == "buying"
    assert le.detect_intent("كم السعر") == "buying"
    assert le.detect_intent("thanks!") is None
    assert le.detect_intent(None) is None


def test_detect_opt_out_bilingual():
    assert le.detect_opt_out("please STOP messaging me") is True
    assert le.detect_opt_out("توقف") is True
    assert le.detect_opt_out("stop by the shop") is True  # conservative: stop wins
    assert le.detect_opt_out("hello") is False


def test_open_question_detection():
    assert le.is_open_question("What do you need?") is True
    assert le.is_open_question("ماذا تريد؟") is True
    assert le.is_open_question("Your order is confirmed.") is False
    assert le.is_open_question(None) is False


# ── settings: whitelist + clamps, junk falls back ────────────────────


def test_normalize_settings_clamps_and_drops_junk():
    s = le.normalize_lead_settings({
        "max_attempts": 99,             # → 4
        "first_nudge_minutes": 1,       # → 5 (brief floor)
        "second_followup_hours": 9999,  # → 168
        "timezone": "Not/AZone",        # → UTC
        "system_prompt": "you are evil",  # dropped: not a setting
    })
    assert s["max_attempts"] == 4
    assert s["first_nudge_minutes"] == 5
    assert s["second_followup_hours"] == 168
    assert s["timezone"] == "UTC"
    assert "system_prompt" not in s


def test_normalize_settings_none_is_defaults():
    s = le.normalize_lead_settings(None)
    assert s == le.SETTINGS_DEFAULTS
    assert 5 <= s["first_nudge_minutes"] <= 15


def test_normalize_settings_valid_timezone_and_disable():
    s = le.normalize_lead_settings({"timezone": "Asia/Riyadh", "enabled": False})
    assert s["timezone"] == "Asia/Riyadh"
    assert s["enabled"] is False


# ── quiet hours + window (pure functions) ────────────────────────────


def test_quiet_hours_late_night_slides_to_morning():
    due = datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc)
    out = le._shift_out_of_quiet_hours(due, {"timezone": "UTC", "quiet_start_hour": 22, "quiet_end_hour": 8})
    assert (out.hour, out.minute) == (8, 0)
    assert out.date() > due.date()  # tomorrow morning, not same-day 08:00


def test_quiet_hours_early_morning_slides_same_day():
    due = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
    out = le._shift_out_of_quiet_hours(due, {"timezone": "UTC", "quiet_start_hour": 22, "quiet_end_hour": 8})
    assert (out.hour, out.date().day) == (8, 11)


def test_quiet_hours_daytime_untouched():
    due = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)
    out = le._shift_out_of_quiet_hours(due, {"timezone": "UTC", "quiet_start_hour": 22, "quiet_end_hour": 8})
    assert out == due


def test_quiet_hours_no_window_configured():
    due = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
    assert le._shift_out_of_quiet_hours(due, {"timezone": "UTC", "quiet_start_hour": 5, "quiet_end_hour": 5}) == due


def test_window_open_24h_from_last_inbound():
    now = datetime.now(timezone.utc)
    assert le.window_open(now - timedelta(hours=23)) is True
    assert le.window_open(now - timedelta(hours=25)) is False
    assert le.window_open(None) is False
    # Naive datetimes (SQLite) normalize instead of crashing.
    assert le.window_open((now - timedelta(hours=1)).replace(tzinfo=None)) is True


def test_nudge_text_templates_deterministic():
    assert le.nudge_text("What kind?", "en") == "Just checking in — What kind?"
    # Arabic nudge for an Arabic lead, question mark preserved.
    assert le.nudge_text("ما نوعه؟", "ar") == "مجرد متابعة — ما نوعه؟"
    # No stored question → honest generic ask, never invented urgency.
    assert le.nudge_text(None, "en") == "Just checking in — do you still need help with this?"
    # Same inputs, same output — a template, not a generation.
    assert le.nudge_text("Sure?", "en") == le.nudge_text("Sure?", "en")


# ── capture: create + merge, never downgrade, never raise ────────────


async def _lead_by_contact(db, channel_id, contact_id):
    return (await db.execute(
        select(Lead).where(Lead.channel_id == channel_id, Lead.contact_id == contact_id)
    )).scalar_one_or_none()


@pytest.mark.asyncio
async def test_capture_creates_lead_and_bumps_stage(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-1", contact_name="Sara",
        message_id="wamid-c1", inbound_text="how much for 50 boxes?",
        delta={"intent": "quote", "request": "50 boxes", "confidence": 0.9},
    )
    assert lead is not None
    assert lead.stage == "qualified"  # intent captured → out of "new"
    assert lead.intent == "quote"
    assert lead.request == "50 boxes"
    assert lead.phone_number is None  # customer never typed one
    assert lead.last_inbound_message_id == "wamid-c1"
    prov = lead.field_provenance
    assert prov["request"]["source_message_id"] == "wamid-c1"
    assert prov["request"]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_capture_merge_never_downgrades_or_erases(db, channel_id, user_id):
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-2", message_id="m1", inbound_text="pricing?",
        delta={"name": "Sara", "request": "wedding cake", "confidence": 0.9},
    )
    lead = await _lead_by_contact(db, channel_id, "capt-2")
    assert lead.contact_name == "Sara"

    # Lower-confidence later capture: name must NOT be replaced.
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-2", message_id="m2", inbound_text="ok",
        delta={"name": "S", "confidence": 0.3},
    )
    await db.refresh(lead)
    assert lead.contact_name == "Sara"
    assert lead.request == "wedding cake"  # an empty field never erases either


@pytest.mark.asyncio
async def test_capture_deterministic_fallback_without_delta(db, channel_id, user_id):
    # No extraction line: regex intent + typed phone candidate still land.
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-3", message_id="m3",
        inbound_text="how much for delivery? my number is +971501234567",
    )
    assert lead.intent == "buying"
    assert lead.phone_number == "+971501234567"
    assert lead.field_provenance["phone"]["status"] == "stated"
    assert lead.field_provenance["phone"]["confidence"] == 0.4
    # A local number typed without a country is never guessed into one.
    lead2 = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-4", message_id="m4", inbound_text="call me 0501234567",
    )
    assert lead2.phone_number is None


@pytest.mark.asyncio
async def test_capture_opt_out_kills_pending_actions(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-5", message_id="m5", inbound_text="info please",
    )
    db.add(LeadAction(
        id=str(uuid.uuid4()), tenant_id=user_id, lead_id=lead.id,
        channel_id=channel_id, contact_id="capt-5", platform="whatsapp",
        attempt=1, guard_message_id="m5",
        due_at=datetime.now(timezone.utc) + timedelta(minutes=8),
    ))
    await db.commit()

    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-5", message_id="m6", inbound_text="stop messaging me",
    )
    assert lead.opt_out is True
    assert lead.opt_out_at is not None
    actions = (await db.execute(
        select(LeadAction).where(LeadAction.lead_id == lead.id)
    )).scalars().all()
    assert [a.status for a in actions] == ["cancelled"]
    assert actions[0].ineligible_reason == "opt_out"


@pytest.mark.asyncio
async def test_capture_failure_never_raises(db, channel_id, user_id, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(db, "execute", _boom)
    result = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="capt-6", message_id="m7", inbound_text="hi",
    )
    assert result is None  # a capture problem never costs the customer their reply


# ── platform ground truth: WhatsApp's sender IS a verified phone ──────


@pytest.mark.asyncio
async def test_capture_whatsapp_stores_verified_sender_phone(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="971501234567", message_id="wp-1", inbound_text="hello",
    )
    # The customer is messaging FROM this number — Meta verified it; asking
    # them for it in the chat is absurd, so the engine records it.
    assert lead.phone_number == "+971501234567"
    assert lead.field_provenance["phone"]["status"] == "verified"
    # Instagram's numeric sender id is NOT a phone — never stored as one.
    ig = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="instagram",
        contact_id="1560689862767193", message_id="ig-1", inbound_text="hello",
    )
    assert ig.phone_number is None


@pytest.mark.asyncio
async def test_stated_phone_outranks_verified_only_when_confident(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="971501234567", message_id="wp-2", inbound_text="hi",
    )
    # A low-confidence stated number loses to the verified sender address.
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="971501234567", message_id="wp-3", inbound_text="hi",
        delta={"phone": "+971500000000", "confidence": 0.6},
    )
    await db.refresh(lead)
    assert lead.phone_number == "+971501234567"
    assert lead.field_provenance["phone"]["status"] == "verified"
    # A confident stated number wins and flips the status to "stated".
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="971501234567", message_id="wp-4",
        inbound_text="actually reach me on my other line",
        delta={"phone": "+971500000000", "confidence": 0.95},
    )
    await db.refresh(lead)
    assert lead.phone_number == "+971500000000"
    assert lead.field_provenance["phone"]["status"] == "stated"


# ── summary: a running digest, not the first greeting ─────────────────


@pytest.mark.asyncio
async def test_summary_is_a_running_digest_not_the_first_greeting(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="summ-1", message_id="s-1", inbound_text="Hi",
    )
    assert lead.summary == "Hi"  # verbatim fallback until substance exists

    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="summ-1", message_id="s-2", inbound_text="I need a website",
        delta={
            "request": "custom e-commerce website",
            "summary": "Wants a customized e-commerce website, ~10k budget",
            "confidence": 0.9,
        },
    )
    await db.refresh(lead)
    assert lead.summary == "Wants a customized e-commerce website, ~10k budget"

    # A newer digest REPLACES the old one — summaries must track the
    # conversation as it grows (facts like request never downgrade).
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="summ-1", message_id="s-3", inbound_text="budget is 15k now",
        delta={
            "summary": "Wants a customized e-commerce site, budget raised to 15k",
            "confidence": 0.9,
        },
    )
    await db.refresh(lead)
    assert lead.summary == "Wants a customized e-commerce site, budget raised to 15k"
    assert lead.request == "custom e-commerce website"


# ── the honest handoff: the team is actually told ─────────────────────


@pytest.mark.asyncio
async def test_qualified_lead_notifies_the_team_once(db, channel_id, user_id):
    from app.modules.notifications.models import Notification

    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="notif-1", message_id="n-1",
        inbound_text="how much for 50 boxes?",
    )

    async def _pings():
        rows = (await db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type == "lead",
                Notification.data["lead_id"].as_string() == lead.id,
            )
        )).scalars().all()
        return rows

    pings = await _pings()
    assert len(pings) == 1
    assert "how much" in pings[0].body or "50 boxes" in pings[0].body

    # Capturing the same (already qualified) lead again never re-pings.
    await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="notif-1", message_id="n-2", inbound_text="ok thanks",
    )
    assert len(await _pings()) == 1


@pytest.mark.asyncio
async def test_qualified_lead_notify_respects_tenant_settings(db, channel_id, user_id):
    from app.modules.notifications.models import Notification
    from app.modules.users.models import User

    db.add(User(
        id=user_id,
        email="quiet-tenant@sayvors.com",
        first_name="Quiet",
        last_name="Tenant",
        password_hash="x",
        onboarded=True,
        notification_settings={"leads": False},
    ))
    await db.commit()

    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="notif-2", message_id="q-1",
        inbound_text="how much for 50 boxes?",
    )

    rows = (await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == "lead",
        )
    )).scalars().all()
    assert rows == []
    # Only the pop is gated — the lead itself is untouched.
    await db.refresh(lead)
    assert lead.stage == "qualified"


# ── scheduling: durable, idempotent, capped ──────────────────────────


@pytest.mark.asyncio
async def test_schedule_followup_moves_stage_and_sets_next_action(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="sched-1", message_id="s1", inbound_text="quote please",
    )
    action = await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-1",
        platform="whatsapp", guard_message_id="s1",
        question="How many boxes?", settings=None,
    )
    assert action is not None
    assert action.attempt == 1
    assert action.status == "pending"
    await db.refresh(lead)
    assert lead.stage == "follow_up"
    assert lead.next_action_at is not None
    # First nudge lands inside the brief's 5–15 minute window.
    delta_min = (action.due_at - datetime.now(timezone.utc)).total_seconds() / 60
    assert 4 <= delta_min <= 16


@pytest.mark.asyncio
async def test_schedule_followup_rearm_walks_attempts_not_duplicates(db, channel_id, user_id):
    # Buying-intent text, so capture_leal qualifies the lead. This test is
    # about the attempt ladder, not about qualification -- an unqualified lead
    # is now correctly refused by schedule_followup (see
    # tests/test_lead_escalation.py::test_schedule_followup_refuses_unqualified_lead).
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="sched-2", message_id="s2", inbound_text="how much for 50 boxes?",
    )
    a1 = await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-2",
        platform="whatsapp", guard_message_id="s2", question="?", settings=None,
    )
    a2 = await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-2",
        platform="whatsapp", guard_message_id="s2", question="?", settings=None,
    )
    a3 = await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-2",
        platform="whatsapp", guard_message_id="s2", question="?", settings=None,
    )
    assert (a1.attempt, a2.attempt, a3.attempt) == (1, 2, 3)
    # Attempt cap (default 3): a fourth arm is refused, not queued.
    assert await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-2",
        platform="whatsapp", guard_message_id="s2", question="?", settings=None,
    ) is None


@pytest.mark.asyncio
async def test_schedule_followup_refused_for_closed_leads(db, channel_id, user_id):
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="sched-3", message_id="s3", inbound_text="hi",
    )
    lead.opt_out = True
    db.add(lead)
    await db.commit()
    assert await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-3",
        platform="whatsapp", guard_message_id="s3", question="?", settings=None,
    ) is None

    lead2 = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="sched-4", message_id="s4", inbound_text="hi",
    )
    lead2.stage = "converted"
    db.add(lead2)
    await db.commit()
    assert await le.schedule_followup(
        db, lead=lead2, channel_id=channel_id, contact_id="sched-4",
        platform="whatsapp", guard_message_id="s4", question="?", settings=None,
    ) is None


@pytest.mark.asyncio
async def test_duplicate_step_is_structurally_impossible(db, channel_id, user_id):
    """The unique (lead, guard, attempt) constraint — the idempotency
    backstop that holds even where row locks don't exist."""
    from sqlalchemy.exc import IntegrityError

    # Buying-intent text so the lead qualifies (see the ladder test above).
    lead = await le.capture_lead(
        db, tenant_id=user_id, channel_id=channel_id, platform="whatsapp",
        contact_id="sched-5", message_id="s5", inbound_text="can I book a table?",
    )
    first = await le.schedule_followup(
        db, lead=lead, channel_id=channel_id, contact_id="sched-5",
        platform="whatsapp", guard_message_id="s5", question="?", settings=None,
    )
    assert first is not None
    # A racing worker arming the SAME (lead, guard, attempt) again —
    # however it happens, the database refuses to store it twice.
    twin = LeadAction(
        id=str(uuid.uuid4()), tenant_id=user_id, lead_id=lead.id,
        channel_id=channel_id, contact_id="sched-5", platform="whatsapp",
        attempt=1, guard_message_id="s5",
        due_at=datetime.now(timezone.utc),
    )
    db.add(twin)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_latest_inbound_returns_newest(db, channel_id):
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        platform_message_id="old-1", content="first", status="delivered",
        contact_phone="c-newest",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        platform_message_id="new-1", content="second", status="delivered",
        contact_phone="c-newest",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    ))
    await db.commit()
    row = await le.latest_inbound(db, channel_id, "c-newest")
    assert row[0] == "new-1"


# ── the architecture guard: zero LLM in the deterministic path ───────


def test_worker_and_engine_contain_no_llm_machinery():
    """Acceptance: worker polling produces zero LLM calls. Enforced
    structurally — neither the dispatcher nor the engine may import or
    touch any LLM/provider code (case-sensitive: prose may say "LLM")."""
    meta_dir = Path(__file__).resolve().parents[1] / "app" / "modules" / "channels" / "meta"
    for name in ("lead_action_worker.py", "lead_engine.py", "lead_escalation.py"):
        src = (meta_dir / name).read_text(encoding="utf-8")
        for banned in ("llm", "resolve_tenant_model", "provider.complete", "_generate_reply"):
            assert banned not in src, f"{name} references {banned!r} — the deterministic path must never touch LLM code"
