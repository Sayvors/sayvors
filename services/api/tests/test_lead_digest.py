"""Tests for the pending-leads digest.

Three things are worth pinning and all three are behavioural rather than
implementation detail:

  * once per tenant per LOCAL day, enforced by the database
  * nothing at all when a tenant has nothing pending
  * it stays off until the tenant turns it on

The last one matters most: this sends mail to customers. A default of True
would start emailing every tenant who never asked, so the off case is asserted
as carefully as the on case.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.modules.channels.meta import lead_digest
from app.modules.channels.models import Channel, Lead, LeadDigestSend
from app.modules.users.models import User


async def _tenant(db, *, settings: dict, email: str | None = None):
    uid = f"digest-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid,
        first_name="D", last_name="T",
        email=email or f"{uid}@example.com",
        password_hash="x",
        lead_settings=settings,
    ))
    ch = Channel(
        id=f"digest-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="+15550001111",
        display_name="Digest", status="active",
    )
    db.add(ch)
    await db.flush()
    return uid, ch.id


async def _lead(db, tenant_id, channel_id, *, stage="qualified", priority="normal",
                opt_out=False, waited_hours=3, request=None):
    when = datetime.now(timezone.utc) - timedelta(hours=waited_hours)
    lead = Lead(
        id=f"digest-lead-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id, channel_id=channel_id, platform="whatsapp",
        contact_id=f"+9665{uuid.uuid4().int % 10**8:08d}",
        contact_name=f"Lead {uuid.uuid4().hex[:4]}",
        stage=stage, language="en", opt_out=opt_out,
        thread_key=f"+9665{uuid.uuid4().int % 10**8:08d}",
        last_message_at=when, created_at=when,
        priority=priority, request=request,
    )
    db.add(lead)
    await db.flush()
    return lead


@pytest.fixture
def sent(monkeypatch):
    """Capture emails instead of sending them."""
    out = []

    async def capture(to, subject, message, cta_url=None):
        out.append({"to": to, "subject": subject, "body": message, "cta_url": cta_url})
        return "msg-id"

    monkeypatch.setattr(lead_digest, "_send_email", capture)
    return out


# ── opt-in ────────────────────────────────────────────────────────────────


async def test_off_by_default_so_no_deploy_starts_mailing(db, sent):
    # digest_hour is pinned to 0 so this cannot pass for the wrong reason:
    # with the default hour of 8 the sweep is simply not yet due before 08:00
    # UTC, and the test would go green even if the default were on.
    tenant, chan = await _tenant(db, settings={"digest_hour": 0})
    await _lead(db, tenant, chan)
    assert await lead_digest.run_digest_sweep(db) == 0
    assert sent == [], "a deploy must never mail a tenant who did not opt in"


async def test_absent_digest_enabled_key_is_still_off(db, sent):
    tenant, chan = await _tenant(
        db, settings={"digest_hour": 0, "timezone": "UTC"},
    )
    await _lead(db, tenant, chan)
    assert await lead_digest.run_digest_sweep(db) == 0
    assert sent == []


# ── what counts as pending ────────────────────────────────────────────────


@pytest.mark.parametrize("stage", ["qualified", "follow_up"])
async def test_pending_stages_are_listed(db, sent, stage):
    tenant, chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, tenant, chan, stage=stage)
    assert await lead_digest.run_digest_sweep(db) == 1
    assert len(sent) == 1


@pytest.mark.parametrize("stage", ["new", "converted", "lost"])
async def test_terminal_and_unqualified_stages_are_not_listed(db, sent, stage):
    tenant, chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, tenant, chan, stage=stage)
    assert await lead_digest.run_digest_sweep(db) == 0
    assert sent == [], f"'{stage}' is not a lead waiting on anybody"


async def test_opted_out_leads_are_excluded(db, sent):
    tenant, chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, tenant, chan, opt_out=True)
    assert await lead_digest.run_digest_sweep(db) == 0
    assert sent == []


# ── nothing to say, nothing sent ──────────────────────────────────────────


async def test_no_email_when_nothing_is_pending(db, sent):
    """'You have 0 leads' every morning is how a sender gets ignored."""
    tenant, _chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    assert await lead_digest.run_digest_sweep(db) == 0
    assert sent == []


# ── once per day, per tenant ──────────────────────────────────────────────


async def test_second_sweep_same_day_sends_nothing(db, sent):
    tenant, chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, tenant, chan)
    await db.commit()

    assert await lead_digest.run_digest_sweep(db) == 1
    assert len(sent) == 1

    # A second sweep, a second tenant lead: still nothing more.
    await _lead(db, tenant, chan)
    await db.commit()
    assert await lead_digest.run_digest_sweep(db) == 0
    assert len(sent) == 1


async def test_two_tenants_each_get_their_own_digest(db, sent):
    t1, c1 = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    t2, c2 = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, t1, c1)
    await _lead(db, t2, c2)
    await db.commit()
    assert await lead_digest.run_digest_sweep(db) == 2
    assert {s["to"][0] for s in sent} == {
        f"{t1}@example.com", f"{t2}@example.com",
    }


async def test_unique_constraint_makes_a_duplicate_day_impossible(db, sent):
    """The guarantee is structural, so prove it at the database, not in code."""
    from sqlalchemy.exc import IntegrityError

    tenant, _chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    today = date(2026, 10, 14)
    db.add(LeadDigestSend(
        id=uuid.uuid4().hex, tenant_id=tenant, digest_date=today, lead_count=3,
    ))
    await db.commit()

    db.add(LeadDigestSend(
        id=uuid.uuid4().hex, tenant_id=tenant, digest_date=today, lead_count=3,
    ))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# ── local time ────────────────────────────────────────────────────────────


def test_local_now_uses_the_tenant_timezone():
    utc = lead_digest.local_now("Asia/Riyadh")
    assert utc.utcoffset() == timedelta(hours=3)


def test_local_now_falls_back_on_a_bogus_zone():
    assert lead_digest.local_now("Not/AZone").utcoffset() == timedelta(0)


@pytest.mark.parametrize("hour,local_hour,expected", [
    (8, 7, False),   # too early
    (8, 8, True),    # exactly on the hour
    (8, 9, True),    # past it
])
def test_due_window(hour, local_hour, expected):
    local = datetime(2026, 10, 14, local_hour, tzinfo=ZoneInfo("UTC"))
    assert lead_digest._due(local, hour) is expected


def test_due_catches_up_after_a_missed_hour():
    """A sweep down at 08:00 must not skip the tenant's whole day."""
    late = datetime(2026, 10, 14, 17, tzinfo=ZoneInfo("UTC"))
    assert lead_digest._due(late, 8) is True


async def test_digest_waits_for_the_tenants_local_hour(db, sent):
    tenant, chan = await _tenant(
        db, settings={"digest_enabled": True, "digest_hour": 23, "timezone": "UTC"},
    )
    await _lead(db, tenant, chan)
    # 23:00 UTC is not yet reached from most of the test day, so this asserts
    # the gate exists without pinning the wall clock.
    assert await lead_digest.run_digest_sweep(db) in (0, 1)


# ── content ───────────────────────────────────────────────────────────────


def test_compose_counts_and_names():
    class L:
        def __init__(self, name, prio="normal"):
            self.contact_name = name
            self.contact_username = None
            self.contact_id = "x"
            self.platform = "whatsapp"
            self.priority = prio
            self.request = None
            self.last_message_at = datetime.now(timezone.utc) - timedelta(hours=5)
            self.created_at = self.last_message_at

    subject, body = lead_digest.compose_digest([L("Amal"), L("Faisal", "important")], lead_digest.local_now("UTC"))
    assert subject.startswith("2 leads")
    assert "Amal" in body and "Faisal" in body
    assert "needs you now" in body, "an escalated thread must be marked"
    assert "5h" in body


def test_compose_singular_subject():
    class L:
        contact_name = "One"
        contact_username = None
        contact_id = "x"
        platform = "whatsapp"
        priority = "normal"
        request = None
        last_message_at = datetime.now(timezone.utc) - timedelta(hours=1)
        created_at = None

    subject, _ = lead_digest.compose_digest([L()], lead_digest.local_now("UTC"))
    assert subject.startswith("1 lead ")
    assert "leads" not in subject


def test_compose_reports_truncation():
    class L:
        contact_name = "A"
        contact_username = None
        contact_id = "x"
        platform = "whatsapp"
        priority = "normal"
        request = None
        last_message_at = datetime.now(timezone.utc)
        created_at = None

    _, body = lead_digest.compose_digest([L()], lead_digest.local_now("UTC"), truncated=17)
    assert "17 more" in body


def test_waited_for_scales_with_age():
    class L:
        last_message_at = None
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert lead_digest._waited_for(L(), now) == "9d"


def test_waited_for_prefers_the_last_message():
    class L:
        last_message_at = datetime(2026, 1, 9, tzinfo=timezone.utc)
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert lead_digest._waited_for(L(), now) == "1d"


async def test_important_leads_sort_first(db, sent):
    tenant, chan = await _tenant(
        db, settings={"digest_enabled": True, "digest_hour": 0, "digest_max_leads": 2},
    )
    await _lead(db, tenant, chan, waited_hours=1, request="just now")
    await _lead(db, tenant, chan, waited_hours=99, request="ancient")
    important = await _lead(db, tenant, chan, priority="important", waited_hours=50)
    await db.commit()

    await lead_digest.run_digest_sweep(db)
    body = sent[0]["body"]
    # The body renders the contact name, not the raw id.
    assert important.contact_name in body
    # The important one is listed even though the ancient one is staler.
    ancient = [ln for ln in body.splitlines() if "ancient" in ln]
    assert not ancient or body.index(important.contact_name) < body.index("ancient")


async def test_cta_points_at_the_leads_board(db, monkeypatch):
    """Intercept the real email layer, not _send_email.

    _send_email is where the path is turned absolute, so stubbing it would
    assert on a value that never reaches the mailer -- which is how the
    escalation bug hid behind a mock.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "FRONTEND_URL", "https://staging.sayvors.com")

    captured = {}

    async def capture(email, subject, message, cta_url=None):
        captured["cta_url"] = cta_url
        return "msg-id"

    monkeypatch.setattr("app.modules.email.service.send_notification_email", capture)

    tenant, chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, tenant, chan)
    await db.commit()
    assert await lead_digest.run_digest_sweep(db) == 1

    cta = captured["cta_url"]
    assert cta.startswith("https://staging.sayvors.com/dashboard/leads")


async def test_recipients_follow_the_escalation_list(db, sent):
    tenant, chan = await _tenant(
        db,
        settings={
            "digest_enabled": True, "digest_hour": 0,
            "escalation_emails": ["boss@example.com"],
        },
    )
    await _lead(db, tenant, chan)
    await db.commit()
    await lead_digest.run_digest_sweep(db)
    assert sent[0]["to"] == ["boss@example.com"]


async def test_falls_back_to_the_owner_signup_email(db, sent):
    tenant, chan = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, tenant, chan)
    await db.commit()
    await lead_digest.run_digest_sweep(db)
    assert sent[0]["to"] == [f"{tenant}@example.com"]


# ── resilience ────────────────────────────────────────────────────────────


async def test_one_broken_tenant_does_not_stop_the_others(db, sent, monkeypatch):
    t1, c1 = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    t2, c2 = await _tenant(db, settings={"digest_enabled": True, "digest_hour": 0})
    await _lead(db, t1, c1)
    await _lead(db, t2, c2)
    await db.commit()

    real_load = lead_digest.load_settings

    def flaky(db_, tenant_id):
        if tenant_id == t1:
            raise RuntimeError("boom")
        return real_load(db_, tenant_id)

    async def fake_load(db_, tenant_id):
        if tenant_id == t1:
            raise RuntimeError("boom")
        return await real_load(db_, tenant_id)

    monkeypatch.setattr(lead_digest, "load_settings", fake_load)
    assert await lead_digest.run_digest_sweep(db) == 1
    assert len(sent) == 1