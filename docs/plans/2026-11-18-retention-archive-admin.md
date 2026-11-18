# Retention archive + admin control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make retention windows admin-configurable, archive rows to cold storage before deletion in a training-ready, tool-call-preserving format, and expose backup-now / clean-now controls in the admin console.

**Architecture:** mirror the existing `AdminBackupConfig` / `AdminBackupRun` pattern — a single-row DB config plus an audit row per run. The hourly retention sweep reads config from the DB, and for each table archives a batch to S3 (gzipped JSONL, categorised by kind, PII stripped) before deleting it. The admin API and console read/write the same config and can trigger one-off archive or clean runs. Nothing about the customer-facing data changes.

**Tech Stack:** SQLAlchemy async, Alembic, boto3 via `integrations.storage.s3`, FastAPI admin router, Next.js admin console.

---

## File map

- Create `services/api/app/modules/retention_archive.py` — payload formatting, PII strip, S3 upload, audit rows.
- Modify `services/api/app/modules/admin/models.py` — `RetentionConfig`, `RetentionRun`.
- Modify `services/api/app/modules/retention.py` — read config, archive-before-delete, clean-now.
- Create `services/api/app/modules/admin/retention.py` — get/update config, trigger runs, list runs.
- Modify `services/api/app/modules/admin/router.py` — five endpoints under `/admin/retention`.
- Modify `services/api/app/config.py` + `integrations/storage/s3.py` — `S3_ARCHIVE_BUCKET`, `kind="archive"`.
- New Alembic revision after `20261118140000`.
- Create `services/api/tests/test_retention_archive.py`.
- Modify `apps/admin/app/(dashboard)/...` — Retention page.
- Update `readiness-report.html` + `docs/security/` durable doc.

## Decisions locked in

- **Archive is private** — dedicated `S3_ARCHIVE_BUCKET`, never the public media bucket.
- **PII**: reviewer names dropped/hashed; review text kept because it is the model input; operator notes dropped.
- **Tool trajectories preserved**: `tool_calls`, `selected_strategies`, `retrieved_offers`, `analysis`, `status`, model and token counts stay in the JSONL. This is the reason to archive at all.
- **Categorised**: one S3 prefix per kind — `review_generation/YYYY/MM/`, `connect_progress/YYYY/MM/`.
- **Lead time** (`backup_lead_days`, default 2): archive rows this many days *before* they become eligible for deletion, so a slow S3 outage never forces a choice between keeping rows forever and deleting unarchived data.
- **Fail closed on the delete path**: if archiving is enabled and the upload fails, the rows are NOT deleted. The hourly sweep logs and moves on.
- **Manual clean-now honours the same rule** — it can never delete unarchived rows while archive is enabled.
- **No invented training claims**: the archive is a prepared asset, not a trained model.

---

### Task 1: config + audit models and migration

- [ ] Add `RetentionConfig` (single row `id="default"`): `review_log_days=90`, `connect_event_days=30`, `backup_lead_days=2`, `archive_enabled=False`, `last_run_at`, `updated_at`.
- [ ] Add `RetentionRun`: `id`, `kind`, `s3_key`, `rows`, `size_bytes`, `status`, `trigger_type`, `error`, `started_at`, `finished_at`, with indexes on started_at and kind.
- [ ] Migration creates both tables; single head verified.

### Task 2: archive service

- [ ] `S3_ARCHIVE_BUCKET` in config; `s3._bucket("archive")` returns it, never falls back to media.
- [ ] `format_jsonl(kind, rows)` — gzipped bytes; PII stripped; tool fields intact.
- [ ] `archive_rows(kind, rows, trigger)` — upload, write `RetentionRun`, return the row. Raises on S3 failure.
- [ ] Unit tests with a fake S3 client: payload shape, PII absence, tool-call presence, fail-on-error.

### Task 3: wire the sweep

- [ ] `retention.py` reads `RetentionConfig` once per run (default row if absent).
- [ ] For each kind: archive rows in `[cutoff+lead, cutoff)` before deleting rows `< cutoff`.
- [ ] If `archive_enabled` and upload fails → log, count `-1`, skip deletion for that kind.
- [ ] `clean_now(kind)` and `backup_now(kind)` service functions for the API.

### Task 4: admin API

- [ ] `GET`/`PUT /api/v1/admin/retention/config` — validate bounds (days 1..3650, lead 0..365).
- [ ] `POST /api/v1/admin/retention/backup-now`, `/clean-now`, `GET /runs`.
- [ ] All behind `require_admin`; admin audit middleware records mutations.

### Task 5: admin console

- [ ] Retention page: two day inputs + lead input + archive toggle, Save, Backup now, Clean now, run history table.

### Task 6: verify, document, commit

- [ ] Full backend suite; admin console `tsc` + build.
- [ ] Durable doc in `docs/security/` on the archive invariants.
- [ ] Commits split code/docs; never push without an explicit request.
