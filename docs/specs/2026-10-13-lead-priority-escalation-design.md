# Lead Qualification Gate + Importance Escalation

Date: 2026-10-13
Status: design approved, not yet implemented
Area: `services/api/app/modules/channels/` (lead pipeline), `apps/web/app/dashboard/` (leads UI)

## Problem

Two defects in the lead pipeline, both discovered while auditing how leads are
selected.

**1. Every conversation is treated as a sales lead.** `capture_lead()`
(`lead_engine.py:255`) upserts a `Lead` on every inbound WhatsApp/Instagram DM
with no filter, no threshold and no rejection path. Someone types "hello" and a
lead row exists.

The only qualification signal is `stage`: `new -> qualified`
(`lead_engine.py:363`) when `intent` or `request` is present — from either the
buying-word regex (`detect_intent`, `lead_engine.py:237`) or the LLM's silent
`LEAD: {...}` line (`LEAD_PROMPT_BLOCK`, `lead_engine.py:32`).

The defect is that **qualification is never used as a gate**. `schedule_followup`
(`lead_engine.py:474`) refuses only on `enabled=False`, `max_attempts < 1`,
`opt_out`, or `stage in ("converted","lost")`. The actual trigger for a
three-message sales sequence is `is_open_question()`
(`lead_engine.py:248`) — a trailing `?` or `؟` on the AI's own reply.

Net effect: a customer who says "hello", receives an AI reply ending in a
question, and never mentioned buying anything, receives three sales nudges
across 72 hours. That is the fastest route to a reported or blocked number.

**2. The AI cannot tell you when it is failing.** Nothing measures whether the
customer is satisfied. When the AI replies and the customer keeps writing, that
is a strong signal the bot is not resolving the conversation — but it is
recorded nowhere, surfaced nowhere, and pulls in no human.

## Goals

1. Never send a sales follow-up sequence to an unqualified lead.
2. Detect "AI answered, customer wrote again" after 3 consecutive cycles, stop
   the AI, and pull a human in by email.
3. Self-heal: if no human acts within 24 hours, the AI resumes.
4. Make priority a real, sortable, indexable field on the leads board.
5. Remove the fake hot/warm/cold score UI that implies a ranking system does not
   exist.

## Non-goals

Explicitly out of scope, for a later spec:

- **Voice escalation.** The intent is that an unanswered Important lead will
  eventually be phoned by an automated call. Not now; the email path is built so
  that a future channel slots in beside it without changing lead state.
- Lead ownership / human assignment.
- Per-member escalation routing.
- Tenant-configurable threshold (the value 3 is fixed in this spec).
- Scale hardening that is not caused by this feature: partitioning
  `ix_lead_actions_due`, pruning `event_outbox`, Redis/Kafka single-instance,
  read replicas, and queueing outbound email. Tracked separately; the index work
  *this* feature requires is specified below.

## Constraints carried from the existing design

- **No LLM in the decision path.** `lead_action_worker.py:155` declares that
  `_process_action` "contains no model/LLM imports and must never gain any",
  and `tests/test_lead_engine.py:585` enforces it by scanning
  `lead_engine.py` and `lead_action_worker.py` for `llm`,
  `resolve_tenant_model`, `provider.complete` and `_generate_reply`.
  The escalation counter is history arithmetic and must stay that way: a
  scheduling bug must be debuggable in a database row, not in a prompt.
- **No migration for new tenant knobs.** Settings ride the existing
  `lead_settings` JSON column, validated by `normalize_lead_settings`.
- **Cosmetics must never break message handling.** Every new call is guarded.

## Data model

Added to `leads` (migration on top of `20261013120000`):

| Column | Type | Default | Purpose |
|---|---|---|---|
| `ai_miss_count` | Integer | 0, not null | Consecutive AI-replied-then-customer-wrote cycles |
| `priority` | Enum `lead_priority` (`normal`,`important`) | `normal`, not null | Sortable, indexable escalation state |
| `priority_since` | DateTime(tz) | null | When it became important; drives the 24h resume |
| `escalated_at` | DateTime(tz) | null | Escalation email sent |
| `escalation_reminder_at` | DateTime(tz) | null | When to remind; **null means never/ already done** |
| `handover_sent_at` | DateTime(tz) | null | Holding line already delivered (idempotency) |

Indexes:

```sql
-- Board sort: WHERE tenant_id = ? ORDER BY priority DESC, updated_at DESC
CREATE INDEX ix_leads_tenant_priority
    ON leads (tenant_id, priority, updated_at DESC);

-- Reminder sweep, cross-tenant. Partial so Postgres only ever walks the
-- handful of rows awaiting a reminder, never the full lead table.
CREATE INDEX ix_leads_pending_reminder
    ON leads (escalation_reminder_at)
    WHERE priority = 'important';
```

The partial index is the single most important line here. The sweep is the only
query in this feature that is not tenant-scoped; without it, a 15s poll scans
every lead row in the system.

Tenant setting, inside `lead_settings`:

```json
{ "escalation_emails": ["sales@example.com", "owner@example.com"] }
```

**Default recipient.** When `escalation_emails` is absent or empty, the
escalation goes to the tenant owner's signup email: the `User.email` where
`User.id == lead.tenant_id`. This is a guaranteed-existing row, not optional
config — the consumer already relies on that identity for `response_style`
(`consumer.py`, `select(User).where(User.id == tenant_id)`). Escalation
therefore works on day one with zero setup, and a tenant that adds recipients
keeps the owner implicitly unless they clear the list.

## Behaviour

### 1. The counter

Evaluated on inbound only, in `consumer.py`, immediately after the inbound
`ChannelMessage` is persisted:

- Look at the most recent outbound message in the thread.
- If it exists and was AI-authored, `ai_miss_count += 1`.
- Otherwise (`no outbound yet`, or a **human** authored the last one),
  `ai_miss_count = 0`.

"AI-authored" is decided structurally, not by heuristics: the consumer writes
outbound `ChannelMessage` rows itself, so the flag is set on the row it creates.
A message sent by a human from the dashboard inbox does not set it. This must
be a stored boolean on `channel_messages`, not a string comparison against
content.

### 2. Priority

Recomputed in exactly one place, in both directions:

```
priority = 'important'  if ai_miss_count >= 3 else 'normal'
```

`ai_miss_count` is the only input that ever moves `priority`. The timestamps are
bookkeeping and are never read to decide priority. This keeps a single writer, so
the two fields cannot drift: fixing the counter logic corrects priority
automatically.

On **entering** `important`, stamp `priority_since = now()` and clear
`escalated_at`, `escalation_reminder_at` and `handover_sent_at` to `NULL`.

On **leaving** `important` (counter fell back below the threshold, or the 24h
resume fired), clear all four: `priority_since`, `escalated_at`,
`escalation_reminder_at`, `handover_sent_at`.

This matters for re-escalation. Without clearing, a lead that de-escalates and
later becomes Important again would find `escalation_reminder_at IS NULL` and
silently receive **no email at all** — the reminder would read as already
handled. Clearing on exit makes every escalation a fresh cycle.

### 3. Handover — the AI stops

On the transition into `important`:

1. `cancel_pending_actions(channel_id, contact_id, reason="escalated")` so no
   scheduled nudge fires into a thread that is now silent.
2. Send one holding line — e.g. *"let me get my colleague to help with this."*
   Set `handover_sent_at`. Guarded by that column, so a re-trigger never sends
   it twice.
3. Suppress all further AI replies for this thread while `priority =
   'important'`.

### 4. Resume after 24h

A worker sweep reads
`priority='important' AND priority_since <= now() - 24h AND handover_sent_at IS NOT NULL`.

- If a human has replied since escalation, the lead already dropped to `normal`
  via counter reset — nothing to do.
- Otherwise: resume AI replies, set `priority='normal'`, and clear
  `priority_since`, `escalated_at`, `escalation_reminder_at` and
  `handover_sent_at`.

**This is a safety requirement, not a nicety.** While a lead is Important the AI
is silent. If the escalation email is misrouted or the recipient is unavailable,
the customer receives nothing. The 24h resume converts that silent-failure risk
into self-healing.

### 5. Escalation email

On transition into `important`:

- Recipients: `lead_settings.escalation_emails`, or the owner's signup email
  when empty.
- Send via the existing `send_notification_email(to, subject, message, cta_url)`
  (`app/modules/email/service.py:410`, Resend-backed). `cta_url` deep-links to
  the thread in the inbox.
- Set `escalated_at = now()` and `escalation_reminder_at = now() + 4h`.

Reminder sweep (`escalation_reminder_at IS NOT NULL AND <= now()`):

- If a human has replied, the counter reset already dropped priority; skip.
- Otherwise send **one** reminder, then set `escalation_reminder_at = NULL`.
  `NULL` is the terminal "already reminded" marker — this is why the column is
  nullable rather than a boolean.
- No further email. Escalation is deliberately bounded to avoid the reminder
  habit that gets notification channels muted.

### 6. De-escalation

Any human outbound message resets `ai_miss_count` to `0`, which drops priority
back to `normal` on the next inbound evaluation. To reactivate a handover
thread, a human must reply — that is the intended semantic.

### 7. The qualification gate

`schedule_followup` (`lead_engine.py:474`) additionally refuses unless
`lead.stage == "qualified"`.

This is independent of everything above: one condition, separately revertible.
Existing tenants with unqualified-but-following leads stop receiving sequences
immediately on deploy, which is the intent.

## UI

**Leads board** (`apps/web/components/leads/LeadsBoard.tsx`): priority column
and badge, sortable, with a filter. Rendered from the real `priority` field.

**Delete the mock.** `apps/web/components/dashboard/tabs/LeadsTab.tsx:11-24`
holds a hardcoded `leadsData` array — `score: 92/85/78/68/55/45`,
`status: "hot"|"warm"|"cold"`, tags like `"high-intent"` — with **zero fetch
calls**, still rendered by `ChannelWorkspace.tsx:175-179`. It implies a ranking
system that has never existed. It is removed and replaced with the real value.

State coverage for the new column and badge:

| State | Behaviour |
|---|---|
| No escalated leads | Explicit "nothing escalated" row, not an empty table |
| Loading | Skeleton rows matching board shape |
| Fetch failure | Inline error with retry; priority shows "unknown", never a stale or optimistic value |
| Email send failed | Surfaced on the lead; `escalated_at` still set so the reminder can recover. Never silently swallowed. |
| Escalated, awaiting human | Badge plus `priority_since` age ("6h") |
| Resumed after 24h | No badge; the audit trail is in `priority_since` history, not the UI |

Aesthetic direction is inherited from the existing board — no new visual
language. Priority badge uses the existing semantic tokens (`coral` for
important, neutral `ink/40` for normal) rather than introducing a colour.

## Data flow

```
inbound WhatsApp/Instagram DM
  -> consumer persists ChannelMessage
  -> escalation counter updated (one place)
  -> priority recomputed from counter (one place)
       |
       +-- became 'important' --------------------------+
       |     cancel_pending_actions(reason="escalated")   |
       |     send holding line (once, guarded)            |
       |     escalate_email -> escalated_at, reminder+4h |
       |                                                   |
       +-- stayed/became 'normal'                         |
             reset handover state if it was important      |
                                                           |
reply attempt (WhatsApp + Instagram)                      |
  -> if priority == 'important': skip AI reply             |
                                                           |
lead_action_worker (15s poll)                              |
  -> claim pending actions, guards unchanged               |
  -> schedule_followup now requires stage == 'qualified'  |
                                                           |
escalation_sweeper (15s poll, in worker process) -----------+
  -> partial index: reminder due?      -> send once, null it
  -> important > 24h, no human reply  -> resume AI, normalise
```

## Error handling

| Failure | Behaviour |
|---|---|
| Email provider rejects | Log; `escalated_at` still set so the 4h reminder retries. Never blocks the message path. |
| Resend rate-limited (burst after an outage) | Same as above; reminder absorbs it. Escalation volume is unbounded by design, so the partial index keeps the sweep cheap even when many leads escalate at once. |
| Holding line send fails | `handover_sent_at` unset; thread goes silent anyway. Logged, and the 24h resume still applies. Deliberate: a failed cosmetic line must not block escalation. |
| Sweep crashes | Idempotent by column state; next tick re-reads the same partial index. |
| Counter computed wrong | Priority self-corrects on the next inbound; there is no second writer to disagree with it. |

## Testing

- Counter: human-reply resets; AI-reply increments; first contact is 0;
  non-text messages do not increment.
- Threshold: exactly 3 escalates, 2 does not; dropping back below 3 de-escalates.
- Re-escalation: important -> normal -> important sends a **second** escalation
  email and arms a fresh reminder (guards the state-clearing regression above).
- Handover: holding line sent exactly once across repeated triggers; AI replies
  suppressed while important; suppressed again after resume.
- Resume: fires at 24h, skipped if a human replied in the meantime.
- Email: sends to the configured list; **falls back to the owner's signup email
  when the list is empty**; reminder sends once then never again.
- Gate: `schedule_followup` refuses for `stage="new"`, allows `"qualified"`.
- Migration: upgrades on a populated table; `DEFAULT 'normal'` backfills
  existing rows.
- Index: `EXPLAIN` on the board query and the sweep shows index usage, not a
  sequential scan.

## Open risks

- **The AI genuinely goes silent.** Acknowledged and bounded to 24h by the
  resume, but during that window an unstaffed tenant's escalated customers
  receive nothing. Mitigation is the owner-default recipient list, which is
  populated without configuration.
- **Threshold 3 may be low.** A customer asking three genuine clarifying
  questions in a row will escalate without being dissatisfied. Acceptable: the
  cost is one email and a handover, and the resume bounds the silence.
- **Burst escalation.** A provider outage can push thousands of leads to
  Important simultaneously. Emails are not rate-limited by this spec; the
  reminder absorbs rejects. Queueing outbound email is deliberately deferred to
  the scale spec, and is the right place to fix it.
