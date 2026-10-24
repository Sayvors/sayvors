# Unified Job System — Implementation Plan (1M+ users)

Date: 2026-10-24
Status: plan — not yet implemented
Scope: `services/api` (jobs, kafka, outbox, channels, posts, media, rag, stt, tts)
Design reference: `docs/specs/2026-10-10-unified-job-processing-design.md`
Owner: platform/infrastructure

---

## 0. State assessment — what already exists

The `jobs` module and runner are **partially built**. This plan does not
rebuild them; it completes the migration and closes the gaps that block
1M-user scale.

### Already implemented

| Component | Status | Evidence |
|---|---|---|
| `jobs` table + `Job` model | ✅ | `app/modules/jobs/models.py` |
| `JobStatus` / `JobLane` / `JobType` enums | ✅ | `app/modules/jobs/types.py` — 10 types, 4 lanes |
| `submit_job`, `claim_due_jobs`, `complete_job`, `retry_job`, `fail_job`, `cancel_job`, `block_job` | ✅ | `app/modules/jobs/service.py` |
| `JobRunner` with per-lane concurrency, per-tenant in-flight caps, leases | ✅ | `app/modules/jobs/runner.py` |
| Job reaper (lease expiry, accepted reconciler, stuck-lane report) | ✅ | `app/modules/jobs/reaper.py` |
| Handlers: `post.publish`, `post.delete`, `stt.job`, `tts.job` | ✅ | `app/modules/jobs/handlers/` |
| Kafka topic provisioning (explicit partitions) | ✅ | `app/modules/kafka/topics.py` |
| Manual offset commit (`enable_auto_commit=False`) | ✅ | `app/modules/kafka/client.py` |
| Producer: `acks=all`, idempotence, gzip, linger | ✅ | `app/modules/kafka/client.py` |
| `enqueue_event_in` (transactional outbox) | ✅ | `app/modules/outbox/service.py` |
| `FOR UPDATE SKIP LOCKED` on outbox drain | ✅ | `app/modules/outbox/service.py` |
| Worker registration (4 lane runners + reaper) | ✅ | `app/workers/main.py` |
| `max_poll_interval_ms`, `session_timeout_ms` defaults | ✅ | `app/modules/kafka/client.py` |

### Gaps (what this plan closes)

| Gap | Impact at 1M users | Phase |
|---|---|---|
| 6 of 10 job types have no handler and are never submitted | Features bypass the queue entirely | 1 |
| Topic provisioning not called in worker warmup (only in runner.start) | Topics may not exist before consumers connect | 0 |
| `JOB_LANES` env allowlist not implemented | Cannot scale a single lane independently | 0 |
| `enqueue_event` (commit-then-signal) still used at ~25 call sites | At-most-once dispatch on crash | 1 |
| No per-tenant fairness in claim query (priority aging) | One noisy tenant starves others | 2 |
| No provider rate-limit pacer (429 handling) | Rate-limit violations → dead jobs | 2 |
| Slow endpoints still run inline (publish 500 calls, posts 50, Localith, media) | Request timeouts, connection exhaustion | 2 |
| `rag.jobs` worker not registered in `loops` dict | RAG ingest runs per-process, not scalable | 2 |
| No dead-letter replay endpoint | Dead jobs require manual DB intervention | 1 |
| No `max_poll_interval_ms` passed to consumer (uses default, which is fine but explicit is safer) | — | 0 |
| No `job_lanes` allowlist in worker | Cannot scale lanes independently | 0 |
| Kafka availability is process-global (mark_kafka_unavailable) | A blip disables Kafka for the whole process | 0 |
| `alembic/env.py` model-import list stale (missing 7 modules) | `--autogenerate` emits spurious drops | 0 |
| `run_followup_worker` not in API lifespan | Follow-ups don't run in dev/single-process mode | 0 |
| Cancel-without-await (tasks cancelled but never gathered) | Resource leaks on shutdown | 0 |
| No `max_attempts` per lane (all default 5) | Bulk jobs retry too few times | 1 |
| No job status API for clients (submit returns 202 but no polling endpoint) | Clients can't track progress | 1 |
| No admin UI for job queue (dead letters, stuck lanes, retry) | Operators blind to queue health | 3 |
| No load test | Can't verify 1M-user readiness | 4 |

---

## Phase 0 — Blocking prerequisites (1 week)

> These must ship before any new job type is added. Without them, new jobs inherit
> the same loss and scaling problems.

### 0.1 Topic provisioning in worker warmup

**File:** `app/workers/main.py`
**Change:** Call `provision_topics()` before starting any consumer/runner. Currently
called inside `runner.start()` which runs per-lane and can race.

```python
# In workers/main.py _amain(), before loop registration:
from app.modules.kafka.topics import provision_topics
await provision_topics()
```

**Acceptance:** Topics exist with correct partition counts before any consumer connects.
`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false` in both compose files.

### 0.2 `JOB_LANES` env allowlist

**File:** `app/workers/main.py`, `app/config.py`
**Change:** Add `JOB_LANES: str = ""` to settings. When set, only start runners
for those lanes. Empty = all lanes (backward compat).

```python
# In _amain():
lanes = [l.strip() for l in settings.JOB_LANES.split(",") if l.strip()] or ["realtime", "publishing", "media", "bulk"]
for lane in lanes:
    loops[f"job-runner-{lane}"] = lambda l=lane: JobRunner(l).start()
```

**Acceptance:** `JOB_LANES=realtime` starts only the realtime runner. Other lanes
are not started. Enables per-lane horizontal scaling.

### 0.3 Kafka availability per-consumer (not process-global)

**File:** `app/modules/kafka/client.py`, `app/modules/jobs/runner.py`
**Change:** `mark_kafka_unavailable()` currently sets a process-global flag. Move
to per-consumer state. Add a background prober (like Redis re-arm) that re-latches
Kafka for each consumer independently.

**Acceptance:** A Kafka blip disables only the affected consumer, not all lanes.
Re-arm prober restores connectivity within 30s.

### 0.4 `alembic/env.py` model-import fix

**File:** `app/alembic/env.py`
**Change:** Add missing imports: `team`, `channels.meta`, `notifications`, `media`,
`locations`, `billing`, `user_feedback`. Without this, `--autogenerate` emits
spurious drops.

**Acceptance:** `alembic revision --autogenerate` produces no unexpected drops.

### 0.5 `run_followup_worker` in API lifespan

**File:** `app/main.py`
**Change:** Add `run_followup_worker()` to the lifespan loop list (currently only
in worker entrypoint). Dev/single-process mode needs it.

**Acceptance:** Follow-up worker runs in dev mode (`RUN_BACKGROUND_WORKERS=true`).

### 0.6 Cancel-without-await fix

**File:** `app/workers/main.py`, `app/main.py`
**Change:** `tasks.cancel()` must be followed by `await asyncio.gather(*tasks, return_exceptions=True)`.

**Acceptance:** Clean shutdown with no "Task was destroyed but it is pending" warnings.

### 0.7 DB pool headroom check at boot

**File:** `app/config.py`, `app/database.py`
**Change:** Log a warning if `pool_size * worker_count > max_connections - 10`.

**Acceptance:** Boot log shows pool headroom calculation.

### Phase 0 exit criteria

- [ ] All Phase 0 items merged
- [ ] `python -m alembic upgrade head` succeeds
- [ ] Worker starts with `JOB_LANES=realtime` and only runs realtime
- [ ] No "task destroyed pending" warnings on shutdown
- [ ] Topic provisioning runs before consumers

---

## Phase 1 — Correctness (2 weeks)

### 1.1 Migrate `enqueue_event` → `enqueue_event_in` at all call sites

**Files:** `auth/service.py` (11 sites), `profile/service.py` (5 sites),
`channels/router.py` (4 sites), `analytics/consumer.py` (1 site)

**Change:** Replace `enqueue_event(...)` (commit-then-signal) with
`enqueue_event_in(db, ...)` (transactional). This closes the at-most-once
dispatch hole.

**Acceptance:** No `enqueue_event(` calls remain outside `outbox/service.py`.
`grep` for `enqueue_event(` returns only the definition and `enqueue_event_in`.

### 1.2 Emit `review.enriched` inside consumer session

**File:** `analytics/consumer.py:217-228`
**Change:** Move the `enqueue_event` call inside the `async with db:` block,
before commit.

**Acceptance:** Enrichment event is committed atomically with the review update.

### 1.3 Dead-letter topic + operator replay endpoint

**Files:** new `app/modules/jobs/router.py`, `app/modules/jobs/service.py`
**Change:**
- DLQ topics already provisioned in `topics.py`. Add a `dead` job → DLQ publish
  in `retry_job` when `attempts >= max_attempts`.
- Add `POST /api/v1/admin/jobs/{job_id}/replay` — resets a dead job to
  `queued` with `attempts=0`.
- Add `GET /api/v1/admin/jobs?status=dead` — list dead jobs.

**Acceptance:** A job that exhausts retries appears on the DLQ topic. Operator
can replay it via the endpoint. Replay resets attempts and sets status to queued.

### 1.4 Job status API for clients

**Files:** new `app/modules/jobs/router.py`
**Change:** Add:
- `GET /api/v1/jobs/{job_id}` — returns status, progress, result, error
- `GET /api/v1/jobs?status=&lane=&limit=` — list jobs for current tenant
- `POST /api/v1/jobs/{job_id}/cancel` — cancel if cancellable

**Acceptance:** Client can submit a job, poll status, and cancel. Tests cover
each endpoint.

### 1.5 Per-lane `max_attempts`

**File:** `app/modules/jobs/types.py`, `app/modules/jobs/service.py`
**Change:** Add `MAX_ATTEMPTS_BY_LANE = {"realtime": 3, "publishing": 5, "media": 3, "bulk": 10}`.
`submit_job` uses lane default when `max_attempts` not explicitly provided.

**Acceptance:** Bulk jobs get 10 attempts; realtime gets 3.

### 1.6 Unique index on `ChannelComment.platform_comment_id`

**File:** `app/modules/channels/models.py`, new migration
**Change:** Add `unique=True` to `platform_comment_id` column. Migration creates
unique index (nullable, so multiple NULLs allowed).

**Acceptance:** Duplicate platform comment id raises IntegrityError.

### Phase 1 exit criteria

- [ ] No `enqueue_event(` (non-`_in`) calls remain
- [ ] Dead-letter replay endpoint works
- [ ] Job status API returns correct data
- [ ] `max_attempts` varies by lane
- [ ] All Phase 1 tests pass

---

## Phase 2 — Throughput (3 weeks)

### 2.1 Per-tenant in-flight cap in claim query

**File:** `app/modules/jobs/runner.py` (`_tick`)
**Change:** Before claiming, check `job:inflight:{tenant_id}:{lane}` Redis counter.
If at cap, skip the job (defer to next tick). The `_admit_tenant` method already
exists but is called after claim. Move the check before claim, or add a
`HAVING` clause.

Actually, the current approach claims then checks. Better: add a SQL-level
filter that excludes tenants at their cap. Since Redis is ephemeral, fall back
to the jobs table count if Redis is down.

**Acceptance:** One tenant with 100 queued jobs cannot occupy all 8 realtime
slots. Other tenants' jobs still run.

### 2.2 Provider rate-limit pacer

**Files:** new `app/modules/jobs/pacer.py`, `app/modules/channels/meta/providers/base.py`
**Change:**
- Add `META_RPS`, `LOCALITH_RPS` settings (default: 10/s, 5/s).
- Redis token-bucket per provider: `ratelimit:provider:{name}` with TTL.
- On 429 from provider: move job to `blocked` with `next_run_at = now + Retry-After`.
- `blocked` jobs are swept by the reaper when `next_run_at <= now()`.

**Acceptance:** A 429 response does not consume an attempt. Job moves to blocked.
Reaper releases it after Retry-After.

### 2.3 Move slow endpoints to jobs (S6)

**Files:** `channels/router.py:1224-1305`, `posts/router.py:203-218`,
`localith/router.py:135-159`, `media/router.py:158-175`
**Change:** Return `202 {job_id}` instead of running inline. Create job via
`submit_job`, enqueue to outbox. Client polls `GET /api/v1/jobs/{job_id}`.

**Acceptance:** Endpoints return 202 immediately. Jobs appear in queue. Client
can poll for completion.

### 2.4 Remove blocking publish (S6b)

**Files:** `posts/service.py:363-381`, `media/service.py:376-383`
**Change:** Replace `asyncio.to_thread(_post, ...)` with job submission.
The `_post` call (60s timeout, advisory lock) becomes a `post.publish` job.

**Acceptance:** No `asyncio.to_thread` in posts/media service. Publish runs in
the publishing lane.

### 2.5 Register `rag.jobs.start_worker` in loops dict

**File:** `app/workers/main.py`
**Change:** Add `"rag-ingest": rag.jobs.start_worker` to the loops dict so it
runs in the worker process (not lazily from request handlers).

**Acceptance:** RAG ingest runs in the worker process. `RUN_BACKGROUND_WORKERS=false`
gates it correctly.

### 2.6 Priority aging (anti-starvation)

**File:** `app/modules/jobs/service.py` (`claim_due_jobs`)
**Change:** Order by `effective_priority` where
`effective = max(1, priority - age_minutes)` (age = minutes since created_at).
Prevents a steady stream of priority-0 realtime work from starving bulk.

**Acceptance:** A bulk job created 30 minutes ago with priority 50 gets
effective priority 20, beating a fresh priority-40 realtime job.

### Phase 2 exit criteria

- [ ] Per-tenant cap prevents single-tenant starvation
- [ ] 429 responses move jobs to blocked, not dead
- [ ] Slow endpoints return 202
- [ ] No `asyncio.to_thread` in posts/media service
- [ ] RAG ingest runs in worker process
- [ ] Aging prevents starvation

---

## Phase 3 — Migration + observability (2 weeks)

### 3.1 Migrate existing job tables

**Files:** `rag/models.py`, `stt/models.py`, `tts/models.py`, `posts/models.py`,
`media/models.py`
**Change:** Add `job_id` FK to each domain table. On submit, create a `Job` row
and link it. Old tables remain as projections. New code paths use `submit_job`.

Migration strategy:
1. Add `job_id` column (nullable) to each domain table.
2. Create jobs for existing rows (backfill script).
3. Update handlers to write to domain tables.
4. Remove old lifecycle columns (`status`, `attempts`, `next_retry_at`) in a
   later migration.

**Acceptance:** All new work goes through `submit_job`. Old tables are projections.

### 3.2 Admin job queue UI

**Files:** `apps/admin/app/(dashboard)/jobs/page.tsx`, `app/modules/jobs/router.py`
**Change:**
- `GET /api/v1/admin/jobs` — list jobs with filters (status, lane, tenant)
- `GET /api/v1/admin/jobs/{id}` — job detail with external_intent/result
- `POST /api/v1/admin/jobs/{id}/replay` — replay dead job
- `POST /api/v1/admin/jobs/{id}/cancel` — cancel queued/retrying job
- Admin page: table with status chips, lane, tenant, attempts, error, actions

**Acceptance:** Operator can view, filter, replay, and cancel jobs from the UI.

### 3.3 Stuck-lane alerting

**File:** `app/modules/jobs/reaper.py`
**Change:** When `report_stuck_lanes` returns non-empty, emit a GlitchTip/Sentry
alert (not just a log line). Use `sentry_sdk.capture_message` with level=error.

**Acceptance:** A stuck lane triggers an alert in GlitchTip.

### 3.4 Kafka consumer lag monitoring

**File:** new `app/modules/jobs/metrics.py`
**Change:** Expose Prometheus gauges:
- `sayvors_job_queue_depth{lane}` — count of queued+retrying jobs
- `sayvors_job_oldest_age_seconds{lane}` — age of oldest queued job
- `sayvors_job_processing_duration_seconds{lane,job_type}` — histogram

**Acceptance:** Metrics appear on `/metrics`. Grafana dashboard can be built.

### Phase 3 exit criteria

- [ ] All new work goes through `submit_job`
- [ ] Admin job queue UI functional
- [ ] Stuck-lane alerts fire
- [ ] Prometheus metrics exposed

---

## Phase 4 — Validation (1 week)

### 4.1 k6 load test

**File:** new `tests/load/job_system.k6.js`
**Change:** Script that submits 1000 jobs across 10 tenants in 4 lanes, measures
submit→start latency, throughput, and error rate. Run before and after lane
migration.

**Acceptance:** p95 submit→start < 5s for realtime lane at 10× current peak.

### 4.2 Chaos test: kill a worker mid-job

**Change:** Start worker, submit a job with a 30s handler, kill the worker at 10s,
restart, verify the job completes (lease reclaim + retry).

**Acceptance:** Job completes within 2× lease timeout. No duplicate side effects.

### 4.3 Multi-replica scaling test

**Change:** Run 4 worker replicas, submit 1000 jobs, verify linear throughput
increase and no duplicate processing.

**Acceptance:** Throughput scales linearly up to partition count. No duplicates.

### Phase 4 exit criteria

- [ ] Load test passes at 10× peak
- [ ] Chaos test passes
- [ ] Multi-replica test passes
- [ ] Readiness report updated

---

## Migration list

| # | Revision | What |
|---|---|---|
| 1 | `j6k7l8m9n0o1` | Add `job_id` FK to domain tables (nullable) |
| 2 | `k7l8m9n0o1p2` | Backfill `job_id` for existing rows |
| 3 | `l8m9n0o1p2q3` | Add `ChannelComment.platform_comment_id` unique index |

## Test plan

| Phase | Test files | What they verify |
|---|---|---|
| 0 | `test_job_foundations.py` (existing) | Lane caps, lease reclaim |
| 1 | `test_job_submit.py` (new) | Submit, idempotency, cancel, status API |
| 1 | `test_job_dlq.py` (new) | Dead letter, replay |
| 2 | `test_job_fairness.py` (new) | Per-tenant cap, priority aging, 429 handling |
| 2 | `test_job_endpoints.py` (new) | Slow endpoints return 202 |
| 3 | `test_job_admin.py` (new) | Admin queue UI endpoints |
| 4 | `tests/load/job_system.k6.js` | Load, chaos, scaling |

## Acceptance criteria (1M+ users)

1. **Throughput:** Realtime lane handles 1000 msg/min per replica, scales linearly to 8 replicas.
2. **Latency:** p95 submit→start < 5s for realtime, < 60s for publishing.
3. **Durability:** Zero job loss on worker crash (lease reclaim + retry).
4. **Fairness:** One tenant cannot occupy more than 3 slots per lane per replica.
5. **Idempotency:** Replaying a job produces no duplicate side effects.
6. **Observability:** Queue depth, oldest age, and processing duration are visible in Prometheus.
7. **Recovery:** Dead jobs can be replayed via admin endpoint. Stuck lanes trigger alerts.

## Estimated timeline

| Phase | Effort | Depends on |
|---|---|---|
| Phase 0 | 1 week | Nothing |
| Phase 1 | 2 weeks | Phase 0 |
| Phase 2 | 3 weeks | Phase 1 |
| Phase 3 | 2 weeks | Phase 2 |
| Phase 4 | 1 week | Phase 3 |

**Total: ~9 weeks** for a single senior developer with AI pairing.

---

## What NOT to do

- Do not create a 5th competing job table. `jobs` is the single source of truth.
- Do not use Kafka as a job store — it is dispatch only.
- Do not use Redis as a job store — it holds only reconstructible state.
- Do not skip the lease mechanism — it is the only crash-recovery path.
- Do not claim exactly-once execution — it is at-least-once with reconciliation.
- Do not merge Phase 2 before Phase 1 — throughput without correctness loses work.
- Do not skip the load test — "it works on my machine" is not 1M-user evidence.
