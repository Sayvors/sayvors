# Sayvors — 1M-User Scale Readiness Audit

**Date:** 2026-10-31
**Scope:** Security, performance/scalability, API surface, infrastructure/ops — evaluated against a 1,000,000+ user target.
**Baseline:** Re-verifies every open finding from `security-audits/00-audit-scope-and-architecture.md` (2026-09-13) and the 2026-09-21 remediation plan against current code on `development`, plus new passes over performance, API design, and infrastructure.
**Method:** Code-verified only. Every finding cites `file:line`. Items not re-verified are explicitly marked *carry-over*.

---

## 1. Executive summary

Since the September audit the platform has undergone a security and architecture
transformation: the 14 highest-risk findings from pass 00 are **fixed and verified
in code** (§3). The application layer — auth, tenant isolation, budget gates, job
queue, observability — is now genuinely production-grade and unusual for its stage.

**What is not ready for 1M users is the infrastructure layer.** The "production"
deployment is a single hand-provisioned 2 GB EC2 box running docker-compose, with
unscheduled backups, a single-node unauthenticated Kafka, a single-node
unauthenticated Redis, local-disk media storage, and migrations racing at container
boot. The application is stateless enough to scale horizontally *except* for one
breaker (uploads fall back to local disk) and one hot path (synchronous LLM SSE
streams pinning the DB pool).

**Posture:** application layer A−, infrastructure layer D.
**First things that break under load, in order:**
1. Single-writer Postgres (all jobs, outbox, rollups, analytics) — no replica, no PgBouncer in prod.
2. Synchronous SSE LLM/chat streams exhausting the 10-connection DB pool and request workers.
3. Local-disk uploads split-brain the moment a second API replica appears.
4. Single-node Kafka (RF=1, plaintext) loses messages on disk failure; single-node Redis holds all auth state.
5. Manual SSH deploys with mutable image tags — no rollback, no reproducibility.

**Bottom line:** the code can serve 1M users; the deployment cannot. The P0 list in
§8 is mostly infrastructure and is non-negotiable before any real scale.

---

## 2. Architecture today (what the audit found)

- **API:** FastAPI, ~38 routers mounted (`app/main.py:534-574`), 100 MB global body
  limit (`main.py:498`), request-ID + admin-audit + CSRF double-submit middleware,
  `/health` (liveness, no deps) vs `/readyz` (DB/Redis/Kafka, 503 on degradation)
  split (`main.py:592-623`), Prometheus `/metrics` with HTTP latency, job-queue
  depth/age, Redis memory (`main.py:626-689`).
- **Workers:** separate `python -m app.workers` process (`app/workers/main.py`)
  running 11 poll/consume loops + 4 job-queue lanes (`realtime`, `publishing`,
  `media`, `bulk`) via `JOB_LANES`/`WORKER_LOOPS` allowlists. API sets
  `RUN_BACKGROUND_WORKERS=false` in the worker deployment.
- **Job system:** Postgres-backed queue — `FOR UPDATE SKIP LOCKED` claims, leases
  with expiry, reaper, lane heartbeats, tenant admission control, hard deadlines
  (`modules/jobs/`, indexes `ix_jobs_lane_due`, `ix_jobs_lease`, `ix_jobs_hard_deadline`).
- **Billing:** durable credit wallet — `users.ai_credit_cents` + `billing_events`
  ledger, reserve/settle with idempotency keys, hold reaper, admin-editable rate
  card (`billing/pricing.py`, `PricingRate` model), plan entitlements
  (`billing/entitlements.py`), fail-closed (`BudgetExhausted` 402 /
  `BudgetUnavailable` 503 raised *before* any provider call).
- **Data:** Postgres 16 + pgvector (HNSW index on `document_chunks`), writer +
  reader engines with statement/idle-tx/lock timeouts and pool-headroom check
  (`database.py:18-85`), PgBouncer in dev compose.
- **Events:** Kafka (outbox → producer; analytics consumer re-resolves tenant
  from DB, payload `user_id` untrusted — `analytics/consumer.py:45-80`).
- **Frontends:** Next.js 16 `apps/web` (httpOnly cookie access token, CSRF
  double-submit, edge middleware) and `apps/admin`.

---

## 3. Fixed since the September audit (verified in code)

| # | Sept finding | Status | Evidence |
|---|---|---|---|
| 1 | Email OTP verify brute-force (no limit/attempt cap) | **FIXED** | 10/60s per IP+email (`email/router.py:133`) + 5-attempt budget that invalidates the code (`email/service.py:246-270`) |
| 2 | Arbitrary-recipient email relay | **FIXED** | Admin-only, same-domain recipients unless explicit flag, rate-limited (`email/router.py:61-102`) |
| 3 | Webhook verification fallthrough | **FIXED** | Fail-closed: no channel → 503, no secret → 503, bad sig → 403 + per-IP brute-force limit + per-channel 100/60s, 413 body cap (`channels/router.py:1291-1367`) |
| 4 | Global `response_strategies` (cross-tenant prompt injection) | **FIXED** | `tenant_id` column indexed (`review_engine/models.py:84`); all queries scoped via `tenant_id_of(user)` + `require_perm` RBAC |
| 5 | Fernet key = sha256(JWT_SECRET) | **FIXED** | Dedicated `CHANNEL_ENCRYPTION_KEY`, fail-fast in production, legacy-key fallback for rotation (`core/crypto.py`, `config.py:345-347`) |
| 6 | Access-token blacklist not checked | **FIXED** | `is_token_blacklisted(jti)` + `ver` claim vs `user.token_version` on every authenticated request (`core/deps.py:76-81`) |
| 7 | Tokens in URL query strings | **FIXED** | 120 s single-use `google_connect` tickets replace `?token=` (`channels/router.py:1373+`) |
| 8 | Shared Localith account across tenants | **FIXED** | Per-tenant Fernet-encrypted API keys (`localith/models.py:35`) |
| 9 | RAG data-source SSRF / port-scan oracle | **FIXED** | `_assert_connectable_host` blocks private/loopback/link-local with rebinding-safe resolution; driver errors sanitized (`rag/connectors.py:150-197`) |
| 10 | Kafka consumer trusts payload `user_id` | **FIXED** | Consumer re-resolves channel owner from DB; forged `user_id` logged and ignored; unknown channel dropped (`analytics/consumer.py:45-80`) |
| 11 | 7 in-process workers in the API pod | **FIXED** | Dedicated worker process, lane sharding, leases, reaper (`workers/main.py`, `modules/jobs/`) |
| 12 | JSON-embedded vectors (no vector index) | **FIXED** | pgvector column + HNSW `vector_cosine_ops` index (`alembic/versions/c3d4e5f6a7b8`, `rag/models.py:291`) |
| 13 | Unbounded LLM spend / no quotas | **FIXED** | Credit ledger with reserve/settle, per-call pre-auth, plan entitlements, per-tenant rate limits (`llm/router.py:42-44`, `billing/`) |
| 14 | No observability | **FIXED** | Structured JSON logs w/ request_id+tenant_id, GlitchTip w/ PII scrubbing, `/metrics`, `/readyz`, job-queue metrics |
| 15 | (New) Voice-note pipeline idempotency | **PRESENT** | `idempotency_key=asr:wa:{wamid}`, dedupe by `platform_message_id`, guard message ids (`channels/meta/consumer.py:912,1119,1899`) |

Also verified good: signup/login lockout + per-IP+per-email limits; refresh
rotation with reuse detection; admin audit-log middleware (`main.py:222-293`);
Kafka topics provisioned with explicit partition counts before consumers start
(`workers/main.py:109-116`); migration guard + single-head gate in CI; 139
migrations with wide `IF NOT EXISTS` idempotency; DB statement_timeout 30 s /
idle-in-tx 60 s / lock_timeout 5 s (`config.py:14-20`); schema indexing is strong
across messages, leads, review issues, billing events, jobs.

---

## 4. Security — remaining findings

### BLOCKER / MAJOR

**S1 — Prometheus exposed unauthenticated on 0.0.0.0** (MAJOR)
`docker-compose.prod.yml:160-161` publishes `9090:9090` on all interfaces (dev
compose correctly binds 127.0.0.1). Exposes internal metrics and the PromQL
query surface to the internet. *Fix:* bind `127.0.0.1:9090:9090` today; put
metrics behind the internal network only.

**S2 — Redis: no AUTH, single node** (MAJOR)
Prod compose Redis has no `requirepass` (`docker-compose.prod.yml:114-129`). It
holds OTPs, the token blacklist, and all rate-limit state — any container-network
compromise equals full auth-control compromise. `noeviction` + 128 MB is
deliberate and correct, but means a full Redis = hard auth outage, and no memory
alarm exists despite the metric being exported. *Fix:* `requirepass` + TLS
(`rediss://` already supported, `config.py:54-60`), ElastiCache/managed, alarm at
75% memory.

**S3 — Kafka: PLAINTEXT, no SASL, RF=1, auto-create on** (MAJOR, mitigated)
`docker-compose.prod.yml:131-154`. Forged events are now *mitigated* by the
consumer re-resolving tenants from DB (§3 #10), but the bus itself is still
unauthenticated and single-broker (message loss on disk failure). *Fix:* SASL/TLS
(client support already wired, `config.py:66-74`), `auto.create.topics.enable=false`,
3-broker KRaft or MSK — or drop Kafka for control events and keep the Postgres
jobs/outbox path (see §7).

**S4 — `str(e)` reaches clients in HTTPException details** (MEDIUM)
Residual info-leak class: `media/router.py:51,79,81,117,119,136,149,151` (502s
carry upstream provider error text), `locations/router.py:172,204,206`,
`localith/router.py:152,343`, `email/router.py:99,101,119`, `auth/router.py:161`.
*Fix:* generic client messages, full detail to logs/GlitchTip only.

**S5 — Account enumeration on signup** (MEDIUM, carry-over, still present)
`auth/service.py:65` raises `ValueError("Email already registered")` →
`auth/router.py:161` returns it verbatim as 409 detail. *Fix:* identical
201/202 response regardless of existence.

**S6 — No `.dockerignore`; build context is repo root** (MAJOR, supply chain)
Zero `.dockerignore` files in the repo; staging build context is the monorepo
root (`deploy-staging.yml:96-97`) — `.env`, `.env.prod`, `.git`, `.venv`,
`node_modules` all ship to the build daemon. COPY lines keep secrets out of
*layers*, but the daemon receives them. *Fix:* add `.dockerignore` per build
context immediately.

### MINOR / carry-over (not re-verified — flagged for triage)

- **S7** LLM chat rate limit fails open on Redis outage (`llm/router.py:44`,
  `fail_closed=False`) — spend is still bounded by the fail-closed credit gate,
  so this is availability-over-abuse-limit by design; document the decision.
- **S8** Admin console token in `sessionStorage` (Sept finding E-path;
  `apps/admin/lib/admin-api.ts`) — re-verify; httpOnly cookie preferred.
- **S9** Frontend localStorage keys (`sayvors_agent_draft`, `sayvors_agents`)
  not cleared on logout — re-verify in `apps/web`.
- **S10** OpenAPI `/docs` + `/redoc` enabled in production (`main.py:498` does
  not pass `docs_url=None`) — full API surface disclosure; disable in prod.
- **S11** Dev compose ships inline `PGBOUNCER_PASSWORD=postgres` (`docker-compose.yml:45`) — dev-only, acceptable.

---

## 5. Performance & scalability findings

### BLOCKER for 1M users

**P1 — Single-writer Postgres, no replica, no PgBouncer in prod.**
`DATABASE_READER_URL` defaults empty (`config.py:7`); writer/reader engines
exist and are wired (`database.py:36-55,164-173`) but nothing sets the reader.
PgBouncer is dev-compose-only. Every job claim, outbox drain, rollup, and
dashboard read hits one instance. *Fix:* RDS Multi-AZ + read replica wired into
`DATABASE_READER_URL`, PgBouncer in transaction mode in front of both, pool
sizing revisited (see P5).

**P2 — Local-disk upload fallback.**
`core/storage.py` falls back to local disk when S3/GCS is unconfigured; prod
compose mounts a single-node `uploadsdata` volume; `deploy/env.prod.example`
sets `S3_MEDIA_BUCKET` but leaves `S3_DOCS_BUCKET` commented; real user uploads
already sit on disk (`services/api/data/uploads/`, 27 files). Two API replicas =
split-brain media. *Fix:* force object storage in production (fail startup if
backend == local), migrate existing uploads, drain the volume.

**P3 — Alembic runs at container boot.**
`services/api/Dockerfile:31` and `docker-compose.prod.yml:47` run
`alembic upgrade head && uvicorn`. One replica is fine; N replicas racing the
same migration is a corruption/lock pileup. *Fix:* one-shot migration job in
the deploy pipeline (CI gate already verifies single head).

### MAJOR

**P4 — Synchronous SSE LLM streams pin the DB pool and request workers.**
`llm` chat/stream and `review-engine` generate-stream hold an authenticated
request (and its DB session) open for the full provider stream duration. With
`DB_POOL_SIZE=5 + overflow=5` per process, ~10 concurrent slow streams exhaust
the pool and every other endpoint queues behind them. The async job lanes
(realtime/media/bulk) are the right pattern — the *synchronous* streaming
endpoints are the remaining hot path. *Fix:* cap concurrent streams per
instance (semaphore), consider streaming from a job/SSE-bridge, raise pool via
PgBouncer, and add per-tenant stream concurrency to the budget gate.

**P5 — Pool/timeout sizing for scale.**
`DB_POOL_SIZE=5`, `MAX_OVERFLOW=5`, `pool_timeout=30s` (`config.py:11-13`) —
correct for a t4g.micro (the boot headroom checker even models 87 connections,
`database.py:58-85`), but at 1M users with PgBouncer transaction pooling these
need per-instance tuning plus `WORKER_REPLICA_COUNT`-aware provisioning.

**P6 — Offset pagination on hot lists.**
List endpoints use `limit/offset` with bounds (e.g. `limit ≤ 500`,
`channels/customers_router.py:28-29`). Fine to ~10k rows per tenant; deep
offsets on messages/inbox/reviews degrade at scale. *Fix:* keyset (cursor)
pagination on the high-volume lists (inbox threads, messages, review insights,
usage events).

**P7 — In-process `/metrics` breaks under `uvicorn --workers > 1`.**
Counters/histograms are module-level globals (`main.py:92-97`); with worker
processes each scrape hits a random worker with partial state. *Fix:*
`prometheus_client` with `PROMETHEUS_MULTIPROC_DIR`, or one worker per pod.

### MINOR

- **P8** `recompute_daily_rollup` runs per channel event (`analytics/consumer.py:272`) — fine today; watch hot channels, consider incremental aggregation.
- **P9** Global `body_limit=100 MB` (`main.py:498`) — bounded, acceptable; keep `MAX_UPLOAD_SIZE_MB=100` enforcement verified at the edge too.
- **P10** No load-test tooling in repo (k6/locust) despite checklist item J-1 — add scripts + run before scale-out.
- **P11** HNSW present; tune `ef_search`/dimensions and monitor index build time as `document_chunks` grows.

---

## 6. API surface findings

**A1 — No global rate limit** (MAJOR). Limits are per-endpoint and now broad
(auth, admin, webhooks, LLM chat 60/min/tenant, generation 100/min/channel,
assistant, media-sync, posts, team — verified across routers). But there is no
global request ceiling and no edge (Caddy) rate limiting; a zero-day expensive
endpoint is unprotected until a decorator is added. *Fix:* global middleware
floor + Caddy rate limiting.

**A2 — Budget/entitlement enforcement is real and fail-closed** (GOOD).
Every LLM call goes through `gateway.complete/stream` with `purpose` required,
credit reserve/settle, entitlement check (`gateway.py:145-230`), and one
`llm_usage_events` row per call (indexed on tenant/provider/model/purpose —
`llm/models.py:96-124`). Streaming settles in `finally` so client disconnects
still charge. This is the single most important scale-control in the codebase.

**A3 — Idempotency & dedupe** (GOOD). Jobs carry `idempotency_key`; voice-note
pipeline dedupes by `platform_message_id`/`wamid`; outbox gives at-least-once
with idempotent upserts; webhook dispatch is per-verified-channel rate-limited.
Gap: no idempotency-key convention on *client-facing* POSTs (double-submit
protection is CSRF-only). *Fix:* accept `Idempotency-Key` on billing/mutation
endpoints.

**A4 — Consistent validation & RBAC** (GOOD). Pydantic schemas everywhere
spot-checked; `TenantContext`/`require_perm` RBAC (`modules/team/context.py`)
applied to review-engine, customers, inbox; tenant resolution is centralized.

**A5 — Error schema inconsistency** (MINOR). Mix of `{"detail": ...}`,
`{"ok": ..., "message": ...}`, and raw strings; SSE endpoints stream errors
differently. *Fix:* single `Error` schema + global exception handler (currently
only `EntitlementDenied` has one, `main.py:519-530`).

**A6 — Versioning/deprecation** (MINOR). `/api/v1` prefix only; no deprecation
headers or sunset policy. Fine until v2.

**A7 — Test coverage** (MINOR). Real test suite exists (auth, voice notes,
pricing, RAG pgvector, model-schema parity, migration guard in CI). No
coverage gate; billing/ledger and jobs lane logic deserve dedicated suites
before they carry real money at scale.

---

## 7. Infrastructure & ops findings

Condensed from the full infra pass (all anchors verified):

| # | Finding | Severity | Anchor |
|---|---|---|---|
| I1 | "Prod" = one hand-provisioned 2 GB EC2, compose-only; no IaC, no autoscaling, no second AZ | **BLOCKER** | `docker-compose.prod.yml:1-5`; `deployments/` empty |
| I2 | Backups exist (`scripts/db_backup.py` → S3) but **nothing schedules them**; no PITR; restore never rehearsed | **BLOCKER** | `PRODUCTION-CHECKLIST.md:70` (I-10 open) |
| I3 | Boot-time alembic race at N replicas | **BLOCKER** | `Dockerfile:31`, compose `:47` |
| I4 | Single-node Kafka RF=1 plaintext; single-node Redis no-auth | **BLOCKER/MAJOR** | compose `:114-154` |
| I5 | Mutable `:staging` image tag; SHA tag built but unused | MAJOR | compose `:30-32`; `deploy-staging.yml:98-101` |
| I6 | API image runs as root, single-stage with compilers; web healthcheck calls `curl` that only exists in the deps stage (always fails) | MAJOR | `services/api/Dockerfile`, `apps/web/Dockerfile:4,22` |
| I7 | No image vuln scan, no dependabot, no automated CD, manual SSH deploy, no rollback | MAJOR | `.github/workflows` |
| I8 | No Grafana/alert rules, no tracing, no log shipping; `/metrics` multi-worker bug (P7) | MAJOR | `OPS-2-OBSERVABILITY.md:49-51` |
| I9 | Caddy is a single point; documented Cloudflare WAF target state not implemented | MAJOR | `deploy/Caddyfile` |
| I10 | Kafka/Redis/Postgres prod compose: Postgres is external RDS w/ `ssl=require` (good); Redis/Kafka single-node (see S2/S3) | — | compose |

**What already works well:** structured logging + request IDs across api/worker;
GlitchTip with PII scrubbing and release tagging; liveness/readiness split;
migration guard + single-head CI gate; config fail-fast gates
(`validate_production_settings()` requires explicit `CHANNEL_ENCRYPTION_KEY`,
`ADMIN_PASSWORD_HASH`, non-wildcard `ALLOWED_HOSTS`, non-localhost CORS —
`config.py:334-376`); gitleaks in CI; `.env*` untracked (`.env.prod` verified
not in git index); worker loop allowlist fails fast on typo'd names.

---

## 8. Prioritized roadmap to 1M users

### P0 — before any real scale (blocks everything)
1. **Backups:** enable RDS PITR ≥7d, schedule `db_backup.py`, rehearse
   `db_restore.py`, write the runbook. (I2)
2. **Object storage:** force S3/GCS for media *and* docs in production (fail
   startup on local backend), migrate existing uploads. (P2)
3. **Migrations out of boot:** one-shot pre-deploy migration job. (P3/I3)
4. **Data layer:** RDS Multi-AZ + read replica → `DATABASE_READER_URL`; PgBouncer
   (transaction mode) in prod; re-tune pools. (P1/P5)
5. **Kafka & Redis:** managed (MSK/ElastiCache) or consolidate control events
   onto the Postgres jobs/outbox queue (which already has leases, reaper, lanes
   — Kafka is only needed for analytics fan-out); SASL/TLS, auto-create off,
   RF≥3. (S3/I4)
6. **Box hardening today (cheap):** Prometheus → 127.0.0.1, Redis `requirepass`,
   digest-pinned images, `.dockerignore`, non-root `USER`. (S1/S2/S6/I5/I6)
7. **IaC + platform:** Terraform for VPC/ECS-or-EKS/RDS/ElastiCache/S3; retire
   the hand-rolled EC2. (I1)
8. **Streaming hot path:** per-instance stream concurrency cap + pool headroom;
   move heavy generation onto job lanes. (P4)
9. **Alerting:** Grafana + alerts on error rate, p99, job-queue depth/age,
   Redis memory ≥75%, Kafka lag, `/readyz`. (I8)
10. **Edge:** global rate limit at Caddy/ALB + WAF (Cloudflare per the documented
    target state). (A1)

### P1 — before 100k MAU
11. Cursor pagination on high-volume lists. (P6)
12. `prometheus_client` multiproc metrics. (P7)
13. CI/CD with health-gated deploy + rollback; image scanning; dependabot. (I7)
14. Kill `str(e)` client leaks; fix signup enumeration; disable `/docs` in prod.
    (S4/S5/S10)
15. k6 load test at 10× peak (J-1), chaos kill-mid-job (J-2), multi-replica
    double-processing test (J-3).
16. `Idempotency-Key` on mutation endpoints. (A3)

### P2 — hardening for 1M
17. OpenTelemetry tracing; log shipping off-box; Grafana dashboards.
18. Per-tenant rate-limit headers + quota dashboard (billing data exists).
19. Admin console httpOnly session cookie; frontend localStorage cleanup on
    logout (re-verify S8/S9).
20. Incremental analytics rollups; HNSW tuning; deep-pagination audits.

---

## 9. Honest capacity read

- **Today (single box, single RDS):** comfortably hundreds of tenants / low
  thousands of DAU; the job-queue design means background load (replies, sync,
  publishing) already scales by adding workers.
- **Hard ceilings in current shape:** one Postgres writer for *everything*
  (jobs + outbox + rollups + OLTP), synchronous SSE streams vs a 10-connection
  pool, local-disk media, single-node Redis/Kafka, one box.
- **After P0:** the architecture (stateless API + Postgres queue + lane-sharded
  workers + credit-gated AI) is the *right* shape for 1M users; the remaining
  work is operational (managed services, IaC, multi-AZ) rather than
  application rewrites.

---

## 10. Housekeeping

- `readiness-report.html` should be updated with the §3 "fixed" verifications
  and the P0 items above (repo rule: keep the consolidated report current).
- `docs/security/` should gain the durable write-ups for the credit ledger and
  the job-queue lease/reaper design once P0 lands (per repo convention: how it
  works, not what was fixed).
- Carry-over items S8/S9 and the SSE `str(e)` class need a 30-minute re-verification
  pass; everything else in this report was code-verified on 2026-10-31.

*No application code was modified for this audit.*
