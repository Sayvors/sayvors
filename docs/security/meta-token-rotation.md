# Meta WhatsApp Token Lifecycle

This document describes the server-side credential lifecycle for WhatsApp
`MetaConnection` rows. Facebook, Instagram, app secrets, webhook verification
tokens, and the separate Page-token storage issue are out of scope.

## Classification is authoritative

Embedded Signup codes are exchanged server-side and the complete response is
kept in memory through classification. Only the opaque access token is stored,
Fernet-encrypted, in `access_token_encrypted`; response bodies and plaintext
tokens are never written to logs, notifications, or API representations.

When type or expiry is unknown, `WhatsAppAdapter.inspect_token()` calls Graph
`/debug_token`. The caller credential is a short-lived app access token
obtained server-side with `grant_type=client_credentials`; the inspected
business token is only the `input_token` parameter. App ID, validity, token
type, `expires_at`, `data_access_expires_at`, and scopes are captured.

| Confirmed type | Lifecycle action |
| --- | --- |
| `USER` | Exchange with `fb_exchange_token` immediately at connect and within seven days of expiry. |
| `BUSINESS_INTEGRATION_SYSTEM_USER` | No exchange. Null reported expiry means non-expiring and healthy. |
| `SYSTEM_USER` | No exchange. Null reported expiry means non-expiring. The current due scan does not auto-select system/business kinds, so unusual expiring tokens require operator monitoring. |
| Other/unknown | Never guess an exchange. Inspect, preserve deadlines, and alert before expiry when rotation is unsupported. |

The earlier of token expiry and data-access expiry is the effective send
deadline. A 60-day fallback is used only when a User-token long-lived exchange
omits expiry; it is recorded as `user_exchange_fallback_60d`. No synthetic
expiry is assigned to system/business tokens. If an exchange omits
`data_access_expires_at`, the previously classified deadline is preserved so a
later token expiry cannot silently extend data access.

## Secret-safe provider and telemetry I/O

OAuth credentials are sent as form fields rather than URL query parameters.
The Graph caller credential remains a server-generated app access token; tenant
tokens are never used as caller authentication for `/debug_token`. Sentry and
GlitchTip error and transaction hooks recursively strip URL query strings before
transmission, preventing OAuth credentials or tenant tokens from entering
telemetry even when an HTTP integration captures a request URL.

## Durable state and bounded worker

Migration `20261128110000` adds token kind, data-access expiry, last rotation,
consecutive attempts, safe error code, next-attempt backoff, lease deadline,
and index `ix_meta_connections_token_rotation_due` on
`(provider, status, token_expires_at)`.

`meta-token-rotation` is registered in the worker entrypoint. It starts with up
to five minutes of jitter, then runs every six hours. Each pass selects at most
100 due WhatsApp rows in `active` or recoverable `error` state and executes at
most five Meta operations concurrently. Healthy non-expiring system/business
tokens, leased rows, rows in backoff, and non-WhatsApp providers are excluded.

A row is claimed by one atomic conditional UPDATE with a ten-minute lease. The
transaction is committed and the session closed **before** any Meta HTTP call.
Persistence uses compare-and-swap on connection ID, encrypted token, lease, and
eligible status. A reconnect or competing worker therefore cannot be
overwritten by a stale result. Expired leases are reclaimable after a crash.

Transport failures, HTTP 408/425/429, and 5xx retain the old ciphertext, record a
bounded safe code, and schedule exponential backoff from 15 minutes up to six
hours. Other permanent 4xx responses mark `needs_reauth`. Invalid token metadata
is recorded as a retryable safe code; unexpected internal errors are also
recorded as retryable rather than misclassified as revoked credentials.

## Send guard and reauth transitions

`decrypt_connection_token()` is the central WhatsApp guard. It returns no token
for `expired`, `revoked`, or `needs_reauth`, or when either authoritative
deadline is at/before now. Active and recoverable-error connections remain
usable before the deadline, including inside the rotation window. Facebook and
Instagram credential behavior is unchanged. Inbound webhook persistence does
not use this send guard.

Validation, the rotation worker, and automated WhatsApp send paths call the
shared reauth helper after permanent auth rejection. Callers capture the
encrypted credential before provider I/O and pass it as a compare-and-swap
precondition, so a stale rejection cannot mark a newly reconnected token as
needing reauth. The helper conditionally transitions the row and inserts
tenant/admin notifications in the same transaction. Repeated failures cannot
duplicate alerts for one episode; a successful reconnect clears the error and
starts a new episode. HTTP 400 is only treated as send-auth failure when Meta's
safe error code/message indicates an OAuth/token problem, so ordinary
payload/window errors are not mislabeled. WhatsApp session completion requires
an authorization code, and tokenless WhatsApp upserts fail closed instead of
reactivating an old credential.

Tenant notifications deep-link to `/dashboard/channels`. Admin notifications
are global warnings containing only tenant ID, connection ID, and a safe
failure code. Unsupported expiring tokens receive one pre-expiry attention
alert per error episode and remain validation-only.

## API and operations

`MetaConnectionOut` exposes only `token_expires_at`, `token_last_rotated_at`,
and coarse `token_health` (`healthy`, `rotating`, `reauth_required`). It never
exposes ciphertext, plaintext, token type internals, raw provider errors, or
lease details.

Before production rollout, apply the migration, run a focused Meta/WhatsApp
regression pass, verify up/down/up on PostgreSQL, and smoke-test with a dedicated
WhatsApp connection. Monitor processed, retry, and reauth-required counts. A
merchant revocation still requires reconnection; automatic rotation must never
silently downgrade authentication.

Official references:

- <https://developers.facebook.com/documentation/business-messaging/whatsapp/access-tokens>
- <https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business>
- <https://developers.facebook.com/docs/graph-api/reference/debug_token>
- <https://developers.facebook.com/docs/facebook-login/access-tokens>
