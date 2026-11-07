# Tenant lifecycle: suspend, export, purge

Last updated: 2026-11-07.

Platform operators manage a workspace from **Admin → Tenants → (tenant) → Workspace
controls**. Three operations exist, all restricted to `require_admin` and recorded
in `admin_audit_logs` by the admin audit middleware (mutating requests only).

## Suspension

- Stored on the **owner's** `users` row: `suspended_at` + `suspension_reason`.
  Employees inherit it through `tenant_id`; there is no per-member flag.
- Enforced in three places, all sharing `users.status.suspension_message`:
  1. `get_current_user` — every authenticated request (owner and members).
  2. Password login — checked after the password proves ownership, so the
     message cannot be used to enumerate accounts.
  3. Refresh — a suspended workspace cannot mint new access tokens; the
     presented refresh token is revoked.
- Suspending bumps the owner's `token_version` and revokes refresh tokens for
  the owner and every employee, so existing sessions die immediately even if
  Redis is unavailable.
- Reactivation clears the columns. It does **not** restore old sessions; users
  sign in again.
- Data is never deleted by suspension.

## Export

- `GET /api/v1/admin/tenants/{id}/export` streams a JSON attachment.
- Scope is derived from ORM metadata, not a hand-written list: every table with
  `tenant_id`, `user_id` (owner + employees), or `channel_id` is included, so a
  new tenant-owned table is covered automatically.
- System tables (`platform_operators`, `admin_audit_logs`, `alembic_version`)
  are never exported.
- Columns whose name contains `password_hash`, `key_encrypted`, `secret`,
  `token_hash`, or `encrypted` are dropped from the export. Provider secrets
  and hashes are not customer data.
- The export is logged (row count + tenant) because GETs are not written to the
  audit log by the middleware. **Export before purge.**

## Purge

- `POST /api/v1/admin/tenants/{id}/purge` requires the tenant's exact email in
  `confirm` (case-insensitive). A wrong value returns 400 and deletes nothing.
- Runs in one transaction, children first (reverse dependency order), then the
  user rows. A partial purge cannot be committed.
- Same metadata-derived scope as export. `event_outbox` has no tenant column,
  so its rows are swept by `payload.tenant_id`.
- Media objects are collected from `*storage_key` / `file_key` columns before
  the rows are deleted and removed best-effort afterwards — a storage outage
  cannot abort the database purge.
- The assistant's long-term memory profile in Redis is deleted
  (`assistant.memory.forget_profile`).
- The purge itself is logged at WARNING with tenant id and row counts.

## Invariants to preserve

- Never make suspension depend on a background job; it must be enforced in the
  request path.
- Never export decrypted secrets or password hashes, even for an operator.
- Never purge without an export in the same session; the API cannot enforce
  that, the admin UI presents export as the first action in the same panel.
- Any new tenant-owned table must expose `tenant_id` or `user_id`, otherwise
  export and purge will miss it. Tables keyed only by a foreign key that is not
  `channel_id` need an explicit clause in `tenant_ops._scope_clause`.
