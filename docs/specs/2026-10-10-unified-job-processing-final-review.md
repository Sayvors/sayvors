# Unified Job Processing — Final Corrections (Round 2)

Date: 2026-10-10
Reviews: `2026-10-10-unified-job-processing-design.md` (v1),
`2026-10-10-unified-job-processing-review.md` (v2)
Status: design only — no code, no migrations
Verdict on v2: **two claims were wrong and are retracted** (§2.3, §6.1). Five further
gaps were underspecified. All six are corrected below.

---

## 1. Dispatch watchdog — resolving the `dispatched_at` contradiction

### 1.1 The defect

v2 defined the same column twice, incompatibly:

| Location | Claim |
|---|---|
| §1.3 | `dispatched_at` — *"set by the lane consumer on first claim"* |
| §4.2 | sweeper predicate `dispatched_at IS NULL`, and `SET dispatched_at = now()` at dispatch time |

If the sweeper sets it, the consumer must not — and the §1.3 wording would make the
consumer set it on a job the sweeper had already stamped, so `dispatched_at IS NULL`
stops matching and the job is never re-dispatched.

Underneath that is a worse semantic problem. The sweeper cannot set a field meaning
"dispatched" when it has only written an outbox row. Publication to Kafka happens later,
asynchronously, via the outbox drainer. So `dispatched_at` at sweeper-time means
*"an outbox row exists"*, not *"a message is in Kafka"* — and it is set before the fact
it claims.

Two concrete holes follow:

- **Outbox row dies.** `mark_failed` sets `status='dead'` after `MAX_RETRIES=10`
  (`outbox/service.py:83-107`). No message is ever published. `dispatched_at` is
  already set, so no watchdog predicate ever matches. The job is `queued` forever.
- **Broker loses the message.** `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1`
  (`docker-compose.yml:50`) with a single-node broker. Acknowledged, then gone with the
  disk. Same permanent orphan.

### 1.2 Correction — a visibility timeout, not a boolean

Replace `dispatched_at` with three fields that separate *intent*, *dispatch* and
*claim*:

```sql
dispatch_attempts   INT         NOT NULL DEFAULT 0
last_dispatched_at  TIMESTAMPTZ NULL     -- outbox row written; NOT a delivery receipt
claimed_at          TIMESTAMPTZ NULL     -- consumer won the claim (§4)
```

**Exactly one writer for each:**

| Field | Written by | When | Transaction |
|---|---|---|---|
| `last_dispatched_at`, `dispatch_attempts` | Sweeper only | When it creates the outbox row | Sweeper's tx, with the outbox insert |
| `claimed_at` | Lane consumer only | Inside the winning claim | Claim tx |

The consumer **never** touches `last_dispatched_at`. That is the contradiction resolved.

### 1.3 Selection predicate

```sql
WITH due AS (
    SELECT id FROM jobs
    WHERE status = 'queued'
      AND next_run_at <= now()
      AND (last_dispatched_at IS NULL
           OR last_dispatched_at < now() - make_interval(secs => $visibility_seconds))
    ORDER BY <effective_priority>, next_run_at, created_at
    LIMIT $batch
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs
SET status = 'queued',
    last_dispatched_at = now(),
    dispatch_attempts = dispatch_attempts + 1
FROM due WHERE jobs.id = due.id
RETURNING jobs.id, jobs.lane;
```
followed, **in the same transaction**, by one `event_outbox` row per returned id.

This is the SQS visibility-timeout pattern. It is self-correcting because a failed
dispatch simply fails to be claimed, and the timeout then expires.

### 1.4 Why the timeout can be generous

`visibility_seconds` is **not** a latency SLO. A duplicate dispatch is harmless (§1.5),
so the only cost of a long timeout is delayed repair of a genuinely lost message. Kafka
retention (7 days default) is the real recovery window for a message that *is* present.
Set `visibility_seconds = 1800` (30 min) for all lanes; lower only if operator
complaints justify it.

### 1.5 Why duplicate dispatch is harmless — three layers

1. **Same key ⇒ same partition.** The duplicate outbox row carries the identical
   `{"job_id": ...}` and therefore the identical Kafka key. At an unchanged partition
   count, `murmur2(key) % N` is identical, so both records are ordered in one partition.
2. **The claim is atomic and single-winner.** `UPDATE ... WHERE status='queued'`
   (§4.1). The second consumer to see the duplicate gets zero rows and commits its
   offset. The handler never runs twice.
3. **Handlers are idempotent regardless** (§5).

Layer 2 is the one that matters and it does not depend on layers 1 and 3. A duplicate
is harmless even if it lands in a different partition, because the claim is the
serialisation point.

### 1.6 Liveness: a dispatch that can never succeed must not loop

If no consumer is running for a lane, or the topic has no partitions, the sweeper would
redispatch forever. Bounded by:

```sql
IF dispatch_attempts >= $max_dispatch_attempts THEN
    status = 'failed', error_code = 'never_dispatched'
```

This is a **liveness detector for "no worker is serving this lane"** — a failure mode
that is currently invisible, because `workers/main.py:90-99` starts every loop and
nothing reports when one silently dies. `never_dispatched` in the admin job view is the
signal.

`failed` (not `dead`): no attempt was ever made, so this is an operational fault rather
than a poison job, and it must be replayable without an operator override.

### 1.7 Failure-window test

`G31` — dispatch visibility timeout:
```
t0  sweeper dispatches J (last_dispatched_at=t0, dispatch_attempts=1)
t1  stop the lane consumer entirely
t2  advance last_dispatched_at past visibility_seconds
t3  sweeper runs again -> dispatch_attempts=2, new outbox row
t4  restart the consumer -> J claimed once, claimed_at set
assert J.attempts == 1              (handler ran exactly once)
assert J.dispatch_attempts >= 2     (redispatch happened)
```

`G32` — dead outbox row repair: force `mark_failed` on a `job.dispatch` row until
`status='dead'`; assert the sweeper still re-dispatches at the visibility timeout and the
job completes. **This is the case v2's watchdog could not see.**

`G33` — `never_dispatched`: run the sweeper with no consumer for a lane; assert the job
reaches `failed` with `error_code='never_dispatched'` within
`max_dispatch_attempts × visibility_seconds`.

**Migration/rollout:** three columns replace one. No backfill needed — all existing
rows are new. Ships in the Phase 0 migration.

---

## 2. Tenant concurrency cap — v2's proof was wrong, and is retracted

### 2.1 The retraction

v2 §4.4 claimed the correlated `count(*)` was safe because it *"is evaluated against the
same snapshot as the outer `UPDATE`, so it cannot observe a stale count."*

**That is incorrect.** `engine` is created with no `isolation_level`
(`app/database.py:8-16`), so the session runs at PostgreSQL's default **READ COMMITTED**.
Under READ COMMITTED each *statement* takes its snapshot at statement start. Two
concurrent claim transactions for the same tenant both observe `count = 2`, both evaluate
`2 < 3` as true, and both update — leaving `count = 4`.

The subquery is a plain aggregate over `jobs`. The outer `UPDATE` locks only the *target
job row*, which differs between the two transactions, so the two locks do not conflict
and nothing serialises them. Atomicity of a single statement guarantees each statement
is not torn; it does **not** make a multi-statement-invariant check safe.

### 2.2 Correction — a transaction-scoped advisory lock as the critical section

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';

SELECT pg_advisory_xact_lock($1);          -- $1: int64, hashed in Python (see §2.5)

SELECT count(*) FROM jobs
 WHERE tenant_id = $2 AND status = 'running';

-- if count < cap:
UPDATE jobs
   SET status = 'running', claimed_at = now(),
       lease_owner = $3, lease_expires_at = now() + make_interval(secs => $4),
       attempts = attempts + 1
 WHERE id = $5 AND status = 'queued' AND next_run_at <= now()
RETURNING *;
COMMIT;
```

**Why this is correct.** `pg_advisory_xact_lock` is a *mutual exclusion primitive*. For
a fixed tenant, at most one transaction can be inside the critical section, so the
`count(*)` and the `UPDATE` are serialised with respect to each other. Tenant A's
critical section does not block tenant B's, because the lock key differs. There is no
window in which two transactions read the same count and both proceed.

**Why the lock is taken first.** Lock acquisition order is fixed — advisory lock, then
job rows. With only one advisory lock per transaction there is no cycle, so no deadlock.

**Why `pg_advisory_xact_lock` and not the repo's `take_lock`.**
`scheduling/__init__.py:41-47` uses **session**-scoped `pg_advisory_lock` /
`pg_try_advisory_lock` with an explicit `release_lock`. Two problems for this use:

- A session-scoped lock survives `COMMIT`. If `release_lock` is skipped or the code path
  raises, the lock is held until the pooled connection is *closed* — not returned. With
  `pool_pre_ping=True` and a long-lived pool that is a long outage. Transaction-scoped
  release cannot leak.
- The caller's savepoint discipline (`scheduling/__init__.py:67-78`, documented against
  `MissingGreenlet`) must be preserved; that lesson transfers even though the primitive
  changes.

**The alternative, and why it is not primary.** A `tenant_job_slots` counter row with

```sql
UPDATE tenant_job_slots SET running = running + 1
 WHERE tenant_id = $1 AND running < $cap RETURNING running;
```

is a single round-trip and *is* correct under READ COMMITTED — a blocked `UPDATE`
re-evaluates its predicate against the new row version (EvalPlanQual), unlike a
subquery. But it drifts: a worker that crashes between increment and decrement
throttles the tenant permanently until reconciled. It is the right optimisation if the
extra round-trip ever measures; it is the wrong default.

**On lock acquisition failure.** `lock_timeout` expiry raises `LockNotAvailable`. The
claim then **fails closed**: no job is started, the consumer commits the offset, and the
sweeper re-dispatches after the visibility timeout. It must *not* fall back to an
unlocked claim. A 5 s timeout against a ~1 ms critical section means this is
pathological; if it fires routinely, the invariant is already broken and failing closed
is the correct response.

### 2.3 Real PostgreSQL concurrency test

The SQLite harness (`tests/conftest.py:36-42`) serialises all writes and **cannot**
detect this race. A passing unit test here would be a false positive. Required:

`tests/integration/test_tenant_cap.py` — real Postgres, marked `integration`, skipped by
default:

1. **Negative control.** Create a tenant, `max_tenant_inflight = 3`, submit 50 jobs.
   Claim them from **50 concurrent connections** via `asyncio.gather`, each opening its
   own session. Assert `max_concurrent_running <= 3` **with the advisory lock removed**.
   **This test must fail.** If it passes, the test is not exercising concurrency.
2. **Positive control.** Same setup, advisory lock present. Assert
   `max_concurrent_running <= 3` and `total_claimed == 50`.
3. **No cross-tenant interference.** Two tenants, cap 3 each, 40 concurrent claims.
   Assert both reach exactly 3 and the wall-clock is materially below the serial time —
   proving the lock is per-tenant, not global.
4. **Fencing.** Kill a claim transaction after it holds the lock. Assert the lock is
   released (a second claim for the same tenant succeeds) — the transaction-scope
   guarantee.
5. **Lock timeout.** Hold the advisory lock from a separate connection for 10 s; assert
   the claim raises, starts no job, and does not fall back.

Tests 1 and 2 together are the only honest evidence; a single passing test is not.

### 2.4 Measurement, not assertion

Expose live concurrency from the engine's own pool (`engine.pool.checkedout()`,
`.size()`, `.overflow()`) plus
`SELECT count(*) FROM jobs WHERE status='running' GROUP BY lane` via the partial index
from §2.6. Assert `running <= cap` continuously in the integration suite, and alert on
`running > cap` in staging — the advisory lock makes it a code bug, not a tuning
matter.

### 2.5 Key hashing — do not reuse `hashtext`

`scheduling/__init__.py:45` builds its lock key with `hashtext(namespace || key)`.
`hashtext` is an **undocumented internal** function whose output is not guaranteed
stable across PostgreSQL major versions. An upgrade could silently change the meaning of
every existing advisory lock namespace, including the publish locks.

For the new tenant lock, hash in Python and pass a signed 64-bit integer:

```python
import hashlib
lock_id = int.from_bytes(hashlib.blake2b(f"job-claim:{tenant_id}".encode(),
                                          digest_size=8).digest(), "big", signed=True)
```

Flagged for a separate ticket: the existing `hashtext` usage should migrate too.

### 2.6 Index

```sql
CREATE INDEX ix_jobs_tenant_running ON jobs (tenant_id) WHERE status = 'running';
```

**First `postgresql_where` index in this repo** (verified: zero precedent across 77
migrations). Without it the correlated count is a sequential scan per claim. It cannot
be exercised by the SQLite harness — the integration test in §2.3 is its only coverage.

**Rollout:** advisory lock needs no migration. The partial index ships in the Phase 0
migration. Deploy the index before any lane runs.

---

## 3. Ordering keys — per-tenant is over-coupled

### 3.1 The defect

v2 §D.3 keyed `realtime` by `tenant_id`, justified as *"it co-limits a tenant's jobs to
one partition, which gives per-tenant ordering for free."*

Two problems:

1. **Ordering is over-specified.** Nothing in the product requires a merchant's
   WhatsApp conversation with customer A to be ordered against their conversation with
   customer B. The real requirement is **per-conversation**.
2. **It caps tenant throughput structurally.** One tenant maps to one partition, and §2's
   one-in-flight-per-partition rule then serialises them at `1/T_p50`. A tenant with
   fifty simultaneous conversations processes them one at a time. v2's §3.4 acknowledged
   this only as a "capacity limit"; it is actually an avoidable design error.

### 3.2 Corrected keys per lane

| Lane | Ordering requirement | `lane_key` | Effect |
|---|---|---|---|
| `realtime` (messaging) | Per **conversation** | `f"{tenant_id}:{platform}:{contact_id}"` | A merchant's conversations run in parallel; each is internally ordered |
| `publishing` | Per **listing**, by `scheduled_on` | `listing_id` | Scheduled posts for one listing publish in order |
| `media` | None — assets are independent | `media_id` | Full parallelism |
| `bulk` | None | `job_id` | Full parallelism |
| review enrichment | None — per review | `review_id` | Full parallelism |

Sources verified: `channels/models.py:198-203` gives
`UniqueConstraint("tenant_id","platform","contact_id", name="uq_contact_profiles_identity")`,
so `contact_id` is a stable conversation key. `posts/models.py` carries `listing_id`.

**Review enrichment is a throughput win.** `outbox/worker.py:110` currently keys
`review-events` as `f"{event.event_type}:{payload.get('user_id', ...)}"` — per tenant.
Changing to `review_id` lets one merchant's review backlog drain in parallel.

`lane_key` is written **once, at submit**, and never recomputed. It is required for
§1.5 layer 1 and must be immutable.

### 3.3 Quota stays separate from ordering

These are now genuinely orthogonal, which v2 blurred:

- **Ordering** = the partition key. Decides which messages a consumer sees together.
- **Quota** = the advisory lock + count (§2). Decides how many of a tenant's jobs may
  run *at once*, across **all** partitions and **all** lanes.

Because `lane_key` is no longer tenant-wide, the quota is no longer a backstop for
ordering — it is the *only* thing bounding a tenant's concurrent work. That makes §2's
correctness argument load-bearing rather than defence-in-depth, and it is why the §2.3
integration test is mandatory rather than optional.

### 3.4 Ordering is no longer guaranteed by Kafka — and that is fine

With per-conversation and per-listing keys, Kafka still gives ordering within a key at
a fixed partition count. But §6 established that this breaks on expansion, so:

- The **subject-level guard** (§4.6) remains the authoritative mechanism for
  `publishing`.
- For `realtime`, the conversation guard is the same predicate with
  `subject_type='conversation'`.

Kafka ordering becomes an optimisation that reduces contention, not a correctness
guarantee. The plan should stop describing it as the latter.

### 3.5 Tests

`G34` — ordering: submit 20 jobs for one listing with `scheduled_on` ascending, assert
the domain row publishes in exactly that order with 4 concurrent workers.
`G35` — no cross-conversation blocking: one tenant with 10 conversations, assert the
10 run concurrently (not 10×`T_p50` wall-clock).
`G36` — key immutability: replay a job's dispatch after changing partition count; assert
`lane_key` unchanged.

**Rollout:** `lane_key` values are new. Existing topics change key on expansion, which
is §6.5's procedure.

---

## 4. Leases and external side effects

### 4.1 The defect

v2 specified a lease but never said: how long it is relative to handler runtime, what
happens when it expires mid-handler, or how a fenced worker is prevented from writing a
stale result. v2 §4.3's reaper unconditionally set `status='retrying'` — including for a
job whose `external_intent` was written but whose provider call may have succeeded.

### 4.2 Relationships

```
handler_timeout_seconds   per lane (realtime 120, publishing 300, media 900, bulk 3600)
lease_seconds           = handler_timeout_seconds * 1.5 + 30
heartbeat_interval      = lease_seconds / 3
```

The inequality `lease_seconds > handler_timeout_seconds` is the load-bearing one. If the
lease were shorter, the reaper would requeue a job while its handler was still running —
guaranteed double execution. If longer, a genuinely dead worker holds its job hostage for
the full lease.

**Heartbeat.** A renewal task every `lease_seconds/3`:

```sql
UPDATE jobs SET lease_expires_at = now() + make_interval(secs => $lease)
 WHERE id = $1 AND lease_owner = $2 AND status = 'running';
```

Zero rows updated means the worker has been fenced — it **must abort the handler**. The
heartbeat is defence-in-depth: `asyncio.wait_for` should already have cancelled it, but
cancellation can be delayed if a handler swallows `CancelledError` or sits in a
non-cancellable await. The heartbeat is the backstop that detects it.

### 4.3 Fencing on completion

Every terminal write carries ownership. Not the job update — also the domain projection:

```sql
-- one transaction
UPDATE jobs
   SET status = 'succeeded', result = $result, finished_at = now(),
       external_result = $external, lease_owner = NULL, lease_expires_at = NULL
 WHERE id = $1 AND lease_owner = $2 AND status = 'running';

-- only if the above returned a row:
UPDATE location_posts
   SET status = 'published', published_at = now()
 WHERE id = $subject_id AND status = 'scheduled';    -- second, independent fence
```

Zero rows from the first statement means a fenced worker. It must then **discard its
result entirely** — no domain write, no result persistence — and increment a
`fence_violation_total` counter. A slow worker that was reaped and re-executed must never
be able to overwrite the newer worker's outcome.

The domain-level predicate (`status='scheduled'`) is a second, independent fence: even if
the job fence were bypassed, the domain row cannot transition twice.

### 4.4 Intent-aware reaper — the correction that matters

```sql
UPDATE jobs SET
    status = CASE WHEN external_intent IS NOT NULL
                   AND external_result IS NULL
                  THEN 'ambiguous'      -- provider call may have succeeded
                  ELSE 'retrying' END,
    attempts = attempts + 1,
    next_run_at = now(),
    lease_owner = NULL, lease_expires_at = NULL
WHERE id IN (SELECT id FROM jobs
             WHERE status = 'running' AND lease_expires_at < now()
             FOR UPDATE SKIP LOCKED)
RETURNING id;
```

**A plain retry here can double a Google post.** If `external_intent` is set and
`external_result` is not, the worker died somewhere around the provider call and the
outcome is genuinely unknown. That is a distinct state, not a retryable failure.

`ambiguous` is a new enum value. It is:

- **not** automatically retried,
- **not** replayable by the ordinary operator endpoint — replay requires
  `force=true`, because a blind retry may double the side effect,
- surfaced in the admin job view with both the intent payload and any reconciliation
  evidence.

### 4.5 Provider action idempotency and reconciliation

| Provider | Idempotency key? | Reconciliation possible? |
|---|---|---|
| Meta Graph messaging | No | **Partly** — a returned `messages[0].id` is lost with the response |
| EmbedSocial / Localith publish | No | **No** — `publish_media_post` returns an item id we would have lost |
| Google GBP reviews (reply) | No | No |

So for the publish path the honest sequence is:

```
T1  BEGIN
    UPDATE jobs SET external_intent = {provider, operation, dedupe_key, started_at}
     WHERE id=$1 AND lease_owner=$2;
    COMMIT                                   -- durable BEFORE the call
T2  response = await provider.publish(...)   -- may succeed; response may be lost
T3  BEGIN
    UPDATE jobs SET external_result = provider_post_id(response), status='succeeded' ...
     WHERE id=$1 AND lease_owner=$2;
    UPDATE location_posts SET status='published' WHERE id=$3 AND status='scheduled';
    COMMIT
```

`services/api/app/modules/scheduling/__init__.py:107-120` already provides
`provider_post_id(response)` to extract the provider id — reusable here, and it already
handles the nested-dict shapes the adapters return.

If the worker dies between T1 and T3, the reaper (§4.4) routes to `ambiguous`. For
providers in the table above that is the correct end state: **we cannot tell, so we do
not guess.** An operator decides, or an automated reconciliation is built later for a
provider that supports lookup.

### 4.6 Order guarantees for publishing

```sql
AND NOT EXISTS (
    SELECT 1 FROM jobs p
     WHERE p.subject_type = jobs.subject_type
       AND p.subject_id   = jobs.subject_id
       AND p.status IN ('queued','running','retrying')
       AND p.priority_order < jobs.priority_order
)
```

Added to the claim in §2.2. `priority_order` is monotonic (`scheduled_on` for scheduled
posts, `created_at` for ad-hoc).

Best-effort by construction: it stalls behind an earlier job. It cannot stall forever,
because a `running` earlier job is always reaped and a `retrying` earlier job always
reaches a terminal state (`retrying`/`ambiguous`/`dead`). An earlier job in `ambiguous`
**would** stall it indefinitely — so the guard must exclude `ambiguous` from the
blocking set, and the operator resolves it. Stated explicitly because it is a real
interaction between §4.4 and §4.6.

### 4.7 Tests

`G37` — lease expiry mid-handler: handler sleeps past `lease_seconds`; assert the reaper
requeues and the original worker is fenced (result discarded, domain row untouched).
`G38` — stale completion: worker A reaped, worker B succeeds, then A finishes; assert A's
completion affects 0 rows and the domain row reads `published` from B's write only.
`G39` — ambiguous: kill between T1 and T3; assert status is `ambiguous`, not
`retrying`, and that the job is not executed twice.
`G40` — heartbeat fencing: pause the worker past `lease_seconds/3` while blocking the DB;
assert the heartbeat returns 0 rows and the handler aborts.
`G41` — ordering with an ambiguous predecessor: assert later posts do not block
indefinitely and the guard's `ambiguous` exclusion behaves as specified.

**Migration:** new enum value `ambiguous` — an `ALTER TYPE job_status ADD VALUE` in the
Phase 0 migration, or an additional migration if it must ship separately.
**Rollout:** safe to add before any lane runs.

---

## 5. Idempotency API

### 5.1 The defect

v1 §E.1 specified `Idempotency-Key` as *"(optional, recommended)"* and returned
`409 Conflict` on replay. v2 §1.5 then made it mandatory but did not change the 409.

**409 is wrong.** The client's retry *is* the recovery path — it retries precisely
because it never saw a response. Returning an error status for a successful recovery
forces every client to special-case it, and well-behaved clients that treat non-2xx as
failure will retry again, forever, never learning the job id.

### 5.2 Corrected semantics

| Situation | Response |
|---|---|
| First request, new key | `202 Accepted` + body + `Location: /api/v1/jobs/{id}` |
| Replay, same key, same payload | `200 OK` + **current** job state + header `Idempotency-Replayed: true` |
| Replay, same key, **different** payload | `422` `idempotency_key_reuse` |
| Omitted key | `202` + server-generated key in body **and** in the `Idempotency-Key` response header |
| Concurrent identical requests | One `202`, one `200` replay — see §5.4 |

### 5.3 Lost-response recovery

```
t0  client generates key K, POSTs -> response lost (timeout / navigation / crash)
t1  client retries with the SAME key K
t2  server: INSERT conflicts -> SELECT existing -> 200 + { job_id }
t3  client polls /api/v1/jobs/{job_id}
```

This closes v2 §1.4's window 2. It requires the client to generate the key **before** the
first attempt and reuse it across retries — documented, and the reason the server echoes
it back when omitted.

### 5.4 Concurrency

```python
try:
    async with session.begin():
        session.add(Job(idempotency_key=k, ...))
except IntegrityError:
    existing = await select(Job).where(Job.tenant_id == t, Job.idempotency_key == k)
    return 200, existing
```

The losing request must **not** surface a 500. `IntegrityError` is the expected outcome
of a concurrent duplicate and is a normal control path here.

### 5.5 Fingerprint

`request_fingerprint` = hash of `(job_type, canonical_json(payload))`, stored on the
job. A replay whose fingerprint differs is a client bug and returns 422 rather than
silently returning the wrong job's id. Without it, a client bug produces a job that does
something other than what the caller believes — the worst possible failure mode for an
idempotency system.

### 5.6 Scope

`UniqueConstraint("tenant_id", "idempotency_key")` — tenant-scoped, matching every
other tenant-scoped unique constraint in the repo
(`uq_contact_profiles_identity`, `uq_meta_webhook_events_dedupe`). NULL keys are
unaffected by Postgres NULL semantics; since the server now always populates a key, the
"no dedupe" case is expressed by omitting *deduplication intent*, not by NULL.

### 5.7 Tests

`G42` — replay returns 200 with the original `job_id` and never creates a second job.
`G43` — key reuse with a different payload returns 422. `G44` — omitted key: response
echoes a key that then works on replay. `G45` — 20 concurrent identical POSTs: exactly
one `202`, nineteen `200`s, exactly one job row. `G46` — cross-tenant: tenant B reusing
tenant A's key creates a separate job.

**Migration:** `idempotency_key` NOT NULL + `request_fingerprint` — ships in Phase 0.

---

## 6. Database pool and worker concurrency

### 6.1 The contradiction

| v1 §10 | v2 §3.5 |
|---|---|
| *"jobs must not hold a session across an external `await`"* | *"each handler holds one session for the duration of its awaits, so `per_process` is the hard cap on concurrent handlers"* |

Both cannot be true. v2's version was adopted while reasoning from
`config.py:6-7` — *"workers hold sessions across network calls, so size generously"* —
which described the **existing** code, not the proposed code.

### 6.2 Correction — short sessions, and v2's inference was wrong

The rule stands from v1: **no session is open across an external `await`.**

```
S1  BEGIN; SELECT job; UPDATE claim; COMMIT; close      (~2 ms)
     -- session closed --
        await handler()                                  (5 s, no session)
     -- session closed --
S2  BEGIN; UPDATE completion; UPDATE domain; COMMIT; close   (~2 ms)
```

Two short sessions per job. Fraction of a job's life holding a connection:

```
held_fraction ≈ 0.004 s / 5 s = 0.0008   (ASSUMPTION: 2 ms per statement pair)
```

Expected concurrent connections per process:

```
E[connections] = concurrent_handlers × held_fraction + loop_overhead
               = 24 × 0.0008 + ~2                                  ≈ 2.0
```

**Therefore the pool does not cap handler concurrency**, and v2's central inference
was wrong. With 24 partitions on one process, a 5-connection pool is already ample;
handlers queue on the pool for microseconds.

This is a **material correction**: it means partition count may exceed pool size without
idling replicas, which was v2's central scaling constraint and it does not exist.

### 6.3 Corrected budget

`config.py:8-9` currently sets `DB_POOL_SIZE=50`, `DB_POOL_MAX_OVERFLOW=50` —
up to 100 per process. `deploy/env.prod.example:9-10` overrides to 10+10. With 2 api
plus 1 worker that is 30, against a target of ~46 derived from `max_connections=83`
(**ASSUMPTION — confirm with `SHOW max_connections`**).

| Role | `DB_POOL_SIZE` | `MAX_OVERFLOW` | Processes | Total |
|---|---|---|---|---|
| api | 5 | 5 | 2 | 20 |
| worker | 3 | 3 | 6 | 36 |
| | | | | **56** — over the 46 target |
| **chosen** api | 4 | 4 | 2 | 16 |
| **chosen** worker | 2 | 2 | 6 | 24 |
| | | | | **40** ✓ |

`pool_size=2` for a worker running many concurrent handlers looks alarming and is correct
here, because sessions are held 0.08% of the time. The 30 s `pool_timeout`
(`config.py:10`) then supplies real backpressure rather than hanging.

Enforcement in `validate_production_settings()` (`config.py:212-242`):

```
total = (api_replicas + worker_replicas) × (DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW)
if total > 0.7 × 0.8 × max_connections: fail startup, log the arithmetic
```

Also update the comment at `config.py:6-7`, which currently justifies the large pool with
a constraint the new design removes.

### 6.4 Bounding and measuring concurrency

**Bound = partition count.** Per §2's one-in-flight-per-partition rule, a replica runs
at most one job per assigned partition, so there is no `concurrency` setting to
misconfigure.

But a replica can be assigned *every* partition when it is the only consumer. Two
controls:

1. **One lane per worker process** (`JOB_LANES=realtime`, etc.). Since each lane is a
   separate topic and group, a realtime worker is structurally bounded by realtime
   partitions. This is the primary control and needs no new mechanism.
2. **Voluntary pause as a backstop.** Verified in the installed client:
   `AIOKafkaConsumer.pause(*partitions)` exists and *"does not affect partition
   subscription… does not cause a group rebalance"*. A replica that holds more than
   `MAX_PARTITIONS_PER_REPLICA` pauses the excess and resumes it below the threshold.
   Cheap insurance; not required for correctness.

**Measuring** — no new dependency, using what SQLAlchemy and aiokafka already expose:

| Signal | Source |
|---|---|
| DB connection pressure | `engine.pool.checkedout()`, `.size()`, `.overflow()` |
| Handlers in flight | `consumer.assignment()` → count assigned partitions |
| Lane saturation | `SELECT count(*) FROM jobs WHERE status='running' GROUP BY lane` (partial index §2.6) |
| Queue age | `SELECT max(now() - created_at) FROM jobs WHERE status='queued'` |
| Handler latency | In-process counters; percentiles computed on read, emitted to the existing admin health shape (`admin/service.py:380-394`) |

The repo has **zero** metrics infrastructure — no Prometheus, no OTel, no `/metrics`
(`app/main.py:259-261` returns a constant). These counters are a deliberate stopgap that
adds no dependency and fits the constraint of no new infrastructure.

### 6.5 Tests

`G47` — assert no session is open during the handler: in the integration suite, have a
handler block on an event while the test polls `engine.pool.checkedout()`; assert the
count does not rise with the number of blocked handlers.
`G48` — 24 partitions, pool of 3, 24 concurrent jobs; assert all complete and no
`TimeoutError` from `pool_timeout`.
`G49` — boot check: set pools to over-budget and assert startup fails with the
arithmetic in the message.

**Migration/rollout:** none. Configuration change plus one new comment.

---

## 7. Revised schema deltas

Net changes from v2's `jobs` table:

```sql
-- removed
  dispatched_at            -- ambiguous ownership; replaced by the three below
  status 'accepted'         -- never persists; submit writes 'queued' directly

-- added
  dispatch_attempts   INT         NOT NULL DEFAULT 0
  last_dispatched_at  TIMESTAMPTZ NULL
  claimed_at          TIMESTAMPTZ NULL
  request_fingerprint CHAR(64)    NOT NULL

-- status enum gains
  'ambiguous'               -- §4.4; NOT automatically retried, NOT replayable without force

-- idempotency
  idempotency_key   NOT NULL     -- §5.6; server always populates
  UNIQUE (tenant_id, idempotency_key)

-- indexes
  ix_jobs_tenant_running ON jobs (tenant_id) WHERE status = 'running'   -- §2.6
```

Migration shape follows `d8e0f2a4c6b8_channel_comments.py`: `op.create_table`, inline
`sa.Column` / `sa.Index` / `sa.UniqueConstraint`, `server_default` on every NOT NULL
column, `sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)` in
`downgrade()`. `postgresql_where` is new to this repo and is not exercised by the SQLite
harness — integration-test only.

---

## 8. Prioritised implementation plan

| Phase | Item | Blocked by | Test gate |
|---|---|---|---|
| **0.1** | Repair `alembic/env.py` model imports | — | — |
| **0.2** | Migration: `jobs` + `job_attempts`, `dispatched_at` removed, `ambiguous` added, partial index | 0.1 | G32, G33 |
| **0.3** | Idempotency API: fingerprint, 200-on-replay, IntegrityError path | 0.2 | G42–G46 |
| **0.4** | Topic provisioning, explicit counts; disable auto-create | — | — |
| **0.5** | Outbox `FOR UPDATE SKIP LOCKED` (S5) | — | G4 |
| **0.6** | Producer `acks=all`, `enable_idempotence=True`, gzip, singleton lock (S4) | — | — |
| **0.7** | R3, R4 | — | — |
| **1.1** | Tenant-cap advisory lock + `SET LOCAL lock_timeout` | 0.2 | **G47 negative control must fail without the lock** |
| **1.2** | Sweeper with visibility timeout, `never_dispatched` liveness | 0.2 | G31, G32, G33 |
| **1.3** | Lease reaper with `ambiguous` routing | 1.1 | G37, G39 |
| **1.4** | Claim with fencing + subject ordering guard | 1.1, 1.3 | G34, G38 |
| **1.5** | Heartbeat renewal | 1.4 | G40 |
| **2.1** | Lane consumer: one-in-flight-per-partition, explicit `commit({tp: offset+1})` | 0.6, 1.4 | G18, G19 |
| **2.2** | `external_intent` write-ahead + reconciliation | 1.4 | G39 |
| **2.3** | Migrate `stt.job` (no external side effects) | 2.1 | — |
| **2.4** | Idempotency for existing `review-events` / `meta-events` consumers | 0.6 | — |
| **2.5** | Manual offset commit for those consumers | 2.4 | G18, G19 |
| **3.1** | Redis 429 → `blocked`, honour `Retry-After` | 2.1 | G23 |
| **3.2** | Migrate `location_posts` / `location_media` | 2.2, 1.4 | G15, G34 |
| **3.3** | Verify `meta-events` history source, then expand 1→N | — | §6.4 of round-1 review |
| **4.1** | `tests/load/test_lane_throughput.py` — replace all timing assumptions | 2.3 | G1–G6 load set |
| **4.2** | Re-tune partitions, `max_tenant_inflight`, pool from measurements | 4.1 | — |

**Critical path:** 0.2 → 1.1 → 1.3 → 1.4 → 2.1. Everything side-effecting waits on 2.2.

**Rollout gates.** Do not move traffic to a lane until its integration tests pass against
real Postgres. §2.3's negative control and §2.7's session test are the two that cannot
be satisfied by the SQLite harness and must not be waived.

---

## 9. Assumptions still unmeasured

| Symbol | Value | Status |
|---|---|---|
| `max_connections` | 83 | **Assumption.** `SHOW max_connections` on the actual instance |
| Statement-pair latency | 2 ms | **Assumption.** Drives §6.2's `held_fraction` |
| `T_p50` / `T_p95` per lane | 5 s / 15 s | **Assumption.** Replaced by `tests/load/` (4.1) |
| `visibility_seconds` | 1800 s | Chosen for repair latency, not measured |
| Tenant traffic distribution | — | **Assumption.** Drives §3's key choice; one large tenant vs many small is unmeasured |

Every one of these is a planning input, not a correctness input. None of the mechanisms
in §1, §2, §4 or §5 depend on their values.
