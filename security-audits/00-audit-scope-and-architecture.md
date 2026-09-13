# Sayvors — Security Audit Scope & Architecture Mapping (Pass 00)

**Status:** READ-ONLY architecture mapping and threat-surface scoping
**Date:** 2026-09-13
**Auditor:** Security audit pass 00 (scope/architecture)
**Branches observed:** `development` (HEAD `8274fcb`), `main`, `embedsocial`
**Next steps:** Audits 01+ will deep-dive the prioritized list in §20.

---

## 1. Executive summary

Sayvors is an early-stage **reputation-management / AI marketing platform**: merchants
connect business listings (Google Business Profile, Localith/EmbedSocial), and the
platform ingests reviews, runs AI-generated review replies through a strategy engine
with validation, publishes scheduled posts, and exposes dashboards/analytics for
multiple tenants.

The repository is a **monorepo in MVP/dev state**:

- One real backend service (`services/api`, FastAPI) — rich feature surface (17 mounted
  routers) but **no production deployment path is defined**.
- Two real frontends: `apps/web` (customer Next.js app) and `apps/admin` (internal
  Next.js console). All other apps, `gateway`, `packages`, `infrastructure`,
  `deployments`, `configs`, `tools`, and `tests/` are **empty scaffolds**.
- **No CI/CD of any kind** (`.github/` is an empty placeholder), no IaC, no secrets
  manager. The only deployment artifact is a **local-only `docker-compose.yml`**.
- A previous full-stack audit exists (`SECURITY-AUDIT.md`, 2026-08-13) with findings
  G1–G9 and a B+ rating. This pass independently re-verifies the architecture and
  reconciling prior findings against current code.

**Overall risk posture:** development-grade. The application layer has solid controls —
bcrypt(12) password hashing, JWT refresh rotation with reuse detection, double-submit
CSRF, DNS-pinned SSRF guards, parameterized SQL throughout, tenant-scoped queries in
most modules — but the platform-wide weaknesses are **cross-tenant data isolation**
(global strategy table, benchmark cross-tenant reads, shared provider credentials) and
**an undeveloped infrastructure/CICD/secrets story** (root containers, no TLS, live
credentials on disk and in git history, unauthenticated datastores).

**Highest-risk clusters for follow-on passes:**

1. Cross-tenant prompt-injection via the global `response_strategies` table.
2. Email OTP verification without rate limit / attempt cap (online brute-force).
3. Authenticated but **arbitrary-recipient** email relay via `/api/v1/email/send`.
4. Webhook signature verification fallthrough + `webhook_secret` stored in plaintext.
5. Unbounded LLM/RAG cost-abuse and an SSRF/port-probe surface via user-supplied
   database-source `host`/`port`.
6. Secrets hygiene: live untracked `.env` credentials on disk, an API key literal
   reachable in git history, tracked dev DB password.

Reporting convention throughout this document:
**Confirmed vulnerability / Likely vulnerability / Potential vulnerability (needs
verification) / Informational observation.** No application code was modified.

---

## 2. Technology stack discovered

Backend (`services/api/pyproject.toml`):
- **Python ≥3.11**, `uv` workspace (`pyproject.toml:7`, `uv.lock` pinned).
- **FastAPI ≥0.115**, uvicorn, SQLAlchemy 2.0 (async), asyncpg, alembic, pgvector.
- **PyJWT ≥2.10 (HS256)**, bcrypt ≥4.2, `cryptography` (Fernet for provider secrets).
- Redis (`redis>=5.0`), `aiokafka`, `aiomysql` (for user-supplied datasource
  connectors), openai, google-genai, ollama, httpx.
- Document parsing: `pypdfium2`, `python-docx`, `openpyxl`, `trafilatura`.

Frontend (`apps/web/package.json`, `apps/admin/package.json`):
- **Next.js 16.2.12** (App Router, `output: standalone`), **React 19.2.4**, Tailwind 4,
  TypeScript 5. `apps/admin` uses Next.js with a small client-side API helper
  (`lib/admin-api.ts`).

Platforms/infra:
- Docker: `pgvector/pgvector:pg16`, `redis:7-alpine`, `apache/kafka:3.8.0`,
  `python:3.11-slim` (API), `node:20-alpine` (web) — `docker-compose.yml`.
- No Terraform/K8s/Helm/cloud config anywhere in the repo.
- No GitHub Actions workflows, no Dependabot, no secret scanning.

---

## 3. Repository/module structure

```
apps/                        User-facing applications
  web/                       Next.js customer app (REAL, ~large)
  admin/                     Next.js internal console (REAL, small)
  landing/ docs/ mobile/     Empty scaffolds (.gitkeep only)
gateway/                     EMPTY (.gitkeep)
services/api/                THE backend (FastAPI, alembic, tests)
integrations/channels/       embedsocial.py (the only real integration code)
integrations/{ai,email,payments,sms,storage,webhooks}/   empty
packages/                    EMPTY
infrastructure/ deployments/ configs/ tools/             empty (`.gitkeep`)
scripts/                     embedsocial_spike.py, _probe_localith.py
tests/                       EMPTY at root; real tests in services/api/tests/
docs/                        api, architecture, security markdown (partly aspirational)
.github/                     empty (.gitkeep) — NO CI/CD
docker-compose.yml           local dev stack (postgres/redis/kafka/api/web)
SECURITY-AUDIT.md            prior audit (2026-08-13), findings G1–G9
FIXES-NEEDED.md, DEEP-SCAN-REPORT.md, DESIGN.md, *.xlsx/csv  prior work products
```

Git state (relevant to audit):
- 94 commits; branch `development`; remote `github.com/Sayvors/sayvors`.
- `.env`/`.env.*` ignored except `.env.example` (`.gitignore:8`) — **`services/api/.env`
  exists on disk untracked** and contains live credentials (see §15).
- `apps/admin` files are present on disk with local modifications; no CI opinions it.

**Informational:** the monorepo scaffolding (gateway, packages, infra, deployments,
configs) is unrealized; the README describes nginx/TLS gateway + IaC that do not exist.

---

## 4. Backend architecture

Single FastAPI process (`services/api/app/main.py`) that also runs background work in
the same event loop.

- **Bootstrap** (`main.py:170-201`): CORS `allow_credentials=True` with explicit
  origins; custom **double-submit CSRF middleware** (`main.py:30-62`) exempting
  `/api/v1/auth/*`, `/api/v1/admin/*`, `/api/v1/email/otp/*`, `/api/v1/channels/webhook/*`,
  `/health`; `TrustedHostMiddleware` only when `ALLOWED_HOSTS` set (`main.py:181-182`,
  default `["localhost","127.0.0.1"]`).
- **17 routers mounted** (`main.py:185-201`): auth, tts, stt, llm, channels, analytics,
  redis, kafka, rag, profile, localith, locations, posts, admin, email, review-engine, csv.
  (Note: `modules/users/router.py` is **dead code** — not mounted.)
- **Lifespan** (`main.py:65-167`): DB pool warm-up; LLM provider-key refresh from DB
  (`llm/providers/registry.py`); Redis/Kafka availability ping with fail-soft flags;
  startup + periodic retention cleanup; then starts **7 background asyncio workers**:
  retention loop, Google reviews poller, Localith sync, scheduled-post publisher,
  Kafka analytics consumer, GBP performance sync, and an outbox worker.
- **Config** (`config.py`): pydantic-settings from `.env`; **fail-fast at startup if
  `JWT_SECRET` is still `"change-me-in-production"`** (`config.py:95-99`). All other
  provider credentials are env-or-empty with no fail-fast.
- **DB engine** (`database.py`): asyncpg, `echo=False`, pool `size=10/overflow=10`,
  `pool_recycle=1800`, **no `ssl=require`** in `DATABASE_URL`.

Workers reuse the same DB session factory and Redis/Kafka clients as request handlers,
meaning **any bug in a worker touches the same high-privilege stores as the API.**

---

## 5. Frontend architecture

### apps/web (customer app)
- Routes: `(auth)` — login, signup, forgot/reset-password, verify-email, verify-otp;
  `onboarding`; `dashboard/*` — agents, analytics, automations, benchmark, channels,
  contacts, databank, docs, growth, insights, locations, media, posts, profile, reviews,
  services, settings, stt/tts, templates, usage, verification, video-studio, widgets.
- **Auth model:** access token held **only in module memory**
  (`lib/auth-context.tsx:7-9`); refresh token in an **httpOnly cookie**; double-submit
  `X-CSRF-Token` header read from the `csrf_token` cookie (`lib/auth-context.tsx:59-72`).
  401 → single silent refresh then redirect (`lib/api-rag.ts:67-81`).
- **Edge guard** (`middleware.ts`): per-process in-memory `Map` rate limiter keyed on
  **client-craftable `x-forwarded-for`** (`middleware.ts:4-25`); `/dashboard/*` protected
  by **cookie presence only** (`:30-37`); sets security headers + CSP
  (`script-src 'self'` in prod, `style-src 'unsafe-inline'`, HSTS preload).
- **Secret handling:** no hardcoded secrets; `NEXT_PUBLIC_API_URL` default
  `http://localhost:8000` in 7 files; no `app/api/` routes (frontend is a thin client).
- Static mock data in `lib/channel-data.ts`, `lib/agent-wizard-data.ts`.

### apps/admin (internal console)
- Pages: login, overview, tenants, tenant detail, usage, llms, logs.
- **Admin JWT stored in `sessionStorage`** under `sayvors.admin.token`
  (`lib/admin-api.ts:4-15`) — XSS-readable, unlike the customer app.
- Same in-memory/install-less pattern; no server-side route guards found in layout.

---

## 6. Authentication architecture

Core module `services/api/app/modules/auth/` + `app/security.py`.

- **Signup** (`service.py:40-112`): bcrypt(12) hash, email uniqueness, creates
  `EmailVerification` (hashed token), returns access+refresh, **gates sign-in behind
  OTP verification**; `POST /auth/signup` rate-limited 5/60s per IP (`router.py:84`).
- **Login** (`service.py:115-183`): account lockout after 5 failures / 15 min
  (`config.py:20-21`), OTP re-send on unverified email, returns access+refresh;
  `POST /auth/login` rate-limited 10/60s per IP **and** per email (`router.py:132-136`).
- **Tokens** (`security.py`): HS256, JWT `type` claim distinguishes
  access/refresh/admin/email_verify/password_reset; access 15 min, refresh 7 days;
  unique `jti` per token; refresh token stored **SHA-256 hashed** in DB
  (`service.py:66-73,149-158`).
- **Refresh** (`service.py:186-280`): rotation + old-token blacklist in Redis
  (`rate_limit.blacklist_token`); **reuse detection** (revoked-token presented → revoke
  all sessions for the user, blocklist, alert); **user-agent binding** enforced on
  rotation (IP recorded, not enforced).
- **Logout / sessions / password reset / email verify / OTP sign-in** —
  `router.py:219-362`; reset password revokes all refresh tokens (`service.py:358`).
- **Cookies** (`router.py:95-114,150-169`): refresh cookie `httpOnly+Secure+SameSite=Lax`;
  CSRF cookie `Secure+Lax`, readable (double-submit). All cookie-rotation points
  re-issue the CSRF token.
- **Admin auth** (`core/deps.py:48-65` + `modules/admin/router.py:57`): separate
  bcrypt password (no user record), JWT `type=admin`/`sub=admin`, login rate-limited
  5/300s; admin surface entirely exempt from CSRF by design (`main.py:44`).
- **Email OTP** (`modules/email/`): 6-digit code (10 min, Redis), request limited
  3/300s per IP+email (`email/router.py:86`), but **verify has no limit** (see §17).

**Confirmed:** JWT `type` claim enforced (`deps.py:31-33`, `service.py:191-192`).
**Confirmed gap (prior G1/G2):** access-token **blacklist is not checked** in
`get_current_user` (`core/deps.py:20-45` never calls `is_token_blacklisted`), and the
**access token is returned in response bodies** (e.g., `auth/router.py:116-119`), making
logged-out/revoked access tokens usable up to 15 min and exposing the token to XSS.

---

## 7. Authorization architecture

- **User auth:** `get_current_user` (`core/deps.py:20-45`) — Bearer JWT, verifies
  `type=access`, loads `User` by `sub`. Per-object ownership is enforced **inside each
  module's service** via `user_id` equality (e.g., channels `service.py:109-115`,
  rag `service.py:51-59`, llm `service.py:37-59`, databank sources
  `rag/router.py:375-384`).
- **Admin:** `require_admin` (`core/deps.py:48-65`) — JWT `type=admin ∧ sub=admin`.
- **Public (unauth) endpoints:** `/health`, `/api/v1/auth/*` login/signup/refresh/
  forgot/reset/verify/otp/csrf, `/api/v1/email/otp/*`, `/api/v1/channels/webhook/*`,
  `/api/v1/channels/google/connect|c|allback` (see §16), and — **inconsistency** —
  `GET /api/v1/tts/voices` (public catalog).
- **CSRF:** enforced for all non-exempt mutating requests via header/cookie equality
  (`main.py:30-62`).

**Cross-tenant authorization defects (Confirmed, all impact isolation):**

1. **Global strategy table** — `ResponseStrategy` has **no tenant column**
   (`review_engine/models.py:16-36`); `PUT /review-engine/strategies/{id}` lets **any
   authenticated user** flip enable/priority/instructions (`review_engine/router.py:101-124`),
   and `select(ResponseStrategy)` returns the global enabled set to every tenant
   (`strategies.py:15`; generator prompts at `generator.py:40,59`). One tenant can
   inject instructions used to generate **all tenants'** AI review replies.
2. **Benchmark cross-tenant read** — `analytics/benchmark.py:18-46` resolves a fixed
   benchmark user (or "any user having ReviewInsight rows") and returns that tenant's
   aggregate KPIs to any authenticated caller.
3. **Cross-tenant publish trigger** — `POST /posts/sync` (`posts/router.py:124-132`)
   runs `publish_due` for **all tenants** and echoes foreign post-id prefixes + error
   text back to the caller (`posts/service.py:233-252`).
4. **Shared Localith account** — one `LOCALITH_API_KEY` serves all tenants
   (`localith/service.py:46-47`); `GET /localith/listings` returns **every listing under
   the shared account** to any tenant (`localith/router.py:88-97`).

**Informational:** `modules/users/router.py` is unmounted dead code duplicating
signup/login without rate limits — not reachable, but it blurs the "single auth
surface" assumption for future work.

---

## 8. Multi-tenant architecture

Tenancy is **flat `user_id` ownership, no workspace/org hierarchy**: `User` is the
tenant root; child tables use `user_id` FKs (`channels`, `databanks`, `conversations`,
`locations`, `posts`, `review_response_logs.tenant_id`, etc.). `admin` operates across
tenants.

- **Correctly scoped (Confirmed):** channels, rag databanks/documents/sources, llm
  conversations, review-engine CSV/workspaces, profile, posts CRUD, locations against
  the caller's own Localith connection.
- **Shared global infrastructure (by design, Informational):**
  - LLM provider keys are platform-level in `provider_configs` (`llm/models.py:56`),
    admin-managed, Fernet-encrypted; every tenant calls out through them.
  - `response_strategies` is global (see §7) — a **tenancy bug**, not a feature.
  - Single `LOCALITH_API_KEY`, single Resend sender identity.
  - Redis keys for OTP are **de-tenantized email-scoped** (`email/service.py:80`), and
    auth rate-limit keys use IP/email — globally shared, which is correct for abuse
    prevention.
- **Demo-mode leakage risk (Likely):** `DEMO_MODE` (config) makes several analytics
  endpoints return a demo user's data to any caller **and** disables meaningful
  isolation checks; `analytics/benchmark.py` does this unconditionally even outside
  demo mode (see §12).

**Confirmed vulnerability:** the whole-platform prompt-injection path in §7.1
(serializes to "any tenant can alter all tenants' LLM behavior and exfiltrate any
tenant's review data through generated content").

---

## 9. Database architecture

- Engine: PostgreSQL 16 + pgvector (`docker-compose.yml:2-17`), asyncpg.
- **Migrations:** alembic (`services/api/alembic/versions/*`), run on container start by
  both Dockerfile and compose (`docker-compose.yml:81`).
- **Tables observed across modules** (`app/modules/*/models.py`, `alembic` versions):
  `users`; auth: `refresh_tokens`, `email_verifications`, `password_resets`,
  `login_attempts`; `channels`, `auto_reply_configs`, `review_replies`;
  `llm_provider_configs`, `llm_conversations`, `llm_messages`, `llm_usage_events`;
  rag: `databanks`, `documents`, `document_chunks` (JSON-embedded vectors),
  `data_sources`; `location_profiles`, `location_daily_metrics`; `posts`; `localith_connections`;
  `response_strategies`, `review_response_logs`; review CSV workspaces/rows;
  `outbox_events`. (Exact column inventory belongs to the migration-file pass, 01+.)
- **Secrets at rest:** provider/ OAuth passwords Fernet-encrypted (channels tokens,
  `data_sources.password`, provider keys) — but the **Fernet key is derived from
  `JWT_SECRET`** (`channels/service.py:17-23`); anyone who can mint JWTs can decrypt all
  embedded secrets, and there is **no key-rotation story** (rotation breaks decryption).
- **Webhook secret is an exception stored in PLAINTEXT** — `Channel.webhook_secret`
  `String(100)` (`channels/models.py:37`, set at `channels/service.py:83`).
- **At-rest transport:** `database.py:8` has no `ssl=require`; local compose exposes
  Postgres on the host on port 5432 with password `mentee` (`docker-compose.yml:5-11`).
  **Confirmed:** tracked dev credentials (`alembic.ini:4`, `.env.example:1`,
  `docker-compose.yml:68`).
- **Raw SQL:** fully parameterized (`rag/search.py:25-31,53-65,97-102`;
  `review_engine/csv_service.py` `data @> :filter_json`; `rag/tools.py`). No injection
  observed. **Informational:** unchecked `%`/`_` in LIKE patterns (search semantics only).
- **Retention:** login attempts deleted after 30d, expired/revoked refresh tokens after
  7d, outbox 24h (`auth/service.py:485-541`); **no retention policy on PII-heavy
  `review_response_logs`** (full review text + reviewer name + analysis + tool calls,
  `review_engine/models.py:39-60`).

---

## 10. External integrations

| Target | Mechanism | Credential | Notes |
|---|---|---|---|
| Google Business Profile (reviews, posting) | OAuth2 + GBP API (`channels/google_reviews.py`) | Google OAuth client id/secret (`config.py:52-53`); per-channel tokens Fernet-encrypted | OAuth flow passes **JWT as `?token=` query param** (`channels/router.py:379-407`); fixed HTTPS hosts, redirect-less |
| Localith / EmbedSocial | HTTPS REST (`integrations/channels/embedsocial.py`) | **single shared `LOCALITH_API_KEY`** for all tenants | Listing sync, profile patch, review post back |
| Resend (email) | HTTPS (`email/service.py:34-72`) | `RESEND_API_KEY` (`config.py:45`) | OTPs, activation, reset, **arbitrary-recipient send endpoint** |
| LLM providers | OpenAI / Gemini / Groq / Ollama (`llm/providers/*`) | keys in DB, admin-managed, Fernet-encrypted | Chat, generation, intelligence, review-reply |
| User-supplied data sources (rag) | asyncpg/aiomysql connectors (`rag/connectors.py`) | `data_sources.password` Fernet-encrypted | **User-controlled host/port contact** — SSRF/port-probe surface (§16, §17) |
| Resend / Google icon CDN in email HTML | cdn.jsdelivr.net (static) | — | External `<img>` in OTP template headers (`email/service.py:109-118`) |

**Informational:** all outbound HTTP from the API reuses `httpx`; RAG scraping and
review-engine RAG fetch use `core/pinned_http.py` (DNS pinning, 8 MB cap, 3 hops,
HTML/text only) with `assert_public_http_url` (`core/http.py:26-77`) rejecting
non-global IPs. **Potential-verify:** `ipaddress.is_global` edge ranges across Python
versions.

---

## 11. Background jobs / queues

All run **in-process** in the API pod (no separate worker fleet):

1. **Retention cleanup loop** (`auth/service.py:544-561`) — bounded-batch purge.
2. **Google Reviews poller** (`channels/reviews_worker.py`) — atomic per-channel
   `polling_locked_until` claim; honors `approval_mode`/`min_rating_auto`; low ratings
   always queued for approval; mock mode is a logged no-op.
3. **Localith auto-sync** (`localith/worker.py`) — profile/reviews/metrics upsert into
   `ReviewInsight`; emits `review.discovered` events.
4. **Scheduled-post publisher** (`posts/worker.py`, 5-min cadence) — pushes due posts to
   Google via Localith.
5. **Analytics Kafka consumer** (`analytics/consumer.py`) — review enrichment + daily
   rollups; `_handle_discovered` sets `insight.user_id` **from the Kafka payload**
   (internal-trust assumption).
6. **GBP performance sync** (`analytics/performance.py`, 6-h cadence).
7. **Outbox worker** (`outbox/worker.py`) — PG queue drained to Kafka; `MAX_RETRIES=10`
   exponential backoff 2→300s, 24h retention, 3s poll.

**Informational:** outbox pattern gives at-least-once semantics with idempotent
upserts; Kafka auto-creates topics (`docker-compose.yml:47`) with **PLAINTEXT listeners
and no SASL/TLS**, exposed on the host. If the API is ever horizontally scaled, all
seven in-process workers become a correctness/concurrency risk.

---

## 12. Cache architecture

- **Redis** (`modules/redis/client.py`): availability-flagged at startup; used for
  auth rate limits (sliding window, **fails closed** when `AUTH_RATE_LIMIT_FAIL_CLOSED`
  is true — `config.py:24`), session storage, token blacklist, **OTP storage**, and
  profile/usage caches (`profile` module).
- **In-process fallbacks** (`modules/auth/rate_limit.py:35-42`): when Redis is down,
  limits fall back to a per-instance dict **Shared nothing across replicas, resets on
  restart** (prior G5).
- **No TTL/eviction issues observed**; OTP TTL is 10 min (`email/service.py:25`).
- **Potential:** `GET /redis/health` echoes exception detail to the caller
  (informational; environmental only).

**Confirmed:** OTP verification consumes a Redis value **only on success**
(`email/service.py:154-166`) — consecutive wrong guesses are not throttled or absorbed
(→ brute-force surface, §17).

---

## 13. API surface

All under `/api/v1` unless noted. **Auth** column: U = any authenticated user;
Admin = `require_admin`; P = public; W = webhook/OAuth public.

| Router | Notable endpoints | Auth |
|---|---|---|
| `auth` | signup, login, refresh, logout, csrf-token, forgot/reset-password, verify-email, verify-otp, me (GET/PATCH), sessions | P / U |
| `admin` | login, me, overview, tenants, tenant detail, usage, health?probe, llm status/PUT/test, model enable/disable/test/create/delete, remote-models | Admin |
| `channels` | channels CRUD, verification, services CRUD, messages, auto-reply GET/PUT, reviews (list/approve/generate/edit/regenerate/reject), google connect/callback, **webhook/{platform}**, MOA `?token=` | U / P / W |
| `llm` | models list, conversations CRUD, messages, chat, **chat/stream (SSE)**, usage/summary | U |
| `rag` | databanks CRUD, documents upload/preview/delete, scrape, process, jobs, search, sources (test/save/list/delete/schema/preview/query/ingest), reindex/retry/ask | U |
| `analytics` | overview, timeseries, reviews/insights, topics/products/problems/opportunities, acquisition, visibility, executive-summary, intelligence, benchmark, growth | U |
| `review-engine` | generate, **generate-stream (SSE)**, strategies GET/GET/PUT, logs | U |
| `review-engine` CSV | csv upload/search/rows/delete | U |
| `email` | **send**, otp/request, otp/verify | U / P |
| `localith` | config, listings, test, sync, connection GET/PUT/DELETE, profile, **PATCH listing** | U |
| `locations` | locations* (profile/maps) CRUD, metrics for owner | U |
| `posts` | create/list/get/update/delete/publish, **sync** | U |
| `tts` | convert, voices | U (**voices public**) |
| `stt` | transcribe (audio_url) | U |
| `profile` | GET/PATCH, preferences, usage, feedback | U |
| `redis` | health | U |
| `kafka` | health (**enumerates all topics**), (service publish_event/message used internally) | U |
| system | `GET /health` | P |

**Informational observations:** no global request-size limit (prior G8); no
per-user quotas on any AI/LLM/RAG/TTS/STT endpoint (prior G7 — unbounded token spend);
SSE endpoints leak raw `str(e)` fragments to clients (`review_engine/router.py:61-62`,
`llm/router.py:248-249`, `rag/router.py:408/479/504/527`, `localith/router.py:96/124/228/232`,
`admin/router.py:282/371/581`); `kafka /health` returns provider exception text and
`producer.list_topics()`.

---

## 14. Deployment/infrastructure configuration

- **Only deployment artifact:** `docker-compose.yml` (local dev). Services publish
  **postgres:5432, redis:6379, kafka:9092/29092, api:8000 (0.0.0.0), web:3000** to the
  host.
- **No production manifests:** no K8s/Terraform/Helm/cloud configs; `infrastructure/`,
  `deployments/`, `configs/` are empty. `docs/security/*` describe a hardened target
  state (Cloudflare WAF, VPC/SG, distroless non-root, Trivy/cosign, Secrets Manager,
  Kafka SASL) that **does not exist in code**.
- **Dockerfiles:**
  - API: `python:3.11-slim` (mutable tag), runs as **root**, no `USER`; CMD runs
    `alembic upgrade head && uvicorn --host 0.0.0.0`; **no `.dockerignore`** → build
    context can embed `.env`, `.venv`, `node_modules`, `__pycache__` into image layers.
  - Web: `node:20-alpine` multi-stage `standalone`; runner runs as **root**; no
    `.dockerignore`; `NEXT_PUBLIC_API_URL` default plain-HTTP.
- **CI/CD: none.** `.github/` is an empty placeholder; no lint/typecheck/test/SAST/
  dependency-audit/image-scan gates exist (prior I-03).
- **Networking/TLS:** every hop inside compose is plaintext; no TLS termination config
  (the documented nginx gateway doesn't exist); HSTS header is set on a non-HTTPS
  origin (`middleware.ts:47`).
- **Trusted proxy handling:** `TRUSTED_PROXIES=["127.0.0.1","::1"]` (`config.py:27`) —
  correct default, but **nothing deploys a reverse proxy**, so in raw docker usage the
  app trusts only loopback, which is the safe case; if later fronted by a proxy
  without updating this list, either legit IPs get misclassified **or** (if widened to
  e.g. a CIDR) XFF becomes attacker-controllable (prior G4).

---

## 15. Secrets/configuration handling

- **Configuration model:** pydantic-settings, single `.env` per service
  (`config.py:90`, `docker-compose.yml:65-66`). No per-environment separation, no
  secret manager, no rotation procedure (prior G6/M-08).
- **Untracked live `.env` on disk (`services/api/.env`, git-ignored):** contains real
  credentials. **Confirmed — treat all as compromised; rotate:**
  - `JWT_SECRET` — live HS256 signing secret.
  - `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (`…apps.googleusercontent.com`,
    `GOCSPX-…`).
  - `LOCALITH_API_KEY` (`es3dfbe…`) — shared across all tenants (§8).
  - `RESEND_API_KEY` (`re_…`).
  - `ADMIN_PASSWORD_HASH` (bcrypt) with an adjacent in-file comment containing the
    **plaintext temporary admin password**) — administrative session goal = full
    platform compromise. This file is a build-context candidate for the API image
    (no `.dockerignore`).
- **API key literal in git history (Confirmed):** `git log -S es3dfbe0793d8fabac`
  → commits `d63ae85` / `c2ba4bc`; `.agents/project-context.md:66` previously contained
  the full `LOCALITH_API_KEY` literal. Reachable on descendant branches; the key must
  be **rotated** and history scrubbed if the repo is ever shared.
- **Tracked dev DB password `mentee` (Confirmed):** `services/api/alembic.ini:4`,
  `services/api/.env.example:1`, `docker-compose.yml:68`; default URL uses password
  `postgres` (`config.py:5`).
- **Good practices observed:** `.env*` git-ignored (except example); JWT default
  fail-fast (`config.py:95-99`); OAuth/provider secrets Fernet-encrypted at rest;
  refresh tokens stored hashed; keys never baked into frontend bundles (except the
  public `NEXT_PUBLIC_API_URL`).
- **Confirmed weakness:** the Fernet key for every stored secret is `sha256(JWT_SECRET)`
  (`channels/service.py:17-23`) — **single point of failure**; a JWT-secret leak
  decrypts all provider/OAuth/data-source credentials, and rotating it bricks all
  stored secrets.

---

## 16. Trust boundaries

```
        ┌──────────────── INTERNET ────────────────┐
        │  (unauthenticated webhooks, OTP, auth,   │
        │   signup/login/refresh, health, static)  │
        └───┬───────────────────┬──────────────────┘
            │ HTTPS*             │ *no TLS anywhere in repo; local compose only
   ┌────────▼────────┐   ┌───────▼────────┐   ┌──────────────┐
   │ apps/web (Next) │   │ apps/admin     │   │ 3rd-party     │
   │  bearer-in-mem, │   │ token in       │   │ webhooks /    │
   │  csrf double-   │   │ sessionStorage │   │ Google OAuth  │
   │  submit          │   └───────┬────────┘   └──────┬───────┘
   └────────┬────────┘           │Bearer/CSRF         │HMAC / OAuth
            │  CORS allow-list    │                    │
   ┌────────▼──────────────┐  ┌──▼───────┐    ┌───────▼────────┐
   │  services/api (FastAPI │  │  DB, Redis, Kafka  │            │
   │  CSRF mw, TrustedHost, │  │  (local, plaintext,│            │
   │  JWT deps, instance    │  │  no-auth, Kafka    │            │
   │  workers share same    │  │  auto-create)      │            │
   │  credentials)          │  └────────────────────┘            │
   └───┬────────┬────────┬──┘
       │        │        │
       ▼        ▼        ▼
   Google BPO  Resend   Localith(shared key)  LLM providers (OpenAI/Gemini/Groq/Ollama)
     (Fernet-        (single          (single tenant-agnostic
     encrypted      sender           key)               admin-managed,
      per-tenant     identity)                           platform-level)
      tokens)
       │
       ▼
   User-supplied Postgres/MySQL data sources (host/port from tenant input)
```

Notable boundary conditions:
- **Webhooks are a trusted-input boundary but verification is weak:** platforms are
  expected to sign with HMAC-SHA256 (`channels/router.py:317-324`), but when no active
  channel exists **or** the channel has an empty `webhook_secret`, the signature check
  is **skipped with only a log** and the payload is still parsed and dispatched
  (`channels/router.py:355-373`). Dispatcher is a stub today, so impact is latent but
  the boundary is wrong.
- **OAuth callback/cotrusion boundary transmits a long-lived access token in a GET
  query string** (`channels/router.py:379-407`; frontend `channels/page.tsx:199-200`,
  `onboarding/page.tsx:129`).
- **Internal data bus (Kafka) is plaintext and trust-forged:** the analytics consumer
  trusts `user_id` from the Kafka message (`analytics/consumer.py:77`); anyone who can
  write to the topic (any pod, due to PLAINTEXT + auto-create) can populate another
  tenant's `ReviewInsight` rows. **Understanding:** producer code is reviewed, but the
  channel itself is unauthenticated in compose.
- **The API process itself spans the boundary between request handling and trusted
  long-running background work** — same secrets, same DB, same Redis/Kafka.

---

## 17. External attack surfaces

Ranked by expected exploitability × impact. (Full verification is deferred to later
passes; each item marked accordingly.)

| # | Surface | Vector | Classification |
|---|---|---|---|
| E1 | `POST /api/v1/email/otp/verify` | **No rate limit / no attempt cap** on a 6-digit space (10-min TTL, only consumed on success) → online brute-force to bypass email verification, abuse password reset | **Confirmed vulnerability** (`email/router.py:95-102`, `email/service.py:154-166`) |
| E2 | `POST /api/v1/channels/webhook/{platform}` | Unauthenticated ingestion; signature optional when no channel/secret → spoofed review events, platform-impersonation; HMAC replay unmitigated | **Confirmed vulnerability** (acceptance `channels/router.py:355-373`); replay = Potential |
| E3 | `POST /api/v1/email/send` | Any authenticated tenant can mail **arbitrary recipients** with arbitrary subject/body/CTA from the brand sender → spam/phishing relay, deliverability/trust damage, and (Potential) HTML-injection into the email template | **Confirmed vulnerability** (`email/router.py:60-74`; `email/service.py:220-225`) |
| E4 | `POST /api/v1/auth/login` + signup/forgot/reset/verify-otp | Brute-force / enumeration / lockout bypass via spoofed identity; note good per-IP+per-email limits and fail-closed Redis, but XFF trust is narrow; email-uniqueness 409 discloses account existence (`auth/service.py:43`) | **Likely vulnerability** (account enumeration); PoC-verify spoofing of `X-Forwarded-For` once a proxy is introduced |
| E5 | `GET /api/v1/channels/google/connect?token=<access>`, and `?token=` on OAuth/verify endpoints | Bearer access token placed in URL query string → leaks to browser history, access/referrer logs, proxies | **Confirmed vulnerability** (`channels/router.py:379-407`, `apps/web/app/dashboard/channels/page.tsx:199-200`, `apps/web/app/onboarding/page.tsx:129`) |
| E6 | LLM/RAG/review-engine chat+stream + tools | Unbounded per-user token spend (cost abuse); prompt-injection via tenant-supplied `system_prompt`, `custom_instructions`, RAG content, and databank text | **Likely vulnerability** (abuse); prompt-injection surface Confirmed at `llm/router.py:180-260`, `channels/review_reply.py:111-117`, `review_engine/generator.py:40,59` |
| E7 | RAG data-source endpoints (`test/schema/preview/query`) | Server connects to **tenant-supplied host:port** (postgres/mysql) → internal-network probing, blind port scan via error-detail differences (`rag/router.py:387-528`, `rag/connectors.py:79-211`) | **Confirmed vulnerability** (SSRF/scan surface) |
| E8 | RAG document upload + scrape | Extension-allowlist only (no MIME/magic check), size configured but enforcement is `MAX_UPLOAD_SIZE_MB`; no malware scanning; scrape is well-guarded (DNS-pinned, HTML/text only) | **Likely vulnerability** (malicious-doc processing); PoC-verify parser fuzzing |
| E9 | `GET /api/v1/tts/voices` (public), `/api/v1/kafka/health` (authenticated) | Open catalog (info only); authenticated topic enumeration on a plaintext broker | **Informational** to **Likely** (`tts/router`, `kafka/router`) |
| E10 | `POST /api/v1/admin/llm/{provider}/remote-models?key=...` | Provider API key passed as a **URL query parameter** → key exposure in logs/proxies | **Confirmed, low severity** (`admin/router.py:509-581`) |
| E11 | `apps/web` external `href`s | Backend/provider-supplied URLs rendered into `<a href>`/`<img src>` (review URL, maps_url, website_url) with **no scheme validation wired in** (`lib/validation.ts` exists but is unused) — `javascript:` click-scripting if any upstream data is attacker-influenced | **Potential vulnerability** (`reviews/page.tsx:601`, `channels/page.tsx:459,464`, `locations/page.tsx:433`) |
| E12 | `apps/web` OTP/reset tokens in URL query strings; `verification_token` written to localStorage and never consumed | Token surface print in history/logs; dead store of a credential | **Likely/Potential** (`AuthForm.tsx:243-245`, `app/(auth)/reset-password/page.tsx:18`, `verify-email/page.tsx:15`) |

---

## 18. Internal trust boundaries

| Boundary | From → To | Risks |
|---|---|---|
| Web → API | browser JS → API (Bearer + CSRF) | Token theft via XSS; access token in query strings; CSRF exempts admin/auth/webhook paths — ok if never cookie-auth'd |
| Admin console → API | sessionStorage JWT → `require_admin` | Admin token read by any XSS; admin surface has `?probe=true` live-call endpoints, custom `api_url` (admin-only SSRF), verbose errors |
| API → DB | pooled asyncpg | No TLS; tracked dev password; plaintext `webhook_secret`; Fernet key = sha256(JWT_SECRET) |
| API → Redis | OTP/rate-limit/blacklist/session | OTP verify brute-force (E1); in-process fallback resets limits on restart; no `requirepass` in compose (local-only) |
| API → Kafka | outbox producer; analytics consumer | PLAINTEXT + auto-create topics; consumer trusts `user_id` from payload |
| API → providers | OpenAI/Gemini/Groq/Ollama, Resend, Google BPO, Localith | Platform-level keys shared by all tenants; key passed in query string (admin remote-models); shared Localith account leaks listings across tenants |
| API → tenant-supplied sources | RAG connectors | SSRF/scan surface (E7) |
| Workers vs requests | same process, same stores | No isolation; a worker whose input is attacker-influenced (e.g., Kafka `user_id`) touches tenant data with no extra checks |
| Frontend ↔ localStorage | `sayvors_agent_draft`, `sayvors_agents`, theme/onboarding keys | Not cleared on logout — shared-device exposure (**Likely**, `apps/web` localStorage writes) |

---

## 19. High-value assets

1. **JWT signing secret** (`services/api/.env`, plus git-history adjacency) — forges any
   user/admin session; also derives the Fernet key for all stored secrets.
2. **Provider credentials:** Google OAuth pair, Localith key, Resend key, admin
   `ADMIN_PASSWORD_HASH`; LLM provider keys (admin-managed). All single-DB, single-key.
3. **Cross-tenant customer data:** review text + reviewer names + contact/location PII
   (`Channel`, `LocationProfile`, `ReviewInsight`, `ReviewReply`,
   `review_response_logs` — full transcripts), analytics, scheduled posts.
4. **Admin plane:** user/tenant management, provider key management, usage dashboards,
   model enable/disable, health/probe live calls.
5. **Compute/egress:** unbounded LLM chat + RAG processing on platform-held keys
   (financial + data-leak risk).
6. **Scraped/databank documents** stored on local disk (`services/api/data/uploads`,
   git-ignored; not served back) — integrity/availability, supply-chain for RAG prompts.

---

## 20. Areas requiring deeper investigation (prioritized for passes 01+)

Priority reflects expected likelihood-and-impact; each will get a dedicated pass that
reads the exact code paths and, where feasible, confirms exploitability.

1. **Cross-tenant strategy/prompt injection** — global `response_strategies`
   (no tenant column) + any-user `PUT /strategies/{id}` + global load → instructions
   injected into all tenants' LLM prompts; confirm end-to-end path into generated
   replies and rollback/detection options.
2. **Email OTP brute-force** — add limits/attempt caps; confirm whether
   `verify-otp` OTP usage intersects signup/login and whether a guessed OTP can
   complete sign-in on a victim account; inspect timing behavior of the compare.
3. **Email relay** — full impact of `/api/v1/email/send`; HTML-injection into
   template; recipient/policy gating; abuse of `cta_url`; from-identity spoofing
   within the brand domain.
4. **Webhook verification fallthrough + plaintext secret** — trace accept-without-verify
   conditions per platform; replay/timestamp gaps; the pending dispatcher
   (`handle_webhook`) and what it will do; secret at rest.
5. **Access-token lifecycle** — blacklist not checked in `get_current_user`; tokens in
   response bodies; `?token=` query flows (Google connect, OAuth verify) end to end
   including Referrer/log leakage; admin sessionStorage token; `verification_token`
   localStorage dead store.
6. **LLM/RAG cost & abuse controls + prompt hardening** — absence of quotas; streaming
   SSE behavior; tool-call loop limits; prompt-injection scope for tenant-supplied
   instructions / databank text / scraped content; output-validation bypasses in
   `review_engine/validator.py`.
7. **Datasource connector SSRF/scanning** — `host`/`port` from tenant input;
   connection/version/error verbosity; `validate_readonly_sql` bypasses
   (`FOR UPDATE`, DDL words, multi-statement); row limits; TLS offload.
8. **Secrets hygiene & hardening** — rotate and scrub items in §15 (verified findings);
   `.dockerignore`; fail-fast for **all** required env vars; per-tenant key model for
   Localith/LLM; Fernet key separation + rotation; remove tracked `mentee` credentials.
9. **Infrastructure/CI/CD gap** — no CI, no image scanning, no IaC, no TLS, root
   containers, mutable base tags, no resource limits, empty `.github/`; Kafka plaintext
   + auto-create; compose datastores unauthenticated on host ports.
10. **Auth-adjacent enumeration/lockout** — signup 409 email disclosure; reset
    messaging; OTAbuse of `forgot-password` token quiescing; refresh reuse family-revoke
    follow-through; `get_client_ip`/XFF trust model end to end (frontend edge + admin
    login + backend).
11. **PII/retention/privacy** — `review_response_logs` full-transcript retention,
    `login_attempts` emails, `LocalithConnection` raw JSON snapshots, data-export/
    delete endpoints (GDPR), consent audit trail for `newsletter`.
12. **File upload & parser hardening** — MIME magic-byte validation, size enforcement
    verification, parser resource limits (PDF/XLSX), filename/path handling, storage
    ACLs, malware scanning options.
13. **Kafka/consumer integrity** — trust of `user_id` in payloads, topic ACLs, replay,
    idempotency boundaries between consumer, outbox, and workers when horizontally
    scaled.
14. **Frontend defense-in-depth** — server-side dashboard auth (cookie validity),
    external-URL scheme validation for all `href`/`img`, localStorage cleanup on
    logout, CSP `style-src`, `connect-src` exact-origin enforcement.

---

*End of pass 00. No application code was modified or fixed during this audit — this
document is the scoping and reference baseline for security-audits/01+.*