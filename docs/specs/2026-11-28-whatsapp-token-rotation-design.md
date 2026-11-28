# WhatsApp Token Rotation — Production Design

Date: 2026-11-28
Status: Approved for implementation
Scope: WhatsApp Meta connections only

## Goal

Rotate WhatsApp business access tokens before expiry so merchants do not repeat the WhatsApp connection journey. Detect revoked or permanently rejected tokens early, fail closed for new sends, preserve inbound webhooks and history, and alert the tenant and platform operators.

## Current gap

- `MetaConnection.access_token_encrypted` already stores tokens with Fernet encryption.
- `MetaConnection.token_expires_at` exists but code-exchange responses do not reliably populate it.
- Tokens are decrypted at each use with no proactive rotation or expiry-health workflow.
- A token rejected by Meta is discovered during a send and there is no durable rotation audit or reconnect alert.

## Non-goals

- Facebook and Instagram token rotation.
- Rotation of the Meta app secret or webhook verification token.
- Changing phone numbers, message history, assets, or webhook subscriptions.
- Eliminating reconnection when the merchant revokes permissions or Meta permanently rejects the token.

## Architecture

### 1. Capture and normalize credentials

The WhatsApp adapter exchanges the Embedded Signup code, then exchanges the returned token for a long-lived token through Meta's `oauth/access_token` endpoint using `grant_type=fb_exchange_token`.

- Preserve `expires_in` when Meta returns it.
- Store `token_expires_at` as a UTC timestamp.
- If Meta omits expiry on a long-lived exchange, use a documented 60-day fallback and keep the token eligible for early rotation.
- Never log or persist the plaintext token outside the existing encrypted column.

### 2. Durable rotation state

Add to `MetaConnection`:

- `token_last_rotated_at`: last successful long-lived exchange.
- `token_rotation_attempts`: consecutive failed rotation attempts.
- `token_rotation_error`: bounded safe error code, never raw provider text or token fragments.

Add an index on `(provider, status, token_expires_at)` so the due-token scan does not become a full-table walk at scale.

A single Alembic migration adds the fields and index. Existing rows remain valid; null rotation fields mean "not yet enrolled".

### 3. Scheduled rotation worker

A dedicated worker loop runs every six hours with startup jitter.

Selection rules:

- `provider = whatsapp`.
- Status is `active` or recoverable `error`.
- Token exists and is not revoked.
- Token is within seven days of expiry, has unknown expiry, or has not yet been enrolled in long-lived rotation.

Execution rules:

- Bounded batch of 100 connections per pass.
- Bounded concurrency of five token exchanges.
- Lock one connection row, recheck due state, then perform the exchange.
- On success, encrypt and store the new token, expiry, last-rotation timestamp, clear error state, restore `active`, and reset attempts.
- On transient transport, 429, or 5xx failures, keep the old token, record a safe error code, apply exponential backoff, and retry in a later pass.
- On permanent 400/401/403 rejection, mark `needs_reauth`, block new sends, and emit alerts.

The row lock is held only for one connection; no global lock or unbounded fan-out is introduced.

### 4. Connect-time rotation

After code exchange and before storing a new WhatsApp connection:

1. Attempt the long-lived token exchange immediately.
2. Store the long-lived token and expiry on success.
3. If the exchange is transiently unavailable, store the original encrypted token with its known expiry (when available), mark a recoverable rotation error, and let the worker retry without forcing the merchant through onboarding again.
4. If Meta permanently rejects the token, fail the connect with a safe reconnect message.

### 5. Send guard and failure handling

`decrypt_connection_token()` becomes the central WhatsApp expiry guard:

- Return no token for `expired`, `revoked`, or `needs_reauth` connections.
- Return no token when `token_expires_at` is at or before the current time.
- Continue returning tokens for active connections inside the rotation window.

Existing send paths already treat a missing token as a connection failure. Inbound webhooks do not depend on this guard and remain unaffected.

When a WhatsApp send receives a permanent authentication rejection from Meta, the connection is marked `needs_reauth` through a shared helper and alerts are emitted once. Repeated failures do not generate duplicate alerts.

### 6. Alerts and health visibility

Tenant alert:

- In-app notification: "WhatsApp needs reconnection" with a Channels deep link.
- Sent only after a permanent authentication failure, not for transient rotation failures.

Admin alert:

- Global `AdminNotification` with severity warning, tenant identifier, connection identifier, and safe failure code.
- No token, token fragment, authorization header, or raw provider response.

API/UI:

- `MetaConnectionOut` exposes `token_expires_at`, `token_last_rotated_at`, and a coarse `token_health` value (`healthy`, `rotating`, `reauth_required`).
- The tenant Channels page displays automatic-rotation health and a reconnect action only when required.
- Existing connection validation and disconnect flows remain unchanged.

## Security invariants

- Tokens remain Fernet-encrypted at rest.
- Plaintext tokens never enter logs, admin notifications, tenant notifications, telemetry, or API responses.
- All rotation queries are tenant-safe and provider-scoped.
- Rotation uses the server-configured Meta app credentials only.
- The worker is bounded by batch size, concurrency, request timeout, and retry backoff.
- Permanent auth failures fail closed for new sends; they never silently downgrade to an unauthenticated request.
- Rotation state changes are atomic with the encrypted token and expiry update.

## Testing

### Unit/service tests

- Long-lived exchange parses and stores `expires_in`.
- Missing expiry uses the documented fallback.
- Due-token selection includes near-expiry, unknown-expiry, and unenrolled tokens.
- Successful rotation encrypts the new token and clears prior errors.
- Same-plan retry and concurrent workers cannot double-rotate a connection.
- Transient failures retain the old token and schedule retry.
- Permanent rejection marks `needs_reauth` and emits one tenant/admin alert.
- Expired/revoked/needs-reauth connections return no send token.
- Active tokens inside the leeway window remain usable.
- Notifications and logs contain no plaintext token.

### Integration/API tests

- Connect flow stores a long-lived token and expiry.
- Rotation worker processes a bounded batch and is safe under two workers.
- Connection API exposes health without exposing credentials.
- Tenant and admin notifications are created once per failure episode.
- Existing WhatsApp connect, send, webhook, disconnect, and retention tests remain green.

### Verification gates

- Focused Meta/WhatsApp test files.
- Full backend suite because the shared `MetaConnection` model and worker entrypoint change.
- Alembic up/down/up and migration guard.
- Gitleaks tracked-file scan.
- TypeScript/build only if the tenant Channels UI changes.
- Staging smoke test with a dedicated WhatsApp test connection before enabling production traffic.

## Rollout

1. Deploy the migration and code; existing tokens are not cleared.
2. Worker enrolls existing WhatsApp tokens, validates unknown expiry, and rotates them before expiry.
3. Verify rotation and alerts with a staging connection.
4. Monitor rotation success, retry, and reauth-required counts.
5. Facebook/Instagram rotation remains a separate future change.

## Success criteria

- No merchant is forced to reconnect solely because a WhatsApp token aged out.
- Revoked or invalid tokens stop new sends and produce actionable tenant/admin alerts.
- Rotation is auditable, idempotent, bounded, secret-safe, and safe across multiple workers.
