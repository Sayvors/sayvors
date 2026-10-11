# Unified Job Processing — Design Review & Corrections

Date: 2026-10-10
Reviews: `docs/specs/2026-10-10-unified-job-processing-design.md` (v1)
Status: review only — no code, no migrations executed
Kafka facts verified against the installed `aiokafka 0.14.0` in `.venv`

---

## 0. Verdict

Six blocking questions. **Four of them found real defects in v1.** Two of those defects
were load-bearing enough that v1 would not have been safe to build.

| # | Question | Defect in v1 | Blocks production |
|---|---|---|---|
| 1 | State consistency | `accepted` state and its reconciler were incoherent — an impossible state with no recovery owner | No |
| 2 | Offset safety | **Bounded concurrency + "commit after handler" as written can commit past unfinished work. Data loss.** | **Yes** |
| 3 | Capacity | Partition counts asserted with no model or measurement | No |
| 4 | Fairness | Priority cannot be enforced by a single partitioned topic; the aging formula was ad hoc | No |
| 5 | DLQ durability | DLQ via a Kafka topic contradicts "Postgres is the authority" and fails during a Kafka outage | **Yes** |
| 6 | Partition expansion | **v1 claimed the stored key preserves partition placement. It does not.** | **Yes** for `publishing` |

### Verified Kafka primitives this review depends on

From the installed client, not from documentation:

```
aiokafka.AIOKafkaConsumer.commit(offsets=None)
  "When explicitly passing offsets use either offset of next record"
  await consumer.commit({tp: msg.offset + 1})
```

Committing offset *N* means *up to but not including N* — i.e. `msg.offset + 1`.
`commit()` with no argument commits the consumer's **current fetch position**.

```python
# aiokafka/partitioner.py — DefaultPartitioner.__call__
idx = murmur2(key)
idx &= 0x7FFFFFFF
idx %= len(all_partitions)      # ← partition count is in the modulus
return all_partitions[idx]
```

Defaults confirmed in `.venv/Lib/site-packages/aiokafka/consumer/consumer.py:247-257`:
`enable_auto_commit=True`, `auto_commit_interval_ms=5000`,
`max_poll_interval_ms=300000`, `session_timeout_ms=10000`, `max_poll_records=None`.

---

## 1. Job state consistency — `accepted → queued`

### 1.1 The defect

v1 §C.3 specified `accepted` as the post-insert state, then `accepted → queued` as a
*"dispatcher, same tx as outbox insert"*. Then it added a reconciler for *"`accepted`
rows with no outbox row older than 60s"*.

That reconciler can never fire, and the state is dead weight:

- v1 §C.4 says submit inserts the job **and** the outbox row **in the caller's
  session, one commit**. If that holds, an `accepted` row and its outbox row are
  created atomically. There is no window in which one exists without the other.
- So the reconciler's precondition is unsatisfiable, and `accepted` never persists past
  its own transaction.

Worse, v1 left the transition owner unspecified — "a dispatcher" — while also claiming
the dispatcher only publishes `{job_id}` and never touches job state. Two different
components both claimed ownership of the same transition.

### 1.2 Correction — drop `accepted`, submit `queued` directly

`accepted` exists in a transactional-outbox design only to cover a gap where the event
*cannot* be written atomically. Once job and outbox share one transaction, that gap
does not exist. The state is removed.

**Submit transaction** — the only commit in submission:

```
BEGIN
  INSERT jobs (status='queued', attempts=0, next_run_at=now(),
               dispatched_at=NULL, lane_key=<key>)
  INSERT event_outbox (event_type='job.dispatch',
                       payload={"job_id": <id>}, topic='<lane>-dispatch',
                       status='pending', attempts=0, next_retry_at=now())
COMMIT                                    -- both rows, or neither
```

**Who owns what, unambiguously:**

| Transition | Owner | Mechanism |
|---|---|---|
| — → `queued` | API request | Single tx with outbox row |
| `queued` → `running` | Lane consumer | Atomic claim, §4 |
| `running` → terminal / `retrying` | Lane consumer | Same tx as domain projection |
| `retrying` → `queued` | **Sweeper** (§4.3) | Atomic tx with a *new* outbox row |
| `running` → `queued` | **Lease reaper** | Lease expiry only |
| `queued`, never dispatched → re-dispatch | **Dispatch watchdog** | `dispatched_at IS NULL` |

No dispatcher ever writes job state. The outbox drainer publishes; that is all.

### 1.3 Adding `dispatched_at` closes the durable gap

The job needs one new column:

```
dispatched_at TIMESTAMPTZ NULL      -- set by the lane consumer on first claim
```

The outbox row alone is not sufficient proof of dispatch. With
`KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1` and a single-node broker
(`docker-compose.yml:41-52`), an acknowledged message can be lost with the broker's
disk. The outbox row was already marked `sent`, so nothing would ever retry it.

**Dispatch watchdog** (new, 60s interval, leader-guarded by advisory lock):

```sql
UPDATE jobs SET dispatched_at = NULL
WHERE dispatched_at IS NULL
  AND status = 'queued'
  AND created_at < now() - interval '5 minutes'
```
then insert a fresh outbox row per affected id in the same transaction. Duplicate
dispatches are harmless — §2's claim is idempotent.

### 1.4 Crash windows

| Window | State on disk | Recovery |
|---|---|---|
| Crash before COMMIT | Neither row | Client got no 202. Retries with `Idempotency-Key` → fresh submit |
| Crash after COMMIT, before response | Both rows | Outbox drains normally. Client retries with same key → 409 + existing `job_id` |
| Crash after outbox `send`, before `mark_sent` | Both rows, outbox `pending` | Re-published. Duplicate dispatch → idempotent claim (§2) |
| Crash after `mark_sent`, broker loses the message | Job `queued`, `dispatched_at NULL` | **Watchdog** re-dispatches after 5 min |
| Consumer crashes mid-handler | Job `running`, lease held | **Reaper** requeues on lease expiry (§4.2) |

Every window terminates. None require operator action except §1.3's broker-loss case,
which the watchdog handles automatically.

### 1.5 The idempotency key is load-bearing, not optional

Window 2 above is only safe *because* the client can retry into a 409. So
`Idempotency-Key` must be **required**, not optional, on `POST /api/v1/jobs`. v1 listed
it as "(optional, recommended)". Corrected: mandatory; the API generates one internally
for first-party callers that omit it.

This is served by `UniqueConstraint("tenant_id", "idempotency_key")` on `jobs` —
Postgres NULL semantics make it a no-op for NULL, which is why the key must be
non-null in practice.

### 1.6 Tests and blocking

Required integration tests: `G2` (Kafka down from submit through dispatch), new `G16`
(broker loses a dispatched message → watchdog recovers), `G6` (duplicate dispatch),
`G17` (crash between job INSERT and COMMIT → neither row).

**Does not block production.** It is a design-clarity defect, not a data-loss one, once
corrected.

---

## 2. Kafka offset safety — the serious defect

### 2.1 The defect

v1 §D.4 specified per-lane concurrency of **8** for `realtime`, **4** for `publishing`,
**2** for `media`. v1 §C.4 said *"Only then `await consumer.commit()`"*, and v1 §D.5
said `max_poll_records=1`.

These three statements are mutually inconsistent and the combination is unsafe.

`max_poll_records=1` limits how many records are **fetched**, not how many are
**processed**. With a concurrency-8 handler pool consuming from a single partition:

1. Offsets 100…107 are fetched (or fetched earlier at `max_poll_records=None`).
2. Eight handlers run concurrently.
3. Handler for 107 finishes first, calls `commit({tp: OffsetAndMetadata(108)})`.
4. Broker now records 108. **Handlers 100–106 are still running.**
5. Process is OOM-killed.
6. On restart the group resumes at 108. **Seven completed-or-in-flight jobs are never
   redelivered.** Their Kafka records are still there, but nobody will ever read them.

This is worse than the at-most-once bug the audit found, because it is *silent* and
*newly introduced* — the current code fails in the same direction but at least one
record at a time, so a crash loses one job rather than an unbounded batch.

v1's §D.5 note that `max_poll_records=1` "keeps one-at-a-time" is simply wrong about
what that setting does.

### 2.2 Correction — one in-flight record per partition; concurrency comes from partitions

**Rule: a lane consumer processes at most one record per assigned partition at a time.
It never pipelines within a partition. Throughput comes from partition count.**

This makes the commit trivially safe, because there is only ever one unfinished record
in a partition.

```
for each partition p assigned to this consumer:
    for msg in consumer.getmany(...) filtered to p, in offset order:
        1. await handler(msg)                    # bounded, see §3
        2. await persist_outcome(...)            # DB tx COMMIT completes here
        3. await commit({TopicPartition(p): OffsetAndMetadata(msg.offset + 1, "")})
```

### 2.3 Proof that a later offset cannot be committed past an unfinished earlier one

Let *C(p)* be the last offset committed for partition *p*, i.e. the group resumes at
*C(p)*.

**Invariant I.** During processing of record *m* on *p*: *C(p) ≤ m.offset*.
*Proof.* By construction the consumer processes *p* in ascending offset order and holds
exactly one record. The only write to *C(p)* is step 3 for the record currently being
processed, which commits *m.offset + 1*. Before step 3, *C(p)* holds its previous value,
which was some *m'.offset + 1* with *m' < m*, hence *C(p) ≤ m.offset*. ∎

**Invariant II.** After step 3 completes for record *m*: *C(p) = m.offset + 1* and every
record in *p* with offset < *m.offset + 1* has a durable outcome in PostgreSQL.
*Proof.* By Invariant I, *m* is the only unfinished record in *p* at the moment step 3
runs, and step 2 committed its outcome before step 3 was invoked. All records below
*m* were processed earlier and committed by the same reasoning. ∎

**Corollary (crash safety).** If the process dies at any instant, every record in *p*
below *C(p)* has a durable outcome; every record at or above *C(p)* is unprocessed and
will be redelivered from *C(p)*. No window exists in which a record has been read,
skipped, and not recorded — because a record is only ever "skipped" by being committed,
and it can only be committed after its outcome is durable. ∎

**Corollary (rebalance).** A rebalance moves partitions between consumers mid-stream.
The new owner resumes at *C(p)*, which by Invariant II never points past unfinished
work. The previous owner's in-flight record on *p* was never committed, so it is
redelivered — exactly once by the new owner. `commit()` may itself raise
`CommitFailedError` after a rebalance; **that is safe and must not be retried blindly**:

```python
try:
    await commit_one(tp, msg.offset + 1)
except CommitFailedError:
    # The record is still uncommitted and will be redelivered. Nothing to do:
    # the DB already holds the outcome, so redelivery re-runs the handler and
    # the idempotency key makes it a no-op.
    log.warning("commit failed after rebalance on %s", tp)
```

Note the ordering constraint that makes this work: **the DB commit (step 2) must
precede the Kafka commit (step 3).** Reverse them and a crash between them loses the
job with a committed offset — reintroducing exactly the audit's R1.

### 2.4 Consequence: concurrency is a partition-count decision, not a pool setting

| Lane | v1 claimed | Corrected mechanism |
|---|---|---|
| realtime | 8 per replica | 24 partitions ⇒ 24 concurrent handlers, 1 per partition |
| publishing | 4 | 12 partitions |
| media | 2 | 6 partitions |
| bulk | 1 | 6 partitions |

A worker replica that gets fewer partitions than its configured lane count simply does
less work. This removes the `JOB_LANE_CONCURRENCY` setting from v1 entirely — **one less
knob, one less way to get the offset bug back.**

### 2.5 The head-of-line cost, stated honestly

One-in-flight-per-partition means a 120s LLM job stalls its partition for 120s. With
`lane_key = tenant_id`, that stalls *that tenant's other jobs only*. Mitigations:

- Bounded handler timeout (`asyncio.wait_for`, §3.2) caps the stall.
- Per-tenant keying localises the blast radius; other tenants are unaffected.
- Long work (media, bulk) lives on separate topics with their own partitions, so it can
  never block a realtime partition.
- A sustained stall would be visible as per-partition lag (§G11).

This is a deliberate trade: strict ordering for safety, localised rather than global
head-of-line blocking.

### 2.6 aiokafka-specific hazard: no blocking poll thread

Unlike kafka-python, aiokafka's fetcher is co-scheduled on the same event loop. A
**CPU-bound** handler would starve heartbeats and trip `max_poll_interval_ms`, evicting
the consumer. All proposed handlers are I/O-bound and `await`, so this is safe today —
but the **media lane decodes and resizes images**, which is CPU-bound.

**Correction:** the media lane handler must offload to a process/thread pool
(`asyncio.to_thread` is already the codebase idiom at `posts/service.py:363`) so the
event loop never blocks. This is a new requirement v1 did not state.

### 2.7 Tests and blocking

`G18` — assert no offset is committed while an earlier record in the same partition is
unfinished. Implementation: wrap the consumer with a fake that records
`commit()` calls; force handler for offset *N* to hang; let *N+1*… complete (impossible
under the corrected design — assert it cannot happen); kill; assert redelivery starts at
the right offset.

`G19` — kill during `max_poll_interval_ms` window; assert the partition is reassigned and
resumes at the last durable outcome.

**BLOCKS PRODUCTION.** This is a silent multi-record data-loss bug. It must not ship.

---

## 3. Capacity and partitions

### 3.1 The defect

v1 §D.1 asserted 24/12/6/6/6 partitions with no derivation. v1 §10 asserted pool sizes
that were internally inconsistent: it recommended `DB_POOL_SIZE=5` + overflow 5 = 10
per process, then counted 6 processes as 60 against a "target ≤ 50" it had itself set.

### 3.2 Everything below is an ASSUMPTION until the load test runs

| Symbol | Assumed | Basis |
|---|---|---|
| `T_llm_p50` | 4.0 s | `budget.py:30` describes a typical grounded reply as ~3k prompt + ~500 completion tokens on a budget model. **Not measured** |
| `T_llm_p95` | 12.0 s | **Not measured** |
| `T_meta_send` | 0.5 s | Graph adapter `timeout=20.0` (`providers/base.py:38`) is a ceiling, not a measurement |
| `T_tts` | 3.0 s | `meta/voice.py:193` `timeout=60.0` ceiling |
| `T_realtime_job_p50` | 5.0 s | = `T_llm_p50` + `T_meta_send` |
| `T_realtime_job_p95` | 15.0 s | = `T_llm_p95` + `T_tts` |
| `max_connections` | 83 | RDS `t4g.micro` default template. **Must be confirmed with `SHOW max_connections`** |

None of these are measurements. §3.6 replaces every one.

### 3.3 Partition derivation

Service rate for one partition, strictly serial (Invariant I):

```
mu_per_partition = 1 / T_p50
```

Burst absorption — a lane that receives `B` jobs in window `W` needs enough partitions
to drain within `SLO`:

```
P >= B * T_p50 / SLO_drain_seconds
```

Steady-state headroom target: **3× the observed p95 rate**, i.e.
`P >= 3 * R_peak * T_p95`.

#### Scenario matrix

| Scenario | `R_peak` (jobs/s) | `T_p50` | `T_p95` | `P_needed` (3× p95) | Proposed | Verdict |
|---|---|---|---|---|---|---|
| Launch, 50 tenants | 0.5 | 5.0 s | 15.0 s | 23 | 24 | just adequate |
| Growth, 200 tenants | 2.0 | 5.0 s | 15.0 s | 90 | 24 | **insufficient — revisit** |
| Single tenant burst | 20 jobs in 10 s window, drain in 30 s | 5.0 s | — | 4 partitions *for that tenant* | keyed by `tenant_id` | **spills across ~1 partition — see §3.4** |

**Honest reading:** 24 partitions is defensible at launch scale and probably wrong by
200 tenants. The correct answer is to provision 24, measure real `T_p50`/`T_p95` and
`R_peak` in week one, and revisit before growth. Provisioning is a one-line change while
the topic is young — which is exactly why §6 insists new topics are created at their
final count.

`publishing` = 12: the publish path is provider-rate-bound, not CPU-bound, and
`posts/service.py:51` already caps at `MAX_PER_PASS=50` per pass. Twelve partitions is
comfortable; the constraint is Localith quota, not partition count.
`media` = 6 and `bulk` = 6: both are deliberately low-rate lanes that must never
compete with realtime, and are on separate topics so they physically cannot.

### 3.4 A single-tenant burst cannot be spread across partitions

This is a consequence of §2.5 that v1 missed. Because `lane_key = tenant_id` and one
tenant maps to exactly one partition, a burst from **one** tenant serialises behind
itself at `1/T_p50`. Twenty jobs from one tenant = 20 × 5 s = 100 s, not 20 jobs in
parallel.

This is the intended behaviour — it is what guarantees per-tenant ordering — but it
must be stated as a **capacity limit per tenant**, not an average:

```
max_sustained_jobs_per_second_per_tenant = 1 / T_p50 = 0.2
```

Mitigation is admission control, not more partitions: §4.4's per-tenant in-flight cap
and a submission-time check that returns `429` with `retry_after_ms` when a tenant's
queue depth exceeds a threshold. **`POST /v1/media/sync` and `POST /posts/sync`, which
already loop up to `MAX_PER_PASS=50` inline (`posts/router.py:203-218`), must be
converted to jobs precisely because they are single-tenant bursts.**

### 3.5 PostgreSQL connection budget — corrected

```
usable      = 0.8 * max_connections          # 20% reserved for admin/maintenance
target      = 0.7 * usable                    # headroom for migration/lock spikes
per_process = floor(target / total_processes)
```

With `max_connections = 83` (**unverified**), `target = 46`:

| Topology | Processes | `per_process` | `DB_POOL_SIZE` | `MAX_OVERFLOW` | Total |
|---|---|---|---|---|---|
| Prod today | 3 | 15 | 8 | 7 | 45 |
| Prod + 3 workers | 6 | 7 | 4 | 3 | 42 |
| Prod + 6 workers | 10 | 4 | 3 | 1 | 40 |

v1's "5 + 5 = 10 per process" would have produced **60 connections against a target of
46** for the 6-process case. Corrected above.

Two consequences:

1. **Connection cost per concurrent job.** Each handler holds one session for the
   duration of its `await`s. `per_process / 1` is therefore the hard cap on concurrent
   handlers per replica, *independent of partition count*. At 4+3=7, **7 partitions is
   the per-replica ceiling**, not 24. This is a genuine new constraint v1 did not
   identify: **partitions must exceed `replicas × DB_POOL_SIZE`** or replicas idle.
2. **Holding a session across an external `await` is what forces the big pool.** The
   comment at `config.py:6-7` justifies `DB_POOL_SIZE=50` with *"workers hold sessions
   across network calls"*. §4.1's claim must therefore be enforced in code — open the
   session, load the job, **close it**, run the handler, open a new session to record the
   outcome. Two short sessions per job instead of one long one. That change is what
   makes a small pool viable, and it is why v1's pool recommendation was both too large
   and internally contradictory.

Add to `validate_production_settings()` (`config.py:212-242`): compute
`processes × (DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW)` and fail startup if it exceeds the
computed target, logging the arithmetic.

### 3.6 Load-test plan that replaces every assumption

Add `tests/load/test_lane_throughput.py`, run against the compose stack, **not** the
SQLite harness:

1. **Latency baseline.** Drive `N=500` synthetic realtime jobs through a stub provider
   (no real LLM spend). Record true `T_p50`, `T_p95`, `T_p99` per job type. **Replaces
   every timing in §3.2.**
2. **Partition sweep.** For P in {1, 4, 12, 24}: measure sustained throughput and p95
   queue age. Confirms linear scaling to partition count and locates the knee.
3. **Concurrency vs pool.** Fix P=24, vary `DB_POOL_SIZE` in {3, 5, 8, 12}. Confirms
   the §3.5 ceiling empirically.
4. **Fairness.** 10 tenants at 9× the mean rate, plus a low-priority stream. Assert no
   tenant exceeds its cap and low-priority jobs are served within their SLO.
5. **Head-of-line.** One tenant issues a 50-job burst; assert other tenants' p95 is
   unchanged.
6. **Backpressure.** Submit 10× capacity. Assert `429` with `retry_after_ms` rather than
   unbounded queue growth.

Until (1) and (2) report, **every partition count in this document is a hypothesis, not
a design decision.** Re-run this before growth, not after.

### 3.7 LLM and provider limits

No provider rate limit is configurable anywhere in the repo (verified: nothing in
`config.py:112-189`; `providers/instagram.py:475-492` reads Meta's
`content_publishing_limit` for display only and never consults it before publishing).
Add `META_GRAPH_RPS`, `LOCALITH_RPS`, `LLM_RPS_PER_TENANT`, all defaulting to values
below the provider's documented ceiling. The existing `PLAN_MESSAGE_LIMITS`
(`config.py:189`) is a monthly billing quota and is **not** a rate limit — do not
conflate them.

`billing/budget.py` already gates spend but fails open on Redis outage
(`:127-129`) and prices unknown models at zero (`:54`). Both must be fixed before the
job system routes LLM traffic through it at volume.

### 3.8 Blocking

**Does not block production.** Provisioning, schema and dispatch are unaffected. It
blocks *capacity planning*, and specifically blocks any decision to scale replicas
before test (3) confirms the DB-pool ceiling.

---

## 4. Scheduling and fairness

### 4.1 The defect

v1 §D.4 stated jobs are ordered by `(priority, next_run_at, created_at)` and that
aging is `effective = max(1, priority - age_minutes)`. Two problems:

1. **The ordering is unenforceable.** A partitioned Kafka topic serves records in
   *publication* order per partition. Once a job is on a topic, no consumer re-orders it.
   Priority expressed as a column is therefore decoration unless the selection happens
   *before* publication.
2. **The aging formula mixes units** — subtracting minutes from a 0–100 priority
   points score — with no stated divisor and no statement of what it should achieve.

v1 also left "how does a job become eligible again after backoff" unanswered. If the
consumer simply receives a record and the job is not yet due, it must either block or
redeliver. v1 implied neither.

### 4.2 Correction — two-phase: Postgres selects, Kafka only signals

```
Phase 1 (SELECTION — sweeper, Postgres decides what is eligible)
Phase 2 (SIGNAL    — outbox -> Kafka -> consumer claims an already-selected job)
```

This is the same shape the RAG system already uses with `BLPOP` as a wake-up hint
(`rag/jobs.py:80-109`), generalised.

**Phase 1 — the sweeper.** Every lane runs a sweeper loop (advisory-lock guarded so
exactly one replica does this per lane):

```sql
WITH due AS (
    SELECT id FROM jobs
    WHERE status IN ('queued', 'retrying', 'blocked')
      AND next_run_at <= now()
      AND dispatched_at IS NULL
    ORDER BY <effective_priority> ASC, next_run_at ASC, created_at ASC
    LIMIT $batch
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs SET status = 'queued', dispatched_at = now()
FROM due WHERE jobs.id = due.id
RETURNING jobs.id, jobs.lane;
```
then, **in the same transaction**, one `event_outbox` row per returned id on
`<lane>-dispatch`.

`FOR UPDATE SKIP LOCKED` is what makes multiple dispatchers safe: each sweeper
transaction takes a disjoint set of rows.

This also answers the missing piece: **retry is not "requeue the same job".** A retried
job stays `retrying` with a future `next_run_at`; it is simply not selected until due.
The consumer never waits on a job.

**Aging — made explicit.** Age is measured in priority points, with a stated divisor:

```
effective_priority = greatest(0, priority - floor(age_seconds / AGING_DIVISOR_SECONDS))
```

`AGING_DIVISOR_SECONDS = 300` (default). A bulk job at priority 100 therefore reaches
effective priority 0 after 50 minutes of waiting. With priority bands
`realtime=0..20`, `publishing=20..40`, `media=40..60`, `bulk=60..100`, this means a bulk
job is promoted into the realtime band after ~67 minutes — long enough to protect
latency, short enough that nothing starves.

Anti-starvation is guaranteed twice over: aging inside a lane, and lane isolation
across lanes.

### 4.3 Lease reaper

Independent loop, 30s:

```sql
WITH stale AS (
    SELECT id FROM jobs
    WHERE status = 'running' AND lease_expires_at < now()
    ORDER BY lease_expires_at
    LIMIT $batch
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs
SET status = 'retrying', attempts = attempts + 1,
    next_run_at = now(), lease_owner = NULL, lease_expires_at = NULL
FROM stale WHERE jobs.id = stale.id
RETURNING jobs.id;
```

If `attempts` now exceeds `max_attempts`, transition to `dead` **in the same
transaction** (§5). A crashed worker is therefore recovered without operator action,
and a poison job still terminates.

### 4.4 The claim — atomic, and the authority for fairness

One statement. It is the only place a job starts running:

```sql
UPDATE jobs
SET status = 'running',
    started_at = now(),
    lease_owner = $worker_id,
    lease_expires_at = now() + make_interval(secs => $lease_seconds),
    attempts = attempts + 1
WHERE id = $job_id
  AND status = 'queued'
  AND next_run_at <= now()
  AND (
    SELECT count(*) FROM jobs j2
    WHERE j2.tenant_id = jobs.tenant_id
      AND j2.status = 'running'
  ) < $max_tenant_inflight
RETURNING *;
```

Correctness properties:

- **Atomic across workers and dispatchers.** A single statement under MVCC. Zero rows
  returned means the job was claimed, cancelled, or is not yet due — the consumer
  commits the offset and moves on. No `SELECT` then `UPDATE` race exists.
- **The per-tenant cap is enforced by the database**, not Redis. This matters: v1 put
  in-flight caps in Redis, which is not durable and whose failure mode (v1 §G3, Redis
  outage) is fail-open — so the cap would silently vanish exactly when load is highest.
  The subquery is evaluated against the same snapshot as the outer `UPDATE`, so it
  cannot observe a stale count.
- **Cost.** The correlated `count(*)` needs `CREATE INDEX ix_jobs_tenant_running ON
  jobs (tenant_id) WHERE status = 'running'`. This is the **first `postgresql_where`
  index in this repo** (verified: zero precedent across 77 migrations). It is untestable
  under the SQLite harness (`tests/conftest.py:36-42` uses `create_all`), so the claim
  path needs an integration test, not a unit test.

`attempts = attempts + 1` happens **at claim**, not at failure — so a job killed
mid-handler still counts its attempt and cannot loop forever.

### 4.5 Provider-blocked jobs

On HTTP 429 or provider throttle, the handler writes `status='blocked'` with
`next_run_at` derived from `Retry-After` (falling back to exponential backoff with
full jitter). `blocked` is **not** selected by the sweeper until `next_run_at <= now()`,
so a blocked job occupies no consumer and consumes no attempt beyond the one already
counted.

This is a real behaviour change from today, where a Meta 429 **permanently drops the
message** — `channels/meta/consumer.py:586-604` writes `status="failed"` and returns,
and `followup_worker.py:207-214` does the same for follow-ups. Verified: there is no
429 handling anywhere in the repo.

### 4.6 Ordering guard for `publishing`

Kafka's per-key ordering is necessary but not sufficient for scheduled posts, because
§6 shows it does not survive partition expansion and is not guaranteed across a
redelivery. For `publishing` jobs with a `subject_id`, add to the claim predicate:

```sql
AND NOT EXISTS (
    SELECT 1 FROM jobs p
    WHERE p.subject_type = jobs.subject_type
      AND p.subject_id   = jobs.subject_id
      AND p.status IN ('queued', 'running', 'retrying')
      AND p.priority_order < jobs.priority_order
)
```

where `priority_order` is a monotonic sequence (`scheduled_on`, or `created_at` for
ad-hoc). This is a **best-effort** guard: it can stall if an earlier job is stuck, so
it is paired with the lease reaper, which unblocks it within `lease_seconds`. A
permanent stall is impossible because a job in `running` is always reaped and a job in
`retrying` always reaches `dead`.

**This guard is the real ordering guarantee. Kafka's ordering is an optimisation that
avoids most contention, not the mechanism that prevents out-of-order publishes.**

### 4.7 Tests and blocking

`G20` — two dispatchers, overlapping sweeps: assert no job is dispatched twice and none
is skipped. `G21` — 200 jobs, 4 consumers: assert `max_tenant_inflight` never exceeded.
`G22` — continuous priority-0 stream plus low-priority jobs: assert aging promotes them
within the stated window. `G23` — provider returns 429 with `Retry-After: 60`: assert
`blocked`, no further attempts, released at +60s. `G24` — earlier subject job stuck in
`running`: assert later job waits, then proceeds after the reaper.

**Does not block production**, except §4.4's atomic claim, which is a prerequisite for
correct start-once semantics and **does** block the job runtime from accepting traffic.

---

## 5. Dead-letter durability

### 5.1 The defect

v1 §C.5 said attempts beyond `max_attempts` → `dead`, *"plus a row on `<lane>-dlq`
carrying the full job snapshot for operator replay"*.

Two failures:

1. **It contradicts the stated authority model.** If the DLQ topic is the record of
   terminal failure, then Kafka is a second source of truth — precisely what the
   constraint forbids, and the failure Kafka was introduced to avoid.
2. **It fails when it is needed.** If Kafka is down when a job dies, the DLQ write
   fails. Worse, if the process crashes between `UPDATE jobs SET status='dead'` and the
   DLQ `send`, the job is dead in Postgres and invisible in the DLQ — the worst of both.

### 5.2 Correction — `dead` is a Postgres state; the DLQ topic is a convenience

There is no durable DLQ. `jobs.status = 'dead'` **is** the dead-letter record.

```
BEGIN                                    -- one transaction, in the lane consumer
  UPDATE jobs SET
      status='dead',
      error_code=$err_code,
      last_error=$err_text,
      dead_at=now(),
      lease_owner=NULL, lease_expires_at=NULL
  WHERE id=$job_id;
  INSERT INTO job_attempts (job_id, attempt_no, error_code, error_text, started_at, finished_at)
  VALUES ($job_id, $attempt, $err_code, $err_text, $started, now());
  -- Only if operators must be told, and only through the outbox, which is durable:
  INSERT INTO event_outbox (event_type='job.dead', payload={"job_id":...}, topic='ops-events', ...)
COMMIT
```

`job_attempts` is a new append-only table. It is written **only** for failed attempts
and the terminal transition, not for every success — otherwise the write amplification
under the §3.6 load test would be significant. It preserves the original failure text
across a later successful replay, which `jobs.last_error` alone cannot: a replay that
succeeds must not erase why it first failed.

### 5.3 Replay

```
BEGIN
  UPDATE jobs SET status='queued', attempts=0, error_code=NULL,
                 last_error=NULL, dead_at=NULL,
                 dispatched_at=NULL, next_run_at=now()
  WHERE id=$job_id AND status IN ('dead','failed');
  INSERT INTO event_outbox (event_type='job.dispatch', payload={"job_id":...}, topic=...)
COMMIT
```

Replay is an ordinary job submission through the same durable path. **If Kafka is down,
the replay is still recorded and dispatches when Kafka returns** — which is precisely
what a Kafka-based DLQ could not do.

`job_attempts` is never cleared by replay, so the operator sees the full history.

### 5.4 Operator surface does not depend on Kafka

`GET /api/v1/admin/jobs?status=dead` is a Postgres query. This retires the ad-hoc
failure scan at `admin/service.py:426-441`, which today reads only outbox and
`IngestJob` — meaning `LocationPost`, `LocationMedia` and `ReviewReply` failures are
invisible there today.

### 5.5 Crash windows

| Window | Outcome |
|---|---|
| Crash before COMMIT | Job still `running`; lease reaper requeues. No partial state |
| Crash after COMMIT, before Kafka commit | Job is `dead`; record redelivered; handler re-runs and re-fails idempotently; harmless |
| Crash during replay tx | Neither applied; retry the replay |
| Kafka down at terminal write | Outbox holds the `ops-events` row; delivered on recovery. Job is `dead` regardless |
| Postgres unavailable | Nothing commits; Kafka record uncommitted; redelivered on reconnect |

### 5.6 Tests and blocking

`G25` — kill between the `dead` UPDATE and the Kafka commit; assert job is `dead`,
record redelivered, no duplicate `job_attempts` row. `G26` — Kafka down throughout a
terminal failure; assert job is `dead` and the ops outbox row survives. `G27` — replay a
dead job that succeeds; assert `job_attempts` still shows the original failure and
`jobs.last_error` is cleared.

**BLOCKS PRODUCTION.** A DLQ that fails during a Kafka outage loses exactly the failures
an operator most needs to see.

---

## 6. Partition expansion and ordering

### 6.1 The defect — v1's central claim was wrong

v1 §D.3 stated: *"`lane_key` is stored on the job so a replay uses the identical key and
therefore the identical partition."* And v1 §D.1 proposed raising `review-events` and
`meta-events` from 1 partition to 6 and 12.

The second half of that claim is **false**, and v1 stated the opposite:

```python
idx = murmur2(key); idx &= 0x7FFFFFFF; idx %= len(all_partitions)
```

Partition count is **in the modulus**. Key *K* maps to `murmur2(K) % 1 = 0` before an
expansion and `murmur2(K) % 12` after. **The same key moves to a different partition.**

What `lane_key` *does* guarantee, precisely:

- For a **single dispatch event**, the producer computes the partition once and it is
  fixed for that record's life.
- For a **duplicate dispatch of the same job** (outbox replay, §1.4 window 3), both
  records land on the **same** partition *at the current partition count*, because the
  key and the count are both unchanged.

What it does **not** guarantee: that a key's partition is stable **across** a partition
count change.

### 6.2 What breaks on expansion

| Property | Before | After expansion |
|---|---|---|
| Per-key partition stability | yes | **no** |
| Per-key ordering across the expansion boundary | yes | **broken** — pre-expansion records sit on old partitions, post-expansion on new ones, and different consumers own them |
| Record preservation | yes | yes — no data movement; new partitions start empty |

So the ordering that v1 relied on is lost **at the expansion instant**, permanently for
records already written.

### 6.3 Correction — order-bearing topics are provisioned at final count, from birth

The clean fix is to never need an expansion where ordering matters:

| Topic | Created | Expansion needed? | Ordering requirement |
|---|---|---|---|
| `realtime-dispatch` | new, explicit 24 | no | per-tenant |
| `publishing-dispatch` | new, explicit 12 | no | per-listing |
| `media-dispatch`, `bulk-dispatch` | new, explicit 6 | no | none |
| `review-events` | auto-created at 1 | yes, 1→6 | **none** — review enrichment is per-review and order-independent |
| `meta-events` | auto-created at 1 | yes, 1→12 | **per-tenant, today** — see §6.4 |

**Every order-bearing topic is new and provisioned at its final count. So expansion is
never required for a lane with an ordering requirement.** That dissolves the problem
rather than mitigating it.

`disable auto-create` (§D.1) is what enforces this — otherwise a typo creates a 1-partition
topic and reintroduces it.

### 6.4 `meta-events` is the one real regression risk

Keyed by `tenant_id` at 1 partition, `meta-events` currently gives **per-tenant ordering
of inbound messages** — the strongest ordering property the system has today. Expanding
to 12 partitions breaks it.

Whether that breaks behaviour depends on a claim that **must be verified before the
expansion**, not assumed:

- `_generate_reply` (`channels/meta/consumer.py:202-262`) reads a 10-message history.
  If that history is fetched from the **provider** rather than built from consumed
  Kafka records, ordering does not matter and expansion is safe.
  **This needs a source-level check on `followup_worker.py:105-122` and the handler
  body before proceeding.** If history is built from locally-consumed records, then
  expand **only after** verifying the provider-read path.

Mitigations available if the check fails:
- Keep `meta-events` at 1–3 partitions for now; scaling that lane is a separate change.
- Or move history to provider-read first, then expand.

Expansion of a 1-partition topic is otherwise low-risk: no data movement, no re-keying
of existing records, only a rebalance.

### 6.5 Safe expansion procedure

1. Record consumer lag for the topic; require **lag = 0** on every partition.
2. **Pause the sweeper** for that lane (advisory-lock flag) so nothing new is published.
3. Stop lane consumers gracefully — `workers/main.py:119-130` cancels tasks; add the
   missing `await asyncio.gather(*tasks, return_exceptions=True)` (§B.3) so in-flight
   commits finish.
4. Confirm lag is still 0. Any non-zero means a consumer died mid-record — drain before
   continuing.
5. Increase the partition count via `AIOAdminClient`.
6. Restart consumers. A rolling rebalance follows.
7. Re-enable the sweeper.

**Rollback is not a partition decrease** — Kafka does not support it. Rolling back means
restoring the previous deployment, which works only because the schema is additive.
If the new partition count causes trouble, raise it again (safe) rather than reducing it.

### 6.6 Ordering is not the mechanism that prevents bad publishes

§4.6's subject-level guard is. It holds across expansion, across redelivery, and
across a `--scale` change, because it is a database predicate and not a Kafka property.
`lane_key` is retained — it keeps duplicate dispatches on one partition and reduces
contention — but it is an optimisation, not a correctness mechanism, and the plan no
longer claims otherwise.

### 6.7 Tests and blocking

`G28` — assert the partition for a given `lane_key` is stable across duplicate dispatches
at a fixed partition count. `G29` — expand a test topic 1→6 while jobs are flowing;
assert no job is lost and that ordering violations are bounded to the expansion window.
`G30` — run the §4.6 subject guard with a deliberately stuck earlier job; assert
`location_posts` never publishes out of `scheduled_on` order.

**BLOCKS PRODUCTION** for `publishing` — because §6.1 invalidates v1's stated ordering
guarantee and §4.6 must exist before the first scheduled post is migrated.

---

## 7. Corrected implementation plan

Differs from v1 in the marked places.

### Phase 0 — foundations (additive, no behaviour change)

| # | Item | Note |
|---|---|---|
| 0.1 | Repair `alembic/env.py` model imports | Prerequisite — `--autogenerate` is currently unsafe |
| 0.2 | Migration `jobs` + `job_attempts`, `down_revision="d8e0f2a4c6b8"` | New: `dispatched_at`; **removed**: `accepted` from the enum |
| 0.3 | `CREATE INDEX ix_jobs_tenant_running ON jobs (tenant_id) WHERE status='running'` | **First partial index in the repo**; needs an integration test, not unit |
| 0.4 | Topic provisioning (`AIOAdminClient`), explicit counts from §3.3 | Disable auto-create in both compose files |
| 0.5 | Outbox `FOR UPDATE SKIP LOCKED` + claim (S5) | |
| 0.6 | Producer: `acks="all"`, `enable_idempotence=True`, `linger_ms=5`, gzip, singleton `asyncio.Lock` (S4) | |
| 0.7 | R3 — stop marking failures `sent` in the DB-drain fallback | |
| 0.8 | R4 — per-lane Kafka availability + background prober | |

### Phase 1 — reliability

| # | Item | Note |
|---|---|---|
| 1.1 | Idempotency keys for `review-events` / `meta-events` handlers | **Must precede 1.2** |
| 1.2 | Manual offset commit, one in-flight record per partition (§2) | **The blocker.** Sequence is DB commit → then Kafka commit, never the reverse |
| 1.3 | `max_poll_interval_ms` per lane (§2.4) | |
| 1.4 | `enqueue_event_in(db, ...)`; migrate call sites module by module (R2) | |
| 1.5 | Unique indexes on `platform_message_id` / `platform_comment_id` (R2b) | |
| 1.6 | 429 handling: Meta sends and publishes → `blocked`, honour `Retry-After` | Closes the silent-drop bug at `consumer.py:586-604` |

### Phase 2 — job runtime

| # | Item | Note |
|---|---|---|
| 2.1 | `jobs` service: submit (one tx), claim (§4.4), complete, retry, dead (§5.2), replay (§5.3) | |
| 2.2 | Sweeper per lane, `FOR UPDATE SKIP LOCKED`, aging divisor (§4.2) | |
| 2.3 | Dispatch watchdog on `dispatched_at IS NULL` (§1.3) | |
| 2.4 | Lease reaper (§4.3) | |
| 2.5 | Lane consumer: one-in-flight-per-partition, explicit `commit({tp: offset+1})` (§2.2) | **No concurrency pool setting exists** |
| 2.6 | Handler timeout via `asyncio.wait_for` | Mandatory — it bounds the §2.5 stall |
| 2.7 | Media lane handlers offload CPU work off the event loop (§2.6) | |
| 2.8 | Migrate `stt.job` first — no external side effects | |
| 2.9 | Migrate `ingest_jobs` + `scrape_jobs`; re-home the RAG worker out of the API process | |

### Phase 3 — side-effecting lanes

| # | Item | Note |
|---|---|---|
| 3.1 | `external_intent` written **before** the call; reconciliation query on retry | §v1 C.6 |
| 3.2 | Subject ordering guard (§4.6) | **Blocks `publishing`** |
| 3.3 | Migrate `location_posts` / `location_media` | Highest risk |
| 3.4 | `realtime` lane: AI replies, customer DMs | |

### Phase 4 — measurement

| # | Item |
|---|---|
| 4.1 | Run the §3.6 load test; replace every §3.2 assumption with measurements |
| 4.2 | Re-tune partition counts and `max_tenant_inflight` from real data |
| 4.3 | Only then evaluate scaling replicas beyond the §3.5 DB-pool ceiling |

### Explicitly removed from v1

`accepted` state and its reconciler · `max_poll_records=1` as an ordering control ·
per-lane `concurrency` settings · Kafka-based DLQ as the record of terminal failure ·
`lane_key` as a cross-expansion ordering guarantee · `"optional, recommended"` on
`Idempotency-Key` · the unsourced 24/12/6 partition counts.

### Revised file list

Adds to v1 §H.1: `jobs/attempts.py` (models for `job_attempts`), `jobs/sweeper.py`,
`jobs/watchdog.py`. §4.2's sweeper subsumes v1's `reaper.py`; §1.3's watchdog is new.

---

## 8. Deployment decision

| Item | Production-blocking? |
|---|---|
| §2 one-in-flight-per-partition + commit-after-DB | **Yes** |
| §5 `dead` in Postgres, replay via outbox | **Yes** |
| §6 order-bearing topics provisioned at final count + §4.6 subject guard | **Yes**, for `publishing` |
| §4.4 atomic claim with DB-side tenant cap | **Yes**, before the job runtime takes traffic |
| §1 `accepted` removal + `dispatched_at` + watchdog | No |
| §3 capacity model + load test | No — blocks capacity planning, not release |
| §6.4 `meta-events` history-source verification | **Yes**, before that topic is expanded |

Three blocking items, all in the job runtime and all cheap. None require a new
infrastructure decision, a new broker, or a migration that cannot be rolled back
additively. The architecture is sound; v1's *presentation* of three of its guarantees
was not.