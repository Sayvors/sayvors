# Per-conversation context — customers shared one AI history window — FIXED 2026-10-14

Goal: every conversation gets its own AI state. The reply model had been fed
the last N messages **for the whole channel**, not for the customer actually
texting.

**Status: DONE 2026-10-14.** Fixed in `meta/consumer.py`, regression tests in
`tests/test_conversation_context_scoping.py`. Not yet deployed.

## The bug that was reported — root cause

Symptom: a customer writes in English, the AI replies in Arabic, because a
*different* customer on the same WhatsApp number had been writing in Arabic.

`_generate_reply` selected history with:

```python
select(ChannelMessage).where(ChannelMessage.channel_id == channel.id)
                      .order_by(ChannelMessage.created_at.desc())
                      .limit(_HISTORY_MESSAGES)   # 10
```

**No `contact_phone` filter.** Every customer on that number shared one
10-message window.

### The original theory was close but pointed at the wrong place

The hunch was stale per-conversation *language state*. That state was always
correct and already scoped per contact:

- `WhatsAppThreadState` is keyed `UniqueConstraint(channel_id, contact_phone)`.
- `classify_thread` (`thread_stats.py`) filters by `contact_phone`.

Nothing needed clearing or resetting. The bug was the history window the reply
is generated from.

### It was also a privacy incident, not just a language bug

The same window went into the LLM prompt, so when customer A wrote, the prompt
contained customer B's messages and our replies to them — names, orders,
addresses, complaints — and the model could echo them back. Anything the LLM
provider retains had seen it.

## What was changed

- [x] **History scoped per contact.** `_generate_reply` takes a new `contact`
      parameter (WhatsApp phone / IGSID) and filters on
      `ChannelMessage.contact_phone == contact`. The column is designed for
      this — per `channels/models.py`, inbound rows carry the SENDER and
      outbound rows the RECIPIENT, "which is what lets a reply be threaded
      under the same contact as the question it answers". Verified both sides
      are populated on the WhatsApp *and* Instagram paths.
- [x] **Both call sites pass the contact**: `contact=from_wa or None` in
      `_handle_message_received`, `contact=igsid or None` in
      `_handle_instagram_message`.
- [x] **Unknown contact ⇒ empty history, never channel-wide.** Falling back to
      the channel-wide query would BE the leak, so it degrades to no history
      plus the business card and system prompt, which still yields a sane
      first-contact reply. Logged as a warning so the cause is diagnosable.
- [x] **NULL `contact_phone` rows excluded.** Rows predating the column cannot
      be attributed to a person, so they never enter any context rather than
      being guessed at. (Decision taken here; no backfill.)
- [x] **Regression tests** in `tests/test_conversation_context_scoping.py`,
      pinned at the provider boundary by capturing the `LLMRequest` — so they
      assert on the prompt we built, not on model behaviour. 5 tests: the
      reported Arabic case, outbound threading, unknown contact, NULL rows, and
      first-ever message.

The tests were verified to **fail against the old code** (4 of 5, with explicit
`LEAK:` assertions) before the fix was confirmed — a regression test that passes
against the bug proves nothing.

## Scope check (audited all 14 `select(ChannelMessage)` in `app/`)

- `consumer.py` `_generate_reply` — **was the leak.** Now fixed.
- `thread_stats.py:129` `classify_thread` — always correct, filters contact.
- `lead_escalation.py:91` `_latest_outbound` — always correct, filters contact.
- `service.py:401` — channel-wide on purpose: the tenant's own inbox listing,
  tenant-scoped and paginated. Not a leak.
- `service.py:548` / `625` — build `*conditions` dynamically per thread.
- `analytics/messaging_rollup.py:101` — aggregate counts; channel-wide is intent.

So this was one query, not a pattern. `classify_thread` is the reference shape.

## Tests

`tests/test_conversation_context_scoping.py` — 5 tests, passing against the
repo's own `conftest.py`. Captures the `LLMRequest` at the provider boundary, so
it asserts on the prompt we built, not on model behaviour.

Verified to **fail against the old code** (4 of 5, with explicit `LEAK:`
assertions) before the fix was accepted.

## Notes

- `_HISTORY_MESSAGES = 10` is now a per-customer budget rather than a shared
  one. 10 turns per customer is generous; worth revisiting, not urgent.
- Don't scope this by `created_at > <first message of this contact>` — that
  silently truncates long-lived threads. Filter by contact and keep the window.
- Not deployed. Full backend suite run locally: 64/64 on these files, plus
  71/71 on the consumer/Instagram/lead-engine suites most at risk from the
  signature change.