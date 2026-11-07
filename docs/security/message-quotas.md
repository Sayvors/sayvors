# Message quota enforcement

Last updated: 2026-11-07.

## What is limited

Every plan carries `max_messages_per_month` (nullable = unlimited). The count
is **outbound messages per tenant per calendar month** — the same number the
inbox send path has always used. Inbound messages are never counted; they are
what the quota protects the business from answering.

## Where it is enforced

1. **Manual sends** (`/api/v1/inbox/send*`) — `_ensure_messaging_quota` returns
   429 with `X-Entitlement-Denied: quota` once the limit is reached.
2. **AI auto-replies** (WhatsApp and Instagram, `channels/meta/consumer.py`) —
   the gate runs before any model work. The inbound message is still stored
   and published to the inbox; only the generated reply is withheld. The
   inbound row is marked `ai_reply_status = skipped` with
   `Monthly message limit reached` for the operator.
3. **LLM gateway** — `check_feature("ai_replies")` still applies; a plan
   without the AI feature never reaches the provider.

## Counting path

`billing/quotas.py`:

- `count_messages_this_month` (DB) is the source of truth.
- `get_message_usage` memoises it in Redis for **30 seconds**, so a burst of
  inbound messages performs at most one COUNT.
- `invalidate_message_usage` is called after a successful manual send, so the
  next inbound check sees the new message immediately.
- Redis failure falls back to the database; a quota lookup failure in the
  inbound path **fails open** (a customer message must never be dropped
  because billing is unavailable). Manual sends remain protected by the DB.

## Tenant visibility

- `GET /api/v1/billing/entitlements` returns `max_messages_per_month`,
  `messages_used_this_month`, `messages_remaining`.
- The dashboard renders `UsageBanner` under the header from **90% usage**:
  amber "Running low" with the remaining count, red "Message limit reached"
  once exhausted, always with a link to the plans page. There is no
  self-serve top-up yet; the plans page carries the Enterprise contact.

## Invariants

- Suspension (tenant lifecycle) and message quota are independent: a
  suspended workspace is blocked at auth; a quota-exhausted workspace still
  receives and stores messages.
- The 30-second cache only affects *when* the limit is noticed, not the
  ledger: the DB count is authoritative and the cache expires.
- Never move the gate after the LLM call; that would spend credit and then
  discard the answer.
