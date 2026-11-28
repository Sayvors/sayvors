# WhatsApp Token Lifecycle — Production Design

Date: 2026-11-28
Status: Approved for implementation
Scope: WhatsApp Meta connections only

## Goal

Classify WhatsApp credentials using Meta's authoritative token metadata, rotate
only eligible User tokens before expiry, detect revoked or permanently rejected
tokens early, fail closed for new sends, preserve inbound webhooks and history,
and alert the tenant and platform operators.

## Authoritative lifecycle rules

Embedded Signup v4 commonly returns Business Integration System User tokens.
These are intended for server-to-server access without future re-authentication.
They must not be sent through `fb_exchange_token`.

1. Preserve the complete code-exchange payload in memory through classification.
2. When token type or expiry is unknown, inspect it with Graph `/debug_token`,
   authenticated by a server-generated **app access token** (`client_credentials`),
   never by the inspected business token.
3. Exchange only tokens Meta identifies as `USER`, using `fb_exchange_token`.
4. Treat valid `SYSTEM_USER` and `BUSINESS_INTEGRATION_SYSTEM_USER` tokens with no
   reported expiry as non-expiring. Never invent a 60-day expiry for them.
5. Preserve both `expires_at` and `data_access_expires_at`; the earlier timestamp
   is the effective send deadline.
6. For other expiring token types, validate and alert before expiry. Do not guess
   at a server-side rotation mechanism.
7. A 60-day fallback is allowed only when a User-token long-lived exchange omits
   `expires_in`; record that the expiry is a documented fallback.

Official references:

- <https://developers.facebook.com/documentation/business-messaging/whatsapp/access-tokens>
- <https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business>
- <https://developers.facebook.com/docs/graph-api/reference/debug_token>
- <https://developers.facebook.com/docs/facebook-login/access-tokens>

## Non-goals

- Facebook and Instagram token rotation.
- Rotation of the Meta app secret or webhook verification token.
- Changing phone numbers, message history, assets, or webhook subscriptions.
- Fixing the separate plaintext Page-token storage issue.
- Eliminating reconnection when the merchant revokes permissions or Meta
  permanently rejects the token.

## Durable state

`MetaConnection` gains:

- `token_kind`: bounded Meta token type, or null until inspected.
- `data_access_expires_at`: Meta's data-access deadline, when reported.
- `token_last_rotated_at`: last successful User-token long-lived exchange.
- `token_rotation_attempts`: consecutive failed maintenance attempts.
- `token_rotation_error`: bounded safe error code, never provider text.
- `token_rotation_next_attempt_at`: exponential-backoff retry deadline.
- `token_rotation_lease_until`: short claim lease, never held across HTTP.

An index on `(provider, status, token_expires_at)` supports bounded due scans.
Existing rows remain valid; null classification means "inspect before acting".

## Connect-time classification

After code exchange and before storing a new WhatsApp connection:

1. Keep all returned fields available to the classifier; encrypt the token into
   the existing credential column and never persist the plaintext payload.
2. Inspect unknown type/expiry with `/debug_token` using an app access token.
3. For a User token, attempt the long-lived exchange immediately. Store its
   token, reported expiry (or documented User-only fallback), and rotation time.
4. For a confirmed non-expiring system/business token, store it unchanged with
   null expiry and healthy status. No exchange and no synthetic expiry.
5. For another expiring type, store the authoritative deadlines and validate
   without rotation; alert if it is already inside the seven-day leeway.
6. A transient inspection/exchange failure stores the original encrypted token
   and known deadlines with a recoverable error for the worker. A permanent
   rejection fails connect with a safe reconnect message.

## Scheduled maintenance worker

A dedicated loop runs every six hours with startup jitter.

Selection is provider-scoped, bounded to 100 rows, and includes only active or
recoverable-error WhatsApp connections whose lease/backoff permits work. Due
rows have unknown classification/expiry, an unenrolled User token, a User token
inside seven days of expiry, or an unsupported expiring token inside seven days.
Confirmed non-expiring system/business tokens are skipped.

Execution uses at most five concurrent Meta requests:

1. Atomically claim one row with a short lease and commit immediately.
2. Release the database transaction before any Meta HTTP call.
3. Inspect or exchange according to the claimed classification.
4. Compare-and-swap the result only if the encrypted token and lease still match.
   A reconnect or competing worker therefore cannot be overwritten.
5. Success atomically stores ciphertext, deadlines, classification, rotation
   metadata, active status, and cleared error/attempt state.
6. Transport failures, 408/425/429, and 5xx retain the old token, record a safe
   code, and schedule capped exponential backoff.
7. Other permanent 4xx responses or invalid-token metadata mark `needs_reauth`
   and emit one tenant/admin alert for that failure episode.

No database row lock is held during network I/O. Lease duration exceeds the HTTP
timeout; stale claims become eligible again after the lease expires.

## Send guard and auth failures

`decrypt_connection_token()` is the central WhatsApp guard:

- Return no token for `expired`, `revoked`, or `needs_reauth` status.
- Return no token when either token expiry or data-access expiry is at/before now.
- Continue returning tokens for active/recoverable-error connections before the
  deadline, including those inside the rotation window.
- Do not change Facebook/Instagram credential behavior.

Existing send paths already fail closed on a missing token. Inbound webhook
persistence does not depend on this guard. Permanent WhatsApp auth failures in
validation, rotation, and automated send paths use one shared reauth marker.
The marker conditionally transitions status and creates alerts in the same
transaction, so repeated failures do not duplicate notifications.

## Alerts and health visibility

Tenant notification: "WhatsApp needs reconnection" with a Channels deep link,
only after permanent auth rejection. Unsupported expiring tokens receive one
pre-expiry attention alert per error episode instead.

Admin notification: global warning with tenant identifier, connection identifier,
and a safe failure code. No token, fragment, authorization header, app secret,
or raw provider response is stored or logged.

`MetaConnectionOut` exposes `token_expires_at`, `token_last_rotated_at`, and
coarse `token_health`: `healthy`, `rotating`, or `reauth_required`. Credentials,
raw errors, lease details, and token type internals are not exposed.

## Security invariants

- Tokens remain Fernet-encrypted at rest; plaintext exists only in request memory.
- `/debug_token` uses app credentials, never the inspected token as caller auth.
- No blind exchange of system/business tokens and no fabricated expiry.
- Queries are tenant-safe, provider-scoped, indexed, and bounded.
- Worker batch, concurrency, HTTP timeout, lease, and retry backoff are bounded.
- Permanent auth failures fail closed for new sends.
- Rotation state, ciphertext, deadlines, and alerts change atomically.
- Compare-and-swap prevents stale workers from overwriting reconnects.

## Verification

- Unit/service tests for payload/expiry parsing, User-only fallback, app-token
  inspection, classification, due selection, success, lease/CAS concurrency,
  retry/backoff, permanent failure, alert dedupe, and guard behavior.
- Connect/API tests for business-token no-op rotation, User immediate rotation,
  transient recovery, secret safety, and coarse health fields.
- Focused Meta/WhatsApp tests, migration guard, Alembic up/down/up, and
  `git diff --check`. Parent may run the full backend suite afterward.
- Staging smoke test with a dedicated WhatsApp connection before production.
