# Top-up and plan requests

Last updated: 2026-11-07.

## Why requests exist

No payment gateway is connected. Self-serve checkout would be a fake UI, so a
tenant submits a request and an operator approves it. Approval applies the
purchase through the same billing path as a manual admin grant.

## Tenant surface

`/dashboard/billing/topup`:

- WhatsApp messages: presets 500 / 1000 / custom.
- AI credit: $10 / $25 / $50 / $100 / custom.
- Channels: 1 / 3 / 5 / custom.
- Enterprise plan: request button.
- Optional note for the operator; recent requests with status.

Endpoints:

- `POST /api/v1/billing/requests` — `kind` (`messages` | `channels` |
  `ai_credit` | `plan`), `amount`, `plan_slug`, `note`.
- `GET /api/v1/billing/requests` — the tenant's own history.

Duplicate guard: an identical pending request from the same tenant within 24
hours returns the existing row with `duplicate: true` instead of piling up.

## Admin surface

`/requests` in the admin console, plus:

- `GET /api/v1/admin/requests?status=pending`
- `POST /api/v1/admin/requests/{id}/approve`
- `POST /api/v1/admin/requests/{id}/reject`

Approval applies:

| Kind | Effect |
|---|---|
| `messages` | Adds the amount to `tenant_subscriptions.message_bonus`. The effective WhatsApp allowance is always `plans.max_messages_per_month + message_bonus`, so a later plan change keeps the pack without pinning the tenant to an old absolute limit. Invalidates the message-usage cache. |
| `channels` | Adds to `channels_bonus`; effective limit is `plans.max_channels + channels_bonus`. |
| `ai_credit` | `grant_credit()` with idempotency key `billing-request:{id}` — double approval cannot double-grant. |
| `plan` | Sets the subscription to the requested plan; no fake charge. |

The row is locked (`FOR UPDATE`), can only be decided once, records the
operator/time/note, and sends the tenant a bell notification. Every admin
mutation is also captured by the admin audit middleware.

## Invariants

- Approval never takes money; it only records an already-agreed sale.
- Allowances are additive and per-tenant; the plan catalog is untouched.
- A request can never be applied twice, even by two operators at once.
- Prices are selected by the operator, not trusted from the browser.
