# WhatsApp Token Lifecycle Implementation Plan

Date: 2026-11-28
Status: Approved; corrected for Meta's 2026 token lifecycle
Design: `docs/specs/2026-11-28-whatsapp-token-rotation-design.md`

## Critical review

The original request assumed every WhatsApp token should be exchanged. Meta's
current documentation identifies Embedded Signup v4 business tokens as Business
Integration System User tokens intended to avoid re-authentication. This plan
therefore classifies first and rotates only `USER` tokens. It also replaces the
original row-lock-across-HTTP proposal with a committed short lease and
compare-and-swap. The requested plan file was absent; the parent approved using
the design and task scope as the contract.

## Task 1 — Durable state and migration

Write model/migration assertions first. Add token kind, data-access expiry,
rotation audit/backoff/lease fields, and the due-scan index to `MetaConnection`.
Add idempotent migration `20261128110000`, `down_revision=20261128100000`.
Verify model tests, migration guard, and Alembic up/down/up. Commit.

## Task 2 — Adapter classification and connect flow

Write failing adapter tests for complete code payloads, app-token `/debug_token`,
expiry parsing, User-only `fb_exchange_token`, and User-only 60-day fallback.
Implement adapter inspection/exchange and token lifecycle parsing. Write connect
tests proving business tokens are stored without exchange or fake expiry and
User tokens rotate immediately; transient failures remain recoverable. Commit.

## Task 3 — Guard, reauth marker, and API health

Write failing tests for expired/revoked/reauth/data-access guards, active tokens
inside leeway, alert dedupe/secret safety, validation failures, and API health.
Implement the central WhatsApp guard, shared conditional reauth marker, safe
tenant/admin alerts, and coarse `MetaConnectionOut` fields. Wire validation and
automated send failures with connection context. Commit.

## Task 4 — Bounded lease-based worker

Write failing tests for due selection, batch 100/concurrency 5, non-expiring
skips, successful encrypted rotation, duplicate/concurrent claims, stale CAS,
transient backoff, permanent rejection, and unsupported-token alerts. Implement
`meta/token_rotation.py` with short committed leases, no DB lock across HTTP,
five-way bounded execution, and conditional persistence. Register the six-hour
loop in `app/workers/main.py`. Commit.

## Task 5 — Documentation and final verification

Write `docs/security/meta-token-rotation.md`. Run focused Meta/WhatsApp tests,
migration guard, up/down/up, and `git diff --check`. Only after those pass,
update the token-rotation row in `readiness-report.html`. Review the diff for
scope/secret safety and commit. Do not push.

## Focused commands

```powershell
cd services/api
python -m pytest tests/test_meta_token_rotation.py tests/test_meta_token_lifecycle.py tests/test_meta_isolation.py tests/test_meta_oauth.py tests/test_whatsapp_templates.py -q -n 0
python migration_guard.py
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic upgrade head
cd ..
git diff --check
```

The shared model/worker change warrants the full backend suite, but the parent
owns that broader run per the task assignment.
