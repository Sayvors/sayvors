# Meta delivery reconciliation

Last updated: 2026-11-07.

## What Meta provides

Meta has **no message-count API** for WhatsApp, Instagram or Facebook
Messenger. The provider-side data is:

- `messages` webhooks — one event per inbound message.
- `statuses` webhooks — `sent` → `delivered` → `read` / `failed` per outbound
  message id (wamid).
- WhatsApp WABA **conversation analytics** — billable 24-hour conversations by
  category, not a message count.

Our database is therefore not an independent count: it is built from the same
events. The only way to compare is to show what Meta confirmed alongside what
we stored, and explain the gap.

## Storage

`channel_messages` keeps the latest status plus the first time each transition
was observed:

- `status` — `sent` | `delivered` | `read` | `failed` (latest accepted event).
- `delivered_at` — first `delivered` or `read` webhook.
- `read_at` — first `read` webhook.
- `failed_at` — first `failed` webhook.

Transitions are monotonic: a redelivered/out-of-order event never moves a
timestamp forward, and `read` is terminal (a later `delivered` is ignored).

`sent` means "Meta accepted the send, no delivery receipt yet". It is the
number to watch when webhooks break.

## Admin endpoint

`GET /api/v1/admin/tenants/{id}/delivery?days=30` returns:

- `totals`: inbound, outbound, outbound_with_id, outbound_without_id, sent,
  delivered, read, failed, delivery_rate_pct.
- `by_channel`: the same breakdown per connected Meta channel.
- `daily`: the same breakdown per UTC day.

Only `whatsapp`, `instagram`, and `facebook` channels are included; Google
review threads are not Meta delivery.

`delivery_rate_pct = (delivered + read) / outbound_with_id`. Messages without
a wamid are excluded from the denominator — Meta never saw them.

## Why the numbers can differ from Meta

- A missed webhook leaves our row at `sent` (or missing for inbound).
- A send rejected before Meta issued a wamid exists only in our database.
- Messages sent from the WhatsApp Business app rely on the coexistence echo.
- Meta retries webhooks; we dedupe by message id.
- Deleted messages keep their row in our database.
- Conversation analytics counts 24-hour windows, not messages: ten messages in
  one window are one billable conversation.

## Performance

The reconciliation uses two grouped queries in a bounded window:

- per channel + direction + status;
- per day + direction + status.

Both are served by `ix_channel_messages_channel_created` and the partial
`ix_channel_messages_outbound_status (channel_id, status, created_at) WHERE
direction = 'outbound'`. No per-message loop; cost is proportional to the
aggregate, not to the tenant's total history. `days` is capped at 365.
