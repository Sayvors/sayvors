# WebSocket Authentication (Inbox)

## Overview

The inbox WebSocket endpoint (`/api/v1/inbox/ws`) authenticates via JWT. Tokens are read from the httpOnly cookie first, falling back to the `?token=` query parameter for non-browser clients.

## Implementation

### On-connect checks (implemented)

1. **Token decode**: JWT is decoded with `JWT_SECRET` and `JWT_ALGORITHM`. Rejects if `user_id` is missing or `type != "access"` (code 4401).
2. **Blacklist check**: `is_token_blacklisted(payload["jti"])` — rejects revoked tokens (logout, reuse detection). Fail-closed when Redis is down.
3. **Token version check**: `payload["ver"]` must match `User.token_version` in the DB. Rejects tokens issued before a password change or logout-all.
4. **User resolution**: Loads the user row to derive `tenant_key` for workspace-level realtime.

### Not yet implemented

- **Suspension check**: Team member suspension is not checked on WS connect (only on HTTP endpoints via `get_current_user`). Planned.
- **Periodic re-check**: Revocation is only checked at connect time, not during the listen loop. A token revoked after connect stays valid until disconnect.
- **One-time ticket**: Token still rides the URL (`?token=`) for non-browser clients, which leaks it in access logs. Planned: short-lived one-time ticket exchanged via POST.

### Related

- `app/core/deps.py:get_current_user()` — the HTTP-side equivalent that performs the same checks plus suspension enforcement.
- `app/modules/auth/rate_limit.py` — `is_token_blacklisted()` (Redis-backed, fail-closed).
- `app/modules/users/models.py` — `token_version` column (incremented on logout-all / password change).