# WhatsApp Spend Attribution — Production Design

Date: 2026-11-28
Status: Approved for implementation
Scope: WhatsApp only

## Goal

Give tenants and admins real-time WhatsApp message usage plus daily Meta-reported approximate spend, attributed by tenant, Messaging account/WABA, phone, country, pricing category, pricing type, and tier. Enforce the existing plan message allowance before sends using Sayvors-side accounting; never invent Meta cost.

## Data sources

- **Real-time/local:** Sayvors outbound message attempts and delivery records. Used for quota enforcement and immediate UI counts.
- **Daily/provider:** Meta `pricing_analytics` with `COST` and `VOLUME`. Meta labels cost approximate. If COST is unavailable (including shared Solution Partner credit lines), store volume and mark cost unavailable.

## Storage

Add additive, idempotent tables:

- `whatsapp_spend_daily`: tenant, WABA, date/bucket, phone, country, pricing category/type/tier, volume, optional decimal cost, optional native currency, cost status, funding mode (`direct_client` vs `shared_credit_line`/platform-liable), WABA timezone, optional messaging account ID, source, fetched/updated timestamps. Unique attribution hash includes every pricing dimension per tenant/WABA/date.
- `whatsapp_quota_reservations`: tenant, channel, month, idempotency key, status (`reserved`, `consumed`, `released`), timestamps. Unique tenant/idempotency key.
- `whatsapp_monthly_usage`: tenant/month, used count, updated timestamp. Unique tenant/month.

Indexes support tenant/date and WABA/date rollups. Existing message rows are backfilled idempotently; no destructive migration.

## Real-time quota

- Every WhatsApp send reserves quota before the provider call.
- Reservation and monthly counter increment are atomic under a tenant/month row lock.
- Duplicate idempotency keys return the existing reservation.
- Successful sends and failures that may have reached Meta mark consumed and count once, preserving the existing failed-attempt quota policy.
- Only provably pre-send/transport-never-reached failures release and decrement.
- Typing/read indicators do not reserve quota; every actual Messages API send, including each multi-part AI reply, reserves independently.
- The existing plan allowance plus additive bonuses remains authoritative.
- Redis is not the quota source of truth; PostgreSQL arbitrates concurrent workers.

## Daily Meta sync

- Worker runs daily with bounded batches and concurrency.
- Fetches a rolling 7-day window to capture Meta adjustments.
- Uses DAILY granularity and dimensions COUNTRY, PHONE, PRICING_CATEGORY, PRICING_TYPE, TIER.
- Upserts idempotently by attribution hash.
- Stores null cost with `cost_status=unavailable` when Meta withholds COST.
- Retains status-webhook pricing fields (`billable`, `pricing_model`, category/type/subtype) and processes `sent` status for provider-confirmed reconciliation.
- Retires deprecated conversation analytics for spend; WABA `pricing_analytics` is authoritative for approximate Meta cost.

## APIs and UI

Tenant:
- Usage endpoint returns local used/limit/remaining, last sync time, Meta approximate spend, and breakdowns.
- Channels page shows a WhatsApp usage/spend card with “syncing from Meta” state.

Admin:
- Spend endpoint returns per-tenant/WABA totals and cost availability.
- Financials page shows WhatsApp spend and volume alongside existing finance rows.
- Client-direct Meta spend is shown separately and never subtracted from Sayvors platform margin; only platform-liable/shared-credit spend enters Sayvors COGS.

All routes are tenant-scoped or admin-gated. No token or raw provider payload is exposed.

## Regression tests

- Pricing response parsing, dimensions, volume/cost/currency, unavailable cost.
- Idempotent retry/upsert and rolling-window adjustments.
- WABA/phone/tenant attribution and date boundaries.
- Atomic quota race, duplicate reservation, release, and monthly reset.
- Existing send, template, AI reply, lead action, webhook, and billing tests.
- Tenant/admin RBAC and isolation.
- UI local count, pending sync, unavailable cost, and Arabic copy.

## Verification

Focused tests, full backend suite, migration guard and up/down/up, Gitleaks, TypeScript/ESLint/build, and staging smoke test with a WhatsApp test WABA.
