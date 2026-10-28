# Redis Implementation — Sayvors

Operational reference for how Redis is used, what has TTLs, what fails closed vs open,
and what to provision for production (6–8 GB multi-AZ).

---

## What Redis is used for

Redis is **not just auth** — it's auth infrastructure + cache + rate-limit infrastructure
+ job-lane admission control. Every consumer:

| Use case | File | Key pattern | TTL? | Fail behavior |
|----------|------|-------------|------|---------------|
| Auth rate limits (sliding window) | `modules/auth/rate_limit.py` | `ratelimit:{key}` | ✅ `expire(key, window)` | **Fail closed** — deny request |
| Token blacklist | `modules/auth/rate_limit.py` | `bl:{jti}` | ✅ `setex(..., expires_in_seconds, "1")` | **Fail closed** — treat as blacklisted |
| User sessions | `modules/auth/rate_limit.py` | `session:{uid}:{sid}`, index `user_sessions:{uid}` | ✅ `setex(...)` | Fail closed on write |
| OTP codes + attempts | `modules/email/service.py` | `otp:{email}`, `otp:attempts:{email}` | ✅ `setex(..., OTP_TTL_SECONDS, ...)` — 10 min | Fail closed on verify |
| Admin fail counter | `modules/admin/router.py` | `admin:fail:{ip}` | ✅ `expire(..., 900)` — 15 min | Fail closed |
| Connect tickets (Meta OAuth) | `modules/channels/router.py` | `gct:{jti}` | ✅ `setex(..., GOOGLE_CONNECT_TICKET_TTL_SECONDS, "1")` | Degrade to TTL-only (JWT expiry) |
| RAG cache (embeddings, chunks) | `modules/rag/cache.py` | `rag:embed:{hash}`, `rag:chunks:{id}` | ✅ `ex=EMBED_CACHE_TTL` | Fail open (recompute) |
| Job progress | `modules/rag/cache.py` | `job:progress:{id}` | ✅ `ex=3600` — 1 hour | Fail open |
| Profile cache | `modules/profile/service.py` | `profile:{id}` | ✅ `setex(..., ttl, ...)` | Fail open |
| Billing budget mirror | `modules/billing/budget.py` | `ai_balance:{tenant_id}` | ❌ No TTL by design; Postgres ledger is authoritative | Fail open (cache only; DB denies/settles) |
| **(Planned) Job lane in-flight caps** | `docs/specs/job-processing-design.md` | `job:inflight:{tenant}:{lane}` | Planned (TTL-based) | N/A — not built yet |
| **(Planned) Provider pacing** | `docs/specs/job-processing-design.md` | Token bucket per lane/tenant | Planned (TTL-based) | N/A — not built yet |

---

## Fail-closed vs fail-open

| Category | Behavior | Rationale |
|----------|----------|-----------|
| **Auth-critical** (rate limits, blacklist) | **Fail closed** | `AUTH_RATE_LIMIT_FAIL_CLOSED=true` — Redis down = request denied. Prevents brute-force bypass. |
| **Sessions / OTP** | **Fail closed** | Can't store or verify without Redis — login/signup breaks gracefully. |
| **Cache** (RAG, profile, job progress) | **Fail open** | Recompute from DB/source; never blocks the request path. |
| **Billing** | **Fail open** | Spend metering continues; DB reconciles later. |

**Key insight:** Redis down = **nobody logs in** (fail-closed auth). That's why it's load-bearing infrastructure, not a cache.

---

## TTL coverage — nothing accumulates forever

| Category | TTL | Notes |
|----------|-----|-------|
| Rate-limit windows | 60s | Sliding window auto-expires |
| Blacklisted JTIs | 15 min (access token expiry) | Matches access token lifetime |
| User sessions | Configurable (7 days refresh) | Matches cookie max-age |
| OTP codes | 10 min | Short-lived by design |
| OTP attempt counters | 10 min | Same as OTP TTL |
| Admin fail counter | 15 min | `expire(..., 900)` |
| Connect tickets | `GOOGLE_CONNECT_TICKET_TTL_SECONDS` | Strict improvement over URL tokens |
| RAG embeddings cache | `EMBED_CACHE_TTL` | Configurable |
| Job progress | 1 hour | `ex=3600` |
| Profile cache | Configurable TTL | Re-fetched on expiry |
| **Billing balances** | **None** | ⚠️ No TTL — DB is source of truth, keys persist until overwritten |

**Recommendation:** Add a TTL (e.g., 24h) to billing balance keys in a later pass so they don't grow unbounded if tenants are deleted.

---

## Production provisioning (6–8 GB)

| Setting | Value | Rationale |
|---------|-------|-----------|
| Instance type | 6–8 GB | Headroom for: 100k+ sessions, rate-limit windows, blacklist JTIs, OTP codes, connect tickets, billing balances, job progress |
| Architecture | ElastiCache multi-AZ (or 2+ nodes) | Single node = single point of failure |
| Eviction policy | `noeviction` | Don't silently evict OTPs/blacklist/sessions; capacity alarms are the correct control |
| Persistence | AOF enabled | Recover from node failure without losing blacklist/session state |
| Memory alarm | 75% | Page before eviction becomes necessary |
| `maxmemory-policy` | `noeviction` | Keep — evicting auth keys is worse than erroring |
| `timeout` / `retry_on_timeout` | Explicit | Configure in client (see `redis/client.py`) |
| Health check interval | 30s | Detect dead nodes fast |

**Current dev config:** Single 128MB `noeviction` box, no AOF, no alarm, `mark_redis_available()` never called after initial warmup. **Not production-safe.**

---

## Code structure

```
services/api/app/modules/redis/
├── client.py        # Singleton Redis client, reconnect cooldown, fail-closed gate
└── router.py        # Redis health/debug endpoints
```

**`client.py` key behaviors:**
- Caches one `Redis` client per event loop (recreates on loop mismatch — prevents "Event loop is closed" on reload/tests)
- 5-second reprobe cooldown after marked unavailable (prevents permanent latch-off after a blip)
- `get_redis()` returns client; callers handle `ConnectionError`
- `mark_redis_unavailable()` / `mark_redis_available()` for state management

---

## What needs to change for production

1. **Provision 6–8 GB Redis (multi-AZ, AOF, alarm)** — infra, not code
2. **Call `mark_redis_available()` from a background prober** — currently exists but has zero callers (`redis/client.py:69-71`); a boot-time blip permanently disables Redis for the process lifetime
3. **Keep the billing mirror TTL-free** — `ai_balance:{tenant}` mirrors `users.ai_credit_cents`; a TTL was the original wallet-loss bug. Redis loss is repaired from Postgres.
4. **Fail-closed for auth paths** — already default (`AUTH_RATE_LIMIT_FAIL_CLOSED=true`); keep it on in production
5. **Job lane in-flight caps** — planned in job-queue design (`job:inflight:{tenant_id}:{lane}`), not yet built

---

## Quick reference: Redis keys by prefix

| Prefix | Owner | TTL | Example |
|--------|-------|-----|---------|
| `ratelimit:` | auth rate limit | 60s | `ratelimit:login:1.2.3.4` |
| `bl:` | token blacklist | 15 min | `bl:abc123jti` |
| `session:` | user sessions | 7 days | `session:uid:sid` |
| `user_sessions:` | session index | 7 days | `user_sessions:uid` |
| `otp:` | OTP codes | 10 min | `otp:user@example.com` |
| `otp:attempts:` | OTP attempt counter | 10 min | `otp:attempts:user@example.com` |
| `admin:fail:` | admin lockout | 15 min | `admin:fail:1.2.3.4` |
| `gct:` | connect tickets | configurable | `gct:jti123` |
| `rag:embed:` | RAG embedding cache | `EMBED_CACHE_TTL` | `rag:embed:sha256hash` |
| `rag:chunks:` | RAG chunk cache | `EMBED_CACHE_TTL` | `rag:chunks:doc123` |
| `job:progress:` | job progress | 1 hour | `job:progress:job456` |
| `profile:` | profile cache | configurable | `profile:uid` |
| `ai_balance:` | billing mirror (DB is truth) | **none** | `ai_balance:tenant789` |
