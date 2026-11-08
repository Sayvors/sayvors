# Sayvors — Phase 1 Launch Readiness Audit (WhatsApp + GBP)

**Date:** 2026-11-01
**Baseline commit:** `3f57276` on `development` (WA-4/WA-5 message actions committed; tree clean at audit time).
**Scope:** full stack — services/api, apps/web, apps/admin, infra/compose/CI — against a 1M-user target with Phase 1 = WhatsApp + Google Business Profile launching first.
**Method:** re-verification of every open finding in `2026-10-31-scale-readiness-audit-1m-users.md` against current code (five parallel verification passes: security claims, performance claims, WhatsApp/GBP critical path, both frontends, infra/CI-CD), plus lead-audit of areas the prior pass did not cover (billing ledger, backend admin auth, retention, migration chain). Every finding below cites `file:line` verified on 2026-11-01. No files were modified.

**Path correction for all future audits:** config and database live at `services/api/app/config.py` and `services/api/app/database.py` — **not** `app/core/` as the 10-31 audit cited.

---

## 1. Executive summary

The application layer confirmed yesterday's grade (A−): auth, tenant isolation, OAuth,
webhook verification, billing ledger, worker mechanics, and the message-actions work are
genuinely production-grade, and two scary prior claims turned out already fixed or wrong.

But this pass found **four launch blockers the 10-31 audit missed**, all in the Phase 1
path or its storage, plus a set of MAJOR gaps that are cheap to fix but public today:

1. `meta_webhook_events` retention is a **no-op** — the sweeper deletes statuses no code
   ever writes. The table grows forever with raw payloads and breaks at launch scale, not 1M.
2. **An AI reply, once lost, is permanently lost** — dedupe early-return converts crashes
   and transient Meta/LLM failures into silent "success"; sends have no retry and no DLQ.
3. **Inbox message history is unbounded** on the frontend — one response, all rendered.
4. **Backups are never scheduled** and the prod env template leaves the required bucket
   var commented out — as configured, backups would fail; as operated, RPO is infinite.

Posture: application A− (unchanged, now with named gaps), Phase 1 messaging path B
(solid mechanics, broken loss-recovery and status bookkeeping), infrastructure D (unchanged),
frontend B− (good bones, three launch-relevant majors).

---

## 2. Verdicts on the 2026-10-31 audit claims

### Security (S-items)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| S1 | Prometheus 0.0.0.0:9090 | **CONFIRMED** | `docker-compose.prod.yml:160-161`; only other public ports are caddy 80/443 |
| S2 | Redis no auth, AOF off, 128MB | **CONFIRMED** | compose `:121`; restart loses OTPs/blacklist/rate-limits (DB revoked-flag is the backstop, `auth/rate_limit.py:66-69`) |
| S3 | Kafka PLAINTEXT RF=1 auto-create | **CONFIRMED** | compose `:137-145`; no published ports (mitigating); client SASL/TLS support exists (`app/config.py:61-75`) |
| S4 | `str(e)` to clients | **CONFIRMED, broader** | ~130 `detail=str(` sites across nearly every router; worst are meta/storage/rag 502s carrying driver errors |
| S5 | Signup enumeration | **CONFIRMED** | `auth/service.py:62-65` → `auth/router.py:158-161` 409 verbatim (forgot-password is correctly generic) |
| S6 | No .dockerignore, root build context | **CONFIRMED** | zero `.dockerignore`; `deploy-staging.yml:88` `context: .` |
| S7 | LLM rate limit fail-open | **CONFIRMED** | `llm/router.py:39-48`; one more fail-open site: `meta/router.py:798` (WA profile fetch) |
| S8 | Admin token in sessionStorage | **FIXED** | `apps/admin/lib/admin-api.ts` — httpOnly cookie, path-scoped, SameSite=strict, zero JS token storage |
| S9 | Agent-draft keys not cleared | **CHANGED** | claimed keys gone; logout still clears nothing — chat transcripts + `verification_token` persist (`apps/web/lib/auth-context.tsx:246-254`) |
| S10 | /docs + /redoc in prod | **CONFIRMED** | `main.py:499` no docs gating; Caddy proxies every path → publicly browsable on api.staging.sayvors.com |
| S11 | Dev inline PGBOUNCER_PASSWORD | **CONFIRMED** | `docker-compose.yml:45`, dev-only |

New security verifications: **auth fails closed** on Redis outage at every endpoint incl.
blacklist checks (`AUTH_RATE_LIMIT_FAIL_CLOSED=True` default; only 2 deliberate fail-open
sites). `validate_production_settings()` (`app/config.py:334-376`) is real and enforced at
import in prod — but does not cover Redis/Kafka/docs/cookie flags. **No global rate limit**
exists; throttling is per-endpoint opt-in only.

### Performance (P-items)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| P1 | Single-writer PG, no replica | **CONFIRMED, worse** | `get_db_read` has **zero call sites** repo-wide (419 uses of writer); PgBouncer dev-only; `DB_POOL_MODE` is dead config |
| P2 | Local-disk upload fallback | **CONFIRMED (nuanced)** | media on S3, but `S3_DOCS_BUCKET` commented out in `env.prod.example:68` → private docs on local volume; no fail-closed startup check |
| P3 | Alembic at boot | **CONFIRMED (latent)** | `Dockerfile:31`, compose `:47`; worker correctly gated on api health; race requires >1 api replica |
| P4 | SSE streams pin DB pool | **REFUTED (half)** | both stream endpoints `db.close()` before generation (`llm/service.py:206-207`, `review_engine/service.py:759-760`); **no concurrency cap confirmed** — only fail-open 60/min limit |
| P5 | Pool sizing | **CONFIRMED** | 5/5/30s defaults; env template overrides 10/10; headroom check warns only |
| P6 | Offset pagination | **MIXED** | keyset cursor exists in inbox service (`channels/service.py:1780-1788`) **but is dead code** — route never exposes `cursor` (`router.py:716-728`); filters applied post-LIMIT in Python; most other lists offset + COUNT(\*) |
| P7 | In-process /metrics | **CONFIRMED** | globals `main.py:93-98`; prod runs 2 uvicorn workers → each scrape sees ~half; no prometheus_client |
| P8 | Rollup per review event | **CONFIRMED** | ≈6-7 queries + 2 commits per event; coalesce range is unindexable |
| P9 | 100MB body limit | **CONFIRMED** | `main.py:499`; webhooks add their own 1MB caps |

### Infra (I-items) — all ten CONFIRMED, with refinements

I1–I10 stand as written (single box, unscheduled backups, boot migrations, single-node
Kafka/Redis, mutable `:staging` tag, root containers + broken web healthcheck, no vuln
scan/dependabot/CD, no alerting, bare Caddy, RDS ssl=require good). Refinements: gitleaks
**does** run in the deploy workflow; deploy is human-run `docker compose pull` on the box
(repo went private, breaking the old git-pull deploy); RDS `ssl=require` encrypts but does
not authenticate the server (no `verify-full`); cloudflared tunnel ingress config is
**untracked** — production entry point exists outside the repo (`next.config.ts:11-14`).

### Frontend claims from readiness-report.html

Virtualized thread list ✓, notifications bell 45s with `document.hidden` guard ✓, CSP
nonce + strict-dynamic ✓ (web), TanStack Query defaults sane ✓, admin httpOnly cookie ✓.
Still true and still open: the rest of §4 below.

---

## 3. Findings

### BLOCKER (launch-blocking)

**B1 — `meta_webhook_events` retention is a no-op; the table grows forever.**
`retention.py:73-82` deletes only `status IN ("processed","duplicate","rejected")`.
`meta/webhooks/router.py` writes only "received"/"unresolved"; **nothing in the codebase
ever writes "processed" or "rejected"** — the consumer never marks the event row. Every
unique webhook event, including every `message.status` for every message, persists with
full `raw_payload` JSON. Breaks at launch scale (weeks–months on a busy number), long
before 1M users. *Fix (one line):* add "received"/"unresolved" to the retention status
list (shorter age), or write "processed" when the worker finishes an event. The index
(`ix_meta_webhook_events_status_created`) already exists.

**B2 — An AI reply, once lost, is permanently lost.**
`meta/consumer.py:1212-1221`: dedupe by `platform_message_id` early-returns before
anything else. Inbound row commits at `:1253`; if the process crashes, the LLM is down,
or the send throws after that commit, the worker retries the event — but the retry hits
the dedupe check and returns success. The retry machinery launders a lost reply into
"handled". *Fix:* a reply-pending state on the inbound row that the dedupe path re-drives
instead of early-returning.

**B3 — No retry/DLQ on sends toward Meta.**
`providers/base.py _graph` (`:59-71`): exactly one attempt, 20s timeout, raises on ≥400.
`consumer.py:1905-1942` catches `MetaAPIError`, writes a `status="failed"` row, returns.
No retry, no backoff, no dead-letter for replies. One transient Meta 5xx during an outage
= permanently unanswered customer (with B2, the retry can't save it either). The
EventOutbox retry taxonomy (transient/permanent/ambiguous) already exists — the send path
just doesn't use it.

**B4 — Backups never scheduled; template breaks them; no DR rehearsal.**
`scripts/db_backup.py` has cron only as a docstring comment (`:13`); zero
cron/systemd/compose/workflow scheduling in the repo; no retention/pruning; and
`deploy/env.prod.example:68` leaves `S3_DOCS_BUCKET` commented out — following the
template, the backup fails its env check. `db_restore.py:99-119` does `DROP DATABASE`
on whatever URL it is handed with no interlock. RPO = infinite as operated.

**B5 — Inbox message history is unbounded on the frontend.**
`apps/web/lib/api-inbox.ts:150-162` `fetchThreadMessages` has no pagination — the entire
thread history returns in one response and renders in full (`InboxView.tsx:974-979,
1565`). The 500-message buffer cap applies only to WS appends. A 10k-message thread =
10k-row JSON + 10k React nodes on open. *Fix:* cursor pagination + windowed rendering
before launch.

### MAJOR — security

| # | Finding | Anchor |
|---|---|---|
| S-1 | `/metrics`, `/readyz`, `/docs`, `/redoc`, `/openapi.json` publicly reachable — Caddy proxies every path, routes unauthenticated/unthrottled | `deploy/Caddyfile:1-3`, `main.py:499,607,628` |
| S-2 | SSRF in WhatsApp `_publish_status_update` — `http.get(media_url)` on tenant-supplied URL, no scheme/host/IP validation; the correct guard (`_assert_media_fetchable`) exists one module away, unused here | `whatsapp.py:699-751`; pattern at `meta/router.py:1523-1566` |
| S-3 | Meta webhook ingress has **no rate limit at all** (only HMAC); legacy webhook caps verified traffic at 100/min/channel (would 429 Meta at scale if ever wired) and its handler is a **stub returning None** | `meta/webhooks/router.py:43-77`; `channels/router.py:1646-1649`, `service.py:1238-1243` |
| S-4 | SayvorsChat markdown renderer accepts `javascript:` hrefs from AI output (prompt-injectable via customer messages) → XSS in dashboard origin | `SayvorsChat.tsx:127-133` — allowlist http/https/mailto |
| S-5 | Next middleware rate limiter: in-memory Map, no eviction (memory-DoS, farmable via spoofed XFF) AND 100 req/min/IP trips office NATs; per-instance so multi-replica makes it inconsistent | `apps/web/middleware.ts:4-24` |
| S-6 | apps/admin ships **zero security headers** (empty next.config, no middleware) | `apps/admin/next.config.ts:4-6` |
| S-7 | CSP breaks Google Maps in prod — `img-src`/`connect-src` missing maps hosts | `middleware.ts:86,90` vs `LocationsMap.tsx:36-40` |
| S-8 | Redis unauthenticated + AOF off + 128MB in prod (see S2) | compose `:114-129` |
| S-9 | Kafka PLAINTEXT/RF=1/auto-create (see S3) | compose `:131-154` |
| S-10 | `str(e)` to clients, systemic (~130 sites; worst = 502 driver errors in meta/storage/rag) | grep `detail=str(` tree-wide |
| S-11 | Signup enumeration (see S5) | `auth/router.py:158-161` |
| S-12 | No `.dockerignore`; repo root is the build context (`.git`, docs, stray `.env` ship to the daemon) | `deploy-staging.yml:88` |
| S-13 | Prometheus on 0.0.0.0:9090 (see S1) | compose `:160-161` |
| S-14 | Containers run as root (both Dockerfiles); no CPU limits; no log-rotation config on a 2GB no-swap host | `services/api/Dockerfile`, `apps/web/Dockerfile` |

### MAJOR — scale/performance

| # | Finding | Anchor |
|---|---|---|
| P-1 | Read-replica plumbing is dead code — every auth check (2+ queries/request) hits the primary; no cache; PgBouncer prod-absent | `database.py:170` (sole ref), `core/deps.py:21-82` |
| P-2 | Customers page: loads ≤10,000 threads + the **entire Lead table** per request + 2 queries per Google-review thread (N+1), filters/sorts in Python, RBAC applied **after** slicing (short pages, wrong totals) | `customers_service.py:96-160`, `customers_router.py:47-53` |
| P-3 | Inbox keyset cursor is dead code from HTTP; category/priority/important/RBAC filters run in Python post-LIMIT — threads beyond the first 500 unreachable | `channels/router.py:716-737` vs `service.py:1780-1788` |
| P-4 | `message.status` dedupe collapse — parser keys all statuses on the same `(wamid, "message.status")`, so only the FIRST status per wamid survives; delivered/read/failed invisible forever; outbound rows never leave "sent" | `parser.py:64-77`, unique constraint `meta/models.py:128-131` |
| P-5 | AI-reply throughput: single worker replica ≈ 2 msg/s (concurrency 8, 5s poll) vs a 10k msg/min launch target — 60-100× gap; horizontal scaling is designed-in (`--scale worker`, `WORKER_LOOPS`) but not the default topology; ingress commits per event (~4 round trips) | `meta_events_worker.py:53-59`, `webhooks/router.py:80-158` |
| P-6 | No outbound pacing toward Meta's ~80 msg/s per-number limit; first viral tenant trips 429s which (per B3) are terminal | send path, `whatsapp.py` |
| P-7 | Metrics multi-worker blindness (see P7) + `/metrics` scrape runs live DB+Redis queries | `main.py:93-98,654-699` |

### MINOR (selected, with anchors)

- **M-1** Legacy `/channels/webhook/{platform}` is a signature-verified stub that silently drops payloads — delete or quarantine (`service.py:1238-1243`).
- **M-2** Dead Kafka consumer, never started, would never commit offsets if started (`consumer.py:3072-3110`); `meta-events` topic produced but never consumed.
- **M-3** `int(content_length)` can 500 on malformed header (`channels/router.py:1591`, `webhooks/router.py:46`); `hmac.compare_digest` on verify_token can TypeError on non-ASCII (`verifier.py`).
- **M-4** PII inconsistency: `ChannelMessage.contact_phone` encrypted, but `WhatsAppThreadState`/`ConversationContext`/IGSID `contact_profile.contact_id` plaintext.
- **M-5** AI auto-replies bypass `_ensure_messaging_quota` (human sends only) — bounded by budget gate, but free-tier AI reply count is uncapped. <strong>Decision 2026-11-03:</strong> AI auto-replies remain unbounded by `max_messages_per_month`. The LLM budget gate (`check_feature(tenant_id, "ai_replies")`, fail-closed entitlement + credit reserve/settle before every LLM call) directly caps dollar cost (tokens), whereas the messaging quota caps human conversation volume. AI replies are selectively triggered by `should_ai_reply()` — not every inbound message generates one. Documented in docs/guides/billing-and-notifications.md under "Messaging quota vs. AI auto-replies." **Superseded 2026-11-08:** the allowance is WhatsApp-only and now gates both human sends (inbox + templates) and WhatsApp AI auto-replies; Instagram/Facebook are excluded. Approved packs are additive `message_bonus` over the plan limit. Current behaviour: `docs/security/message-quotas.md`.
- **M-6** Logout clears no localStorage: `verification_token` (dead credential, written at `AuthForm.tsx:385`, never read), chat transcripts, contact groups.
- **M-7** Inbox pin/archive/delete failures swallowed (`catch { /* keep stale */ }`, `InboxView.tsx:369-412`) — violates the repo's no-silent-failure rule; Delete button not busy-guarded (double-fire).
- **M-8** `send()` wipes the composer draft even when the provider rejected the send (`InboxView.tsx:1072`).
- **M-9** Admin overview: two effects share one `liveInterval` ref — each kill's the other; live stats frozen until manual refresh (`overview/page.tsx:270-291`). Logs poll lacks `document.hidden` guard (`logs/page.tsx:82`).
- **M-10** WS reconnect: exponential backoff caps at 16s, **no jitter** — API restart reconnects every dashboard in lockstep (`use-inbox-realtime.ts:109-143`).
- **M-11** `channel_messages` has no retention/partitioning story — product decision needed before it is the largest table (`retention.py` covers webhook events, notifications, usage, jobs, outbox only).
- **M-12** `llm_usage_events` lacks `(tenant_id, created_at)` composite; review-insights search uses unindexable `LOWER(LIKE %…%)` + offset (`analytics/service.py:275-280`).
- **M-13** JobPanel dead code (2s poll, not imported); `optimizePackageImports` lists non-dependencies; `DB_POOL_MODE` consumed nowhere.

### Status re-verification — 2026-11-08 (open items only)

The ledger in `readiness-report.html` counts four items still open from this
pass: S-8, S-9, S-10 and M-9 readiness IDs. All four were re-checked against
the tree at `524ef6a` and the live staging box; **none are fixed**:

- **S-8 Redis** — staging still runs `redis-server --maxmemory 128mb
  --maxmemory-policy noeviction`; `CONFIG GET appendonly` returns `no`;
  `CONFIG GET requirepass` is empty; `deploy/prometheus.yml` has no
  `rule_files` and there is no alertmanager. The 128 MB ceiling is also the
  most a 2 GB t3.small can give Redis next to api+worker (768 MB each) and
  Kafka (384 MB), so the real fix is the managed-cache move, not a bigger
  `maxmemory`.
- **S-9 Kafka** — staging still advertises `PLAINTEXT://kafka:9092`, sets
  `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true`, and runs one broker with
  replication factor 1. Needs SASL/TLS + a real broker topology (or
  consolidation onto the Postgres outbox), not a one-line compose edit.
- **S-10 `str(e)` sweep** — 125 `detail=str(` sites remain, mostly 4xx
  validation/ownership paths. The Phase 1 `upstream_http_error()` work
  converted the 502 provider paths; the per-site safe/public split is still
  the open work.
- **M-9 scale wiring** — `get_db_read()` still has zero call sites; `/metrics`
  is still in-process globals under two uvicorn workers; Alembic still runs
  in the API container command; `channel_messages` retention/partitioning is
  still an open product decision. Only M-9(d) (indexes) and M-9(f)
  (throughput runbook) were completed.

---

## 4. Verified good (launch-confidence list)

- **Billing ledger** (`billing/ledger.py`): row-locked reserve/settle, terminal-state
  idempotency (retries cannot double-charge), expired-hold reversal, recover-before-expire
  reaper ordering, fail-closed DB errors, Redis as post-commit mirror only. Two notes:
  late settle can push a balance negative by design (next reserve denies — acceptable);
  finalized idempotency-key retry raises ValueError rather than returning the prior result.
- **Admin auth, both ends**: operator accounts + per-account/global lockouts + IP limits +
  httpOnly path-scoped cookie + audit log; `require_admin` rejects user JWTs, uses
  X-Requested-With as CSRF substitute; client guard never fetches data before the check.
- **Webhook ingestion**: timing-safe HMAC over raw bytes, fail-closed on missing
  secret/header, 1MB raw-body cap, ingest-dedupe via unique constraint, outbox pattern
  (no Kafka in the request path), worker with SKIP LOCKED + leases + bounded backoff +
  dead-letter + concurrency caps.
- **OAuth (Meta + Google)**: hashed one-time state with atomic claim, single-use 120s
  tickets burned via Redis getdel, refresh-token healing, revocation checks mirrored in
  the WS auth path.
- **Auth**: fails closed on Redis outage everywhere it matters; lockout, rotation with
  reuse detection, token blacklist + version checks.
- **Tenant isolation** on every checked path (channels, inbox, customers, localith, meta,
  google), consumer re-resolves tenant from DB.
- **Message actions (WA-4/WA-5)**: migration idempotent both directions, single head,
  endpoints tenant-scoped (403 cross-tenant), removal outbound-only with evidence
  preservation, deleted messages excluded from AI history; 388-line test file covers the
  edge cases.
- **Indexes match hot query shapes** on channel_messages/threads (inbox, thread loads,
  dedupe partial unique index).
- **Frontends**: httpOnly-cookie auth (no tokens in JS) both apps; nonce CSP +
  strict-dynamic (web); virtualized lists; React Query with no refetch storms and
  surfaced errors; WS instead of polling; lean bundles; single dangerouslySetInnerHTML
  (hardcoded constant); all `_blank` links carry noopener.
- **Kafka producer** acks=all + idempotence; consumers manual-commit; outbox drain with
  DLQ + capped backoff; retention sweeps batched/bounded where they apply.
- **Migration chain**: single head (`f6a2d9c4e713805b`), 146 revisions, no broken links.

---

## 5. Prioritized launch list (Phase 1: WhatsApp + GBP)

### Fix now — code, hours not days
1. **B1** retention status list (one line) + write a terminal status in the worker.
2. **P-4/M1** include status in `message.status` event identity (1-2 lines in parser).
3. **B2+B3** reply-pending re-drive + send retry via existing outbox taxonomy.
4. **S-2** route WhatsApp status media fetch through `_assert_media_fetchable`.
5. **S-4** protocol allowlist in SayvorsChat links; **S-7** add maps hosts to CSP.
6. **B5** cursor pagination on thread messages + windowed render.
7. **S-1/S-10** Caddy: block `/metrics /readyz /docs /redoc /openapi.json` (or admin-gate);
   disable docs in prod (`docs_url=None` when `ENVIRONMENT=production`).
8. **S-3** rate-limit meta ingress (generous, fail-closed); delete/quarantine legacy stub.
9. **P-2/P-3** wire the existing inbox cursor to the route; push customers filtering into
   SQL with RBAC-before-slice.
10. **M-6/M-7/M-8/M-9/M-10** logout cleanup, surface inbox action errors, draft preservation,
    admin polling ref fix, WS jitter.

### Fix before real customers — ops, needs the production VM decision
11. **B4** schedule `db_backup.py` (cron/systemd/Actions), set retention, uncomment
    `S3_DOCS_BUCKET`, rehearse `db_restore.py` once, add an interlock.
12. Redis: `requirepass` + AOF + 1-2GB (S-8); Prometheus → 127.0.0.1 (S-13).
13. Pin `:staging` → SHA tag (one line; SHA tags already pushed).
14. `.dockerignore` at root + api/ (S-12); non-root USER (S-14); `UVICORN_WORKERS=1` per
    pod or multiproc metrics (P-7).
15. Alerting: even one alertmanager rule set (queue depth, Redis memory ≥75%, 5xx rate)
    closes the biggest ops gap (I8).
16. Alembic out of boot before scaling api >1 (P3); legacy webhook endpoint removal (M-1).

### Phase 2 / scale-out (designed for, not yet wired)
17. Read replica → `DATABASE_READER_URL` + actually route hot reads (`get_db_read` exists,
    zero callers); PgBouncer in prod; auth short-TTL cache (P-1).
18. Worker scaling runbook: `--scale worker=N` + `WORKER_LOOPS=meta-events-ai-replies`
    split; batch ingress commits (P-5).
19. Outbound pacing token bucket per number (P-6).
20. `channel_messages` retention/partitioning decision (M-11); keyset pagination
    everywhere (P-3 follow-up).

---

## 6. Bottom line

The codebase is closer to launch-ready than the infra is, and the Phase 1 messaging path
needs ~a day of focused fixes (B1, P-4, S-2 are each small; B2/B3 is the one substantive
change) to stop losing replies silently. The frontend needs the message-history
pagination before any tenant with long threads touches it. Nothing here requires
re-architecture; the blockers are bookkeeping, retry wiring, and bounds that were missed,
not design flaws. Infrastructure remains the long pole and is unchanged from yesterday's
verdict: the app can serve 1M users; the single 2GB box cannot.

*No application code was modified for this audit. `readiness-report.html` should absorb
§3/§5 per the repo's housekeeping rule — left untouched here per instruction.*
