# Email delivery (production path)

Last updated: 2026-11-07.

## Architecture

Requests never call Resend. They write an `email_outbox` row; a worker sends it.

```
API handler → enqueue_email() → email_outbox(status=queued)
                                   │
                    email-outbox worker (bounded concurrency)
                                   │
                    Resend API ──→ provider_id
                                   │
                 webhook (Svix) → email_events + suppression
```

- `email_outbox` — one row per email; `idempotency_key` is unique.
- `email_events` — queued / sent / delivered / bounced / complained /
  unsubscribed / failed / suppressed, deduped by Svix id.
- `email_suppressions` — addresses that must never receive another email.

## Retry policy

- Transient: HTTP 429, 5xx, timeout, connection error.
- Backoff: 1m → 5m → 30m → 2h → 6h; then `dead`.
- Permanent: 4xx (invalid recipient, rejected payload) → `dead` immediately.
- A worker crash after claiming leaves a row in `sending`; the row is retried
  when its `next_attempt_at` passes (the claim query only takes due rows).
- **Every** email is idempotent at the provider too (`Idempotency-Key` header).

## Suppression

Checked before enqueue and updated by the webhook:

- `bounced` (hard) and `complained` → suppress immediately, stop sending.
- `unsubscribed` (one-click link) → suppress and set `users.newsletter=false`.

Review-request and newsletter emails carry:

- `List-Unsubscribe`
- `List-Unsubscribe-Post: List-Unsubscribe=One-Click`

The link is `/api/v1/email/unsubscribe`, HMAC-signed with `JWT_SECRET` so it
cannot be forged.

## Webhook

`POST /api/v1/email/webhook/resend` — Svix signature required
(`RESEND_WEBHOOK_SECRET`, `whsec_...`), 5-minute timestamp window, duplicate
Svix ids ignored. Unsigned events are rejected: a forged "unsubscribed" event
would suppress arbitrary addresses.

## Required configuration

| Variable | Purpose |
|---|---|
| `RESEND_API_KEY` | Provider key |
| `RESEND_FROM` | From address (SPF/DKIM/DMARC-aligned domain) |
| `RESEND_WEBHOOK_SECRET` | Svix signing secret — webhook is disabled without it |
| `EMAIL_WORKER_BATCH` | Rows claimed per pass (default 20) |
| `EMAIL_WORKER_CONCURRENCY` | Parallel sends per pass (default 4) |
| `WORKER_LOOPS` | Must include `email-outbox` if the allowlist is used |

## Domains (ops checklist)

- Separate `auth.` (OTP/transactional) from customer-facing bulk email
  (`mail.` or a dedicated subdomain) for reputation isolation.
- SPF, DKIM and DMARC aligned and verified before launch; start at
  `p=quarantine`, move to `p=reject`.
- Warm up the sending domain; do not blast 1M on day one.
- Monitor `email_events` for bounce/complaint spikes (admin
  `/api/v1/admin/email/stats`).

## Operational visibility

- `GET /api/v1/admin/email/stats?days=7` — outbox status counts, provider
  events, suppression size.
- Dead letters stay in `email_outbox` with `status='dead'` and the provider
  error; retry them after fixing the cause.
- The worker logs every failure with the outbox id.

## Not yet built

- Newsletter campaign table/UI (the outbox and unsubscribe path are ready;
  a campaign row should expand recipients in batches, not insert 1M rows in
  one request).
- Resend open/click analytics are recorded as events but not charted.
