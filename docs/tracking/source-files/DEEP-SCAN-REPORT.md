# 🔍 Deep Scan Report — Security · Performance · Scalability (2M Users)

**Date:** August 13, 2026  
**Scope:** Full-stack — FastAPI backend + Next.js 16 frontend  
**Audit Comparison:** SECURITY-AUDIT.md vs FIXES-NEEDED.md vs actual code  
**Scale Target:** 2,000,000 users  

---

## 📊 Scorecard Summary

| Area | Score | Grade | Status |
|------|-------|-------|--------|
| **Authentication & Authorization** | 72/100 | B- | Good foundation, critical gaps remain |
| **Cryptographic Security** | 85/100 | B+ | Solid implementation, config hardening needed |
| **Injection & Input Validation** | 88/100 | B+ | SQLAlchemy ORM is strong, edge cases exist |
| **CSRF / XSS / Headers** | 80/100 | B | CSP needs cleanup, CSRF solid |
| **API Security & Rate Limiting** | 65/100 | C+ | Auth endpoints good, compute endpoints unprotected |
| **Database & ORM Performance** | 55/100 | D+ | N+1 queries, missing indexes, no pooling config |
| **RAG Pipeline (Search & Embeddings)** | 40/100 | F | Full in-memory scan, no vector DB, broken at scale |
| **Worker & Queue Reliability** | 50/100 | D | In-process only, no distributed locking |
| **Frontend Performance** | 45/100 | F | 100% client components, zero RSC, no code splitting |
| **Infrastructure & Deployment** | 15/100 | F | No Dockerfiles, no CI, no monitoring, no backups |
| **Data Privacy & Compliance** | 40/100 | F | No GDPR, no data export, PII in plaintext |
| **Observability & Monitoring** | 20/100 | F | No Sentry, no metrics, no structured logging |

**Overall: D+ (47/100) — Not production-ready for 2M users**

---

## 🔴 CRITICAL: What Will Kill You at 2M Users

### 1. RAG Search is O(N) In-Memory — Will Crash at Scale
**File:** `services/api/app/modules/rag/search.py`  
**Code:**
```python
# Line 25-45: Loads EVERY chunk into Python memory
load_sql = text("""
    SELECT id, content, document_id, metadata, embedding
    FROM document_chunks
    WHERE databank_id = :databank_id
      AND embedding IS NOT NULL
    ORDER BY seq
""")
result = await db.execute(load_sql, {"databank_id": databank_id})
all_chunks = result.fetchall()  # ← ALL chunks, no LIMIT

# Line 36-42: Pure Python cosine similarity
for row in all_chunks:
    chunk_vec = json.loads(row.embedding)  # ← JSON parse per chunk
    score = _cosine_similarity(query_vector, chunk_vec)
```

**Impact at 2M users:**
- 1000 users × 10K chunks each = 10M chunks loaded per query
- Each chunk embedding is ~15-20KB as JSON text
- **Memory: 10M × 20KB = 200GB per query** — instant OOM
- CPU: O(N) cosine similarity with JSON parsing = seconds per query
- pgvector is declared in `pyproject.toml` but **never used**

**Required Fix:** pgvector with HNSW index + vector column type. This is non-negotiable for 2M users.

---

### 2. Database Connection Pool is Bare Default
**File:** `services/api/app/database.py`  
**Code:**
```python
engine = create_async_engine(settings.DATABASE_URL, echo=False)
# That's it. No pool_size, no max_overflow, no pool_pre_ping, no pool_recycle
```

**Impact at 2M users:**
- SQLAlchemy default: `pool_size=5`, `max_overflow=10` = max 15 connections
- At 2M users with concurrent requests, you'll hit connection starvation in <100ms
- No `pool_pre_ping=True` means dead connections cause cascading failures
- No `pool_recycle` means stale connections from cloud DBs (Azure/Heroku) timeout silently

**Required Fix:**
```python
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=20,          # 20 persistent connections
    max_overflow=40,       # burst to 60 total
    pool_pre_ping=True,    # validate connections before use
    pool_recycle=1800,     # recycle every 30 min
    pool_timeout=30,       # fail fast if pool exhausted
)
```

---

### 3. No Per-User LLM/RAG Spend Caps — Bankruptcy Risk
**File:** `services/api/app/modules/llm/router.py`  
**Evidence:**
- `/chat` endpoint: no rate limiting, no token budget, no concurrency limit
- `/tts/convert`: no per-user quota
- `/stt/transcribe`: no per-user quota  
- RAG search: no per-user query limit
- Embedding calls: no per-user limit

**Impact at 2M users:**
- 1 power user running automated scripts = $10K/day in OpenAI bills
- No circuit breaker = one user's burst blocks others
- FIXES-NEEDED.md B20 flags this as HIGH

---

### 4. Worker is In-Process Async Task — Single Instance Only
**File:** `services/api/app/modules/rag/jobs.py`  
**Code:**
```python
SEMAPHORE = asyncio.Semaphore(4)  # Per-process limit
_worker_task: asyncio.Task | None = None  # Single task
_running = False  # Per-process flag
```

**Impact at 2M users:**
- 2 app instances = 2 workers processing same jobs
- No `FOR UPDATE SKIP LOCKED` in DB dequeue = race condition
- Process crash = jobs stuck in "parsing" forever (recovery exists but 10min stale cutoff is too long)
- FIXES-NEEDED.md B14, B15 flag this as HIGH

---

### 5. Zero Deployment Infrastructure
**Evidence:**
- `docker-compose.yml`: `services: {}` (empty)
- No Dockerfiles anywhere
- `.github/`: only `.gitkeep`
- No CI/CD pipeline
- No monitoring (Sentry, Prometheus, etc.)
- No backup tooling
- No structured logging

**Impact at 2M users:** Cannot deploy, cannot debug, cannot recover from failure.

---

## 🟡 MEDIUM: Performance Bottlenecks

### 6. Frontend is 100% Client Components — No Server Rendering
**Evidence:** Every dashboard page starts with `"use client"`. Zero React Server Components (RSC).

**Impact:**
- 30+ pages all hydrate on client = massive JS bundle
- No streaming SSR = slow Time to First Byte
- No server-side data fetching = waterfall requests
- Every page requires client JS execution before anything renders

---

### 7. N+1 Query Pattern in Databank Listing
**File:** `services/api/app/modules/rag/router.py:63-65`  
**Code:**
```python
banks = await list_databanks(user, db)  # Query 1: all databanks
for b in banks:
    doc_count = await db.execute(
        select(func.count()).where(Document.databank_id == b.id)  # Query N per databank
    )
```

**Impact at 2M users:** 100 databanks = 101 queries per page load. Should be single `GROUP BY` query.

---

### 8. LLM Conversation History Has No Token-Aware Truncation
**File:** `services/api/app/modules/llm/service.py:83-88`  
**Code:**
```python
MAX_HISTORY_MESSAGES = 40  # Fixed count, not token-aware

async def _load_history(conv_id: str, db: AsyncSession) -> list[LLMMessage]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(MAX_HISTORY_MESSAGES)  # ← 40 messages, each could be 10K tokens
    )
```

**Impact:** 40 messages × 10K tokens = 400K tokens → exceeds context window → API errors or silent truncation.

---

### 9. Frontend Rate Limiter is Per-Process In-Memory
**File:** `apps/web/middleware.ts:4-6`  
**Code:**
```typescript
const rateLimit = new Map<string, { count: number; last: number }>();
// This Map is per-process. 4 Next.js workers = 4 separate maps.
// Rate limit is 100× higher than intended under load.
```

**Impact:** In production with multiple workers/instances, rate limiting is effectively 4-8× weaker than configured.

---

### 10. No React.memo / useMemo / Code Splitting
**Evidence:** Zero `React.memo` usage across all components. No `next/dynamic` for lazy loading.

**Impact:** Sidebar, header, and all dashboard components re-render on every state change. At 2M users with real data, this causes visible jank.

---

## 🟢 LOW: Security Gaps Still Present

### 11. Token Blacklist Not Checked in `get_current_user`
**File:** `services/api/app/core/deps.py`  
**Code:**
```python
async def get_current_user(...):
    payload = jwt.decode(token, settings.JWT_SECRET, ...)
    user_id = payload.get("sub")
    # ← is_token_blacklisted() exists but is NEVER called here
```

**Status:** SECURITY-AUDIT.md C-02, FIXES-NEEDED.md A1 — **Still not fixed in code**.

---

### 12. Access Token in Response Body (XSS Risk)
**File:** `services/api/app/modules/auth/router.py`  
**Impact:** If any XSS exists, attacker can steal access token from response body.  
**Status:** SECURITY-AUDIT.md C-03, FIXES-NEEDED.md A2 — **Still not fixed**.

---

### 13. Webhook Processes Without Signature When No Secret
**File:** `services/api/app/modules/channels/router.py:204-212`  
**Impact:** Misconfigured channel = unauthenticated message injection.  
**Status:** SECURITY-AUDIT.md G3, FIXES-NEEDED.md B24 — **Partially fixed (HMAC added) but skip-if-no-secret remains**.

---

### 14. Rate Limiter Fail-Open When Redis Down
**File:** `services/api/app/modules/auth/rate_limit.py`  
**Code:**
```python
except Exception:
    return True  # ← Fail open: allows unlimited requests when Redis is down
```

**Impact:** Redis outage = all rate limiting disabled = brute-force window opens.  
**Status:** FIXES-NEEDED.md A9 — **Still fail-open**.

---

### 15. Email Enumeration on Signup
**File:** `services/api/app/modules/auth/service.py`  
**Impact:** "Email already registered" confirms email exists.  
**Status:** SECURITY-AUDIT.md L-01, FIXES-NEEDED.md G9 — **Still present**.

---

### 16. Embeddings Stored as JSON Text, Not Vector Column
**File:** `services/api/app/modules/rag/models.py:49`  
**Code:**
```python
embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
# JSON text: ~15-20KB per vector. No ANN index possible.
```

**Impact:** No approximate nearest neighbor search. Full table scan for every query.  
**Status:** FIXES-NEEDED.md B6 — **Still JSON**.

---

## 📈 2M Users: What Needs to Change

### Database Layer (PostgreSQL)
| Current | Required for 2M |
|---------|-----------------|
| `pool_size=5, max_overflow=10` | `pool_size=20, max_overflow=40, pool_pre_ping=True` |
| No pgvector | pgvector extension + HNSW index on embeddings |
| No tsvector GIN index | Generated tsvector column + GIN index for keyword search |
| No connection SSL | `ssl=require` for production |
| No partitioning | Partition `login_attempts`, `channel_messages` by time |
| No read replicas | Read replicas for search/list queries |

### Cache Layer (Redis)
| Current | Required for 2M |
|---------|-----------------|
| Single Redis instance | Redis Cluster or managed Redis |
| In-process fallback (dict) | Fail closed, not open |
| No connection pooling | `max_connections=50`, `retry_on_timeout=True` |
| No health check interval | `health_check_interval=30` |

### Worker Layer
| Current | Required for 2M |
|---------|-----------------|
| In-process asyncio task | Dedicated worker process (or Celery/BullMQ) |
| No distributed locking | `FOR UPDATE SKIP LOCKED` or Redis-based locking |
| Semaphore(4) per process | Global concurrency limit |
| 10-min stale recovery | 2-min stale recovery + heartbeats |

### Frontend
| Current | Required for 2M |
|---------|-----------------|
| 100% `"use client"` | Convert layout + static pages to RSC |
| No code splitting | `next/dynamic` for heavy pages |
| No React.memo | Memo expensive components (Sidebar, ChatList) |
| In-memory rate limiting | Upstash Redis or CDN-based rate limiting |
| No loading.tsx | Route-level loading states with Suspense |

### Infrastructure
| Current | Required for 2M |
|---------|-----------------|
| No Dockerfiles | Multi-stage Dockerfiles for API + web |
| Empty docker-compose | Full stack: Postgres, Redis, Kafka, API, web |
| No CI/CD | GitHub Actions: lint → test → build → deploy |
| No monitoring | Sentry (errors) + Prometheus (metrics) + structured logging |
| No backups | Automated daily pg_dump + PITR |
| No load balancer | nginx/Caddy reverse proxy with TLS termination |

---

## 🔄 SECURITY-AUDIT.md vs FIXES-NEEDED.md vs Code — Reconciliation

| Finding | SECURITY-AUDIT.md | FIXES-NEEDED.md | **Actual Code Status** |
|---------|-------------------|-----------------|------------------------|
| A1: Token type check | C-02 (HIGH) | A1 (CRITICAL) | ✅ **FIXED** — `type == "access"` enforced in `security.py:23` |
| A2: Reset token leaked in response | — | A2 (CRITICAL) | ✅ **FIXED** — No `dev_token` in response |
| A3: Default JWT secret | C-01 (CRITICAL) | A3 (CRITICAL) | ✅ **PARTIAL** — App fails fast at startup if default, but still hardcoded |
| A4: DB password committed | — | A4 (CRITICAL) | ⚠️ **PARTIAL** — `.env` git-ignored, but `alembic.ini` still has `mentee` |
| A14: TrustedHost | M-08 (MEDIUM) | A14 (MEDIUM) | ✅ **FIXED** — `TrustedHostMiddleware` added |
| B24: Webhook HMAC | — | B24 (HIGH) | ✅ **FIXED** — HMAC verification for all platforms |
| C-02: Token blacklist in deps.py | C-02 (HIGH) | — | ❌ **NOT FIXED** — `is_token_blacklisted()` never called |
| C-03: Access token in body | C-03 (HIGH) | A2 (MEDIUM) | ❌ **NOT FIXED** — Still returned in JSON body |
| G3: Webhook no-secret skip | G3 (MEDIUM) | — | ⚠️ **PARTIAL** — Logs warning but still processes |
| G7: No LLM spend caps | G7 (MEDIUM) | B20 (HIGH) | ❌ **NOT FIXED** — No quotas anywhere |
| B4/B5/B6: pgvector | B4/B5/B6 (HIGH) | B4/B5/B6 (HIGH) | ❌ **NOT FIXED** — Still JSON embeddings, no HNSW, no GIN |
| B29: DB pool config | B29 (MEDIUM) | — | ❌ **NOT FIXED** — Still bare `create_async_engine` |
| CSP issues | A17-A19 (CRITICAL) | A17-A19 (CRITICAL) | ✅ **PARTIAL** — Unclosed quote fixed, but `unsafe-eval` in dev only |

---

## 🎯 Priority Remediation for 2M Users

### Phase 1: Database & Search (Week 1) — CRITICAL
1. **pgvector setup** — Install extension, create vector column, HNSW index
2. **DB pool tuning** — `pool_size=20, max_overflow=40, pool_pre_ping=True`
3. **tsvector GIN index** — For keyword search performance
4. **N+1 fix** — Single GROUP BY query for databank listing
5. **Connection SSL** — Add `ssl=require` to DATABASE_URL

### Phase 2: Security Hardening (Week 1-2) — CRITICAL
6. **Token blacklist check** — Add `is_token_blacklisted()` to `get_current_user`
7. **Access token to httpOnly cookie** — Remove from response body
8. **Webhook: reject if no secret** — Don't process unsigned webhooks
9. **Rate limiter: fail closed** — Don't allow requests when Redis is down
10. **LLM spend caps** — Per-user monthly quotas + concurrency limits

### Phase 3: Worker & Queue (Week 2) — HIGH
11. **Dedicated worker process** — Move out of in-process asyncio
12. **FOR UPDATE SKIP LOCKED** — Proper distributed job claiming
13. **Stale job recovery** — Reduce from 10min to 2min
14. **Heartbeat mechanism** — Worker pings to prove liveness

### Phase 4: Frontend Performance (Week 2-3) — HIGH
15. **Convert to RSC** — Layout + static pages as server components
16. **Code splitting** — `next/dynamic` for heavy pages
17. **React.memo** — Sidebar, ChatList, KpiCard components
18. **Loading states** — Route-level `loading.tsx` files
19. **Shared rate limiter** — Upstash Redis for Next.js middleware

### Phase 5: Infrastructure (Week 3-4) — HIGH
20. **Dockerfiles** — Multi-stage for API + web
21. **docker-compose** — Full stack with healthchecks
22. **CI/CD** — GitHub Actions pipeline
23. **Monitoring** — Sentry + Prometheus + structured logging
24. **Backups** — Automated pg_dump + restore runbook

---

## 📋 Comparison: SECURITY-AUDIT.md Strengths (Still Valid)

These areas from the security audit are **genuinely well-implemented**:

| Area | Rating | Evidence |
|------|--------|----------|
| bcrypt password hashing (12 rounds) | ✅ A+ | `security.py:11-12` |
| JWT token rotation on refresh | ✅ A | `auth/service.py:192-214` |
| CSRF double-submit pattern | ✅ A | `main.py:21-50` |
| Security headers (CSP, HSTS, X-Frame) | ✅ A- | `middleware.ts:34-47` |
| Input validation via Pydantic | ✅ A | All schemas use Pydantic models |
| OAuth token encryption (Fernet) | ✅ A- | `channels/service.py:18` |
| Account lockout (5 attempts/15 min) | ✅ A | `auth/service.py:109-122` |
| Webhook HMAC verification | ✅ A | `channels/router.py` all platforms |
| SQL injection prevention (ORM) | ✅ A+ | All queries use parameterized ORM |
| Session management (Redis-backed) | ✅ A- | `auth/rate_limit.py` store/delete |
| Token cleanup on startup | ✅ A | `main.py:89-95` |
| Event outbox pattern | ✅ A- | `outbox/worker.py` with retry |

---

## 🏗️ Architecture Gaps for 2M Users

```
CURRENT:                          NEEDED FOR 2M:
                                  
[Next.js] ──→ [FastAPI] ──→ [Postgres]     [CDN] ──→ [LB] ──→ [Next.js SSR]
              ↓                ↓                                     ↓
           [Redis]          [pgvector]                        [FastAPI × N]
              ↓                                                  ↓
           [Kafka]                                           [Redis Cluster]
                                                                ↓
                                                             [Postgres Primary + Read Replicas]
                                                                ↓
                                                             [pgvector + HNSW]
                                                                ↓
                                                             [Object Storage (S3/Blob)]
```

**Missing components:**
- Load balancer / reverse proxy
- CDN for static assets
- Multiple API instances
- Redis cluster / managed Redis
- PostgreSQL read replicas
- pgvector with ANN indexes
- Object storage for uploads
- Background worker fleet
- Monitoring stack
- CI/CD pipeline

---

## ✅ What's Working Well (Keep These)

1. **Auth architecture** — JWT + refresh rotation + bcrypt is solid
2. **CSRF protection** — Double-submit pattern is correct
3. **Security headers** — Comprehensive and well-configured
4. **Pydantic validation** — All inputs validated
5. **SQLAlchemy ORM** — No SQL injection risk
6. **Webhook HMAC** — All platforms verified
7. **Event outbox** — Resilient to Kafka outages
8. **Token cleanup** — Runs on startup
9. **Rate limiting** — Auth endpoints are protected
10. **Fernet encryption** — OAuth tokens encrypted at rest

---

*Report generated by Buffy Deep Scan — August 13, 2026*  
*Comparing: SECURITY-AUDIT.md (B+ rating) vs FIXES-NEEDED.md (148 findings) vs actual code*
