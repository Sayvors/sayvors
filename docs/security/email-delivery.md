# Email delivery (production path)

Last updated: 2026-11-08.

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
- A worker crash after claiming leaves a row in `sending`. Every worker runs a
  bounded reaper once a minute: rows whose `claimed_at` is older than 15
  minutes go back to `queued` with a fresh `next_attempt_at` if attempts
  remain, or to `dead` when the retry budget is exhausted. Replay is safe
  because the row keeps the same Resend `Idempotency-Key`.
- **Every** email is idempotent at the provider too (`Idempotency-Key` header).

## Suppression

Checked before enqueue and updated by the webhook:

- `bounced` (hard) and `complained` → suppress immediately, stop sending.
- `unsubscribed` (one-click link) → suppress and set `users.newsletter=false`.

Review-request and newsletter emails carry:

- `List-Unsubscribe`
- `List-Unsubscribe-Post: List-Unsubscribe=One-Click`

The link is `/api/v1/email/unsubscribe`, HMAC-signed with the dedicated
`EMAIL_UNSUBSCRIBE_SECRET` so it cannot be forged and rotating `JWT_SECRET`
does not invalidate links already delivered. Verification also accepts the
legacy `JWT_SECRET`-signed form so opt-outs sent before the key migration keep
working; new links are only minted with the dedicated key.

## Bulk review-request email cap

Review-request email is separate from the plan's WhatsApp allowance, but it is
not unbounded. Every tenant is capped at `BULK_EMAIL_DAILY_LIMIT` (default
500) review-request emails per rolling 24 hours, counted at enqueue time in
`review_requests` (`channel='email'`).

- `POST /api/v1/analytics/review-requests/bulk` queues only the remaining
  headroom and reports `used` / `max` / `remaining` / `window: "24h"`; the rest
  are returned in `skipped_quota` instead of silently over-sending.
- `POST /api/v1/analytics/review-requests` with `deliver=true` returns 429
  once the cap is exhausted.
- The cap protects the shared Resend sending domain from one runaway campaign;
  it does not gate OTP, billing or other transactional mail.

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
| `EMAIL_UNSUBSCRIBE_SECRET` | Dedicated unsubscribe HMAC key; required in deployed envs, must differ from `JWT_SECRET` |
| `EMAIL_WORKER_BATCH` | Rows claimed per pass (default 20) |
| `EMAIL_WORKER_CONCURRENCY` | Parallel sends per pass (default 4) |
| `BULK_EMAIL_DAILY_LIMIT` | Per-tenant review-request email cap per rolling 24h (default 500) |
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
