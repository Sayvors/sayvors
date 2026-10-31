"""Urgency escalation and the opt-in confusion counter.

The old rule escalated any thread where the customer wrote three times after
an AI reply — so a normal "what do you need?" conversation was muted after a
few turns and the customer got "let me get my colleague" instead of an answer.

Escalation is now intent-driven: an explicitly urgent message pages a human
immediately, and the counter is off unless a tenant opts in *and* only moves
when the classifier says the customer came back confused.
"""
import pytest

from app.modules.channels.meta import lead_escalation
from test_lead_escalation import _noop_async, _seed_thread


@pytest.mark.parametrize(
    "text",
    [
        "I need this urgent please",
        "can you do it ASAP?",
        "I need it right now",
        "this is an emergency",
        "as soon as possible",
        "بسرعة من فضلك",
        "هذا عاجل",
        "الآن أحتاجه",
        "still waiting for an answer",
        "no one has replied",
        "this is the third time I ask",
    ],
)
def test_urgency_markers_are_detected(text):
    assert lead_escalation.detect_urgency(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hi, what is your working hours today?",
        "nowadays I sell shoes online",
        "I want an e-commerce website for shoes and jewelry",
        "Why don't you help me",
        "",
        None,
    ],
)
def test_normal_questions_are_not_urgent(text):
    assert lead_escalation.detect_urgency(text) is False


@pytest.mark.asyncio
async def test_urgent_message_escalates_on_the_first_turn(db, monkeypatch):
    """No counter, no threshold: the customer said it is urgent."""
    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)
    lead_escalation.clear_settings_cache()

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=1, phone="+15550000031")
    await lead_escalation.update_escalation_state(db, lead, urgent=True)
    await db.commit()

    assert lead.priority == "important"
    assert lead.priority_since is not None
    assert lead.ai_miss_count == 0, "urgency is not a confusion miss"


@pytest.mark.asyncio
async def test_normal_followups_never_escalate(db, monkeypatch):
    """Three answered questions in a row must not mute the AI."""
    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)
    lead_escalation.clear_settings_cache()

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3, phone="+15550000032")
    for _ in range(5):
        await lead_escalation.update_escalation_state(db, lead, confused=False)
        await db.commit()

    assert lead.ai_miss_count == 0
    assert lead.priority == "normal"


@pytest.mark.asyncio
async def test_confusion_counter_is_off_by_default(db, monkeypatch):
    """Threshold 0 means the counter never pages anyone; only urgency can."""
    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)
    lead_escalation.clear_settings_cache()

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3, phone="+15550000033")
    from app.modules.users.models import User

    user = await db.get(User, lead.tenant_id)
    user.lead_settings = {"escalation_threshold": 0}
    await db.commit()
    lead_escalation.clear_settings_cache()

    for _ in range(6):
        await lead_escalation.update_escalation_state(db, lead, confused=True)
        await db.commit()

    assert lead.ai_miss_count == 6, "the signal is still counted..."
    assert lead.priority == "normal", "...but it must not page anyone at 0"


@pytest.mark.asyncio
async def test_urgent_handover_uses_its_own_line(db, monkeypatch):
    """An urgent customer gets an acknowledgement, not "let me get a colleague"."""
    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)

    sent: list[str] = []

    class _Adapter:
        async def send_text_message(self, phone_number_id, token, to, text):
            sent.append(text)
            return "wamp-urgent"

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=1, phone="+15550000034")
    lead.priority = "important"
    await db.commit()

    await lead_escalation.escalate_to_human(
        db, lead, _Adapter(), "PHONE", "tok", urgent=True
    )
    await db.commit()

    assert sent == [lead_escalation.URGENT_HANDOVER_TEXT]
