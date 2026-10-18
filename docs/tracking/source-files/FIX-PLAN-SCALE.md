# Sayvors — Scale Readiness Fix Plan (2M Users)

> Scope: **service-layer fixes only** (auth, AI/LLM, RAG, STT/TTS, Kafka/Redis/Outbox, DB pool).
> Deployment/infra issues (Docker, CI, monitoring, backups) are tracked separately in `FIXES-NEEDED.md` Phase D and are **out of scope here**.

**Bottom line:** The architecture (modular monolith + transactional outbox + Redis + Kafka + provider abstraction) is the right skeleton for 2M users. Nothing needs a fundamental redesign — the gap is execution. Estimated total effort: **4–6 weeks**.

| Service | 2M-Ready? | Effort | Priority |
|---|---|---|---|
| Auth | 🟡 Close | ~1–2 weeks | P1 |
| LLM | 🟡 Close | ~1 week | P1 |
| RAG search (pgvector) | 🔴 No | 2–3 days | **P0** |
| RAG ingest/worker | 🔴 No | ~1 week | **P0** |
| STT / TTS | ⚪ Not built | TBD | P3 |
| Kafka / Redis / Outbox | 🟡 Pattern right | ~3 days | P1 |
| DB pool config | 🔴 Hours | Hours | **P0** |

---

## P0 — Week 1: The walls you hit first

### 0.1 Database connection pool (hours)
**Where:** `services/api/app/database.py:8`

`create_async_engine` uses all defaults: `pool_size=5`, `max_overflow=10`, `pool_pre_ping=False`, no `pool_recycle`. Every module funnels through these ~15 connections per instance.

**Fix:**
```python
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,        # default 20
    max_overflow=settings.DB_MAX_OVERFLOW,  # default 40
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
)
```
Make sizes env-configurable per deployment. `pool_pre_ping` removes stale-connection errors behind load balancers.

---

### 0.2 RAG vector search — swap to pgvector (2–3 days, contained rewrite)
**Where:** `services/api/app/modules/rag/search.py` (whole file), `rag/models.py:70`

**Current behavior (fatal at scale):**
- `hybrid_search` loads **every chunk of the databank into Python memory**, `json.loads` each ~20KB embedding, and runs cosine similarity in a pure-Python loop → 10k chunks ≈ 200MB RAM + seconds of CPU **per query**.
- Embeddings stored as JSON text, not vectors. pgvector is a declared dependency but **never used**.
- Keyword search computes `to_tsvector` on the fly with **no GIN index** → full table scan per query.

**Fix:**
1. Alembic migration:
   - Add `embedding_vec vector(1536)` column (dimension = your embedding model's) to `document_chunks`.
   - Backfill from the JSON `embedding` column, then drop it.
   - `CREATE INDEX ... USING hnsw (embedding_vec vector_cosine_ops)`.
   - Add generated `tsv tsvector` column (`to_tsvector('english', content)`) + GIN index.
2. Rewrite `hybrid_search` as two indexed top-K queries:
   - Vector: `ORDER BY embedding_vec <=> :qv LIMIT :top_k`
   - Keyword: `tsv @@ websearch_to_tsquery(...)` with the GIN index
   - Keep the existing RRF merge — it operates on two small lists, which is exactly right.
3. Fix dimension consistency: lock one embedding model per chunk index (see 0.4 / audit B11).

**Result:** per-query cost drops from O(N chunks in Python) to two indexed lookups. This alone takes RAG from ~100 concurrent users to 2M-user territory.

---

### 0.3 RAG uploads — actually persist files (1–2 days)
**Where:** `services/api/app/modules/rag/service.py:87-108`

Uploads are read into memory but **never written anywhere**; the parser then opens `/tmp/sayvors_docs/{doc.id}.{ext}` — a path that never exists. **Every ingest job fails.** Also `file.read()` has no size cap → memory DoS.

**Fix:**
- Stream upload to object storage (S3/Azure Blob) or shared volume; store the storage key on the `Document` row; parser reads from storage.
- `await file.read(MAX_UPLOAD_SIZE)` — reject beyond a hard cap (e.g. 25MB).
- Verify magic bytes, not just extension (xlsx/pdf/docx are executed by parsers).

---

### 0.4 RAG ingest worker — real job leasing (~1 week)
**Where:** `services/api/app/modules/rag/jobs.py`

Worker is an in-process asyncio task: per-instance semaphore/flags, no DB locking, no crash recovery. Multi-instance = same job processed twice; a process death = rows stuck in `parsing` forever.

**Fix:**
- `SELECT ... FOR UPDATE SKIP LOCKED LIMIT :batch` leasing with a `lease_expires_at` column and heartbeats.
- On startup (and periodically): reset stale in-progress jobs to `queued`.
- Cap docs per job batch (e.g. 50) instead of enqueuing all pending into one job (audit B8).
- Move to a dedicated worker process (can still share the codebase; the `make api-dev` API process no longer runs ingestion).
- Sanitize `job.error` before returning to users (leaks filesystem paths today — audit B17).
- Wire in the (currently dead) embedding cache and `content_hash` dedup (audits B7, B12) — big cost saver at scale.

---

## P1 — Weeks 2–3: Auth + LLM guardrails

### 1.1 Auth — fail closed + remove single-process assumptions
**Where:** `services/api/app/modules/auth/rate_limit.py`

All rate-limit/blacklist/session checks `except Exception: return True/pass` — when Redis blips (it will, at scale), brute-force protection and token revocation silently vanish. The in-process `_fallback_store` dict only works with a single API instance.

**Fix:**
- Auth-critical checks (login, refresh, blacklist) **fail closed** if Redis is unavailable; log loudly / emit alert event.
- Remove or disable the dict fallback in multi-instance deployments (config flag).
- IP extraction: stop trusting `x-forwarded-for` unconditionally; configurable trusted-proxy count, else `client.host` (audit A8).

### 1.2 Auth — login_attempts firehose + cleanup
**Where:** `services/api/app/modules/auth/service.py` (`login`, `cleanup_expired_data`)

- A `LoginAttempt` row is inserted on **every** login, success or failure → at 2M users this is a constant insert firehose + unbounded growth.
  **Fix:** log failures (and lockouts) only; successes are already in `log_login` events → drop them from the table, or move the whole thing to Redis/Kafka async.
- `cleanup_expired_data` runs only at app startup → effectively never on long-lived pods. **Fix:** schedule it (asyncio repeating task / cron / outbox-driven) and make deletes **batched** (`DELETE ... LIMIT 1000` in a loop) to avoid long locks.
- `delete_all_sessions` uses `SCAN` over `session:{user_id}:*` → O(keyspace). **Fix:** maintain a per-user Set of session keys; delete via `SMEMBERS` + `DEL`.
- Refresh-token reuse detection: on use of a revoked token, revoke the whole family for that user (audit A6). Compare the token fingerprint at refresh (currently dead code — audit A7).

### 1.3 LLM — quotas, budgets, and session hygiene
**Where:** `services/api/app/modules/llm/service.py`, `llm/router.py`

1. **Per-user quotas (the big one):** no rate limits or token budgets on `/chat`, `/tts/convert`, `/stt/transscribe` → one user can bankrupt provider spend. Add quota middleware: per-minute requests + monthly token budget per user, tracked in Redis, spend events to Kafka.
2. **Honor `max_tokens`:** schema accepts up to 100k, service hardcodes 1000. Clamp per-model instead of ignoring.
3. **Don't hold a DB session across provider calls:** `send_message`/`stream_message` hold the AsyncSession for the full provider round trip (seconds) → pool exhaustion under load. Persist the user message and commit/close, call the provider, then open a new session to persist the reply.
4. **Pooled provider clients:** reuse httpx/OpenAI clients across requests; no per-call construction (audit B10).
5. **Timeouts + retries + circuit breaker** per provider: exponential backoff on 429/5xx, cap total wait; one slow provider must not stall workers.
6. **Streaming crash-safety:** persist an assistant placeholder before streaming and finalize after; client disconnect currently orphans the turn (audit B21).
7. Map provider errors to safe messages; never propagate raw exception text (may contain keys/URLs — audit B23).

*(Note: `_load_history` is already capped at 40 messages — audit B18 is stale.)*

### 1.4 Redis / Kafka / Outbox hardening
**Where:** `modules/redis/*`, `modules/kafka/*`, `modules/outbox/*`

- Pattern is correct (transactional outbox → Kafka). Keep it.
- Replace **every** silent `except: pass` with categorized handling: degrade where safe (sessions cache), fail closed where not (auth, quotas).
- Outbox worker: add `FOR UPDATE SKIP LOCKED` too if multiple API instances run it; add retry/backoff with dead-letter topic for poison events.
- Emit a health/degradation signal (metric or event) whenever a dependency is marked unavailable — today it's invisible.

---

## P2 — Week 4: Channels, SSRF, encryption

- **Encrypt channel credentials at rest** (`channels/models.py`): `access_token`, `refresh_token`, `webhook_secret` are plaintext. Field-level encryption with KMS-wrapped keys (audit B25).
- **Require `webhook_secret`** to process non-verify webhooks (audit G3 gap in B24).
- **SSRF guards** before any scraper/URL-fetching ships: block loopback/private/link-local ranges, resolve DNS and re-check, allowlist schemes (audits B9, B26 — `rag/schemas.py`, `stt/schemas.py`).
- **Pagination everywhere:** `list_all_databanks` has none + N+1 count per databank (audit B13); sweep all list endpoints for limit/offset.
- **LLM conversation continuity:** accept `conversation_id` in `/chat` (audit B19) — required for the auto-reply product to make sense.

## P3 — Later

- **STT/TTS:** real provider implementations, pooled clients, quotas, SSRF-safe `audio_url` fetching.
- **PII column encryption** for emails/conversation content (audit A13) with DB snapshot encryption.
- **JWT hardening:** add `iss`/`aud`/`iat`/`jti` verification in `decode_token` (audit A11).

---

## Suggested order of execution

1. **0.1** DB pool config — hours, unblocks load testing everything else.
2. **0.2** pgvector search rewrite + migration — biggest scalability win.
3. **0.3 + 0.4** RAG upload persistence + worker leasing — makes RAG actually function.
4. **1.1 + 1.2** Auth fail-closed + retention — security and table growth.
5. **1.3** LLM quotas — before this, don't expose `/chat` publicly at all.
6. **1.4** Dependency degradation semantics.
7. P2/P3 as capacity allows.

Each numbered item is independently shippable — no big-bang rewrite required.
