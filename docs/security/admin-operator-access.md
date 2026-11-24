# Admin Operator Access

## Scope

Platform admin access is separate from tenant user accounts. It uses named operator accounts stored in `platform_operators` and short-lived admin JWTs (`type: "admin"`). Every admin mutation/request is recorded in `admin_audit_logs`.

The admin surface is `apps/admin`. Tenant-facing routes do not grant platform admin privileges.

## Configuration

| Setting | Purpose |
| --- | --- |
| `ADMIN_PASSWORD_HASH` | bcrypt hash for legacy/shared admin password. Required by production config validation. Used for legacy bootstrap/fallback. |
| `ADMIN_BOOTSTRAP_USERNAME` | Optional first operator username to create on startup when no operators exist. |
| `ADMIN_BOOTSTRAP_PASSWORD` | Optional plaintext password used once for startup bootstrap when no operators exist. Rotate/remove after the operator is created. |
| `ADMIN_SESSION_MINUTES` | Admin JWT lifetime. Default `120`. |
| `ADMIN_MAX_CONSECUTIVE_FAILURES` | Per-operator failed-login threshold before a 15-minute lock. Default `10`. |
| `ADMIN_COOKIE_NAME` | httpOnly admin session cookie name. Default `sayvors_admin_token`. |

## Bootstrap

### Startup bootstrap

On API startup, if `platform_operators` is empty:

1. If `ADMIN_BOOTSTRAP_USERNAME` is set, create that operator as `superadmin`.
2. If `ADMIN_BOOTSTRAP_PASSWORD` is set, hash it for the new operator.
3. If no bootstrap username is set but `ADMIN_PASSWORD_HASH` is set, create a legacy `admin` superadmin using `ADMIN_PASSWORD_HASH` as its password hash.

The startup bootstrap logs a warning instructing operators to set bootstrap credentials or rotate the password immediately.

### Login fallback bootstrap

`POST /api/v1/admin/login` also supports legacy bootstrap for deployments where no operator rows exist yet:

- If there are no operators and `ADMIN_PASSWORD_HASH` is configured, username `admin` with the matching legacy password creates a `platform_operators` row for `admin` as `superadmin`.
- If there are no operators and no `ADMIN_PASSWORD_HASH`, login returns `503 Admin access is not configured.`

## Authentication and Session

- Admin login: `POST /api/v1/admin/login` with `username` and `password`.
- Successful login sets an httpOnly, `SameSite=Strict` admin cookie scoped to `/api/v1/admin` and returns `expires_in_minutes`.
- Admin APIs accept either the admin cookie or `Authorization: Bearer <admin-token>`.
- Cookie-authenticated admin requests must include `X-Requested-With: XMLHttpRequest`. This is a CSRF guard for browser-cookie auth.
- Admin tokens carry `type: "admin"` and a `sub` operator ID. Tokens with the wrong type are rejected by `require_admin`.
- Logout blacklists the presented admin token JTI and clears the admin cookie.

## Operator Accounts

`platform_operators` fields include:

- `username` (unique)
- `password_hash` (bcrypt)
- `role` (`operator` or `superadmin`)
- `is_active`
- `failed_login_count`
- `locked_until`
- `created_at`, `last_login_at`

Management endpoints (admin-authenticated):

- `GET /api/v1/admin/operators` — list operators.
- `POST /api/v1/admin/operators` — create operator. Validates username, password length, and role.
- `PATCH /api/v1/admin/operators/{operator_id}` — activate/deactivate, change role, or reset password.

Passwords are bcrypt-hashed. Operator responses never include `password_hash`.

## Lockout and Failure Handling

- Login rate limit: 5 attempts per 5 minutes per IP when not in testing mode.
- Global admin lockout: repeated failures increment a Redis-backed global failure counter; when over the configured threshold, admin login is temporarily locked.
- Per-operator lockout: wrong password increments `failed_login_count`; at `ADMIN_MAX_CONSECUTIVE_FAILURES` the account gets `locked_until = now + 15 minutes`. Locked accounts return `423`.
- Successful login resets per-operator failure count/lock and clears the global Redis failure counter.
- Inactive or unknown operators return the same generic wrong-credentials response.

## Audit Log

`admin_audit_logs` records admin actions with operator identity, action, method, path, status, IP, user agent, detail, and timestamp.

- `GET /api/v1/admin/audit-log` supports `limit`, `offset`, `q`, `method`, and `status` filters.
- Operator create/update endpoints write explicit audit rows (`operator.create`, `operator.update`).
- Admin audit middleware records admin requests; audit write failures are logged as warnings and do not fail the original request.

## Recovery

- Preferred: sign in with another active `superadmin` and reset/disable accounts through `/operators`.
- If no operators can authenticate: set `ADMIN_BOOTSTRAP_USERNAME` and `ADMIN_BOOTSTRAP_PASSWORD` only when the operators table is empty, or use a controlled DB recovery procedure to create/reset a superadmin password hash. Remove bootstrap plaintext password env vars after recovery.
- Legacy `ADMIN_PASSWORD_HASH` remains a fallback/bootstrap input; keep it configured and secret-managed. Rotating it does not automatically rewrite existing operator hashes.