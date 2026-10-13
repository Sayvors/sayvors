# Lead Qualification Gate + Importance Escalation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Never send a sales follow-up sequence to an unqualified lead; detect "AI answered, customer wrote again" three times running, hand the thread to a human, and escalate by email.

**Architecture:** One new enum + six columns on `leads`, with two indexes (a composite for the board sort, a partial index for the cross-tenant reminder sweep). A single module `lead_escalation.py` owns every counter/priority transition, so the signal and the derived state cannot drift. A sweep worker runs alongside the existing 15s loops for the reminder and the 24h resume.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Alembic, aiosqlite (tests), Pytest. Frontend: Next.js 16 + React 19 + Tailwind 4.

**Spec:** `docs/specs/2026-10-13-lead-priority-escalation-design.md`

---

## File structure

| File | Responsibility |
|---|---|
| `services/api/app/modules/channels/meta/lead_escalation.py` | **NEW.** All escalation state transitions: counter update, priority recompute, handover, clear-on-exit, due-row queries. No LLM imports (enforced by existing test). |
| `services/api/app/modules/channels/models.py` | Add `lead_priority` enum + 6 columns + 2 indexes to `Lead`. |
| `services/api/alembic/versions/20261013140000_add_lead_priority.py` | **NEW.** Migration for the above. |
| `services/api/app/modules/channels/meta/lead_engine.py` | `schedule_followup` qualification gate; `normalize_lead_settings` accepts `escalation_emails`. |
| `services/api/app/modules/channels/meta/consumer.py` | Call counter update after inbound persist; suppress AI reply while important; set `is_ai` on AI-authored outbound rows. |
| `services/api/app/modules/channels/meta/escalation_worker.py` | **NEW.** 15s sweep: reminder + 24h resume. |
| `services/api/app/workers/main.py` | Register the sweep alongside existing loops. |
| `services/api/app/modules/channels/leads.py` | Expose `priority` on the list endpoint + schema. |
| `services/api/tests/test_lead_escalation.py` | **NEW.** All tests for this feature. |
| `apps/web/lib/api-leads.ts` | `priority` on `LeadOut`. |
| `apps/web/components/leads/LeadsBoard.tsx` | Priority badge + sort + filter. |
| `apps/web/components/dashboard/tabs/LeadsTab.tsx` | **DELETE** hardcoded mock; render real data. |
| `apps/web/components/dashboard/ChannelWorkspace.tsx` | Stop rendering the mock tab. |

**Existing constraints that must not be violated:**
- `tests/test_lead_engine.py:585` scans `lead_engine.py` and `lead_action_worker.py` for `llm`, `resolve_tenant_model`, `provider.complete`, `_generate_reply`. `lead_escalation.py` is added to that scan.
- Tests run on SQLite; `FOR UPDATE SKIP LOCKED` is a no-op there. Keep new queries SQLite-safe (no `ON CONFLICT`, no partial-index `WHERE` clause in application queries).

---

## Task 1: Model fields + migration

**Files:**
- Modify: `services/api/app/modules/channels/models.py` (Lead class, ~line 207-291)
- Create: `services/api/alembic/versions/20261013140000_add_lead_priority.py`

- [ ] **Step 1: Add the enum and columns to `Lead`**

In `models.py`, add near the other module enums:

```python
lead_priority = Enum("normal", "important", name="lead_priority")
```

Add these six fields to the `Lead` class, after `next_action_at` (line ~281):

```python
    # Escalation: consecutive "AI replied, customer wrote again" cycles.
    # The sole input that ever moves `priority` -- see lead_escalation.py.
    ai_miss_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    priority: Mapped[str] = mapped_column(
        Enum("normal", "important", name="lead_priority"),
        default="normal", server_default="normal", nullable=False,
    )
    priority_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL is terminal "reminded or never armed" -- not "not yet".
    escalation_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handover_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Add these indexes inside `Lead.__table_args__`, after `ix_leads_channel_contact` (line ~229):

```python
        # Board sort: WHERE tenant_id=? ORDER BY priority DESC, updated_at DESC
        Index("ix_leads_tenant_priority", "tenant_id", "priority", "updated_at"),
```

Note: the partial index is created in the migration only (SQLite cannot express `WHERE` in `CREATE INDEX`), so it is **not** declared in `__table_args__`.

- [ ] **Step 2: Verify `Integer` and `Enum` are imported in models.py**

Run: `grep -n "^from sqlalchemy import" services/api/app/modules/channels/models.py`
Expected: line contains `Enum`, `Index`, `Integer`, `DateTime`. Add any that are missing.

- [ ] **Step 3: Write the migration**

Create `services/api/alembic/versions/20261013140000_add_lead_priority.py`:

```python
"""Add lead escalation state.

Revision ID: 20261013140000
Revises: 20261013120000
Create Date: 2026-10-13

See docs/specs/2026-10-13-lead-priority-escalation-design.md.

Defaults are the non-escalated state, so existing rows backfill to
ai_miss_count=0 / priority='normal' and no tenant is escalated by a deploy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013140000"
down_revision: Union[str, Sequence[str], None] = "20261013120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PRIORITY = sa.Enum("normal", "important", name="lead_priority")


def upgrade() -> None:
    _PRIORITY.create(op.get_bind(), checkfirst=True)
    op.add_column("leads", sa.Column("ai_miss_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("leads", sa.Column("priority", _PRIORITY, nullable=False, server_default="normal"))
    op.add_column("leads", sa.Column("priority_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("escalation_reminder_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("handover_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_leads_tenant_priority", "leads", ["tenant_id", "priority", "updated_at"], unique=False
    )
    # Partial: the reminder sweep is the only cross-tenant query in this
    # feature, and without this it scans every lead row on every 15s tick.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_pending_reminder "
        "ON leads (escalation_reminder_at) WHERE priority = 'important'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_leads_pending_reminder")
    op.drop_index("ix_leads_tenant_priority", table_name="leads")
    for col in (
        "handover_sent_at", "escalation_reminder_at", "escalated_at",
        "priority_since", "priority", "ai_miss_count",
    ):
        op.drop_column("leads", col)
    _PRIORITY.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 4: Verify single head and apply**

Run:
```bash
cd services/api
python -m alembic heads
```
Expected: `20261013140000 (head)` and nothing else.

Run: `python -m alembic upgrade head`
Expected: no errors.

Run: `python -m alembic current`
Expected: `20261013140000 (head)`

- [ ] **Step 5: Commit**

```bash
git add services/api/app/modules/channels/models.py services/api/alembic/versions/20261013140000_add_lead_priority.py
git commit -m "feat(leads): add escalation state columns and indexes"
```

---

## Task 2: Qualification gate

**Files:**
- Modify: `services/api/app/modules/channels/meta/lead_engine.py:474` (`schedule_followup`)
- Test: `services/api/tests/test_lead_escalation.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_lead_escalation.py` with the shared fixtures, then the gate tests. Start with:

```python
import pytest


@pytest.mark.asyncio
async def test_schedule_followup_refuses_unqualified_lead(db, monkeypatch):
    """A lead that never showed buying intent must not get a sales sequence.

    Regression guard for the real defect: every inbound created a Lead, and
    schedule_followup only checked opt_out/stage-closed, so "hello" received
    three nudges across 72 hours.
    """
    from app.modules.channels.meta.lead_engine import schedule_followup
    from app.modules.users.models import User

    uid = "gate-user-1"
    db.add(User(
        id=uid, first_name="G", last_name="A", email=f"{uid}@example.com",
        password_hash="x", lead_settings={"quiet_start_hour": 0, "quiet_end_hour": 0},
    ))
    await db.flush()
    channel = Channel(
        id="gate-chan-1", user_id=uid, platform="whatsapp",
        platform_user_id="+15550000001", display_name="Gate", status="active",
    )
    db.add(channel)
    await db.flush()
    lead = Lead(
        id="gate-lead-1", tenant_id=uid, channel_id=channel.id,
        platform="whatsapp", contact_id="+966500000001",
        stage="new", language="en", opt_out=False, thread_key="+966500000001",
    )
    db.add(lead)
    await db.commit()

    result = await schedule_followup(
        db, lead=lead, channel_id=channel.id, contact_id="+966500000001",
        platform="whatsapp", guard_message_id="wamid-gate-1",
        question="What do you need?", settings={"quiet_start_hour": 0, "quiet_end_hour": 0},
    )
    assert result is None, "unqualified lead must not be armed"

    lead.stage = "qualified"
    await db.commit()
    armed = await schedule_followup(
        db, lead=lead, channel_id=channel.id, contact_id="+966500000001",
        platform="whatsapp", guard_message_id="wamid-gate-1",
        question="What do you need?", settings={"quiet_start_hour": 0, "quiet_end_hour": 0},
    )
    assert armed is not None, "qualified lead must be armed"
```

Add the needed imports at the top of the test file (`Channel`, `Lead`, and the `_test_session_factory` pattern used by `tests/test_voice_and_followup.py`, plus the `db` fixture from `conftest.py`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py::test_schedule_followup_refuses_unqualified_lead -q`
Expected: FAIL — `result` is not None for `stage="new"`.

- [ ] **Step 3: Add the gate**

In `lead_engine.py`, in `schedule_followup`, extend the refusal block at line ~490:

```python
    if (
        not settings["enabled"]
        or settings["max_attempts"] < 1
        or lead.opt_out
        or lead.stage in ("converted", "lost")
        # Qualification gate. capture_lead creates a Lead for every inbound
        # DM, so without this an unqualified conversation ("hello") receives
        # the full sales sequence the moment the AI's reply ends in a "?" --
        # is_open_question was the only gate and it says nothing about intent.
        or lead.stage != "qualified"
    ):
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py -q`
Expected: PASS.

- [ ] **Step 5: Check existing lead tests still pass**

Run: `cd services/api && python -m pytest tests/test_lead_engine.py tests/test_voice_and_followup.py -q`
Expected: all pass. If `test_voice_and_followup.py` follow-up tests fail because their seeded leads are `stage="new"`, update `_seed_lead` in that file to pass `stage="follow_up"` — those tests exercise the *worker*, not the gate.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/modules/channels/meta/lead_engine.py services/api/tests/test_lead_escalation.py
git commit -m "fix(leads): gate follow-up sequences on stage=='qualified'"
```

---

## Task 3: Escalation module — counter and priority

**Files:**
- Create: `services/api/app/modules/channels/meta/lead_escalation.py`
- Test: `services/api/tests/test_lead_escalation.py`

- [ ] **Step 1: Write the failing counter tests**

Append to `tests/test_lead_escalation.py`. Add a helper that seeds a lead plus a thread of `ChannelMessage` rows:

```python
async def _seed_thread(db, *, last_outbound_is_ai: bool | None, count: int, tenant: str):
    """Seed a lead and `count` inbound messages, optionally preceded by an
    AI-authored outbound so the counter increments."""
    uid = f"esc-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="E", last_name="S", email=f"{uid}@example.com",
        password_hash="x", lead_settings={"quiet_start_hour": 0, "quiet_end_hour": 0},
    ))
    channel = Channel(
        id=f"esc-chan-{uuid.uuid4().hex[:8]}", user_id=uid, platform="whatsapp",
        platform_user_id="+15550000002", display_name="Esc", status="active",
    )
    db.add(channel)
    await db.flush()
    lead = Lead(
        id=f"esc-lead-{uuid.uuid4().hex[:8]}", tenant_id=uid, channel_id=channel.id,
        platform="whatsapp", contact_id="+966500000009",
        stage="qualified", language="en", opt_out=False, thread_key="+966500000009",
    )
    db.add(lead)
    await db.flush()
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    if last_outbound_is_ai is not None:
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="outbound",
            content="ai reply", content_type="text", status="sent",
            contact_phone="+966500000009", is_ai=last_outbound_is_ai,
            created_at=base,
        ))
        await db.flush()
    for i in range(count):
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="inbound",
            content=f"still waiting {i}", content_type="text", status="delivered",
            contact_phone="+966500000009", created_at=base + timedelta(minutes=i + 1),
        ))
    await db.commit()
    return lead
```

Then:

```python
@pytest.mark.asyncio
async def test_counter_increments_after_ai_reply(db):
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=1)
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 1
    assert lead.priority == "normal"      # below threshold


@pytest.mark.asyncio
async def test_counter_resets_after_human_reply(db):
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=False, count=1)
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 0


@pytest.mark.asyncio
async def test_first_contact_is_zero(db):
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=None, count=1)
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 0


@pytest.mark.asyncio
async def test_priority_escalates_at_three_and_deescalates(db):
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    lead.ai_miss_count = 2
    await db.commit()

    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 3
    assert lead.priority == "important"
    assert lead.priority_since is not None

    # Counter drops -> priority drops with it, and escalation state clears.
    lead.ai_miss_count = 0
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.priority == "normal"
    assert lead.priority_since is None
    assert lead.escalated_at is None
    assert lead.escalation_reminder_at is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py -q -k counter or priority`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.channels.meta.lead_escalation'`.

- [ ] **Step 3: Add `is_ai` to `ChannelMessage`**

The counter must know whether an outbound reply came from the AI. This is a
stored flag, never string matching on content. In `models.py`, add to
`ChannelMessage`:

```python
    # True when the platform's AI authored this outbound row. Set only by the
    # consumer on rows it writes itself. Drives lead_escalation's counter --
    # never inferred from message text, which would misclassify a human who
    # happens to type similar words.
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
```

Create migration `services/api/alembic/versions/20261013141000_add_channel_message_is_ai.py`
with `down_revision = "20261013140000"` and:

```python
def upgrade() -> None:
    op.add_column(
        "channel_messages",
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("channel_messages", "is_ai")
```

Run: `cd services/api && python -m alembic upgrade head`
Expected: `20261013141000 (head)`

- [ ] **Step 4: Create the escalation module — skeleton**

Create `services/api/app/modules/channels/meta/lead_escalation.py`:

```python
"""Lead importance escalation: counter, priority, handover state.

The only place `priority` is ever written. `ai_miss_count` is the sole input
that moves it, so the two cannot drift -- fixing the counter logic corrects
priority automatically.

Deliberately free of LLM imports: the counter is history arithmetic. A
scheduling bug must be debuggable in a database row, not in a prompt.
(Enforced by tests/test_lead_engine.py::test_worker_and_engine_contain_no_llm_machinery.)
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)

#: Consecutive "AI replied, customer wrote again" cycles before a lead is
#: escalated. Fixed, not tenant-configurable (see spec, non-goals).
ESCALATION_THRESHOLD = 3

#: A handover silences the AI. If no human picks the lead up within this
#: long, the AI resumes -- otherwise a misrouted escalation silently starves
#: the customer. Safety requirement, not a nicety.
HANDOVER_RESUME_HOURS = 24

#: Reminder window after the escalation email. NULL means "already reminded
#: or never armed" -- never "not yet".
REMINDER_DELAY = timedelta(hours=4)

_CLEARED_ON_EXIT = (
    "priority_since", "escalated_at", "escalation_reminder_at", "handover_sent_at",
)
```

- [ ] **Step 5: Implement the counter and priority**

Append to `lead_escalation.py`:

```python
async def _latest_outbound(db, lead) -> "object | None":
    row = (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == lead.channel_id,
                ChannelMessage.contact_phone == lead.contact_id,
                ChannelMessage.direction == "outbound",
            )
            .order_by(ChannelMessage.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    return row


def _clear_escalation_state(lead) -> None:
    for field in _CLEARED_ON_EXIT:
        setattr(lead, field, None)


def _recount(lead, previous_outbound_is_ai: bool | None) -> None:
    lead.ai_miss_count = (lead.ai_miss_count or 0) + 1 if previous_outbound_is_ai else 0


async def update_escalation_state(db, lead) -> None:
    """Update the counter, then recompute priority. The only writer of both.

    Call immediately after persisting an inbound ChannelMessage.
    """
    previous = await _latest_outbound(db, lead)
    _recount(lead, None if previous is None else bool(previous.is_ai))

    was_important = lead.priority == "important"
    now = datetime.now(timezone.utc)
    if (lead.ai_miss_count or 0) >= ESCALATION_THRESHOLD:
        if not was_important:
            # Entering: fresh escalation. Clearing here is what makes a
            # re-escalation send a second email instead of reading the stale
            # NULL reminder as "already handled".
            _clear_escalation_state(lead)
            lead.priority = "important"
            lead.priority_since = now
            await on_escalate(db, lead)
        return

    if was_important:
        lead.priority = "normal"
        _clear_escalation_state(lead)
```

Add imports for `ChannelMessage` from `..models`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py -q -k "counter or priority or first_contact"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/modules/channels/meta/lead_escalation.py services/api/app/modules/channels/models.py services/api/alembic/versions/20261013141000_add_channel_message_is_ai.py services/api/tests/test_lead_escalation.py
git commit -m "feat(leads): escalation counter and priority state machine"
```

---

## Task 4: Handover email + handover line

**Files:**
- Modify: `services/api/app/modules/channels/meta/lead_escalation.py`
- Test: `services/api/tests/test_lead_escalation.py`

- [ ] **Step 1: Write the failing recipient-resolution tests**

```python
@pytest.mark.asyncio
async def test_escalation_defaults_to_owner_signup_email(db, monkeypatch):
    from app.modules.channels.meta import lead_escalation

    sent: list[dict] = []

    async def _fake(email, subject, message, cta_url=None):
        sent.append({"to": email, "subject": subject})
        return "id-1"

    monkeypatch.setattr(lead_escalation, "_send_email", _fake)

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=1)
    recipients = await lead_escalation.resolve_recipients(db, lead)
    assert recipients == [f"{lead.tenant_id}@example.com"]
    assert sent == []      # resolution alone sends nothing
```

- [ ] **Step 2: Run to verify it fails**

Expected: `AttributeError: module ... has no attribute 'resolve_recipients'`.

- [ ] **Step 3: Implement recipient resolution and the email**

Append to `lead_escalation.py`:

```python
async def _send_email(to, subject, message, cta_url: str | None = None) -> str:
    """Indirection so tests can intercept without patching Resend internals."""
    from ...email.service import send_notification_email

    return await send_notification_email(to, subject, message, cta_url)


async def resolve_recipients(db, lead) -> list[str]:
    """Where the escalation goes.

    lead_settings.escalation_emails when set; otherwise the tenant owner's
    signup email. The fallback is a guaranteed-existing row (the consumer
    already relies on User.id == tenant_id for response_style), so escalation
    works with zero configuration.
    """
    from ...users.models import User

    configured = (
        await db.execute(
            select(User.lead_settings).where(User.id == lead.tenant_id)
        )
    ).scalar_one_or_none()
    emails = (configured or {}).get("escalation_emails") or []
    cleaned = [e.strip().lower() for e in emails if isinstance(e, str) and e.strip()]
    if cleaned:
        return cleaned

    owner_email = (
        await db.execute(
            select(User.email).where(User.id == lead.tenant_id)
        )
    ).scalar_one_or_none()
    return [owner_email] if owner_email else []


HANDOVER_TEXT = "Let me get my colleague to help you with this."
ESCALATION_SUBJECT = "A lead needs you: {name}"


async def on_escalate(db, lead) -> None:
    """Side effects on entering 'important'. Never raises.

    Cosmetically a best-effort handover plus one escalation email; neither may
    be able to break message handling, so every call is guarded.
    """
    now = datetime.now(timezone.utc)
    try:
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(lead.tenant_id, {
            "type": "notification",
            "notification": {
                "kind": "lead_escalated",
                "channel_id": lead.channel_id,
                "contact_id": lead.contact_id,
                "contact_name": lead.contact_name,
                "preview": "The AI could not resolve this conversation.",
            },
        })
    except Exception as e:
        logger.warning("escalation inbox event failed: %s", e)

    try:
        recipients = await resolve_recipients(db, lead)
    except Exception as e:
        logger.warning("escalation recipient lookup failed: %s", e)
        recipients = []

    if recipients:
        try:
            await _send_email(
                recipients,
                ESCALATION_SUBJECT.format(name=lead.contact_name or lead.contact_id),
                f"{lead.contact_name or lead.contact_id} kept writing after the AI replied "
                f"{lead.ai_miss_count} times. The AI has stopped replying so someone can take over.",
                cta_url=f"/dashboard/inbox?channel={lead.channel_id}&key={lead.contact_id}",
            )
            lead.escalated_at = now
            lead.escalation_reminder_at = now + REMINDER_DELAY
        except Exception as e:
            # escalated_at stays NULL; the sweep retries rather than pretending
            # the lead has been handed to a human.
            logger.warning("escalation email failed for lead %s: %s", lead.id, e)
```

- [ ] **Step 4: Run the tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/modules/channels/meta/lead_escalation.py services/api/tests/test_lead_escalation.py
git commit -m "feat(leads): escalation email with owner-signup default"
```

---

## Task 5: Handover line + AI suppression

**Files:**
- Modify: `services/api/app/modules/channels/meta/lead_escalation.py`
- Modify: `services/api/app/modules/channels/meta/consumer.py`
- Test: `services/api/tests/test_lead_escalation.py`

- [ ] **Step 1: Write the failing suppression test**

```python
def test_should_ai_reply_false_when_important():
    from app.modules.channels.meta.lead_escalation import should_ai_reply

    class L:
        priority = "important"
    assert should_ai_reply(L()) is False

    class N:
        priority = "normal"
    assert should_ai_reply(N()) is True
```

- [ ] **Step 2: Run to verify it fails**

Expected: `AttributeError`.

- [ ] **Step 3: Implement the predicate and the handover sender**

Append to `lead_escalation.py`:

```python
def should_ai_reply(lead) -> bool:
    """False while the thread is handed to a human."""
    return (lead.priority or "normal") != "important"


async def send_handover(db, lead, adapter, phone_number_id: str, token: str) -> None:
    """One holding line, then silence. Guarded by handover_sent_at so a
    re-trigger never repeats it."""
    if lead.handover_sent_at is not None:
        return
    try:
        await adapter.send_text_message(phone_number_id, token, lead.contact_id, HANDOVER_TEXT)
        lead.handover_sent_at = datetime.now(timezone.utc)
    except Exception as e:
        # Unset on failure: the thread still goes silent and the 24h resume
        # still applies. A failed cosmetic line must not block escalation.
        logger.warning("handover line failed for lead %s: %s", lead.id, e)


async def escalate_to_human(db, lead, adapter, phone_number_id: str, token: str) -> None:
    """Called by the consumer when a thread enters 'important'."""
    from .lead_engine import cancel_pending_actions

    await cancel_pending_actions(db, lead.channel_id, lead.contact_id, reason="escalated")
    await send_handover(db, lead, adapter, phone_number_id, token)
```

- [ ] **Step 4: Wire the consumer**

In `consumer.py::_handle_message_received`, after the reply is generated and
before sending, add:

```python
        # Handover: a thread escalated mid-conversation stops being answered
        # by the AI. The holding line goes out once, then silence.
        if lead is not None and not should_ai_reply(lead):
            await escalate_to_human(db, lead, adapter, phone_number_id, token)
            await db.commit()
            return
```

Where `lead` is the result of the `capture_lead` call in that function; capture
the returned lead in a local if it is currently discarded.

Also call `update_escalation_state(db, lead)` immediately after the inbound
`ChannelMessage` is persisted in `_handle_message_received` and
`_handle_instagram_message`, then `await db.commit()`.

- [ ] **Step 5: Mark AI-authored outbound rows**

Where the consumer writes its outbound `ChannelMessage` (WhatsApp and
Instagram), add `is_ai=True` to the constructor. Without this the counter never
increments.

- [ ] **Step 6: Run tests**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py tests/test_voice_and_followup.py tests/test_instagram_messaging.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/modules/channels/meta/lead_escalation.py services/api/app/modules/channels/meta/consumer.py services/api/tests/test_lead_escalation.py
git commit -m "feat(leads): hand escalated threads to a human, suppress AI"
```

---

## Task 6: Reminder + 24h resume sweep

**Files:**
- Create: `services/api/app/modules/channels/meta/escalation_worker.py`
- Modify: `services/api/app/workers/main.py`
- Test: `services/api/tests/test_lead_escalation.py`

- [ ] **Step 1: Write the failing sweep tests**

```python
@pytest.mark.asyncio
async def test_reminder_sends_once_then_stops(db, monkeypatch):
    from app.modules.channels.meta import lead_escalation

    sent: list[str] = []
    async def _fake(to, subject, message, cta_url=None):
        sent.append(subject); return "id"
    monkeypatch.setattr(lead_escalation, "_send_email", _fake)

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    await lead_escalation.update_escalation_state(db, lead)
    lead.escalation_reminder_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()
    sent.clear()          # drop the initial escalation; only count the reminder

    await lead_escalation.run_reminder_sweep(db)
    await db.commit()
    assert len(sent) == 1
    assert lead.escalation_reminder_at is None, "NULL = already reminded"

    await lead_escalation.run_reminder_sweep(db)
    await db.commit()
    assert len(sent) == 1, "must never remind twice"


@pytest.mark.asyncio
async def test_resume_after_24h(db, monkeypatch):
    from app.modules.channels.meta import lead_escalation

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    await lead_escalation.update_escalation_state(db, lead)
    assert lead.priority == "important"

    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=25)
    await db.commit()

    resumed = await lead_escalation.run_resume_sweep(db)
    await db.commit()
    assert resumed == 1
    assert lead.priority == "normal"
    assert lead.handover_sent_at is None
    assert lead_escalation.should_ai_reply(lead) is True


@pytest.mark.asyncio
async def test_resume_skips_when_human_replied(db):
    """A human reply resets the counter, which already drops priority -- the
    sweep must not then fire for a thread that was handled."""
    from app.modules.channels.meta import lead_escalation

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    await lead_escalation.update_escalation_state(db, lead)
    lead.ai_miss_count = 0
    await lead_escalation.update_escalation_state(db, lead)
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=25)
    await db.commit()

    assert lead.priority == "normal"
    assert await lead_escalation.run_resume_sweep(db) == 0
```

- [ ] **Step 2: Run to verify they fail**

Expected: `AttributeError`.

- [ ] **Step 3: Implement both sweeps**

Append to `lead_escalation.py`:

```python
async def run_reminder_sweep(db, limit: int = 50) -> int:
    """Send the single 4h reminder for leads still awaiting a human.

    Bounded and index-friendly: the partial index ix_leads_pending_reminder
    means this never walks more than the handful of rows actually due, so it
    is safe to call on every tick even at 50M leads.
    """
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(Lead)
            .where(
                Lead.priority == "important",
                Lead.escalation_reminder_at.isnot(None),
                Lead.escalation_reminder_at <= now,
            )
            .order_by(Lead.escalation_reminder_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    sent = 0
    for lead in rows:
        # A human reply already reset the counter and dropped priority.
        if lead.priority != "important":
            lead.escalation_reminder_at = None
            continue
        try:
            recipients = await resolve_recipients(db, lead)
            if recipients:
                await _send_email(
                    recipients,
                    ESCALATION_SUBJECT.format(name=lead.contact_name or lead.contact_id),
                    f"Still no reply on {lead.contact_name or lead.contact_id} "
                    f"after the escalation. The AI will resume in "
                    f"{HANDOVER_RESUME_HOURS}h if nobody picks it up.",
                    cta_url=f"/dashboard/inbox?channel={lead.channel_id}&key={lead.contact_id}",
                )
                sent += 1
        except Exception as e:
            logger.warning("escalation reminder failed for lead %s: %s", lead.id, e)
            continue          # leave the timestamp: retry next tick
        lead.escalation_reminder_at = None    # NULL = terminal, never again
    return sent


async def run_resume_sweep(db, limit: int = 50) -> int:
    """Hand threads back to the AI after HANDOVER_RESUME_HOURS with no human.

    Without this a misrouted escalation silently starves the customer.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HANDOVER_RESUME_HOURS)
    rows = (
        await db.execute(
            select(Lead)
            .where(
                Lead.priority == "important",
                Lead.handover_sent_at.isnot(None),
                Lead.priority_since.isnot(None),
                Lead.priority_since <= cutoff,
            )
            .limit(limit)
        )
    ).scalars().all()

    for lead in rows:
        lead.priority = "normal"
        _clear_escalation_state(lead)
        logger.info(
            "lead %s handed back to the AI: no human action within %sh",
            lead.id, HANDOVER_RESUME_HOURS,
        )
    return len(rows)
```

- [ ] **Step 4: Run the tests**

Expected: PASS.

- [ ] **Step 5: Create the worker loop**

Create `services/api/app/modules/channels/meta/escalation_worker.py`:

```python
"""Escalation sweep loop: 4h reminder + 24h handover resume.

Registered in app/workers/main.py alongside the other pollers. Ticks every 15s
to match the lead action worker; both sweeps are bounded and index-backed, so
a frequent tick costs a handful of index reads rather than a scan.
"""

import asyncio
import logging

from ....database import async_session

logger = logging.getLogger(__name__)

POLL_SECONDS = 15


async def run_escalation_sweeps() -> None:
    from . import lead_escalation

    while True:
        try:
            async with async_session() as db:
                await lead_escalation.run_reminder_sweep(db)
                await lead_escalation.run_resume_sweep(db)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Idempotent by column state -- next tick re-reads the same rows.
            logger.warning("escalation sweep failed: %s: %s", type(e).__name__, e)
        await asyncio.sleep(POLL_SECONDS)
```

- [ ] **Step 6: Register the loop**

In `app/workers/main.py`, in the `loops` dict, add:

```python
        "escalation-sweeps": run_escalation_sweeps,
```

and add the import beside the other worker imports:

```python
    from ..channels.meta.escalation_worker import run_escalation_sweeps
```

- [ ] **Step 7: Extend the no-LLM invariant test**

In `tests/test_lead_engine.py::test_worker_and_engine_contain_no_llm_machinery`, add
`"lead_escalation.py"` to the tuple of filenames scanned.

- [ ] **Step 8: Run tests**

Run: `cd services/api && python -m pytest tests/test_lead_engine.py tests/test_lead_escalation.py -q`
Expected: all pass, including the invariant test.

- [ ] **Step 9: Commit**

```bash
git add services/api/app/modules/channels/meta/lead_escalation.py services/api/app/modules/channels/meta/escalation_worker.py services/api/app/workers/main.py services/api/tests/test_lead_engine.py services/api/tests/test_lead_escalation.py
git commit -m "feat(leads): escalation reminder and 24h resume sweeps"
```

---

## Task 7: Settings + API surface

**Files:**
- Modify: `services/api/app/modules/channels/meta/lead_engine.py` (`normalize_lead_settings`)
- Modify: `services/api/app/modules/channels/leads.py`
- Test: `services/api/tests/test_lead_escalation.py`

- [ ] **Step 1: Add the setting to the normaliser**

In `lead_engine.py`, add to `SETTINGS_DEFAULTS`:

```python
    "escalation_emails": [],
```

and to `normalize_lead_settings`, clamp to a de-duplicated lowercased list of
strings:

```python
    raw_emails = raw.get("escalation_emails") if isinstance(raw, dict) else None
    emails = (
        [e.strip().lower() for e in raw_emails if isinstance(e, str) and e.strip()]
        if isinstance(raw_emails, list) else []
    )
    settings["escalation_emails"] = sorted(set(emails))[:10]
```

- [ ] **Step 2: Expose priority on the list endpoint**

In `leads.py`, add `priority` to the response schema and to the select, and
support an optional `?priority=` filter mirroring the existing `stage` filter.

- [ ] **Step 3: Test the normaliser**

```python
def test_normalize_clamps_escalation_emails():
    from app.modules.channels.meta.lead_engine import normalize_lead_settings

    s = normalize_lead_settings({"escalation_emails": [" A@X.com ", "a@x.com", 5, ""]})
    assert s["escalation_emails"] == ["a@x.com"]

    assert normalize_lead_settings(None)["escalation_emails"] == []
```

- [ ] **Step 4: Run tests and commit**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py -q`
Expected: PASS.

```bash
git add services/api/app/modules/channels/meta/lead_engine.py services/api/app/modules/channels/leads.py services/api/tests/test_lead_escalation.py
git commit -m "feat(leads): escalation_emails setting and priority in API"
```

---

## Task 8: Frontend

**Files:**
- Modify: `apps/web/lib/api-leads.ts`
- Modify: `apps/web/components/leads/LeadsBoard.tsx`
- Modify: `apps/web/components/dashboard/tabs/LeadsTab.tsx` (delete mock)
- Modify: `apps/web/components/dashboard/ChannelWorkspace.tsx`
- Delete: `apps/web/components/dashboard/tabs/LeadsTab.tsx`

- [ ] **Step 1: Add `priority` to the type**

In `apps/web/lib/api-leads.ts`, add to `LeadOut`:

```ts
  /** "normal" | "important" — set by the backend when the AI could not resolve the thread. */
  priority: "normal" | "important";
  /** ISO timestamp of when it became important; null otherwise. */
  priority_since?: string | null;
```

- [ ] **Step 2: Delete the fake mock**

Delete `apps/web/components/dashboard/tabs/LeadsTab.tsx` and remove its render
from `ChannelWorkspace.tsx:175-179`, replacing it with the real
`LeadsBoard` used elsewhere.

- [ ] **Step 3: Add the badge to the real board**

In `LeadsBoard.tsx`, render a badge in the lead row. Use existing tokens, no new
colour language:

```tsx
{lead.priority === "important" && (
  <span
    title={lead.priority_since ? `Escalated ${formatAge(lead.priority_since)}` : "Escalated"}
    className="shrink-0 rounded-full bg-coral/10 px-2 py-0.5 text-[11px] font-semibold text-coral"
  >
    Important
  </span>
)}
```

Add a `formatAge` helper rendering `"6h"` / `"2d"`. Add a sort toggle and a
filter chip that sends `?priority=important`. Cover the states from the spec:
explicit "nothing escalated" when the filtered list is empty, skeleton while
loading, and "unknown" (never a stale value) when the fetch fails.

- [ ] **Step 4: Verify**

Run: `cd apps/web && npx tsc --noEmit`
Expected: no errors outside `.next`.

Run: `cd apps/web && npx eslint lib/api-leads.ts components/leads/LeadsBoard.tsx`
Expected: clean.

Run: `cd apps/web && npm run build`
Expected: `✓ Compiled successfully`.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/api-leads.ts apps/web/components/leads/LeadsBoard.tsx apps/web/components/dashboard/ChannelWorkspace.tsx
git add -A apps/web/components/dashboard/tabs/
git commit -m "feat(web): lead priority badge, delete fake hot/warm/cold mock"
```

---

## Task 9: Verify indexes are used

**Files:** none (verification only)

- [ ] **Step 1: Explain the board query**

Run the board query against Postgres with `EXPLAIN (ANALYZE, BUFFERS)`:
`SELECT * FROM leads WHERE tenant_id = 'x' ORDER BY priority DESC, updated_at DESC LIMIT 50;`
Expected: `Index Scan using ix_leads_tenant_priority`, no `Sort` node over a full scan.

- [ ] **Step 2: Explain the reminder sweep**

Run: `EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM leads WHERE priority='important' AND escalation_reminder_at IS NOT NULL AND escalation_reminder_at <= now() ORDER BY escalation_reminder_at ASC LIMIT 50;`
Expected: `Index Scan using ix_leads_pending_reminder`.

If Postgres reports a sequential scan, the partial index was not created —
check `op.execute` ran and that the working copy is Postgres, not SQLite.

- [ ] **Step 3: Full test run**

Run: `cd services/api && python -m pytest tests/test_lead_escalation.py tests/test_lead_engine.py tests/test_voice_and_followup.py tests/test_instagram_messaging.py tests/test_reviews_worker.py -q`
Expected: all pass.

---

## Out of scope (separate specs)

- Voice-call escalation.
- `ix_lead_actions_due` partitioning (it is not tenant-scoped, so one tenant's
  backlog starves others).
- `event_outbox` pruning.
- Queueing outbound escalation email for burst traffic.
- Read replicas.
