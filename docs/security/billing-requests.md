# Top-up and plan requests

Last updated: 2026-11-28.

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
The read is a convenience, not the invariant: the partial unique index
`uq_billing_requests_pending_dedupe` on
`(tenant_id, kind, COALESCE(amount, -1), COALESCE(plan_slug, '')) WHERE status
= 'pending'` (migration `20261118130000`) is the arbiter. `create_request()`
locks the tenant's user row so check-then-insert cannot interleave; a losing
insert is caught at a savepoint and translated into the same duplicate answer.
Submission is also bounded twice: 10 requests per minute per tenant at the
route, and at most 5 open requests per tenant in the operator queue.

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
| `plan` | Switches the subscription and `users.plan` through `apply_plan_change()`, grants the target plan's `included_credit_cents` once when the plan changes, writes a `plan_grant` event keyed `billing-request-plan:{id}`, and syncs Redis after commit. Bonus allowances are untouched so they stack on the new base. No fake charge. |

Approving any non-credit kind also writes a zero-amount `BillingEvent` with
idempotency key `billing-request-decision:{id}` — a dated audit snapshot of
what was decided, by whom and at what wallet balance. It never moves the
balance. `ai_credit` already writes its own event through `grant_credit()` with
the `billing-request:{id}` key; a rejection writes neither. A commit that
loses that unique key is read back as an already-approved request instead of a
500.

The row is locked (`FOR UPDATE`), can only be decided once, records the
operator/time/note, and sends the tenant a bell notification. Every admin
mutation is also captured by the admin audit middleware.

## Invariants

- Approval never takes money; it only records an already-agreed sale.
- Allowances are additive and per-tenant; the plan catalog is untouched.
- A request can never be applied twice, even by two operators at once.
- The subscription and `users.plan` cannot disagree after a plan approval.
- A plan change grants its included credit exactly once; same-plan reapplication,
  retries and concurrent decisions cannot grant it twice.
- One pending row per (tenant, kind, amount, plan) is a database constraint,
  not just a read-time courtesy; the operator queue is capped at five.
- Prices are selected by the operator, not trusted from the browser.

## Enterprise sales notification

Enterprise is sales-assisted, so a new request also emails the people who will
follow up. The email carries the workspace owner's business name, email and
phone, the submitting user when it was an employee, the plan, the note, the
request id/time and a link to Admin -> Requests.

How it is implemented:

- Recipients live in `enterprise_request_recipients` (migration
  `20261117100000`), platform-level state, not tenant-scoped. Addresses are
  validated and stored lowercase; a unique index makes duplicates a 400 rather
  than a second row. The list is capped at 25 on write and again on read, so
  one request can never fan out without bound.
- Admin API: `GET`/`POST`/`DELETE`
  `/api/v1/admin/billing/enterprise-recipients`, behind `require_admin` and the
  admin rate limit. Mutations are recorded by the existing admin audit
  middleware. There is no tenant-facing way to read or edit the list.
- Delivery is outbox-only (`send_notification_email` -> `email_outbox`); the
  request returns as soon as the rows exist and the worker owns retries. Each
  row's idempotency key is `enterprise-request:{request_id}:{address}`, so a
  retried POST cannot mail twice. The 24-hour duplicate guard already returns
  before the hook.
- Failures are isolated: one bad address is logged and skipped, the remaining
  addresses still send. An empty list logs a warning and leaves the in-app
  admin bell as the fallback; it never fails the tenant's request.

Invariants:

- Tenant contact data goes only to operator-configured, admin-authenticated
  addresses.
- A tenant cannot trigger more than one Enterprise notification batch per
  24 hours (the plan request dedupe key is identical for every Enterprise
  request).
- A notification failure never changes the request's status or blocks it.
