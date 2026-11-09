# 2026-11-08 — Phase 1 MVP Deployment Audit (WhatsApp + Google)

Full-stack pre-launch inspection for the Phase 1 MVP (WhatsApp + Google Business Profile channels), framed for 1M-user readiness and a **managed-cloud (GCP/AWS) deployment target**.

**Method.** Three parallel deep-audit passes over the current tree (HEAD `7d9c589c` era, including the Nov 7–8 code: email outbox + redesign, admin tenant suspension/export/purge, Meta delivery reconciliation, Google location wizard, credits/pricing, quota-stop for AI replies), covering: API core (auth/OTP/passwords/sessions/tenancy/config/DB), integrations (WhatsApp/Google/LLM/email), and jobs + frontends + infra. Every contested or headline claim was re-verified against the code in this tree, and results are reconciled against the prior ledger (`readiness-report.html`, last pass 2026-11-03). Line references are to the tree at audit time.

**Deliverable status:** findings document only. No fixes implemented in this pass.

---

## Executive verdict

The architecture and most of the security posture are genuinely production-grade and re-verified in code: the Oct-12 OTP takeover is fixed with regression tests; tenant isolation, webhook HMAC verification, SSRF guards, the fail-closed LLM budget gate, encrypted-at-rest PII, queue-lane mechanics, admin authorization, and fail-closed production config validation all held under re-audit.

What stands between here and a safe Phase 1 launch:

1. **One new critical isolation break** (cross-tenant job hijack via `POST /jobs`) — small fix, must land before launch.
2. **Two config/deploy hygiene gaps that can silently disarm the entire security stack** (`TESTING` env flag; env-file swap trap) — each is a one-line/one-script guard.
3. **The operational insurance layer does not exist as operated today**: nothing schedules backups, no alerting is configured, error tracking is optional. On the managed-cloud target these become launch work, not deferrals — the single-box items (Redis/Kafka/memory) mostly dissolve in the platform move, but only if the move is part of launch.

Everything else is hardening: ~20 cheap, well-scoped diffs with no architectural impact.

---

## 1. New findings — launch blockers

### 1.1 · P0 · Cross-tenant job hijack through the jobs API

**Where:** `services/api/app/modules/jobs/router.py:45-73`, `app/modules/jobs/handlers/*`

`POST /api/v1/jobs` accepts **any** `job_type` plus an arbitrary `payload` dict from **any authenticated user** — no permission gate (`require_perm` never called), no rate limit, no entitlement/credit check, and client-settable `max_attempts`/`priority`/`lane`.

The job handlers then fetch domain rows by bare ID with **no tenant filter**:

```python
# jobs/handlers/review_request_send.py:19
row = await db.get(ReviewRequest, request_id)   # no tenant check
```

`deliver_request` (`modules/analytics/review_requests.py:142-207`) resolves the sending asset by `row.user_id` — so tenant A can re-drive tenant B's queued/failed review request **from B's connected WhatsApp number, to any phone number, billed to B**. The same bare-ID pattern exists in `handlers/tts_job.py:58-62`, `handlers/stt_job.py:44-48` (re-bills via `stt_job.user_id`, `stt_job.py:96-101`), and `handlers/rag_ingest.py:31-35`.

**Why it matters:** this is a multi-tenant isolation break on the exact channels Phase 1 launches with, plus an unauthenticated-cost queue-flooding vector (bulk lane retries ×10). Prior adversarial passes found tenant isolation clean everywhere else — this endpoint is the exception.

**Fix class (small):** tenant-filter every handler lookup (`user_id == job.tenant_id`), and gate + rate-limit `POST /jobs` (permission + quota), validating `max_attempts` server-side. Consider `ON CONFLICT` for the idempotency insert race (`jobs/service.py:63-73`).

### 1.2 · P1 · `TESTING=true` in a deployed env silently disarms the security stack

**Where:** `app/config.py:216`, `app/modules/channels/meta/webhooks/router.py:56`, `app/config.py:360-410`

`TESTING: bool = False` is a normal pydantic setting read from the env file — deploy-environment controllable, not just a conftest fixture. When set in a deployed environment:

- the **Meta webhook signature check is skipped entirely** (`if not settings.TESTING:` — unauthenticated message injection into WhatsApp ingestion);
- **~25 rate-limit sites across auth/channels/assistant are disarmed** (brute-force controls off);
- IG cache guards turn off.

`validate_production_settings()` checks JWT length, admin hash, hosts/CORS/redirects, the open-relay guard and the SSRF flag — but **never checks `TESTING`** (nor `GOOGLE_REVIEWS_MOCK`, which would fabricate reviews in production, `config.py:229`). One copy-pasted env file turns the WhatsApp ingress unauthenticated with zero boot-time signal.

**Fix class (one line each):** reject `TESTING=true` and `GOOGLE_REVIEWS_MOCK=true` in the production validator (or stop parsing `TESTING` from env entirely and set it in code from conftest).

### 1.3 · P1 · Deploy env-file trap — wrong file silently skips every production check

**Where:** root `.env.prod` (on-disk stub, git-ignored), `.env` (dev), `docker-compose.prod.yml` (`env_file: ./.env.prod`), `app/config.py:360` (validator gated on `ENVIRONMENT`)

The root `.env.prod` on disk is a stub (`ENVIRONMENT=production`, version, GlitchTip only — no `DATABASE_URL`, `JWT_SECRET`, `CHANNEL_ENCRYPTION_KEY`). Deploying it fails closed at boot (good), but the natural operator "fix" is copying the developer-local `.env` — which carries `ENVIRONMENT=development` and therefore **skips every production validation silently**, including the unsubscribe-origin guard, encryption-key requirements, and the two validators in §1.2. The complete template exists at `deploy/env.prod.example` ("Copy to ~/sayvors/.env.prod on the EC2") but nothing enforces that flow.

**Fix class:** deploy-script assertion that the env being shipped has `ENVIRONMENT=production` and the required key set before `docker compose up`; or delete the misleading stub.

---

## 2. New findings — fix before/at launch

### 2.1 · Bulk email channel has no quota gate

`modules/analytics/router.py:783-795` — `skipped_quota` is computed only for `channel == "whatsapp"`. Email bulk sends (up to 500 contacts per call, unlimited calls, `reviews.reply` permission only) flow through Resend unbounded — a spam-complaint and domain-reputation risk on a shared sending domain at scale. WhatsApp is quota-capped (correct).

### 2.2 · No alerting as operated

`deploy/prometheus.yml` scrapes but defines **no rules**; there is no Alertmanager service; `GLITCHTIP_DSN` is empty in `deploy/env.prod.example` — as templated, production has no error tracking at all. The compose comment for Redis says "capacity alarms are the correct control" (`docker-compose.prod.yml:136-139`) — no alarm exists. At launch scale, queue stalls, OOMs and 5xx storms are invisible until customers complain. (The one stuck-lane Sentry alert in `jobs/reaper.py:66-74` needs Sentry configured to go anywhere.)

### 2.3 · OPS-1 (carried, still open) — backups unproven

`scripts/db_backup.py` / `db_restore.py` exist but nothing schedules the dump (no cron/systemd/compose/workflow), `S3_DOCS_BUCKET` stays commented out in `deploy/env.prod.example:84`, and `db_restore.py:99-119` `DROP`s whatever `DATABASE_URL` it is handed, guarded only by prose. **Managed-cloud framing:** automated backups + PITR on Cloud SQL / managed DB answers most of this, but the **rehearsed restore + runbook** remains mandatory launch work regardless of platform.

### 2.4 · LLM output hygiene — customer-facing links are unvalidated

`modules/channels/meta/consumer.py:2359` and `:3651` — generated replies are post-processed only to strip internal markers (LEAD/SEND_ITEM/CHOICES); the remaining free text ships **verbatim to the customer's WhatsApp**. The only link defenses are advisory prompt lines ("never invent…"). Input-side prompt-injection posture is strong (see §6), but nothing enforces output hygiene: a hallucination or successful indirect injection via catalog/review/grounding content emits a customer-visible link — phishing under the tenant's brand, at scale, on the business number. **Fix class:** scan final text for URLs against an allowlist (or strip) before `send_text_message` — one guard function at the two sites.

### 2.5 · ~~Email outbox rows strand in `"sending"` forever~~ — RESOLVED (correction)

The audit pass initially flagged stranded `"sending"` rows (worker crash between claim-commit and delivery). **Re-verification during this audit found the fix already in the tree** (Nov 7–8 outbox work, commit `39abb2ac`): `requeue_stale_sending` re-ages stale in-flight rows (`email/outbox.py:331-355`, REAP_BATCH=100) and is called every worker poll cycle (`outbox.py:384`), safe because each row carries a Resend `Idempotency-Key`. Pinned by `tests/test_email_outbox.py`. No action needed.

---

## 3. New findings — hardening (cheap diffs, P2/P3)

| # | Finding | Where |
|---|---------|-------|
| H1 | Unsubscribe HMAC reuses `JWT_SECRET` with a hardcoded `"sayvors-email"` fallback — rotating JWT_SECRET silently invalidates every outstanding opt-out link (CAN-SPAM/GDPR failure mode); dedicated `EMAIL_UNSUBSCRIBE_SECRET` needed | `email/outbox.py:60-66`; same fallback chain in `channels/service.py:201` (`hash_contact_phone`) |
| H2 | Gemini provider client has no timeout / retry cap (SDK defaults) — a hung call holds a Kafka consumer slot; the OpenAI-compatible provider is disciplined (`AsyncOpenAI(timeout=45.0, max_retries=0)`) | `llm/providers/gemini.py:26` vs `openai_compatible.py` |
| H3 | WhatsApp send pacing **fails open** on Redis outage (deliberate + tested) — during an outage a bulk campaign is unthrottled toward Meta's ~80 msg/s per number; 429s are transient-retried downstream; recommend a process-local fallback limiter | `channels/meta/providers/whatsapp.py:109-124` |
| H4 | OTP email HTML injection: unauthenticated `purpose` field (max 40 chars) rendered unescaped into branded emails from Sayvors' domain — phishing amplifier | `email/router.py:54` → `email/templates.py:199`, subject at `email/service.py:179` |
| H5 | API ships no app-level security headers (HSTS / nosniff / frame / referrer-policy); Caddy adds HSTS at the edge — finish at the app layer, especially given `SameSite=None; Secure` cross-site auth cookies | `app/main.py:536-550` |
| H6 | Retention cleanups on `login_attempts` / `refresh_tokens` have no supporting indexes on the filter columns — full scans on the largest auth tables (every failed login inserts a row) while holding pool connections | `auth/models.py:52-61`; sweeps at `auth/service.py:937-969` |
| H7 | `/auth/verify-otp` has per-IP limit only; resend refreshes the 5-attempt code budget — add per-email verify limit + resend cooldown (hardening, not a hole: ceiling stays tens of guesses/hour against a 1-in-1M code) | `auth/router.py:403`; resend reset at `auth/service.py:166,209-212` |
| H8 | `ipwho.is` third-party geo-lookup on every password reset — privacy/DPA surface + unauthenticated latency dependency on the reset path | `auth/service.py:650-667` |
| H9 | Legacy plaintext PII: decrypt-fallback returns cleartext for non-Fernet rows; verify the `contact_phone_hash` migration **encrypted** (not just hashed) pre-migration `contact_phone` values | `channels/service.py:96-102`; `channel_messages`/`channel_threads` models |
| H10 | 50MB CSV parsed synchronously on the event loop, one ORM object per row — stalls the worker; 100MB `await file.read()` inside a 768MB-container | `review_engine/csv_router.py:37-39`, `csv_service.py:31-59`; `media/router.py:44`; `main.py:532` (global 100MB body limit) |
| H11 | Jobs registry advertises six types with no registered handler (`meta.send_reply`, `meta.send_template`, `media.publish`, `media.process`, `databank.ingest`, `scrape.url`) — anything enqueued burns retries then dies `no_handler`; `jobs/pacer.py` is dead code (real pacing lives in the WhatsApp adapter — verified live) | `jobs/types.py:17-37`, `handlers/__init__.py:19-26`, `jobs/pacer.py` |
| H12 | Admin "rate limit" is a no-op (10,000/min per IP per path) — login lockout is real, but the throttle pretends; add a meaningful limit or drop it. No IP allowlist on admin | `admin/router.py:287-292` |
| H13 | `submit_job` idempotency is read-then-insert against the unique key — concurrent submits race, loser 500s; use `ON CONFLICT`; validate client-supplied `lane`/`priority`/`max_attempts` server-side | `jobs/service.py:63-73`, `jobs/router.py:62-67` |
| H14 | Locations bulk CSV template round-trip lacks formula-injection (`=+-@`) guarding — self-contained (merchant's own data) today; the writer pattern must never be reused for cross-tenant exports | `locations/bulk.py:76-102` |
| H15 | No campaign-level cancel/progress — a 500-message campaign is 500 independent jobs, cancellation is per-job only (per-row accounting itself is good) | `analytics/router.py:744-830`, `jobs/router.py:104-119` |
| H16 | `/metrics` counters are per-process globals under 2 uvicorn workers — scrapes undercount ~50% nondeterministically (multiproc mode or 1 worker/pod) | `app/main.py:95-100` |
| H17 | Alembic runs inside API container boot — safe at 1 replica, a race the moment api scales; move to a deploy step before scaling | `docker-compose.prod.yml:60` |
| H18 | P3 batch: JWT lacks `iss`/`aud` claims (alg pinned, no confusion — cheap defense-in-depth); password policy min-8/no-max/no common-check, bcrypt 72-byte truncation; hard lockout (5/15min) enables targeted login-DoS of a known tenant email; inbox fallback path loads up to 10,000 rows when `channel_threads` is empty; Fernet key is bare `sha256(secret)` (fine while the key is high-entropy) | `security.py:38-59`; `auth/schemas.py:8,51`; `config.py:96-97`; `channels/service.py:~2400`; `core/crypto.py:34-36` |

## 4. Compliance / documentation note

**Opt-out gates business-initiated sends only.** Inbound-triggered AI session replies still answer a contact whose lead has `opt_out` — the opt-out regex cancels *scheduled* template/follow-up actions only. This matches Meta's 24-hour customer-service-window semantics, but **write the decision down**: at complaint-investigation scale you will be asked, and "the code does X" should be a documented decision, not a discovery.

---

## 5. Corrections — claims from this pass that did not survive verification

Recorded so nobody re-chases them:

- ❌ "No outbound rate pacing toward Meta" — **false.** Bulk review-requests route `send_whatsapp_text` → `get_adapter("whatsapp")` → `adapter.send_text_message`, and every adapter send acquires the Redis token bucket (`whatsapp.py:142`, 80 msg/s per number). `jobs/pacer.py` being dead code is item H11, not a blocker. (LAUNCH-P6 verified live.)
- ❌ "AI replies have no retry / no DLQ" — **false.** The `ai_reply_status` state machine with pending-row re-drive, crash-after-send reconciliation, and terminal `ambiguous` doctrine is present and wired (`consumer.py:1085-1104, 1601-1717, 2277-2690`). The quoting agent misread `_send_system_text` (`consumer.py:1294`) — deliberately best-effort system lines. Ledger residual stands: rows whose outbox retry budget is exhausted stay `pending`/`dead` awaiting the (still unbuilt) operator recovery sweep. (LAUNCH-B2/B3 verified live.)
- ✅ Old OTP takeover (SEC-C1) — **confirmed fixed**: commit `69f7be39`; guard at `auth/service.py:835-844` rejects OTP login for verified accounts before any code comparison; 5 regression tests in `test_verify_otp.py`; no residual bypass path (the only other OTP verify endpoint, `/email/otp/verify`, grants no session and sets no `email_verified`).

---

## 6. Verified solid — do not re-fix

**Auth & sessions.** bcrypt cost 12; anti-enumeration everywhere (identical responses, IntegrityError race handling); JWT fixed-algorithm decode + explicit per-surface `type` claims; `jti` blacklist **fail-closed** when Redis is down; `token_version` revocation on password change/logout-all; refresh rotation with reuse-detection killing the whole family + device binding; 12h rolling sessions; one-time Google-connect tickets (120s getdel) so tokens never ride URLs; httpOnly Secure cookies + double-submit CSRF; logout blacklists the presented jti; trusted-proxy-aware client IP; Google ID-token and Facebook `debug_token` verification.

**Tenancy & authorization.** DI-enforced RBAC (`TenantContext`/`require_perm`) resolving tenant from DB on **every** endpoint, suspension enforced in `get_current_user`; hot routers sampled clean of IDOR (inbox media 404-not-403 with ownership, `_get_owned_reply`, cursor channel+contact match, tenant-scoped job reads); orphan admin sub-routers mounted behind `require_admin`.

**Webhooks.** HMAC-SHA256 timing-safe over raw body, verify-before-parse, 1MB cap, 6,000/min Redis limit fail-closed before any body read; legacy route 410; ingest dedupe on unique `(provider, external_event_id, event_type)` with outbox enqueue in the same transaction; tenant resolved via DB lookup, never payload routing.

**SSRF.** `core/http.py` requires every resolved address public (fail-closed); `core/pinned_http.py` dials the pre-validated IP (DNS-rebinding-proof) with per-hop redirect revalidation and byte caps; RAG DB connector same guard + regex-validated table names; prod validator forbids private-host RAG.

**AI/LLM.** Budget gate truly fail-closed — reserve from the durable Postgres wallet **before** the provider call, `BudgetExhausted`(402)/`BudgetUnavailable`(503) short-circuit, refund on provider failure, DB error ⇒ refuse to run unmetered; rate-limited `/chat` + `/chat/stream`; single budget enforcement inside the gateway boundary (test-enforced); prompt-injection posture: untrusted blocks framed "DATA, never instructions", tools take `tenant_id` from server context, attachment bytes never sent to the model, model-echoed phones re-validated via `phonenumbers`.

**Double-send prevention.** Unique partial index on `platform_message_id`; `ai_reply_status` machine; `_has_outbound_reply` closes the crash window; `MetaAmbiguousError` terminal-never-retried; Kafka offsets committed only after the DB outcome; MAX_RETRIES=10 capped backoff.

**WhatsApp + Google integrations.** Credentials/tokens/PINs Fernet-encrypted with prod-required dedicated key; phones HMAC-hashed for lookup; OAuth state one-time hashed + atomic claim + 10-min TTL (both providers); GBP client with refresh leeway, 401 re-issue, 429 backoff+jitter honoring `Retry-After`, bounded sync (`MAX_REVIEW_PAGES=10`), reply read-back verification; per-channel polling leases (`polling_locked_until`) — multi-instance safe; permanent Google errors expire the channel + notify instead of retrying forever; E.164 discipline (`region=None`, never guess).

**Email.** Provider calls only from the durable outbox worker; suppression checked pre-enqueue; local + Resend idempotency keys; Svix-verified bounce/complaint webhooks (HMAC + 300s window); permanent suppression + `newsletter=False` on complaint/unsubscribe; `List-Unsubscribe` + One-Click headers; `PUBLIC_API_URL` origin guard for unsubscribe links (prod-enforced, commit `f2980dea`); admin-only send endpoint, domain-restricted, kill-switch required off in prod.

**Database.** Migration graph single head, 168 revisions, idempotent patterns (221 `IF NOT EXISTS`), enum `create_type=False` discipline; hot-path composite indexes (inbox, threads, leads, usage events, trgm on review insights); pool right-sized with statement/idle-in-tx/lock timeouts, `pool_pre_ping`, reader engine; no SQL injection (raw `text()` sites interpolate internal constants only; input always bound).

**Job queue.** `FOR UPDATE SKIP LOCKED` claims; leases + expired-lease reaper; per-lane DLQ outbox events + `job.dead/failed/succeeded` emitted atomically; hard deadlines cancel instead of run-late; priority aging prevents bulk starvation; per-tenant in-flight cap (Redis, TTL, fail-open — table is truth); retention swept terminal rows; scheduler loops idempotent-by-design with atomic leases/advisory locks/daily markers + deploy jitter.

**Bulk ops.** WhatsApp bulk quota-enforced before queueing with honest per-row accounting; 500-contact cap; durable per-row jobs, idempotent delivery; locations bulk CSV (500 rows / 5MB, per-row ownership verification, per-row report, feature-gated).

**Admin.** `apps/admin` is the single admin surface; server-side `require_admin` on every route (typed JWT, rejects user JWTs); httpOnly path-scoped SameSite=strict cookie + `X-Requested-With`; operator accounts with per-account + global lockout; full mutation audit log; suspend/export/purge gated server-side, purge requires typing the tenant email.

**Frontends.** httpOnly-cookie auth only (no token in JS) on both apps; CSRF double-submit; nonce CSP + `strict-dynamic` + HSTS at edge; `safeHref` scheme allowlist in chat/analytics renderers (tested); only static-constant `innerHTML` usages; no `NEXT_PUBLIC_` secret leakage; session localStorage cleared on logout; bounded buffers (500-message cap) + virtualized lists.

**Deploy hygiene.** Caddy edge-blocks `/metrics` `/docs*` `/openapi.json` + HSTS; docs disabled in prod code; API/redis/kafka ports internal-only; per-service mem/CPU limits, log-rotation caps, healthchecks (shared in-process dependency probe); `/health` vs `/readyz` split; worker waits on api health; non-root containers; `.dockerignore` allowlist build contexts (38KB API context); gitleaks; secrets git-ignored and untracked; prod settings validator at import.

---

## 7. Prior-ledger items still open — re-framed for the managed-cloud target

| Item | Status | Managed-cloud framing |
|------|--------|----------------------|
| **OPS-1** backups | open | Cloud SQL / managed DB automated backups + PITR answers storage; **rehearsed restore + runbook** remains mandatory launch work. Retire the boto3-only scripts or port them. |
| **OPS-4** remainder | open | SHA-pinned deploy images (drop mutable `:staging`) + CI-driven rollout to the managed platform — no more hand-SSH. |
| **S8** Redis | open (code-ready) | Memorystore/ElastiCache with auth+TLS — the env-gated `rediss://` support already in code (da10743) turns on here. AOF/sizing/HA become platform config. |
| **S9** Kafka | open | Managed Kafka (SASL/TLS, RF≥3, auto-create off) **or** collapse control events onto the Postgres outbox path (already the execution-truth) and keep Kafka for analytics fan-out only — decide during the move. |
| **INS-5** memory over-commit | open | Dissolves on managed compute (per-service sizing); keep the limit hygiene. |
| **S10** remainder | ~116 sites | Finish the non-502 `detail=str(...)` sweep (~1 day, per-site safe/public split). |
| **M9** scale wiring | a,b,c,e open | (a) wire `get_db_read()` when the read replica exists; (b) multiproc metrics (H16); (c) migrations out of boot (H17); (e) `channel_messages` archival/partitioning decision — needed before ~100GB. |
| **Phase-4 testing** | open | k6 load test at 10× peak; chaos test (kill worker mid-job → lease reclaim, no duplicate external calls); multi-replica scaling test. Do these **on the managed platform**, pre-launch. |
| **Admin follow-ups** | open | Operator-management tests + bootstrap-config docs. |
| **Nov-2 facts audit** | 6 open | Product track (geo-grid rank, AI-answer visibility, competitor deltas, Saudi benchmark pack) — not launch-blocking. |

## 8. Load math at 1M users (drivers, unchanged from readiness §1)

| Driver | At 1M registered (~30–50k tenants) | State after this pass |
|--------|-------------------------------------|------------------------|
| Inbound messages | 200–800/s peak | Bounded-concurrency workers + lanes exist; throughput runbook targets 10k msg/min; **Phase-4 load test still owed** |
| Meta webhook events | 1–5k/s | Ingress fail-closed, dedupe indexed, retention closes rows; unverified-traffic cap in place |
| Outbound sends | ~80 msg/s per number | Token-bucket pacing live (verified); fail-open fallback gap = H3 |
| Concurrent dashboards | 20–50k WS | Shared pub/sub subscriber + local fan-out; single Redis until managed move |
| DB size | 50–200 GB | Retention sweeps live; `channel_messages` archival decision (M9-e) still owed |

## 9. Suggested order of attack (for whoever picks this up)

1. §1.1 job-hijack tenant filters + `POST /jobs` gate (small, critical).
2. §1.2/§1.3 validator additions (TESTING, MOCK) + deploy-script env assertion (tiny, protects everything else).
3. Managed-cloud provisioning as launch work: managed DB with PITR + **one rehearsed restore** (OPS-1), Memorystore (S8), Kafka decision (S9), SHA-pinned CI deploys (OPS-4), alerting (§2.2 — rules + Alertmanager + GlitchTip DSN).
4. §2.1 bulk-email quota, §2.4 LLM output URL guard (§2.5 resolved — see correction).
5. Hardening table §3 in diff-cost order (H1/H2/H4/H6/H7 are minutes each).
6. Phase-4 tests on the managed platform before opening traffic.

---

*Audit passes: API core, integrations, jobs/frontends/infra — every headline claim re-verified in-tree by the lead auditor; prior ledger reconciled through 2026-11-03; Nov 7–8 code included. Deliverable per request: findings document only.*
