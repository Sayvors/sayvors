# Sayvors — Production-Later Items

Items **deferred for later** because they need a production VM (not your laptop, not a t3.small EC2).

**Rule:** None of these can be meaningfully tested or run on a single 2GB box running API + worker + Redis + Kafka together. Do them when you provision the production VM.

---

## Kafka — 3-broker cluster (not 1)

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| Run 3 Kafka broker containers | Each broker needs 512MB–1GB heap; a t3.small (2GB) would OOM with API+worker+Redis+caddy also running | 3 `kafka-1/2/3` services in `docker-compose.prod.yml`, each with unique `KAFKA_NODE_ID`, shared `KAFKA_CONTROLLER_QUORUM_VOTERS` |
| `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` | The topic provisioning code now exists (`app/modules/kafka/topics.py`, explicit partition counts) — flip it together with the 3-broker change | Set to `"false"` + provision topics with real partitions (24/12/6/6 per lane) |
| `min.insync.replicas=2` | Meaningless with 1 broker | Set when 3 brokers exist |
| Producer `acks="all"`, `enable_idempotence=True` | Code change — can do now | Also do now, safe with 1 broker |
| Consumer `enable_auto_commit=False` + manual commit | Code change — can do now | Also do now, safe with 1 broker |

## Redis — HA (6–8 GB)

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| Redis multi-AZ (ElastiCache or 2+ nodes) | Single 128MB `noeviction` box is all a t3.small can hold | ElastiCache replication group, AOF on, **6–8 GB**, memory alarm at 75% |
| `mark_redis_available()` prober | Code change — can do now | Background prober so a blip doesn't disable Redis for process lifetime |

### Redis TTL coverage — what auto-expires, what doesn't

| Use case | File | Has TTL? | Notes |
|----------|------|----------|-------|
| Auth rate limits | `auth/rate_limit.py` | ✅ Yes | `expire(key, window_seconds)` |
| Token blacklist (`bl:{jti}`) | `auth/rate_limit.py` | ✅ Yes | `setex(..., expires_in_seconds, "1")` |
| User sessions | `auth/rate_limit.py` | ✅ Yes | `setex(..., expires_in_seconds, ...)` |
| OTP codes + attempts | `email/service.py` | ✅ Yes | `setex(..., OTP_TTL_SECONDS, code)` (10 min) |
| Admin fail counter | `admin/router.py` | ✅ Yes | `expire(..., 900)` (15 min) |
| Connect tickets (`gct:{jti}`) | `channels/router.py` | ✅ Yes | `setex(..., GOOGLE_CONNECT_TICKET_TTL_SECONDS, "1")` |
| RAG cache (embeddings/chunks) | `rag/cache.py` | ✅ Yes | `ex=EMBED_CACHE_TTL` |
| Job progress | `rag/cache.py` | ✅ Yes | `ex=3600` (1 hour) |
| Profile cache | `profile/service.py` | ✅ Yes | `setex(..., ttl, ...)` |
| Billing budget balance | `billing/budget.py` | ❌ **No TTL — on purpose** | The 24h TTL was the disappearing-balance bug: the key expired, the next reserve created a permanent `0`. The wallet is now rebuilt from grants minus metered spend when the key is missing. **This is a wallet key, not a cache: it must not expire.** |

**Bottom line:** Almost every Redis key has a TTL, so nothing critical is lost on Redis restart. Auth, OTP, sessions, rate limits, connect tickets, and billing balances all auto-expire — they won't accumulate forever.

With 6–8 GB, you have plenty of headroom for: 100k+ active sessions, rate-limit windows, blacklist JTIs, OTP codes, connect tickets, and billing balances — all with TTLs keeping growth bounded.

## Postgres

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| Read replica for analytics queries | Single RDS instance | Add read replica, route analytics reads there |
| Connection pool right-sizing | Code/config change — can do now | `DB_POOL_SIZE=5`, `MAX_OVERFLOW=5`, boot-time headroom check |
| PgBouncer connection pooling | Code/config change — can do now | `DATABASE_URL` points to PgBouncer (port 6432), `DB_POOL_MODE=transaction`, PgBouncer service in docker-compose |
| DATABASE_READER_URL routing | Code change — done, env-gated | Set `DATABASE_READER_URL` to replica connection string; reads route there automatically |
| Write/read session splitting | Code change — done | `get_db()` for writes (primary), `get_db_read()` for reads (replica) |

## Object storage

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| S3 buckets for uploads | `S3_DOCS_BUCKET` empty; uploads go to local Docker volume | Set `S3_DOCS_BUCKET` + `S3_MEDIA_BUCKET`, private docs in separate bucket |

## Compute HA

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| Second box / AZ / container platform | One t3.small runs everything; one OOM kills auth + messaging + ingestion | Second box behind LB, or ECS/Fly/Render |
| Fan the job workers out | The worker container runs one runner per lane; a second box means a second copy of each lane | `docker compose --scale worker=N` (or two hosts) — the claim is `FOR UPDATE SKIP LOCKED`, so replicas never double-claim. Each replica now names itself (`lane-host-pid`), so a heartbeat says which machine holds a job |
| Lane concurrency is per process | Decided 2026-10-22: it stays per process | Global realtime concurrency = replicas × cap. The fairness guarantee is the per-tenant in-flight cap (2 per lane, Redis, deferred not dropped) — write the arithmetic down when the fleet grows |

## Job queue at scale (added 2026-10-22)

The job system itself is built and verified (`readiness-report.html` §§5). What is left is
infrastructure and two decisions:

| Item | Kind | Status / what to do later |
|------|------|---------------------------|
| Kafka replication factor 1, single broker | Infra | 3 brokers + `min.insync.replicas=2`. The `jobs` table means a broker loss is a *delay*, not data loss — but dispatch still has one point of failure |
| `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"` | Config | The topic provisioning code now exists (`app/modules/kafka/topics.py`, explicit partition counts), so this can be flipped to `"false"` — it is listed here because flipping it on a 1-broker cluster is best done together with the 3-broker change |
| Lane concurrency is per process | Decision | Global realtime concurrency = replicas × cap. Either write it down as intended, or move the cap to a shared counter |
| Worker id per replica | Decision | Every replica of a lane currently reports `realtime-1` in its heartbeat; make it unique so a stuck job names its holder |

## Backups & monitoring

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| RDS PITR ≥ 7 days + restore rehearsal | AWS console config | Verify PITR on, rehearse restore |
| Grafana/CloudWatch dashboards | Need `/metrics` endpoint (just added) + Prometheus target | Hook Prometheus to `/metrics`, build dashboards |

## CI/CD

| Item | Why it can't be done now | What to do later |
|------|-------------------------|------------------|
| GitHub Actions: lint → test → build → deploy | ✅ Done — `.github/workflows/ci.yml` gates the image build (pytest + migration guard + tsc + eslint) and the deploy's `ci-gate` refuses to build until every check is green. 103 test files. The admin console is type-checked in CI; its eslint is not gated. | Remaining: widen the eslint scope (8 files of `apps/web` today) |

---

## What you CAN do today (no new infra)

| Item | Where | Notes |
|------|-------|-------|
| Job queue Phase 0: `jobs` table + migration | `docs/specs/2026-10-10-unified-job-processing-design.md` | Runs fine with existing Postgres |
| Producer hardening (`acks=all`, idempotence) | `app/modules/kafka/client.py` | Safe with 1 broker |
| Consumer manual offset commit | `app/modules/kafka/client.py` | Safe with 1 broker |
| Outbox `FOR UPDATE SKIP LOCKED` drain | `app/modules/outbox/` | Safe with 1 broker |
| DLQ + operator replay | New code | Safe with 1 broker |
| SEC-H1 SSRF fix | `meta/router.py:1507–1553` | Code only |
| CI test gating | `.github/workflows/` | Code only |
| OPS-1 backups (RDS PITR) | AWS console | Config only |
| **Blocker 06 — Backup & restore story** | Needs production VM | RDS PITR on + 7-day retention, nightly pg_dump → S3 (30-day retention), rehearse one restore into scratch DB, write runbook. See launch-readiness-report.html #06. |
