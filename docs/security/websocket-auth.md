# WebSocket Authentication (Inbox)

## Overview

The inbox WebSocket endpoint (`/api/v1/inbox/ws`) authenticates via JWT or a short-lived one-time ticket. Tokens are read from the httpOnly cookie first, falling back to the `?token=` query parameter or `?ticket=` for non-browser clients.

## Implementation

### On-connect checks (implemented)

1. **Ticket path**: If `?ticket=` is provided, validate against Redis (`ws:ticket:{ticket}`). Single-use: deleted after validation. 30s TTL.
2. **Token path**: JWT decoded with `JWT_SECRET`. Checks:
   - `user_id` present and `type == "access"`
   - Blacklist (`is_token_blacklisted`) — rejects revoked tokens (logout/reuse). Fail-closed when Redis is down.
   - `token_version` — rejects tokens issued before password change or logout-all.
   - Suspension — team member suspension enforced (mirrors `get_current_user`).
3. **User resolution**: Loads user row to derive `tenant_key` for workspace-level realtime.

### Periodic checks (implemented)

- Heartbeat runs every 25s. For token-based auth, re-checks blacklist + `token_version` each cycle. Connection closed (4401) if revoked.
- Ticket-based auth skips periodic checks (ticket already consumed, single-use).

### One-time ticket (implemented)

- `POST /api/v1/inbox/ws-ticket` issues a 30s single-use ticket stored in Redis.
- Client exchanges JWT for ticket, then connects with `?ticket=` instead of `?token=`.
- Moves the access token off the URL (access logs) for non-browser clients.

### Not yet implemented

- **Suspension periodic re-check**: Suspension is checked on connect only. A user suspended after connect stays connected until heartbeat revocation fires (token_version bump on suspension would close it).
- **Token in URL deprecation**: `?token=` still accepted for backward compat. Planned: remove once all clients use tickets.

### Related

- `app/core/deps.py:get_current_user()` — the HTTP-side equivalent.
- `app/modules/auth/rate_limit.py` — `is_token_blacklisted()` (Redis-backed, fail-closed).
- `app/modules/users/models.py` — `token_version` column.
- `app/modules/channels/realtime.py` — `subscribe_inbox()` for pub/sub.