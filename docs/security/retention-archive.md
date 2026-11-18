# Retention archive and admin control

Last updated: 2026-11-18.

## Why this exists

Two operational tables grew for the life of a tenant: one row per review-reply
generation (the prompt, the analysis, the tool calls, the result) and one row
per Google connect-import progress step. Both are useful briefly and worthless
forever, but neither had a cleanup job. An admin-configurable policy now
archives them to private cold storage and then deletes them from Postgres.

The archive is not just a backup. `review_response_logs` records the full
tool-call trajectory — `tool_calls`, `selected_strategies`, `retrieved_offers`,
`analysis`, the generated response and the token/latency figures. That is the
shape a tool-using model needs if we ever fine-tune one. The archive preserves
it; a plain delete would lose it.

## How it is implemented

- **Policy**: `retention_config`, a single row (`id="default"`) holding
  `review_log_days` (90), `connect_event_days` (30), `backup_lead_days` (2) and
  `archive_enabled` (false). Same shape as `admin_backup_config`.
- **Audit**: `retention_runs`, one row per archive or clean attempt with kind,
  action, S3 key, row count, size, status, trigger and error.
- **Lead window**: rows are archived in `[now − window − lead, now − window)`,
  i.e. before they become deletable. A slow S3 outage therefore never forces a
  choice between deleting unarchived data and keeping rows forever.
- **Idempotency**: two timestamps on the policy row (`*_archived_through`) are
  high-water marks. The hourly sweep only archives rows newer than the mark;
  the same rows are never uploaded twice.
- **Fail closed**: if `archive_enabled` and the S3 upload raises, the caller
  skips deletion for that kind entirely and reports `-1`. Manual clean-now
  returns 502 with no rows deleted. Archiving off means ordinary time-based
  deletion, which preserves the behaviour that shipped before this feature.
- **S3**: `S3_ARCHIVE_BUCKET` only. The adapter has no fallback to the public
  media bucket. Keys are categorised as
  `retention/<kind>/<year>/<month>/<timestamp>-<random>.jsonl.gz`.
- **PII**: reviewer names and operator identifiers are removed from the JSONL.
  Review text is retained because it is the model input; removing it would make
  the archive useless. This is a deliberate trade-off, not an oversight.

## Admin surface

`GET`/`PUT /api/v1/admin/retention/config`, `POST .../backup-now`,
`POST .../clean-now`, `GET .../runs`, all behind `require_admin`, with the day
values bounded (1–3650, lead 0–365). Console page at `/retention`.

## Invariants

- No row is deleted while archiving is enabled and its upload failed.
- No row is archived twice.
- Customer-visible data is never touched: replies, reviews, the Google
  connection and imported content are stored in different tables and are not
  part of either sweep.
- The archive is an asset prepared for a possible future model; nothing here
  claims a model was trained or that tenant data may be used for training
  without the appropriate consent and terms.
