# Unified Job Processing — Design & Fix Plan

Date: 2026-10-10
Status: planning only — no code, no migrations executed
Scope: `services/api` (the only service), `apps/web` client, `docker-compose*.yml`

Every claim below is anchored to source. Paths are repo-relative; line numbers refer to
the tree as of `d8e0f2a4c6b8` (current Alembic HEAD) unless stated.

---

## 0. What the audit forces before any new code

Three findings dominate and they change the shape of the solution:

1. **The pipeline is at-most-once end to end.** `create_consumer`
   (`services/api/app/modules/kafka/client.py:60-65`) never sets
   `enable_auto_commit=False`, so aiokafka defaults to `True`. Offsets advance on
   `getone()` before the handler runs and commit on a 5s timer. The producer has
   `acks=1` and `enable_idempotence=False` (`client.py:19-24`). A new job lane built on
   this inherits silent loss on every crash.

2. **Horizontal scaling does not exist.** No `num.partitions` is set and no topic is
   ever created programmatically (`AIOAdminClient`/`NewTopic` appear nowhere), so
   auto-create uses Kafka's default of **1 partition**. `docker-compose.prod.yml:67`
   suggests `--scale worker=N`; N>1 adds rebalance churn and buys zero throughput.

3. **Postgres connections are the real ceiling, not CPU.** `DB_POOL_SIZE=50` +
   `DB_POOL_MAX_OVERFLOW=50` (`app/config.py:8-9`) = up to 100 per process. Two api
   workers plus one worker already approaches a `t4g.micro` budget.

A job table without fixing (1) and (2) is a job table that loses work and cannot scale.
Phase 0 is therefore non-negotiable.

---

## A. Recommended architecture

### A.1 The single source of truth

**PostgreSQL `jobs` table owns execution lifecycle. Kafka owns dispatch only.
Redis owns ephemeral admission control. Nothing else is a source of truth.**

There is no second broker. Redis is explicitly *not* a job store — it holds counters,
rate windows and semaphore leases that are reconstructible from `jobs`.

```
HTTP request
   │  (same transaction)
   ├──────────────────────────────────────────────┐
   │  INSERT jobs (status='accepted')            │  ← durable record
   │  INSERT event_outbox (topic=<lane>-dispatch)│  ← same commit, R2 fixed
   └──────────────────────────────────────────────┘
   │ 202 { job_id, status }
   ▼
OutboxWorker (N replicas)  ──producer.send──▶  Kafka <lane>-dispatch  (P partitions)
   ▲ FOR UPDATE SKIP LOCKED                       │
   │                                             ▼
   │                              Worker replica, lane consumer
   │                                 claim job row, set running + lease
   │                                 run handler
   │                                   ├─ ok    → succeeded + commit offset
   │                                   ├─ retry → retrying + next_run_at + commit
   │                                   └─ fatal → dead (DLQ topic) + commit
   ▼
Postgres (jobs)  ──status change──▶  existing domain tables (projection)
```

### A.2 Component responsibilities

| Component | Responsibility | Must not |
|---|---|---|
| `jobs` table | State machine, attempts, leases, results, external intent | Know about Kafka |
| `event_outbox` | Transactional dispatch. Already exists (`outbox/models.py`) | Carry job payloads directly — only `{"job_id"}` |
| OutboxWorker | Drain outbox → Kafka. One `producer.send` per event | Know what a job does |
| Lane consumers | Claim job, run handler, record outcome, commit offset | Publish to Kafka themselves |
| Handlers | Pure-ish domain work, one function per job type | Manage retry/state — the lane does that |
| Domain tables (`location_posts`, `channel_messages`, `documents`, …) | The thing being worked on | Become a second lifecycle |
| Redis | Rate windows, per-tenant in-flight caps, provider pacing | Hold anything you can't rebuild |

### A.3 Relationship to the four existing job tables

Verified inventory — there are already four job-shaped tables plus two de-facto ones.
**Creating a fifth competing one is what the constraint forbids.**

| Existing | Location | Disposition |
|---|---|---|
| `ingest_jobs` | `rag/models.py:135-164`, 7-state enum `ingest_status` | **Migrate.** Richest vocabulary; becomes `job_type='rag.ingest'` with `subject_id` → keep the row as a domain projection of `stage`/`progress` |
| `scrape_jobs` | `rag/models.py:113-133` | **Migrate.** Same |
| `stt_jobs` | `stt/models.py:9-27` | **Migrate** |
| `tts_jobs` | `tts/models.py:23-42` | **Migrate** |
| `location_posts` | `posts/models.py:20-93` | **Keep as domain row.** Its `status`/`attempts`/`next_retry_at` become a projection of the job. Its `Index("ix_posts_due", "status", "scheduled_on")` stays |
| `location_media` | `media/models.py:18-72` | **Keep**, same treatment |
| `event_outbox` | `outbox/models.py` | **Keep and fix.** It is dispatch, not a job lifecycle |

Rule: `jobs` owns *whether and when*; the domain table owns *what*. A test can still
assert `post.status == "published"` — it just becomes a projection written in the same
transaction as the job transition.

---

## B. Prioritised fixes for R1–R5 and S1–S7

### B.0 Phase 0 — blocking prerequisites

| ID | Fix | Files | Risk | Depends |
|---|---|---|---|---|
| **R1** | `enable_auto_commit=False`; commit manually **only after** the job reaches a durable terminal-or-retry state | `kafka/client.py:56-67` (add params), both consumers | Under a crash *before* commit the message replays — **desirable**, but only safe with §6 idempotency. Ship with idempotency or not at all | S3, §6 |
| **R3** | Stop marking failed events `sent` in the DB-drain fallback | `analytics/consumer.py:424-435`, `channels/meta/consumer.py:1334-1343` | Low | — |
| **R4** | Make Kafka availability a per-consumer concern, not a process global; add a background health prober so any lane can re-arm | `kafka/client.py:11,35-43` | Medium — touches both consumers | — |
| **S1** | Explicit topic provisioning with real partition counts; drop `KAFKA_AUTO_CREATE_TOPICS_ENABLE` | new `app/modules/kafka/topics.py`, both compose files | **High** — partition count is immutable in place; a topic already auto-created at 1 partition must be recreated with a data-replay procedure | §D.1 |
| **S5** | `FOR UPDATE SKIP LOCKED` + in-flight claim on the outbox drain | `outbox/service.py:49-67`, `outbox/worker.py:84` | Low | — |
| **S7** | Size the DB pool deliberately; add `max_connections` headroom check at boot | `app/config.py:8-9`, `deploy/env.prod.example:9-10` | Low | §10 |

### B.1 Phase 1 — correctness

| ID | Fix | Files | Notes |
|---|---|---|---|
| **R2** | Make `enqueue_event` accept the caller's `AsyncSession` and commit once | `outbox/service.py:23-46` | The correct pattern already exists at `channels/meta/webhooks/router.py:145-158`. Add an `enqueue_event_in(db, ...)` and migrate the ~25 call sites that currently commit-then-signal (`auth/service.py:91,135,172,476,519,537,669,725,749,772,215`; `profile/service.py:173,195,218,241,300`; `channels/router.py:215,261,285,306,1481`) |
| **R5** | Emit `review.enriched` inside the consumer's session, before commit | `analytics/consumer.py:217-228` | Move the enqueue inside the `async with` block |
| **R2b** | Add a unique index on `ChannelMessage.platform_message_id` and a **unique** index on `ChannelComment.platform_comment_id` | `channels/models.py:75-79,85,129,138` | Today the dedupe `SELECT` is a full table scan and a non-atomic read-then-write. `TODO-instagram-comments.md:23` already claims uniqueness that the schema does not enforce |
| **S3** | Set `max_poll_interval_ms` explicitly (900000) and `session_timeout_ms` (30000) per lane | new lane consumer factory | A handler that exceeds the default 5-min window is evicted mid-flight, and per R1 its offset may already be committed |
| **R-retry** | Dead-letter topic + operator replay endpoint | new | Repo-wide grep for DLQ returns exactly one hit, a TODO at `FIX-PLAN-SCALE.md:132` |

### B.2 Phase 2 — throughput

| ID | Fix | Files | Notes |
|---|---|---|---|
| **S2** | Bounded concurrent handler execution per lane; batching for bulk lanes | new lane runner | `max_poll_records` is never set today (`analytics/consumer.py:465`, `meta/consumer.py:1471-1472` are both `async for msg in consumer`) |
| **S4** | Producer: `acks="all"`, `enable_idempotence=True`, `linger_ms=5`, `compression_type="gzip"`; add an `asyncio.Lock` around singleton init | `kafka/client.py:14-32` | `enable_idempotence=True` forces `acks="all"` and sets `max_in_flight=1`, so out-of-order duplicates are impossible |
| **S6** | Move the four slow inline endpoints to jobs | `channels/router.py:1224-1305` (up to **500 sequential Google calls**), `posts/router.py:203-218` (`MAX_PER_PASS=50`), `localith/router.py:135-159`, `media/router.py:158-175` | Return `202 + job_id` |
| **S6b** | Remove the blocking `asyncio.to_thread` publish | `posts/service.py:363-381`, `media/service.py:376-383` | `_post` defaults to `timeout=60` (`integrations/channels/embedsocial.py:221`) and is serialised under an advisory lock, so one hung request stalls the whole pass |
| **RAG-place** | Register `rag.jobs.start_worker()` in the `loops` dict instead of starting it lazily from request handlers | `rag/jobs.py:36-51`, `workers/main.py:90-99` | `RUN_BACKGROUND_WORKERS=false` does not gate it today; `SEMAPHORE = asyncio.Semaphore(4)` and `_worker_task` are per-process globals (`rag/jobs.py:16-18`) so each uvicorn worker runs its own |

### B.3 Known bugs worth folding in (cheap, unrelated to the job core)

| Item | Location |
|---|---|
| A fresh `httpx.AsyncClient` per outbound send, never closed | `followup_worker.py:200-206`, `channels/service.py:322-324,378-380` |
| `alembic/env.py` model-import list is stale — missing `team`, `channels.meta`, `notifications`, `media`, `locations`, `billing`, `user_feedback`. **`--autogenerate` would emit spurious drops** | `services/api/alembic/env.py:20-36` |
| `run_followup_worker` is registered in the worker but **not** in the API lifespan list | `workers/main.py:97` vs `main.py:157-162` |
| `mark_redis_available()` exists but is **never called** — a Redis blip at warmup disables Redis for the process lifetime | `redis/client.py:69-71` |
| Cancel-without-await: `tasks` are cancelled but never `gather`ed | `workers/main.py:120-121`, `main.py:176-177` |
| `TOKEN_PRICES["unknown"] = (0.0, 0.0)` makes unlisted models free; budget reserve has no TTL so a crashed worker leaks the reserve | `billing/budget.py:54`, `:113-129` |

---

## C. Schema, state machine, dispatch, retry and DLQ

### C.1 Migration

New revision `e1f2a3b4c5d6_unified_jobs.py`, `down_revision = "d8e0f2a4c6b8"`.
Follow `d8e0f2a4c6b8_channel_comments.py` exactly: `op.create_table`, inline
`sa.Column`/`sa.Index`/`sa.UniqueConstraint`, `server_default` on every NOT NULL column,
double-quoted revision strings, and a prose docstring explaining *why*.

**Do not use `postgresql_where`.** There is zero precedent in 77 migrations and the test
harness is in-memory SQLite built from `Base.metadata.create_all`
(`tests/conftest.py:36-42`), which cannot express partial indexes. Native `sa.Enum` is
safe — SQLAlchemy renders it as VARCHAR+CHECK on SQLite.

### C.2 `jobs` table

```python
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                   default=lambda: str(uuid.uuid4()))
    # RBAC-era convention (users/models.py:59-63): every query filters on this.
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)

    job_type: Mapped[str] = mapped_column(Enum(*JOB_TYPES, name="job_type"))
    lane: Mapped[str] = mapped_column(
        Enum("realtime", "publishing", "media", "bulk", name="job_lane"), index=True)
    status: Mapped[str] = mapped_column(
        Enum("accepted", "queued", "running", "retrying", "blocked",
             "succeeded", "failed", "cancelled", "dead", name="job_status"),
        default="accepted", server_default="accepted", index=True)

    # Lower sorts first. 0 = interactive lane, 100 = bulk.
    priority: Mapped[int] = mapped_column(Integer, default=50, server_default="50")

    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Caller-supplied dedupe. NULL means "never dedupe".
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The domain object this job acts on — the domain table keeps the truth.
    subject_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Kafka partition key. See §D.3.
    lane_key: Mapped[str] = mapped_column(String(64))

    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    # Lease so a crashed worker's job is reclaimable.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # §6 — written BEFORE the external call, so a crash mid-call is recoverable.
    external_intent: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    external_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key",
                         name="uq_jobs_tenant_idempotency"),
        # The claim query's covering index — same idiom as posts/media.
        Index("ix_jobs_due", "status", "next_run_at"),
        Index("ix_jobs_lane_due", "lane", "status", "next_run_at"),
        Index("ix_jobs_lease", "status", "lease_expires_at"),
    )
```

Notes on choices:
- `tenant_id` not `user_id`: every table created since RBAC landed uses `tenant_id`
  (`b9c8d7e6f5a4`, `users/models.py:59-63`). `business_id` does not exist anywhere.
- `UniqueConstraint(tenant_id, idempotency_key)`: Postgres NULL semantics make this a
  no-op when the key is NULL, so non-idempotent jobs are unaffected. Same technique
  `channels/models.py:26` already relies on.
- `status` is an Enum for consistency with 31 other status columns in the repo.

### C.3 State machine

```
                    ┌──────────────────────────────┐
                    ▼                              │
   submit ──▶ accepted ──▶ queued ──▶ running ──▶ succeeded   (terminal)
                  │           ▲         │  │
                  │           │         │  ├─▶ retrying ──┘ (next_run_at, attempts++)
                  │           │         │  ├─▶ blocked    (quota/rate limit; released by pacer)
                  │           │         │  └─▶ failed     (terminal, operator retry only)
                  │           │         │
                  └───────────┴─────────┴─▶ dead        (attempts exhausted → DLQ)
   cancel ──▶ cancelled (terminal; legal only from accepted/queued/retrying/blocked)
```

Transitions, with the recovery rule for each:

| From | To | Trigger | On crash mid-transition |
|---|---|---|---|
| — | `accepted` | row insert | none, row is the truth |
| `accepted` | `queued` | dispatcher, same tx as outbox insert | outbox row exists ⇒ replayed; no outbox row ⇒ `accepted` rows are swept by a reconciler |
| `queued` | `running` | lane consumer claims, sets `lease_owner` + `lease_expires_at` | lease expires ⇒ reaper returns to `queued` |
| `running` | `succeeded`/`retrying`/`failed`/`dead` | handler outcome, then **then** offset commit | offset uncommitted ⇒ redelivery ⇒ handler re-runs ⇒ §6 idempotency must hold |
| `retrying` | `queued` | `next_run_at <= now()` sweep | sweeper is idempotent |
| `blocked` | `queued` | pacer releases quota | same |
| `cancelled` | — | user request | terminal; a redelivered dispatch for a cancelled job must re-check status and exit |

**Reaper** (new `app/modules/jobs/reaper.py`, 30s interval): returns `running` rows with
`lease_expires_at < now()` to `queued`, incrementing `attempts`. Lease is the only
mechanism that makes a worker crash recoverable without a DLQ.

**Reconciler** (same loop): `accepted` rows with no outbox row older than 60s get an
outbox row inserted. This closes the R2-shaped hole for any path that forgets.

### C.4 Dispatch flow

1. `submit_job(db, job_type, tenant_id, payload, ...)` adds `Job(status='accepted')` and
   `EventOutbox(event_type='job.dispatch', payload={"job_id": id}, topic=f"{lane}-dispatch")`
   **in the caller's session** — one commit. This is R2 fixed.
2. OutboxWorker drains with `FOR UPDATE SKIP LOCKED`, sends `{"job_id": ...}` only.
   Keeping the payload out of Kafka means the topic is a work queue, not a second copy
   of the truth, and a consumer can re-read the current job state on redelivery.
3. Lane consumer receives, then claims the row:
   ```sql
   UPDATE jobs SET status='running', lease_owner=$1, lease_expires_at=now()+interval
   WHERE id=$2 AND status IN ('queued','retrying')
   RETURNING *
   ```
   A `RETURNING` with no row means someone else won it or it was cancelled → commit
   the offset and move on.
4. Handler runs. Outcome writes the terminal/retry state.
5. **Only then** `await consumer.commit()`.

### C.5 Retry and backoff

Reconcile the three divergent policies the audit found into one, but keep the
per-lane shape that already works:

| Policy | Where it is today | New |
|---|---|---|
| `300 * 2^(n-1)`, cap 7200s, 5 attempts | `scheduling/__init__.py:101-104` | **Reuse verbatim** for `publishing` |
| `2^n`, cap 300s, 10 attempts | `outbox/service.py:83-107` | Keep for the outbox (transport) |
| none | Meta/Google/LLM | New per-lane policy in §D.4 |

**Jitter is mandatory** and is absent everywhere today. A bare `2^n` across N workers
reproduces a thundering herd on recovery:

```python
def backoff_delay(attempt: int, base: int, cap: int) -> timedelta:
    raw = min(base * (2 ** max(0, attempt - 1)), cap)
    return timedelta(seconds=raw * (0.5 + random.random() * 0.5))  # full jitter
```

Attempts beyond `max_attempts` → `dead`, plus a row on `<lane>-dlq` carrying the full
job snapshot for operator replay.

### C.6 Duplicate execution — the honest answer

**Exactly-once execution of external side effects cannot be guaranteed here.** A
publish to Google is an HTTP POST; if the response is lost after the provider committed,
no client-side mechanism can distinguish "never happened" from "happened, reply lost".
Any plan claiming otherwise is wrong.

What is achievable is **at-least-once execution with reconciliation**:

1. **Before** the external call, in its own committed transaction:
   ```python
   job.external_intent = {
       "provider": "localith", "operation": "publish_media_post",
       "dedupe_key": f"{post.id}:{post.revision}", "started_at": now.isoformat(),
   }
   ```
2. **Then** call the provider. On success record `external_result` with the provider's
   returned id and clear `external_intent`.
3. **On retry**, if `external_intent` is set and `external_result` is not, the handler
   runs a **reconciliation query** — list the provider's recent items for that listing
   and match `dedupe_key`/title+window — before considering a re-issue.

This narrows the duplicate window from "any crash during a 60s call" to "provider
reconciliation is itself unavailable", and it is honest about what remains.

Two supporting fixes:
- The advisory lock (`scheduling/__init__.py:50-98`) prevents *concurrent* duplicates.
  Keep it, but it is mutual exclusion, **not** idempotency — `posts/service.py:53-56`
  and `scheduling/__init__.py:9-10` already say so.
- Do **not** reset `attempts` to 0 on success until `external_result` is durable
  (`posts/service.py:399` does reset).

For providers that accept an idempotency key, use it and skip reconciliation.
EmbedSocial/Localith does not; Meta Graph does not for messaging. That is the gap.

---

## D. Topics, partitions, concurrency, fairness

### D.1 Topic plan

| Topic | Partitions | Key | Consumer group | Notes |
|---|---|---|---|---|
| `realtime-dispatch` | 24 | `tenant_id` | `sayvors-jobs-realtime` | AI replies, customer DMs. Latency-critical |
| `publishing-dispatch` | 12 | `listing_id` | `sayvors-jobs-publishing` | Google/EmbedSocial + Meta publishes |
| `media-dispatch` | 6 | `tenant_id` | `sayvors-jobs-media` | Image processing, uploads |
| `bulk-dispatch` | 6 | `tenant_id` | `sayvors-jobs-bulk` | Reindex, backfill, large syncs |
| `<lane>-dlq` | 1 | `job_id` | (operator only) | Dead letters |
| `review-events` | 6 | `review_id` | `analytics-enricher` | existing, keep group id |
| `meta-events` | 12 | `tenant_id` | `meta-events-replier` | existing, keep group id |

Provisioning: a new `app/modules/kafka/topics.py` using `AIOAdminClient` +
`NewTopic(num_partitions=…, replication_factor=1)`, run from `workers/main.py` warmup
*before* any consumer starts. Then set `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` in
both compose files so a typo can never silently create a 1-partition topic.

**Migration hazard:** `review-events` and `meta-events` were auto-created at 1 partition.
Raising the partition count requires no data movement (new partitions are empty and
old keys stay on partition 0), so it is safe — but it **does** change the partition→key
mapping and triggers a rolling rebalance. Do it in a maintenance window, one topic at a
time, with consumers stopped.

`replication_factor=1` is honest for a single-node KRaft broker today and matches
`KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1` (`docker-compose.yml:50`). **A single broker
is a single point of failure** — this design does not fix that and should not be read as
if it did. Minimum production step: 3 brokers, `min.insync.replicas=2`.

### D.2 What horizontal scaling now looks like

| Replicas | realtime throughput | Publishing | Notes |
|---|---|---|---|
| 1 worker | 1 consumer/lane | 1 | Today's de-facto state |
| 2 | 2× | 2× | Linear in partitions. Each replica gets a subset |
| 4 | 4× | 4× | DB pool becomes the constraint (§10) |
| 8+ | 8× | 8× | **Postgres, not Kafka**, is the wall |

Consumers beyond the partition count are **idle members of the group**. They are not
harmful but they are useless and each one adds a rebalance. A worker replica should be
able to run a *subset* of lanes via an env allowlist
(`JOB_LANES=realtime,publishing`) so you can scale a lane without scaling everything.

### D.3 Partition key and ordering

Key by `tenant_id` for all tenant-facing work: it co-limits a tenant's jobs to one
partition, which gives **per-tenant ordering** for free and makes quota enforcement
local rather than distributed.

For publishing, key by `listing_id` — one listing's posts must publish in
`scheduled_on` order. Keying by `tenant_id` would let two workers publish the same
listing's posts concurrently and out of order.

Ordering is **per key, per partition** — Kafka does not order across partitions. This
is sufficient because no lane has cross-tenant ordering requirements.

`lane_key` is stored on the job so a replay uses the identical key and therefore the
identical partition. Without that column, a redelivery after an expansion could land on
a different partition and lose ordering. This is why it is in the schema.

### D.4 Execution lanes and fairness

| Lane | SLO (submit → start) | Handler timeout | `max_poll_interval_ms` | Concurrency/replica | Notes |
|---|---|---|---|---|---|
| `realtime` | p95 < 5s, p99 < 20s | 120s | 900000 | 8 | Bounded by LLM + Meta rate limits, not CPU |
| `publishing` | p95 < 60s | 300s | 900000 | 4 | Provider quota-bound |
| `media` | p95 < 5m | 900s | 1200000 | 2 | Memory-bound |
| `bulk` | best effort | 3600s | 3600000 | 1 | Yielding; must never starve others |

**Fairness mechanisms, in order of preference:**

1. **Per-tenant in-flight cap** (Redis `INCR`/`DECR` with TTL). Default 3 per tenant per
   lane, 10 for `pro`. Prevents one tenant's bulk import from occupying every consumer.
   Redis key: `job:inflight:{tenant_id}:{lane}`.
2. **Strict priority with aging.** Order by `(priority, next_run_at, created_at)`, and
   **add `age` to the effective priority**: `effective = max(1, priority - age_minutes)`.
   Without aging, a steady stream of priority-0 realtime work starves `bulk` forever.
   This is the explicit anti-starvation rule.
3. **Concurrency caps per replica** so one tenant's burst cannot consume all handlers.
4. **Burst budget.** Global admission rate per lane; excess stays `queued`. Better to
   queue honestly than to accept work that will breach an SLO anyway.

**Provider rate limits are not configurable anywhere today.** Verified: no 429 or
`Retry-After` handling exists in `channels/meta/providers/base.py:59-71` or
`integrations/channels/embedsocial.py:221-241`. Meta's `content_publishing_limit` is
read at `providers/instagram.py:475-492` purely for display and never consulted before
publishing. Add `META_*_RPS` / `LOCALITH_RPS` settings and a Redis token-bucket pacer;
on a 429, move the job to `blocked` rather than `retrying`, so it does not consume an
attempt or a retry slot.

### D.5 Consumer configuration

`create_consumer` becomes lane-aware:

```python
AIOKafkaConsumer(
    *topics,
    group_id=group_id,
    enable_auto_commit=False,        # R1
    auto_offset_reset="earliest",
    max_poll_interval_ms=900_000,    # S3
    session_timeout_ms=30_000,
    max_poll_records=1,              # keep one-at-a-time; batching is the handler's job
    value_deserializer=lambda b: json.loads(b.decode()),  # KIP-726; falls back cleanly
)
```

---

## E. API contract

Base: `/api/v1/jobs`. All tenant-scoped — resolve `tenant_id` via `core.deps.get_context`
per `users/models.py:61-63`. Never accept `tenant_id` from the caller.

### E.1 Submit

```
POST /api/v1/jobs
Idempotency-Key: <client string>          (optional, recommended)

{
  "type": "publish.post",
  "payload": { "post_id": "...", "listing_id": "..." },
  "priority": 40,                          (optional; clamped to [0,100])
  "max_attempts": 5,                       (optional)
  "subject": { "type": "location_post", "id": "..." },   (optional, for UI grouping)
  "wait": false
}

202 Accepted
{ "job_id": "...", "status": "queued", "poll_after_ms": 1000, "links": { "self": "/api/v1/jobs/..." } }

409 Conflict   { "error": "duplicate", "job_id": "<existing>" }   on Idempotency-Key replay
422 Unprocessable Content  { "error": "unknown_job_type", "known": [...] }
429 { "error": "quota_exhausted", "retry_after_ms": ... }           admission control refused
```

`type` is a closed registry (`JOB_TYPES`), validated server-side. A payload that fails
its Pydantic schema returns 422 **before** any row is written.

### E.2 Status and result

```
GET /api/v1/jobs/{job_id}
200 OK
{
  "job_id": "...", "type": "publish.post", "lane": "publishing", "status": "succeeded",
  "attempts": 1, "max_attempts": 5,
  "created_at": "...", "started_at": "...", "finished_at": "...",
  "result": { "provider_post_id": "..." },
  "error": null,
  "poll_after_ms": null          // present while non-terminal
}
```

Never return another tenant's job — 404, not 403, so the endpoint is not an existence
oracle.

### E.3 List

```
GET /api/v1/jobs?status=queued&lane=publishing&subject_type=location_post&limit=50&cursor=...
```

Keyset pagination on `(created_at, id)`. Default limit 50, max 200.

### E.4 Cancel

```
POST /api/v1/jobs/{job_id}/cancel
202 { "status": "cancelled" }
409 { "error": "not_cancellable", "status": "running" }
```

Legal only from `accepted | queued | retrying | blocked`. A `running` job is **not**
cancellable — the handler may already have issued the external call. Return 409 with the
current state and let the user retry once it settles. Do not fake success here.

### E.5 Progress

Reuse the existing Redis pub/sub fan-out (`channels/realtime.py:18-25`, channel
`inbox:{tenant_id}`). Publish `job.progress` on a `job:{tenant_id}` channel. This adds
no new transport.

### E.6 Operator surface

- `GET /api/v1/admin/jobs` — filter by lane/status/age
- `POST /api/v1/admin/jobs/{id}/retry` — reset a `dead`/`failed` job to `queued`
- `POST /api/v1/admin/jobs/drain-dlq` — replay a lane DLQ

The existing admin failure panel reads only outbox and `IngestJob`
(`admin/service.py:426-441`), so `LocationPost`/`LocationMedia`/`ReviewReply` failures are
currently invisible there. The job view fixes that and **retires that ad-hoc scan**.

---

## F. Phased implementation, rollout, rollback

### Phase 0 — foundations (no behaviour change visible)
1. `jobs` table + migration; `alembic/env.py` import list repaired first (§B.3).
2. Topic provisioning module; explicit partitions; disable auto-create.
3. Outbox `SKIP LOCKED` (S5) + R3 + R4.
4. Producer hardening (S4) + producer singleton lock.
5. **Rollback:** additive only. Revert deploy; drop the new topics if desired.

*Ship independently of everything else.*

### Phase 1 — reliability (requires Phase 0)
6. Manual offset commit (R1) — **only after** §C.6 idempotency lands for the handlers
   already consuming (`review-events`, `meta-events`).
7. `max_poll_interval_ms` (S3); unique indexes (R2b); `review.enriched` enqueue fix (R5).
8. DLQ + operator replay.

*Rollback:* `enable_auto_commit` is a one-line revert. Expect duplicate processing on
rollback — which is why the idempotency work must precede it.

### Phase 2 — transactional outbox (R2)
9. `enqueue_event_in(db, ...)`; migrate call sites **module by module**, starting with
   `auth` (highest volume).
10. Once the job submit path uses the same helper, job + outbox are atomic by
    construction.
*Rollback:* revert per module. Each module's call sites are independent.

### Phase 3 — the job runtime
11. `app/modules/jobs/`: `models`, `service`, `handlers/`, `runner.py`, `reaper.py`.
12. `dispatcher` loop + `<lane>-dispatch` producers.
13. Lane consumer factory, DLQ, admin surface.
14. Migrate one **low-risk** job type first: `stt.job` or `tts.job`. No external side
    effects, easy to assert.
*Rollback:* flip the job type's registry entry back to the old inline path.

### Phase 4 — lane-by-lane migration
15. `ingest_jobs` + `scrape_jobs` (7-state enum → `stage`/`progress` projection).
    Also relocates the RAG worker out of the API process (§B.2).
16. `publishing` lane: `location_posts` + `location_media`. **Highest risk** — this is
    where the crash-after-publish window lives. Requires the reconciliation handler.
17. `realtime` lane: AI replies, customer DMs, Meta 429 retry (the silent-drop bug at
    `channels/meta/consumer.py:586-604`).

**Backward compatibility:** during 15–17 both paths run. The old worker loop is gated by
a per-type flag defaulting to "new". Domain rows keep their existing `status` values
throughout, so no UI change is needed and no client breaks.

**Rollback for 16/17:** flip the flag. Old loop resumes from the same domain tables —
`ix_posts_due` / `ix_media_due` are untouched.

---

## G. Failure injection and load scenarios

Tests run on in-memory SQLite (`tests/conftest.py:36-42`), so anything needing real
`SKIP LOCKED` semantics, real Kafka offsets, or real advisory locks must be marked
integration and run against the compose stack.

| # | Scenario | Method | Pass criterion |
|---|---|---|---|
| G1 | Worker crashes mid-handler | Kill -9 the worker during a 10s LLM job | Lease expires → reaper requeues → job runs again; **no duplicate external call** thanks to C.6 reconciliation |
| G2 | Kafka outage mid-flight | `docker compose stop kafka` under load | Jobs stay `accepted`; outbox retains rows; resumes without loss |
| G3 | Redis outage | `stop redis` | Jobs still execute — Redis is not on the critical path. Budget fail-open stands (`budget.py:127`) |
| G4 | Outbox drainer race | 2+ drainers, same rows | `SKIP LOCKED` → each row sent once |
| G5 | Duplicate dispatch | Manually re-send the same `{job_id}` twice | Second claim `RETURNING` no row → no-op |
| G6 | Idempotency replay | Same `Idempotency-Key` twice | Second returns 409 + existing `job_id` |
| G7 | Meta 429 on send | Stub 429 with `Retry-After` | Job → `blocked`, no attempt consumed, released when window opens. **Today this loses the message outright** |
| G8 | LLM 429/timeout | Stub provider 429 | Job retries with jittered backoff → `dead` after `max_attempts` → visible in admin |
| G9 | Poison payload | Job that always raises | `dead` within budget, lands on DLQ, replayable |
| G10 | Cross-tenant burst | 50 tenants × 100 jobs | Per-tenant in-flight cap holds; no tenant > its cap; bulk not starved by realtime |
| G11 | Starvation | Continuous priority-0 stream + low-priority jobs | Aging promotes low-priority work within the SLO window |
| G12 | Scale-out | 1 → 4 replicas, realtime lane | Throughput scales ~linearly to partition count; lag falls |
| G13 | Replica > partitions | 8 replicas, 4 partitions | 4 idle; no crash, no duplicate |
| G14 | Pool exhaustion | Saturate workers | Boot-time headroom check fails loudly; `pool_timeout=30` surfaces rather than hangs |
| G15 | Publish crash-after-success | Kill between provider POST and DB commit | Reconciliation finds the post; no duplicate Google post — **the case the current advisory lock cannot cover** |

---

## H. Exact files

### H.1 New

| Path | Purpose |
|---|---|
| `services/api/alembic/versions/e1f2a3b4c5d6_unified_jobs.py` | `jobs` table |
| `services/api/app/modules/jobs/models.py` | `Job` |
| `services/api/app/modules/jobs/service.py` | submit/claim/complete/retry/cancel |
| `services/api/app/modules/jobs/types.py` | `JOB_TYPES` registry + payload schemas |
| `services/api/app/modules/jobs/runner.py` | lane consumer loop |
| `services/api/app/modules/jobs/reaper.py` | lease reaper + accepted-row reconciler |
| `services/api/app/modules/jobs/pacing.py` | Redis token bucket + in-flight caps |
| `services/api/app/modules/jobs/handlers/` | one module per job type |
| `services/api/app/modules/jobs/router.py` | `/api/v1/jobs` |
| `services/api/app/modules/kafka/topics.py` | `AIOAdminClient` provisioning |
| `services/api/app/modules/jobs/migrations/` | *(none — see H.4 for per-type data backfill)* |

### H.2 Modified

| Path:line | Change |
|---|---|
| `outbox/service.py:23-46` | `enqueue_event_in(db, ...)` accepting a session; keep `enqueue_event` as a deprecated wrapper |
| `outbox/service.py:49-67` | `FOR UPDATE SKIP LOCKED` + in-flight claim |
| `outbox/worker.py:84` | raise batch size; key on `job_id` |
| `kafka/client.py:14-32` | producer: `acks="all"`, `enable_idempotence=True`, `linger_ms=5`, gzip; `asyncio.Lock` on singleton |
| `kafka/client.py:56-67` | `create_consumer` gains `max_poll_interval_ms`, `enable_auto_commit=False` |
| `kafka/client.py:35-43` | availability becomes per-lane + background prober |
| `analytics/consumer.py:373-395,424-435,463-483` | no auto-commit; manual commit after durable outcome; stop marking failures sent |
| `channels/meta/consumer.py:1305,1334-1343,1367-1385,1471` | same |
| `analytics/consumer.py:217-228` | enqueue inside the session |
| `channels/models.py:75-79,85,129,138` | unique indexes on `platform_message_id`, `platform_comment_id` |
| `workers/main.py:90-99` | register job lanes + RAG worker in `loops` |
| `workers/main.py:120-121` | `await asyncio.gather(*tasks, return_exceptions=True)` after cancel |
| `main.py:148-165` | mirror the new loops inside the `RUN_BACKGROUND_WORKERS` gate |
| `main.py:157-162` | add the missing `run_followup_worker` |
| `config.py` | `JOB_LANES`, `JOB_MAX_ATTEMPTS`, `JOB_LEASE_SECONDS`, `META_*_RPS`, `LOCALITH_RPS`, `JOB_TENANT_INFLIGHT` |
| `alembic/env.py:20-36` | add the 7 missing model imports |
| `admin/service.py:426-441` | retire the ad-hoc failure scan in favour of the job view |
| `posts/service.py:363-381`, `media/service.py:376-383` | remove `asyncio.to_thread` blocking publish |
| `followup_worker.py:200-206`, `channels/service.py:322,378` | use the module-level `ADAPTERS` singleton |
| `billing/budget.py:54` | remove the zero-price `unknown` family |
| `redis/client.py:69-71` | actually call `mark_redis_available()` from a prober |
| `docker-compose.prod.yml`, `docker-compose.yml` | disable auto-create; add `JOB_LANES` per replica |
| `deploy/env.prod.example` | new settings (note: `UVICORN_WORKERS` is currently absent and defaults to 2) |

### H.3 Functions, by name

`outbox.enqueue_event` → keep + `enqueue_event_in` ·
`outbox.fetch_pending_events` → rewrite ·
`outbox.mark_failed` · `outbox.mark_sent` ·
`kafka.get_kafka_producer` · `kafka.create_consumer` · `kafka.mark_kafka_unavailable` ·
`analytics._process_message` · `analytics._drain_outbox_events` ·
`analytics.run_analytics_consumer` ·
`meta._process_message` · `meta._handle_message_received` · `meta._handle_instagram_message` ·
`meta._drain_outbox_events` · `meta.run_meta_events_consumer` ·
`posts._publish_post_inner` · `posts._register_publish_failure` · `media._publish_media_inner` ·
`scheduling.retry_delay` → extend with jitter ·
`rag.start_worker` / `rag.stop_worker` → re-home ·
`followup._send_followup` · `budget.reserve` / `budget.settle` · `budget.cost_cents`

### H.4 Tests to extend

| File | Add |
|---|---|
| `tests/test_meta_webhooks.py` | outbox written in the **same** transaction as the webhook row |
| `tests/test_instagram_comments_pipeline.py` | keep `test_kafka_replay_does_not_twin`; add concurrent double-delivery (currently protected only in-process) |
| `tests/test_instagram_messaging.py:326-335` | add the no-duplicate-send assertion across a *retry*, not just a replay |
| `tests/test_consumer.py` | manual-commit behaviour; failed job reaches `dead` not `sent` |
| `tests/test_posts.py`, `tests/test_media.py` | job projection keeps `status='published'`; crash-after-publish reconciliation |
| `tests/test_sync_locks.py` | advisory lock still prevents concurrent double-publish |
| `tests/test_localith_sync.py:509` | update the comment that documents `enqueue_event`'s independent session — the behaviour it asserts is being removed |
| **new** `tests/test_jobs.py` | state machine, lease expiry, idempotency key, cancel legality |
| **new** `tests/test_job_dispatch.py` | atomic job+outbox insert; rollback discards both |
| **new** `tests/integration/test_kafka_failures.py` | G2, G4, G9 against a real broker (marked, skipped by default) |
| **new** `tests/integration/test_job_recovery.py` | G1, G15 |

Note: `ingest_jobs`, `scrape_jobs`, `stt_jobs`, `tts_jobs` have **zero** coverage today
(verified by grep). Add coverage while migrating, not before.

---

## I. Is the existing stack sufficient?

**Yes — with one caveat stated plainly.**

Postgres + Kafka + Redis + the existing worker service covers every requirement.
No Celery, no Cloud Tasks, no Temporal, no second broker.

- **Why Kafka here is right:** it is already deployed, already carrying two domains, and
  a durable log. It is the *wrong* tool for a priority task queue with per-tenant
  fairness — Kafka has no native priority, no delayed delivery, and no per-key
  scheduling. But we do not need those from the broker: **the `jobs` table provides all
  three.** Postgres holds the priority, the `next_run_at` schedule and the quota state;
  Kafka only needs to say "there is work". This inverts the usual shape deliberately, and
  it is what lets the existing broker suffice.
- **Why not Celery:** a second broker and a second truth, and it would not remove the
  Postgres job record we need anyway. The constraint forbids it and the reasoning agrees.
- **Why not Temporal:** its value is durable workflow replay across many steps. Sayvors'
  jobs are mostly single external calls with retry. Temporal would be a large operational
  surface for a 2-person-shaped team against an RDS `t4g.micro`.
- **Why not Cloud Tasks:** GCP coupling for a workload already carrying its own
  infrastructure, and the constraint forbids relocating it.

### The caveat

**A single-node KRaft broker is a single point of failure** (`docker-compose.yml:41-52`
sets `KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093`). No application change fixes that.
The plan is correct on a 3-broker cluster with `min.insync.replicas=2` and is only
*resilient* there. Until then, treat Kafka loss as database loss: the outbox and the
`jobs` table are the recovery path, which is exactly why §C.4 keeps payloads in Postgres
and on the wire at most a `{job_id}`.

### What this plan explicitly does not promise

- **Not instant execution.** Submissions are queued. `realtime` targets p95 < 5s under
  normal load; a burst is queued and surfaced as lag, not absorbed. §D.4 caps
  concurrency deliberately.
- **Not exactly-once external effects.** §C.6 gives at-least-once plus reconciliation.
  A provider that offers no reconciliation query keeps a residual duplicate window.
- **Not unlimited throughput.** Scaling stops at the Postgres connection budget (§10),
  not at Kafka.
- **Not zero-cost.** A job system adds a table, four topics, and worker replicas.

---

## 10. Resource and cost budget

**Postgres is the binding constraint.** `DB_POOL_SIZE=50` + `MAX_OVERFLOW=50`
(`config.py:8-9`) means up to 100 connections *per process*.

| Topology | Processes | Max connections |
|---|---|---|
| Prod today | 2 api + 1 worker | 300 |
| Prod + 2 workers | 2 api + 3 worker | 500 |
| RDS `t4g.micro` typical | — | ~83 by default template |

Prod today already over-subscribes. **Action:** set `DB_POOL_SIZE=5`,
`DB_POOL_MAX_OVERFLOW=5` for api and worker (10/process → 50 total), add
`validate_production_settings()` (`config.py:212-242`) a check that
`processes × (size + overflow) < 0.6 × max_connections`, and log the arithmetic at boot.
The comment at `config.py:6-7` justifies the large pool ("workers hold sessions across
network calls") — but §C.3 explicitly forbids holding a session across a call, which
removes the justification.

**Kafka.** 24+12+6+6+6+12+1 = **67 partitions**, ~1 GB retained each with default
retention ≈ a few GB. Brokers are I/O-idle; CPU is irrelevant.

**Worker resources.** LLM and Meta jobs are I/O-bound: 1 vCPU / 512 MB is adequate for
`realtime` at concurrency 8. The current `mem_limit: 384m` (`docker-compose.prod.yml:74`)
is too low for the `media` lane, which decodes images — budget 1 GB there.

**LLM concurrency.** The only semaphore in the codebase is `rag/jobs.py:16` (4). Add
per-lane caps (§D.4) and keep `budget.reserve`/`settle` as the cost gate. Two known
defects to fix in the same pass: `TOKEN_PRICES["unknown"] = (0,0)` makes unlisted models
free, and a crashed worker leaks its reservation because there is no TTL.

**External limits.** Unconfigured everywhere today. §D.4 introduces RPS settings and a
token-bucket pacer. Until they exist, the only throttle in the system is
`MAX_PER_PASS = 50` (`posts/service.py:51`) on a 300s cadence — effectively unbounded
against any real provider allowance.