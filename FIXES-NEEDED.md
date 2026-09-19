# Sayvors — Production Readiness Audit & Fixes Needed
> 10M-user SaaS MVP · Last updated: 2026-08-13 (reconciled with code)
> Audit scope: Backend (65 findings) + Frontend (50 findings) + Infrastructure (33 findings) = **148 total**

---

## The 6 Things That Would Kill You at Launch

| # | Severity | Issue | Where |
|---|---|---|---|
| 1 | CRITICAL | **Account takeover chain**: any token type (refresh/reset) passes as access token + `forgot_password` returns a signed reset token in the API response body | `core/deps.py:26`, `auth/router.py:205` |
| 2 | CRITICAL | **JWT secret is the known default** `change-me-in-production` — HS256 keys are publicly known = forge any token | `config.py:6`, `.env` |
| 3 | CRITICAL | **RAG pipeline is broken**: uploads are never written to disk, parser opens a `/tmp` path that can never exist → every ingest job fails with FileNotFoundError | `rag/service.py:87-108,274` |
| 4 | CRITICAL | **Unbounded upload read** — `file.read()` with no size cap = memory-exhaustion DoS | `rag/service.py:87-90` |
| 5 | CRITICAL | **DB password `mentee` committed** in git (`alembic.ini`, `.env.example`) + `.env.example` ships it | infra #11,12 |
| 6 | CRITICAL | **Zero deployment path** — no Dockerfile, empty compose, no CI, no backups, no monitoring, no logging config | infra audit |

---

## Phase A — Critical Security (Day 1)

### Backend Authentication & Security

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| A1 | `app/core/deps.py:26-33` | ✅ RESOLVED | **Verified fixed:** `deps.py:31-33` now rejects `type != "access"`. | — |
| A2 | `app/modules/auth/router.py:207-221` | ✅ RESOLVED | **Verified fixed:** `forgot-password` returns a generic message and never leaks the token (`router.py:217-221`); signup pops & discards `verification_token` (`router.py:61`). | — |
| A3 | `app/config.py:6` | CRITICAL | `JWT_SECRET: str = "change-me-in-production"` hardcoded default. With HS256 algorithm a known secret = total token forgery. | Make required (no default). Fail fast at startup if still default. Rotate immediately. |
| A4 | `alembic.ini:4` | HIGH (was CRITICAL) | DB password `mentee` committed in git. `.env` is git-ignored (NOT the leak source). `alembic.ini` still hardcodes `postgres:mentee@localhost` (tracked). Low real risk = localhost dev, but should be scrubbed. | Rotate password, scrub `alembic.ini` from history, inject `DATABASE_URL` via env. |
| A5 | `app/modules/auth/service.py:40-102` | MEDIUM | `signup` returns `verification_token` in response body. Email never sent (`TODO`). No `email_verified` gate on login. | Send verification email or remove flow. Gate privileged actions on `email_verified`. |
| A6 | `app/modules/auth/service.py:166-215` | MEDIUM | Refresh-token rotation exists but no reuse detection — stolen token remains viable on paired device. | On use of a revoked token, revoke all refresh tokens for that user (family revocation). |
| A7 | `app/modules/auth/service.py:134` vs `router.py:127-164` | MEDIUM | Token fingerprint computed but never compared at refresh time. Fingerprint check is dead code. | Pass UA/IP into refresh, reject on mismatch. |
| A8 | `app/modules/auth/router.py:30-31` | HIGH | `get_client_ip` reads `x-forwarded-for` directly with no trusted-proxy config. Any client can spoof the header to bypass all IP-based rate limits. | Only trust header behind fixed proxy. Use `client.host` otherwise. |
| A9 | `app/modules/auth/rate_limit.py:21-22` | HIGH | All rate-limiting and blacklist checks fail open (`except Exception: return True`). Brute-force and spam protections completely disabled when Redis is down. | Fail closed on auth-critical paths. Log loudly. |
| A10 | `app/modules/auth/service.py:105-123` | HIGH | Login rate limit is 10 req/min per-IP and header-spoofable. No per-user limiting. No rate limit on `/refresh` at all. | Rate-limit by user_id+IP. Exponential backoff. Protect `/refresh`. |
| A11 | `app/security.py:39-40` | LOW | `decode_token` performs no `issuer`/`audience`/`jti` checks. Access tokens lack `iat`. | Add `iss`, `aud`, `iat` and verify them. |
| A12 | `app/modules/auth/models.py:52-61` | MEDIUM | `login_attempts` table grows unboundedly — no retention/cleanup job. PII (email+IP) retained indefinitely. | Rotate/partition by time. Purge > 30d. Move to Redis/OLAP. |
| A13 | `app/modules/auth/models.py` + `llm/models.py:28-42` | MEDIUM | PII (emails, conversation content) in plaintext DB tables with no column-level encryption. | Encrypt at rest for sensitive fields. Ensure DB snapshots encrypted. |

### Backend CSRF, CORS, Headers

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| A14 | `app/main.py` | ✅ RESOLVED | **Verified fixed:** `main.py:130-131` adds `TrustedHostMiddleware`. | — |
| A15 | `app/main.py:40-47` | LOW | CORS `allow_credentials=True` with env-configurable origins. Misconfigured `"*"` allows credentialed cross-origin. | Always validate CORS origins as exact list. Reject `*` when credentials on. |
| A16 | Frontend `lib/auth-context.tsx:56-63` | MEDIUM | CSRF token read/echoed but never validated. No origin/referer check. | Implement double-submit CSRF validation or `SameSite=Strict` + Origin checks. |
| A17 | Frontend `middleware.ts:43` | CRITICAL | CSP has unclosed quote: `frame-ancestors 'none` → whole policy dropped by browser. | Fix to `"frame-ancestors 'none'"`. |
| A18 | Frontend `middleware.ts:42` | CRITICAL | CSP hardcodes `connect-src 'self' http://localhost:8000`. Production API requests blocked. | Build connect-src from `NEXT_PUBLIC_API_URL` env var. |
| A19 | Frontend `middleware.ts:38` | CRITICAL | `script-src 'self' 'unsafe-eval' 'unsafe-inline'` in production. XSS containment disabled. | Remove `'unsafe-eval'` for production. Use nonce-based CSP. |
| A20 | Frontend `middleware.ts:31` | MEDIUM | `X-XSS-Protection: 1; mode=block` deprecated and ignored by modern browsers. Can introduce issues. | Remove header. |
| A21 | Frontend `next.config.ts:19` | MEDIUM | `Cross-Origin-Opener-Policy: same-origin` will break planned OAuth popup flows. | Use `same-origin-allow-popups` when OAuth popups land. |

---

## Phase B — Scale & Reliability

### RAG Pipeline Fixes

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| B1 | `app/modules/rag/service.py:87-108` | CRITICAL | `upload_document` reads upload into memory but **never writes file anywhere**. Parser opens `/tmp/sayvors_docs/{doc.id}.{doc.file_type}` — path never exists. Every ingest job fails with FileNotFoundError. | Persist uploads to object storage (or shared volume) during upload. Store storage key on Document row. Read from storage in parser. |
| B2 | `app/modules/rag/service.py:87-90` | CRITICAL | `file.read()` with no max size limit. Multi-GB upload read fully into RAM. Memory-exhaustion DoS. | `await file.read(MAX_SIZE)`. Stream to disk/object store. Reject > N MB. |
| B3 | `app/modules/rag/service.py:88-90` | MEDIUM | File-type validation is extension-only. No magic-byte/Content-Type verification. Content then executed by parser (xlsx→openpyxl, pdf→pypdfium2). | Sniff magic bytes. Map Content-Type. Cap file size before parsing. |
| B4 | `app/modules/rag/search.py:25-45` | HIGH | Hybrid search loads **every chunk** of the databank into memory (no LIMIT). O(N) cosine similarity in pure Python. ~100k chunks = MBs–GBs per query. pgvector declared but unused. | Install pgvector. Vector column + HNSW + tsvector GIN index. |
| B5 | `app/modules/rag/search.py:50-56` | HIGH | Keyword search computes `to_tsvector` on the fly with no GIN index. Scans whole table. | Generated tsvector column + GIN index. Use `websearch_to_tsquery`. |
| B6 | `app/modules/rag/models.py:70` | HIGH | Embeddings stored as JSON text (~15-20KB per vector). At millions of chunks this dominates storage. | Switch to pgvector Vector column with ANN index. |
| B7 | `app/modules/rag/cache.py` | LOW | Cache functions defined but **never called** from any code path. Embed/parse dedup is dead. | Wire into `embeddings.py`/`jobs.py`. Cuts cost massively at scale. |
| B8 | `app/modules/rag/service.py:165-196` | MEDIUM | `process_pending` enqueues all pending docs into one job with no cap. 10k-doc databank ties up worker. | Chunk jobs (e.g., 50 docs/job). Enforce per-user concurrency. |
| B9 | `app/modules/rag/schemas.py:44-47` | HIGH | Scrape URLs stored with no scheme/host validation. When scraper ships: SSRF allows targeting 127.0.0.1, 169.254.x, 192.168.x. | Block private/loopback/link-local ranges. Resolve DNS and re-check. Allowlist schemes. |
| B10 | `app/modules/rag/embeddings.py:62-72` | MEDIUM | OpenAI embedding: no timeout, no retries on rate limits/5xx. Ollama path creates fresh `httpx.AsyncClient` per call. | Set timeout. Add retry/backoff. Reuse client. Tune batch size. |
| B11 | `app/modules/rag/embeddings.py:89-101` | MEDIUM | Provider selection probes localhost:11434 on cold start (3s timeout). Provider can differ per instance/time → inconsistent embedding dimensions. | Explicit provider config from env. Validate at startup. Lock model per chunk index. |
| B12 | `app/modules/rag/models.py:49` + `service.py:92` | LOW | `content_hash` computed on upload but never used for dedup. Duplicate uploads re-embedded repeatedly. | Dedupe on `content_hash` (per user/databank). Use existing cache. |
| B13 | `app/modules/rag/router.py:63-77` | MEDIUM | `list_all_databanks` has no pagination. N+1 count query per databank. | Single aggregated GROUP BY query + limit/offset. |

### Worker & Queue Fixes

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| B14 | `app/modules/rag/jobs.py:31-44,56-78` | HIGH | Worker is in-process asyncio task. Multi-instance: each has own Semaphore/flag. DB fallback has no locking — no `FOR UPDATE SKIP LOCKED`. Same job processed twice. | Dedicated worker process. `FOR UPDATE SKIP LOCKED` leasing. Heartbeats. |
| B15 | `app/modules/rag/jobs.py:31-44` | HIGH | No crash recovery. Jobs set to `parsing`/`chunking` before processing. Process death → row stuck forever, never re-queued. | On startup, reset stale in-progress jobs to queued/failed. Add lease expiry + retry queue. |
| B16 | `app/modules/rag/jobs.py:31-44` | MEDIUM | `_worker_task` never cancelled on app shutdown (`stop_worker` exists but nothing calls it). In-flight jobs orphaned. | Lifecycle-register worker in FastAPI lifespan. |
| B17 | `app/modules/rag/jobs.py:111` | LOW | `job.error = str(e)[:2000]` stores raw exception in DB. Leaks filesystem paths to users via error field. | Log full stack server-side. Return sanitized message. |

### LLM & Conversation Fixes

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| B18 | `app/modules/llm/service.py:80-87` | HIGH | `_load_history` selects **entire message history** with no limit. Long conversations grow unbounded. Exceeds model context limits. | Truncate to model context window. Summarize/roll up old turns. |
| B19 | `app/modules/llm/router.py:178,213` | MEDIUM | Every `/chat` call creates a new conversation. Discards multi-turn model. Intentions broken. | Accept `conversation_id` for continuation. |
| B20 | `app/modules/llm/router.py:172-204` | HIGH | `/chat`, `/tts/convert`, `/stt/transcribe` have no per-user rate limiting or token budgets. One user can bankrupt LLM spend. | Per-user/monthly quotas. Concurrency limits. Spend tracking via Kafka. |
| B21 | `app/modules/llm/service.py:158-209` | MEDIUM | Assistant message persisted only after stream completes. Client disconnect = user message orphaned, assistant turn lost. | Persist placeholder + update progressively. Add stream timeout. |
| B22 | `app/modules/llm/schemas.py:45` | LOW | `max_tokens` accepts 100k but service hardcodes 1000. Request value ignored. | Honor/limit `max_tokens` per model. Bound message count. |
| B23 | `app/modules/llm/service.py:139` | MEDIUM | Provider errors wrap raw exception text (sometimes including keys/URLs). Propagated to HTTP responses. | Map to safe error codes/messages. Log full detail server-side. |

### Webhook & Channel Security

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| B24 | `app/modules/channels/router.py:176-222` | ✅ RESOLVED (gap remains) | **Verified fixed:** HMAC signature verification implemented (`router.py:191-209`) + 1 MB body cap. **Gap:** if a channel has no `webhook_secret`, verification is skipped yet payload still processed — tracked as **G3** in `SECURITY-AUDIT.md`. | Require `webhook_secret` to process non-verify webhooks. |
| B25 | `app/modules/channels/models.py:19-20,27` | HIGH | `access_token`, `refresh_token`, `webhook_secret` stored plaintext in DB. Platform OAuth credentials at rest exposed. | Encrypt at rest (KMS/field-level). Never store unencrypted. |
| B26 | `app/modules/stt/schemas.py:5` | LOW | `audio_url` fully user-controlled. When STT provider implemented and fetches it: another SSRF vector. | Fetch server-side with SSRF guardrails. |

### Unbounded Growth & Cleanup

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| B27 | `app/modules/auth/service.py:112-113,127` | HIGH | `login_attempts` grows unboundedly — millions of rows/day at scale. No retention/cleanup. | Rotate/partition by time. Purge > 30d. |
| B28 | `app/modules/auth/service.py:130-140` | HIGH | `refresh_tokens` never purged (only logout deletes). Rotation produces rapidly growing table. | TTL cleanup job. Move sessions to Redis with DB backstop. |

### Database Connection Pool

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| B29 | `app/database.py:8` | MEDIUM | SQLAlchemy defaults: `pool_size=5`, `max_overflow=10`, `pool_pre_ping=False`. Under-serves connection bursts. | Configurable per instance. `pool_pre_ping=True`. `pool_recycle=1800s`. |

---

## Phase C — Frontend Hardening

### Authentication Unification

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C1 | `lib/api.ts` + `lib/api-rag.ts` | CRITICAL | Auth tokens stored in `localStorage` (XSS-readable). Divergent from `auth-context.tsx` (cookie-based). Two conflicting systems. Login sets cookies only; localStorage keys never populated. | Unify on cookie auth. Delete localStorage tokens. |
| C2 | `components/AuthGuard.tsx` | HIGH | Checks `isAuthenticated()` from localStorage — bounces legitimately cookie-logged-in users. | Check session cookie server-side. |
| C3 | `app/dashboard/layout.tsx:6-21` | HIGH | No route protection on dashboard. AuthGuard never imported. Every `/dashboard/*` renders for unauthenticated users. | Check session in layout (server component). Redirect to `/login`. |

### Middleware / Proxy

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C4 | `middleware.ts` | HIGH | Deprecated in Next 16. Must become `proxy.ts`. Current file emits deprecation warnings. | Rename to `proxy.ts` via codemod `npx @next/codemod@canary middleware-to-proxy .`. Re-verify. |
| C5 | `middleware.ts:4-18` | HIGH | In-memory rate limiter `Map` not shared across instances. Wiped on cold start. Keyed on spoofable header. | Use shared store (Upstash Redis) or move to CDN/WAF. |

### Dead UI & UX

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C6 | `agents/create/page.tsx:544` | HIGH | "Save Agent" button has no onClick/handler. | Wire to backend API or disable with "coming soon". |
| C7 | `automations/create/page.tsx:445` | HIGH | "Deploy & Activate" has no handler. 6-step wizard result discarded. | Wire to backend API. |
| C8 | Sidebar links (stt, tts, docs, settings, templates) | HIGH | 6 links to non-existent routes (all 404). | Implement or remove. Add `not-found.tsx`. |
| C9 | `automations/page.tsx:133-154` | MEDIUM | Edit/pause/delete row buttons are no-ops. | Wire to backend or remove. |
| C10 | `agents/page.tsx:183-199` | MEDIUM | Edit/duplicate/delete are no-ops. | Wire to backend or remove. |
| C11 | `agents/customizations/page.tsx` | MEDIUM | Every "Save Changes" and "New Preset" button is no-op. | Wire to backend. |
| C12 | `channels/[slug]/page.tsx:61-65` | MEDIUM | OAuth connect is `alert()` stub. Disconnect no-op. | Wire to backend OAuth flow. |
| C13 | `app/page.tsx:3-7` | MEDIUM | Homepage is unconditional redirect to `/login` with leftover TODO. No landing page, nothing indexable. | Build real landing page or auth-aware redirect. |
| C14 | `widgets/page.tsx:101` | HIGH | "My Widgets" lives in useState, lost on refresh. No persistence. | Persist via backend API. |
| C15 | `contacts/[id]/page.tsx` | MEDIUM | Hardcodes "Sarah Chen / sarah@example.com" regardless of id. | Wire to backend API. |
| C16 | `conversations/[platform]/[id]/page.tsx:6-12` | MEDIUM | Hardcodes same fake thread for every conversation id. | Wire to backend API. |
| C17 | `dashboard/page.tsx:47-84` | HIGH | Dashboard KPIs/tables are all hardcoded mock data. | Wire to backend API. |
| C18 | `Header.tsx:163-174` | MEDIUM | Hardcoded "Syed S." identity. Non-functional Sign out. | Wire to auth context. |

### Performance

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C19 | All dashboard pages | HIGH | 29/29 interactive files use `"use client"` — zero server components. No RSC streaming, no server-side data fetching. | Convert static shells to server components. Fetch data server-side where possible. |
| C20 | `JobPanel.tsx:48-52` | MEDIUM | 2s polling unconditionally — even when collapsed, tab hidden, unauthenticated. No backoff. | Poll only when expanded + tab visible. Add backoff. |
| C21 | Components globally | MEDIUM | Zero `React.memo`/`useMemo` usage. Sidebar, wizards re-render fully on any state change. | Memo GroupHeader, PanelCard, KpiCard, WidgetPreview. |
| C22 | `lib/performance.ts` | LOW | Dead code. `lazyLoad`/`preload` never imported. | Remove or wire in. Use `next/dynamic` for below-the-fold. |
| C23 | `next.config.ts:10-12` | LOW | `experimental.optimizePackageImports` references packages not in package.json. Next 16 graduated this to top-level. | Move to top-level config. |
| C24 | `ThemeProvider.tsx:20-27` | LOW | Theme applied in useEffect → FOUC on every load. | Inline pre-hydration script. |
| C25 | `next.config.ts` | LOW | No `output: "standalone"`. No compression/CDN cache strategy for HTML. | Add `output: "standalone"` for container deploys. |

### Error Handling & Observability

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C26 | Global | HIGH | Zero error boundaries. No `error.tsx`, `global-error.tsx`, `not-found.tsx`. Single client throw → blank page. | Add all three. Add toast/error banner component. |
| C27 | `app/(auth)/reset-password/page.tsx:17` | MEDIUM | Tokens arrive via `?token=` in URL. Leaks to browser history/logs. | Prefer POST-based token submission. |
| C28 | `lib/validation.ts` | MEDIUM | `sanitize`, `isSafeRedirect`, `validateUrl` exported but never used (dead code). | Remove or wire in. |
| C29 | No loading states globally | MEDIUM | No `loading.tsx`/Suspense scaffolding. No `not-found.tsx`. | Add route-level loading/error boundaries. |
| C30 | Signup password rules differ | LOW | AuthForm (8 chars+letter+number) vs validation.ts (8+upper+lower+number). | Unify rules. |

### SEO & Accessibility

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C31 | Global | MEDIUM | No sitemap, no robots.txt, no manifest, no OG/Twitter tags, no metadataBase, no canonical URLs. | Add `sitemap.ts`, `robots.ts`, `manifest.ts`, OG metadata. |
| C32 | `public/` | LOW | Boilerplate SVGs (next.svg, vercel.svg, etc.) shipped to CDN. Dead assets. | Remove. |
| C33 | `public/` | LOW | Missing favicon variants (no apple-touch-icon, no favicon.ico). | Generate. |

### API Wiring Status

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| C34 | `lib/api.ts:1`, `lib/api-rag.ts:3`, `lib/auth-context.tsx:5` | HIGH | `http://localhost:8000` hardcoded as fallback. Missing `NEXT_PUBLIC_API_URL` = production breaks. | Fail build when unset. Default to production API URL. |
| C35 | `lib/api.ts:50-69` + `lib/api-rag.ts:25-41` | HIGH | Refresh-token race: concurrent 401s each fire separate refresh. Divergent refresh endpoints (`/auth/refresh` vs `/api/v1/auth/refresh`). | Unify into single client with shared refresh promise. Confirm correct backend path. |
| C36 | `api-rag.ts:48-79` | MEDIUM | `apiFetch` throws raw response text (leaks backend internals). Sets `Content-Type: application/json` for body-less GET/DELETE. | Map errors to safe messages. Only set Content-Type when body present. |
| C37 | `databank/page.tsx` catch blocks | MEDIUM | All catch blocks empty (`:103,115,137,152,166,180,193,205,216`). Silent failures. Uploads processed sequentially. | Add error toasts. Process uploads in parallel. |
| C38 | `databank/page.tsx:37-38` | LOW | No client-side file size limit. Backend must enforce. | Add client-side validation for UX. |

---

## Phase D — Infrastructure & Observability

### Containers & Deployment

| # | File | Severity | Issue | Fix |
|---|---|---|---|---|
| D1 | `services/api/`, `apps/web/` | CRITICAL | Zero Dockerfiles anywhere. Neither API nor web app can be containerized. | Add multi-stage Dockerfile for API (python:3.11-slim + uv) and web (node:22 + standalone output). |
| D2 | `services/api/`, `apps/web/` | HIGH | No `.dockerignore`. Build contexts ship node_modules, .venv, .next, .env into images. | Add `.dockerignore` per service. |
| D3 | `docker-compose.yml` | HIGH | File is 13-byte stub (`services: {}`). No Postgres, Redis, Kafka, API, or web. | Define full service stack with healthchecks and env injection. |
| D4 | `infrastructure/`, `deployments/`, `configs/` | CRITICAL | All empty scaffolds. No Terraform/Pulumi, no Helm/K8s, no Azure/Fly/Vercel config. | Pick a platform and commit IaC + environment configs. |
| D5 | `Makefile` | HIGH | Only dev targets (`api-dev`, `api-migrate`). No build/test/lint/prod targets. | Add production targets. |

### CI/CD

| # | File | Severity | Issue | Fix |
|---|---|---|---|---|
| D6 | `.github/` | CRITICAL | Contains only `.gitkeep`. No workflows. No CI pipeline at all. | Add CI (lint/typecheck/test/build) + CD (build/push images, migrate, deploy). |
| D7 | `tests/` | HIGH | Empty. Zero test files in entire repo. | Add pytest for API. Add vitest for web. |
| D8 | `apps/web/package.json` | MEDIUM | Scripts: only `dev`, `build`, `start`, `lint`. No `typecheck`, no `test`. | Add `typecheck` script. Add test runner. |
| D9 | `services/api/pyproject.toml` | MEDIUM | No dev/test tooling: no pytest, ruff, mypy. | Add dev dependency group + tool config. |

### Observability & Monitoring

| # | File | Severity | Issue | Fix |
|---|---|---|---|---|
| D10 | Global | HIGH | No monitoring anywhere: no Sentry, Prometheus, OTel, App Insights. Zero visibility into crashes/failures. | Add Sentry (web+API) + Prometheus via `prometheus-fastapi-instrumentator`. |
| D11 | `app/main.py` | MEDIUM | No structured logging. No request logging middleware. No request-ID correlation. Debugging at 10M scale impossible. | Configure JSON structured logging. Add request/response middleware. |
| D12 | `app/main.py:60-62` | MEDIUM | `/health` returns `{"status":"ok"}` unconditionally. Checks nothing. | Add `/health/live` + `/health/ready` (DB, Redis, Kafka ping). |
| D13 | `app/modules/auth/rate_limit.py` | MEDIUM | Rate limiting/blacklists fail open when Redis down. Silent degradation. | Log fallback. Fail closed on auth-critical paths. Add Redis health alerting. |

### Backups

| # | File | Severity | Issue | Fix |
|---|---|---|---|---|
| D14 | Global | CRITICAL | Zero backup tooling. No pg_dump scripts, no WAL-G, no cron. Data loss unrecoverable. | Add managed DB with automated PITR or nightly pg_dump script + restore runbook. |

### Logging & Error Reporting

| # | File | Severity | Issue | Fix |
|---|---|---|---|---|
| D15 | `app/modules/rag/events.py:33` + usage | HIGH | Every login/signup/refresh calls `producer.send_and_wait` synchronously. Kafka down → blocks request for tens of seconds. | Fire-and-forget `send` or write to durable outbox. Never block login on Kafka. |
| D16 | `app/modules/auth/events.py:34-35` | HIGH | All Kafka auth events silently swallowed (`except Exception: pass`). Silent loss of audit trail. | Log + store in outbox table. |
| D17 | Multiple files | HIGH | ~30 `except Exception: pass` instances throughout codebase. Masks real failures. Replace with `logger.exception` + explicit degraded behavior. |

### Docs

| # | File | Severity | Issue | Fix |
|---|---|---|---|---|
| D18 | `README.md` | MEDIUM | Stub only (project structure). No quickstart, env setup, or deployment instructions. | Document prerequisites, local setup, and deployment steps. |
| D19 | `docs/` | MEDIUM | Empty. No architecture docs or ADRs. | Add architecture doc, env-var reference, deploy/backup runbooks. |
| D20 | `apps/web/README.md` | LOW | Untouched create-next-app boilerplate. | Replace with app-specific setup. |

### Stubs & Dead Code

| # | File:Line | Severity | Issue | Fix |
|---|---|---|---|---|
| D21 | `tts/service.py:36-40` | MEDIUM | TTS provider is a stub. Instantly marks job "completed" without doing work. | Implement provider or return 501 (do not fabricate success). |
| D22 | `stt/service.py:24-27` | MEDIUM | STT provider is a stub. Instantly marks job "completed" without doing work. | Same as above. |
| D23 | `channels/service.py:79-84` | MEDIUM | Channel outbound messaging is a stub. Reports success without sending. | Same as above. |
| D24 | `channels/service.py:77-81` | LOW | `db.add(msg)` called twice for same message (duplicate). | Remove duplicate. |
| D25 | `users/` module | MEDIUM | Unregistered legacy router with signup/login that bypasses all auth hardening. | Delete or clearly mark deprecated. |
| D26 | `config.py:4-12` | MEDIUM | All settings plain `str`. Secrets leak through reprs/errors/logging. | Use `SecretStr` for JWT/API keys/DB password. |
| D27 | `config.py:22-27` | MEDIUM | SMTP_* settings exist but no email ever sent. | Implement email delivery or remove flows. |
| D28 | `redis/client.py:10-17` | MEDIUM | No `socket_timeout`, `health_check_interval`, `retry_on_timeout`. | Explicit connection/health settings + pool sizing. |
| D29 | `kafka/client.py:8-16` | MEDIUM | No `acks`, `enable_idempotence`, `retries`. Failed broker leaves singleton broken. | Idempotent producer config. Reconnect handling. |

---

## Phase E — Verified Remaining Gaps (audit reconciliation, 2026-08-13)

The following `FIXES-NEEDED` CRITICALs were **verified already fixed in code** and are NOT actionable:
- **A1** (token `type` not checked) → `deps.py:31-33` enforces `type == "access"` ✅
- **A2** (reset/signup token leaked in body) → `router.py:217-221` generic msg; signup discards token ✅
- **A14** (no `TrustedHostMiddleware`) → `main.py:130-131` adds it ✅
- **B24** (webhook sig = TODO) → `router.py:191-209` verifies HMAC + 1 MB cap ✅ (gap G3 remains)

The **real remaining gaps** are **G1–G9**, fully documented with file:line references in `SECURITY-AUDIT.md` §17.5. Summary:

| ID | Sev | Issue | Where |
|---|---|---|---|
| G1 | HIGH | Token blacklist exists but never checked in `get_current_user` | `core/deps.py:20-44` |
| G2 | HIGH | Access token returned in JSON body (XSS-theftable) | `auth/router.py:85`, `auth/service.py:154` |
| G3 | MED | Webhook processes payload when no `webhook_secret` set | `channels/router.py:204-212` |
| G4 | MED | `X-Forwarded-For` trusted → IP spoofing bypasses rate limits | `auth/router.py:34-36` |
| G5 | MED | In-process rate-limit fallback not scale-safe | `auth/rate_limit.py:35-42` |
| G6 | MED | Dev DB password `mentee` in `alembic.ini` + no DB SSL | `alembic.ini:4`, `database.py:8` |
| G7 | MED | No per-user LLM/RAG spend caps | `llm/*`, `rag/*` |
| G8 | LOW | No global body-size limit / upload MIME check | `main.py`, `rag/router.py` |
| G9 | LOW | No password complexity / email enumeration | `auth/schemas.py`, `auth/service.py:43` |

---

## Full Priority Remediation Order

### 🔴 CRITICAL (must fix before any deployment)

1. Enforce token `type == "access"` in `get_current_user` (A1)
2. Remove `dev_token` from reset response + `verification_token` from signup (A2)
3. Require strong `JWT_SECRET` (fail-fast at startup) + rotate (A3)
4. Remove committed DB password from git + scrub history (A4)
5. Fix RAG upload: persist to disk/object storage + cap size (B1, B2)
6. Add SSRF guards before scraper ships (B9)
7. Install pgvector + vector column + HNSW + tsvector GIN index (B4, B5, B6)
8. Fix CSP (unclosed quote, hardcoded localhost, unsafe-eval) (C17, C18, C19)
9. Add Dockerfiles + real docker-compose + CI pipeline (D1, D3, D6)
10. Add Postgres backups (D14)

### 🟠 HIGH (must fix before 10M scale)

11. CSRF validation + TrustedHost + trusted-proxy IP handling
12. Move worker to dedicated process + `FOR UPDATE SKIP LOCKED` + crash recovery
13. Unify on cookie auth, delete localStorage tokens, protect dashboard routes
14. Rename middleware → proxy, rate limiting to shared store
15. Per-user LLM spend quotas + conversation truncation
16. Webhook signature verification + encrypt channel tokens
17. Login_attempts / refresh_tokens cleanup jobs
18. Error boundaries + loading states + Sentry
19. Wire dead buttons or remove them
20. Structured logging + request IDs + health/ready endpoint
21. Fire-and-forget Kafka (don't block login)
22. Fix `except Exception: pass` pattern (30+ instances)
23. Convert client components to server components where possible
24. TTS/STT stubs: return 501, don't fabricate success

### 🟡 MEDIUM (should fix before beta)

25. Token fingerprint verification at refresh
26. Refresh token family revocation on reuse
27. File type validation (magic bytes)
28. Unbounded conversation history truncation
29. DB connection pool tuning (pool_pre_ping, pool_recycle)
30. LLM provider error message sanitization
31. Stream persistence for LLM chat
32. `next/dynamic` code splitting for heavy pages
33. `React.memo` for heavy components
34. sitemap.ts, robots.ts, OG metadata
35. Test suite (backend pytest + frontend vitest)
36. Documentation (README, docs, runbooks)

### 🟢 LOW (nice to have)

37. Token `iss`/`aud`/`iat` verification
38. Remove deprecated X-XSS-Protection header
39. Remove dead code files (validation.ts utils, performance.ts)
40. Remove boilerplate SVGs from public/
41. Unify password validation rules
42. Add favicon variants
43. Client-side file size validation (UX)

---

## Questions to Resolve Before Building

| # | Question | Options | Recommended |
|---|---|---|---|
| Q1 | Deploy platform for 10M users? | Azure (managed Postgres/Redis) / Fly.io / VPS+Docker / Render | Azure (your existing skills match) |
| Q2 | Install pgvector now? | Yes / Wait for Phase B | Yes — needed for scale, install now |
| Q3 | Scope of this pass? | All 4 phases / Backend criticals first (A+B) | Backend criticals first (A+B), then C+D |
| Q4 | File storage for RAG uploads? | Local disk (dev) + S3/Blob (prod) / Local only | Local disk now, abstract interface for later S3 swap |
| Q5 | Email sending for verification/reset? | SMTP (SendGrid/AWS SES) / Mock / Remove flows | Implement real SMTP (SendGrid free tier) |

---

## Backend File Count: 18 rag files + 25 other module files + 5 config files = 48 total
## Frontend File Count: ~35 component/page files
## Migration: 1 pending (rag tables + auth tables applied successfully)
## Current Branch: `development` (reconciled 2026-08-13)
## Next: Close G1–G2 (HIGH) before launch; G3–G9 can follow in Phase A/B order
