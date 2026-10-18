# Sayvors — Master Action Items

Single consolidated list of every finding, fix, feature, and flag across the project.
Status values: `✅ Done`, `🚧 In Progress`, `⏸️ Pending`, `⏭️ For Later`, `🔴 Critical`, `🟠 High`, `🟡 Medium`, `🟢 Low`.

Source files are referenced by path. Items marked **"For later"** need a production VM — see `production-later.md`.

---

## 🔴 Critical — do before any deployment

| ID | Item | Status | Source | Effort | Notes |
|----|------|--------|--------|--------|-------|
| C-1 | JWT secret default `change-me-in-production` | `🔴 Critical` | `FIXES-NEEDED.md` A3, `config.py:6` | 1h | Fail-fast already in code; needs real secret in `.env` |
| C-2 | Committed DB password `mentee` in `alembic.ini` | `🔴 Critical` | `FIXES-NEEDED.md` A4 | 2h | Scrub from git history, inject via env |
| C-3 | RAG uploads never written to disk + no size cap | `🔴 Critical` | `FIXES-NEEDED.md` B1/B2 | 1–2 days | Every ingest fails with `FileNotFoundError` |
| C-4 | CSP unclosed quote / hardcoded localhost / unsafe-eval | `🔴 Critical` | `FIXES-NEEDED.md` C17–C19 | 1–2 days | `middleware.ts`, `next.config.ts` |
| C-5 | Zero Dockerfiles / stub compose / no CI / no backups | `🔴 Critical` | `FIXES-NEEDED.md` D1/D3/D6/D14 | Days | No deployment path at all |
| C-6 | Token blacklist never checked in `get_current_user` | `🔴 Critical` | `SECURITY-AUDIT.md` G1 | 2h | `is_token_blacklisted()` exists but unused |
| C-7 | Access token returned in JSON body | `🔴 Critical` | `SECURITY-AUDIT.md` G2 | 4h | XSS-readable token |

---

## 🟠 High — within two weeks

| ID | Item | Status | Source | Effort | Notes |
|----|------|--------|--------|--------|-------|
| H-1 | SSRF in media publishing (IG/FB publish probe) | `⏸️ Pending` | `readiness-report.html` SEC-H1 | ~1 day | Route through `fetch_pinned` guard; stop reflecting status |
| H-2 | LLM chat: no rate limit, no metering | ✅ Done | `readiness-report.html` SEC-H2 | ~1 day | Redis sliding window (60/min/tenant) + reserve/settle budget enforcement on `/llm/chat` and `/llm/chat/stream` |
| H-3 | WebSocket auth skips revocation | `🟠 High` | `readiness-report.html` SEC-H3 | 2–4 days | Blacklist + `token_version` checks on connect |
| H-4 | Unindexed `platform_message_id` | `🟠 High` | `readiness-report.html` SCALE-2 | ~1 day | Full-table dedupe scan per webhook |
| H-5 | Inbox N+1 (~1,500 queries per dashboard load) | `🟠 High` | `readiness-report.html` SCALE-3 | 3–5 days | Denormalize counters; cursor pagination |
| H-6 | CI runs no tests | ✅ Done | `readiness-report.html` OPS-3 | 1–2 days | .github/workflows/ci.yml runs pytest+eslint+tsc before image builds; deploy-staging gated on CI pass |
| H-7 | Staged topology stale (worker split not deployed) | `🟠 High` | `readiness-report.html` OPS-4 | ~half day | Merge `development` → `staging`; `RUN_BACKGROUND_WORKERS=false` |
| H-8 | `platform_message_id` index | `🟠 High` | `FIXES-NEEDED.md` B24 gap G3 | ~1 day | Same as H-4 |
| H-9 | Webhook: require secret to process payload | `🟠 High` | `SECURITY-AUDIT.md` G3 | ~half day | Gap remains in B24 fix |
| H-10 | Rate limiter fail-open when Redis down | `🟠 High` | `SECURITY-AUDIT.md` G5 | ~1 day | Fail closed on auth-critical paths |

---

## 🟡 Medium — within a month

| ID | Item | Status | Source | Effort | Notes |
|----|------|--------|--------|--------|-------|
| M-1 | Account deletion / GDPR export | `🟡 Medium` | `readiness-report.html` SEC-M1 | 3–4 days | Owner-initiated delete + export |
| M-2 | Encrypt message content, phones, webhook secrets | `🟡 Medium` | `readiness-report.html` SEC-M2 | 3–5 days | Fernet with existing key |
| M-3 | Webhook rate limit global per platform | `🟡 Medium` | `readiness-report.html` SEC-M3 | ~half day | Key per channel/webhook-secret |
| M-4 | Reviewer-photo download lacks SSRF guard | `🟡 Medium` | `readiness-report.html` SEC-M5 | ~2h | Wrap in `assert_public_http_url` |
| M-5 | Lead pipeline uses `channels.view` not `edit` | `🟡 Medium` | `readiness-report.html` SEC-M6 | ~1h | One-line permission change |
| M-6 | Notification PATCH writes owner's row | `🟡 Medium` | `readiness-report.html` SEC-M7 | ~2h | Key prefs by actor id |
| M-7 | CSP allows `'unsafe-inline'` scripts | `🟡 Medium` | `readiness-report.html` SEC-M8 | 1–2 days | Nonce-based CSP |
| M-8 | No retention on 4 growing tables | `🟡 Medium` | `readiness-report.html` SCALE-4 | 2–3 days | webhook_events, channel_messages, notifications, llm_usage |
| M-9 | DB pool 100 conns/process vs small RDS | `🟡 Medium` | `readiness-report.html` SCALE-5 | ~1 day | Pool 5+5 + statement timeouts |
| M-10 | Redis per-tab pub/sub, unpooled, no re-arm | `🟡 Medium` | `readiness-report.html` SCALE-6 | 2–3 days | Shared subscriber + prober |
| M-11 | DB pool config bare defaults | `🟡 Medium` | `FIX-PLAN-SCALE.md` 0.1 | hours | `pool_size=20`, `max_overflow=40`, `pre_ping`, `recycle` |
| M-12 | pgvector search rewrite | `🟡 Medium` | `FIX-PLAN-SCALE.md` 0.2 | 2–3 days | Biggest scalability win |
| M-13 | RAG upload persistence | `🟡 Medium` | `FIX-PLAN-SCALE.md` 0.3 | 1–2 days | Stream to storage, size cap |
| M-14 | RAG ingest worker leasing | `🟡 Medium` | `FIX-PLAN-SCALE.md` 0.4 | ~1 week | `FOR UPDATE SKIP LOCKED`, crash recovery |
| M-15 | Auth fail-closed + cleanup | `🟡 Medium` | `FIX-PLAN-SCALE.md` 1.1/1.2 | Days | Fail closed when Redis down; batched cleanup |
| M-16 | LLM quotas, budgets, session hygiene | `🟡 Medium` | `FIX-PLAN-SCALE.md` 1.3 | Days | Per-user quotas, honor max_tokens, pooled clients |
| M-17 | Redis/Kafka/Outbox hardening | `🟡 Medium` | `FIX-PLAN-SCALE.md` 1.4 | Days | Fail closed, SKIP LOCKED, degradation signals |

---

## 🟢 Low — nice to have

| ID | Item | Status | Source | Effort | Notes |
|----|------|--------|--------|--------|-------|
| L-1 | Token `iss`/`aud`/`iat` verification | `🟢 Low` | `FIXES-NEEDED.md` A11 | Low | Add to `decode_token` |
| L-2 | Remove deprecated X-XSS-Protection header | `🟢 Low` | `FIXES-NEEDED.md` C20 | Low | `middleware.ts` |
| L-3 | Remove dead code (`validation.ts`, `performance.ts`) | `🟢 Low` | `FIXES-NEEDED.md` C28/C39 | Low | Never wired in |
| L-4 | Remove boilerplate SVGs from `public/` | `🟢 Low` | `FIXES-NEEDED.md` C32 | Low | Dead assets |
| L-5 | Unify password validation rules | `🟢 Low` | `FIXES-NEEDED.md` C30 | Low | AuthForm vs validation.ts differ |
| L-6 | Add favicon variants | `🟢 Low` | `FIXES-NEEDED.md` C33 | Low | apple-touch-icon, favicon.ico |
| L-7 | Client-side file size validation | `🟢 Low` | `FIXES-NEEDED.md` C38 | Low | UX only |

---

## 📦 Product features (pending queue)

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| P-1 | Facebook dashboard section | `⏸️ Pending` | `PENDING-QUEUE.md` #1 | Deferred by user request |
| P-2 | Response tone selector | `✅ Done` | `PENDING-QUEUE.md` #2 | Already implemented |
| P-3 | Multi-location expansion | `⚠️ Partial` | `PENDING-QUEUE.md` #3 | Gaps: Localith cap, add-location wizard, reviews UX |

---

## 🗂️ Analytics upgrade (4-phase plan)

| Phase | Item | Status | Source |
|-------|------|--------|--------|
| Phase 0 | `channel_daily_metrics` table + `handled_by` enum + rollup job | `⏸️ Planned` | `TODO-analytics.md` |
| Phase 1 | Overview page: response health, scorecard, unanswered, AI takeaway | `⏸️ Planned` | `TODO-analytics.md` |
| Phase 2 | Growth page: customer growth, follower growth, review velocity | `⏸️ Planned` | `TODO-analytics.md` |
| Phase 3 | Insights page: "what customers ask", heatmap, AI performance | `⏸️ Planned` | `TODO-analytics.md` |
| Phase 4 | Benchmark page: industry bands, response-time vs market | `⏸️ Planned` | `TODO-analytics.md` |

---

## ⚙️ Job queue (unified processing design)

**Status: Built (Phase 0+1 complete).** See `docs/specs/2026-10-10-unified-job-processing-design.md`.

| Item | Status | Notes |
|------|--------|-------|
| Unified `jobs` table | ✅ Built | `app/modules/jobs/models.py`, migration `z3a4b5c6d7e8` |
| Topic provisioning with real partitions | ✅ Built | `app/modules/kafka/topics.py` |
| Producer hardening (`acks=all`, idempotence) | ✅ Built | `app/modules/kafka/client.py` |
| Consumer manual offset commit | ✅ Built | `app/modules/kafka/client.py` |
| Outbox `FOR UPDATE SKIP LOCKED` drain | ✅ Built | `app/modules/outbox/worker.py` |
| DLQ + operator replay | ⏸️ Not built | Phase 2 pending |
| Lane consumers (realtime/publishing/media/bulk) | ✅ Built | `app/modules/jobs/runner.py` — JobRunner per lane |
| Migrate `ingest_jobs`, `scrape_jobs`, `stt_jobs`, `tts_jobs` | ⏸️ Not built | Phase 2 of design |
| `post.publish` job handler | ✅ Built | `app/modules/jobs/handlers/post_publish.py` |
| `POST /api/v1/channels/publish` endpoint | ✅ Built | `app/modules/channels/publish/router.py` |

---

## 🏗️ Infrastructure (production VM needed)

All items below are **For Later** — see `production-later.md`. None can run on a t3.small or laptop.

| Item | Status | Source |
|------|--------|--------|
| 3-broker Kafka cluster | `⏭️ For Later` | `docker-compose.prod.yml` |
| Redis HA (multi-AZ, AOF, alarm) | `⏭️ For Later` | `readiness-report.html` §6 |
| Postgres read replica + connection pool tuning | `⏭️ For Later` | `FIX-PLAN-SCALE.md` 0.1 |
| S3 buckets for uploads (`S3_DOCS_BUCKET`) | `⏭️ For Later` | `readiness-report.html` §4 |
| Second box / container platform (HA) | `⏭️ For Later` | `readiness-report.html` §4 |
| RDS PITR + restore rehearsal | `⏭️ For Later` | `readiness-report.html` OPS-1 |
| CI/CD pipeline (GitHub Actions) | `⏭️ For Later` | `FIXES-NEEDED.md` D6 |
| Monitoring (Sentry + Prometheus + Grafana) | `⏭️ For Later` | `readiness-report.html` OPS-2 |

---

## ✅ Already verified fixed (do not redo)

| Item | Source | Evidence |
|------|--------|----------|
| OTP verification bypass | `readiness-report.html` SEC-C1 | `auth/service.py:739–768`, tests pass |
| Sequential AI consumer replaced | `readiness-report.html` SCALE-1 | `meta_events_worker.py`, bounded concurrency |
| Token type enforcement (`type == "access"`) | `FIXES-NEEDED.md` A1 | `deps.py:31–33` |
| Forgot-password token not leaked | `FIXES-NEEDED.md` A2 | `router.py:217–221` |
| TrustedHostMiddleware | `FIXES-NEEDED.md` A14 | `main.py:130–131` |
| Webhook HMAC verification | `FIXES-NEEDED.md` B24 | `router.py:191–209` |
| OPS-2 observability | `readiness-report.html` OPS-2 | Sentry + JSON logs + Request-ID + `/readyz` + HEALTHCHECKs + `/metrics` (just added) |

---

## File locations

| File | Location | Purpose |
|------|----------|---------|
| This index | `docs/tracking/action-items.md` | Master consolidated list |
| Production-later items | `docs/tracking/production-later.md` | Deferred infra items |
| Original source files | `docs/tracking/source-files/` | Copies of root-level files |
| Security audit | `docs/security/SECURITY-AUDIT.md` | Full security audit |
| Job queue design | `docs/specs/2026-10-10-unified-job-processing-design.md` | Approved design |
| Readiness report | `readiness-report.html` | HTML readiness report |
