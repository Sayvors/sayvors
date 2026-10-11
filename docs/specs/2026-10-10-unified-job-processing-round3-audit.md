# Unified Job Processing — Round 3 Correctness Audit

Date: 2026-10-10
Audits: `...-design.md` (v1), `...-review.md` (v2), `...-final-review.md` (v3)
Mode: design audit only — no code, no migrations, no schema changes
Verified against: `D:\code\sayvors` working tree, `.venv` (aiokafka 0.14.0, Python 3.14.7),
running containers (`sayvors-redis`, `sayvors-kafka`)

---

## 0. Evidence ledger

### Verified from source

| # | Fact | Evidence |
|---|---|---|
| V1 | `event_outbox` has **no unique constraint**. PK only. | `ceab557d4a2e_add_event_outbox_table.py:32` — `sa.PrimaryKeyConstraint('id')`; three `unique=False` indexes at `:35-37` |
| V2 | `event_outbox.status` is `String(20)`, **not** a native enum | `ceab557d4a2e:30` |
| V3 | Every `enqueue_event` mints a fresh UUID | `outbox/service.py:33` `event_id = str(uuid.uuid4())` |
| V4 | `mark_failed` has **no status guard** — it flips any row, including `sent` | `outbox/service.py:86-107`; `fetch_pending_events` re-selects `status IN ('pending','failed')` at `:56` |
| V5 | `mark_sent` sets `status='sent'` unconditionally for the given ids | `outbox/service.py:74-80` |
| V6 | **Dead outbox rows are never purged.** Cleanup deletes only `status='sent'` | `outbox/service.py:117-119` |
| V7 | PG image is `pgvector/pgvector:pg16` | `docker-compose.yml:3` |
| V8 | **Inline `sa.Enum(...)` inside `op.create_table` works in this repo** (CREATE TYPE is emitted first) | `d8e0f2a4c6b8_channel_comments.py:44-52`; type dropped in `downgrade()` at `:71-72` |
| V9 | All worker loops run as asyncio tasks in **one process** | `workers/main.py:99` `tasks = [asyncio.create_task(fn(), name=name) for ...]` |
| V10 | `location_posts` already carries `google_post_id`, `localith_response`, `attempts`, `next_retry_at` | `posts/models.py:53,73,83-84` |
| V11 | Publish success resets `attempts = 0` in the same tx as `google_post_id` | `posts/service.py:396-404` |
| V12 | The DB-pool justification comment describes **existing** code, not the proposed design | `config.py:6-7` "workers hold sessions across network calls" |

### Verified by execution

| # | Test | Result |
|---|---|---|
| X1 | `asyncio.wait_for(swallows_cancellation(5), timeout=0.3)` on Python 3.14.7 | **Returned `'COMPLETED_ANYWAY'` after 0.36 s. Timeout NOT enforced.** |
| X2 | CPU-blocking coroutine concurrent with `asyncio.sleep(0.1)` heartbeat | Heartbeat starved until the blocker yielded. **No cancellation can be delivered to a blocked loop.** |
| X3 | `docker ps` | Only `sayvors-redis`, `sayvors-kafka` running. **`sayvors-postgres` is not up.** |

### Explicitly UNVERIFIED

| Item | Status |
|---|---|
| `max_connections` | **UNVERIFIED** — no database reachable (X3). All connection-budget arithmetic is arithmetic, not measurement. |
| `statement-pair latency` | **UNVERIFIED** — v3 asserted 2 ms. Retracted as a planning input. |
| Per-lane `T_p50` / `T_p95` | **UNVERIFIED** — unchanged from v1. |

---

## 1. Findings

| ID | Sev | Defect | Failure scenario | Required correction |
|---|---|---|---|---|
| **F1** | **Blocker** | Reaper/sweeper share a process with lane consumers (V9). A handler that blocks the event loop starves its own recovery (X2). | Media handler decodes an image without yielding. Lane wedged, lease reaper never runs, every in-flight job on that replica is stranded until the container dies. | Run control loops in a **separate worker service** (`JOB_LANES=control` vs `JOB_LANE=realtime`). Same image, same `python -m app.workers`, different env. No new infrastructure. |
| **F2** | **Blocker** | `asyncio.wait_for` does **not** bound a handler that suppresses `CancelledError` (X1). v3 §4.2 relied on it. | A handler wrapping a provider call in `except CancelledError: ... cleanup ...` runs to completion. The "hard deadline" never fires; lease is held far past its term. | In-process timeout is **best-effort only**. The real deadline is **lease expiry enforced by a foreign process** (F1). Document `wait_for` as an optimisation, not a bound. |
| **F3** | **Blocker** | Subject-ordering guard is evaluated without serialisation, exactly like the retracted v2 tenant cap (v2 §2.1). | Two `publishing` claims for one listing commit concurrently. Both `NOT EXISTS` subqueries see no earlier job in `running` yet. Both claim. Two posts publish out of `scheduled_on` order. | Acquire a **subject-scoped advisory lock** in the same critical section as the tenant lock, always in order tenant → subject. |
| **F4** | **High** | `dispatch_attempts` increments on *dispatch*, not on *failure* (v3 §1.6). A claim never resets it. | A poison-payload job that **is** dispatched every time reaches `max_dispatch_attempts` and is mislabelled `never_dispatched` — an operator is told the lane is broken when the job is at fault. | Reset `dispatch_attempts = 0` on successful claim. The limit then means "dispatched N times, never claimed" — genuinely undeliverable. |
| **F5** | **High** | Outbox has no dedupe identity (V1, V3). Every redispatch is a new row. | Visibility-timeout redispatch at 30 min intervals on a job nobody consumes: unbounded `event_outbox` growth, and **no query can tell you how many dispatches a job has had**. | Add `dispatch_seq` to the outbox payload; the job row remains the sole authority. Add an index or accept and document the growth. |
| **F6** | **High** | `mark_failed` can resurrect a `sent` event (V4). | `producer.send` delivers; the ack is lost; `send` raises; `mark_failed` sets `status='failed'`, `attempts=1 < 10`. `fetch_pending_events` re-selects it. **The event publishes twice.** | Harmless for job dispatch (claim dedupes) but must not be relied on. Add `AND status <> 'sent'` to `mark_failed`. |
| **F7** | **Medium** | Dead outbox rows are never purged (V6). | Every permanently-failing event accumulates forever. No endpoint exposes the count (`get_outbox_stats` at `:125` has no router). | Extend `cleanup_sent_events` to `status IN ('sent','dead')`, and expose `get_outbox_stats` in admin. |
| **F8** | **Medium** | Connection budget derived from an unverified `max_connections=83` (X3) and an assumed 2 ms statement. | Budget tuned against a fictional number; real instance allows fewer, or the pool is far larger than needed. | Equation corrected in §5. **Numbers marked UNVERIFIED** until `SHOW max_connections` runs against the real instance. |
| **F9** | **Medium** | `jobs.status` would be a native enum, and v3 contemplated `ALTER TYPE ADD VALUE` for `ambiguous`. | PG 16 permits `ALTER TYPE ... ADD VALUE` inside a transaction **but the new value cannot be used in that same transaction** (V7). A migration that adds the value and uses it as a `server_default` fails. | Not applicable — `jobs` is **new**. Define `ambiguous` in the initial `CREATE TYPE`. The split-migration rule applies only to future additions. |
| **F10** | **Low** | v3 asserted 2 ms statement latency and derived `held_fraction = 0.0008` from it. | Budget conclusions inherited from a fabricated number. | Retracted. §5 states the equation; the constant is a measurement, not an assumption. |

---

## 2. Corrected invariants

These must hold under concurrency, worker crash, broker outage, provider timeout and
retry. Each is stated so it can be falsified by a test.

**I1 — At most one execution.** At most one worker executes a job's handler at any
instant. *Holds because* the claim (`UPDATE ... WHERE id=$1 AND status='queued'`) is a
single-row write under row lock, and the sweeper only ever writes `status='queued'`
for jobs that are not `running`. *No ordering assumption.*

**I2 — A stale worker cannot persist state.** Every terminal write and every domain
projection is conditional on `lease_owner = $me AND status='running'`, and the domain
write additionally on its own prior status (`status='scheduled'`). Zero rows ⇒ the
write is discarded and `fence_violation_total` increments.

**I3 — Dispatch is at-least-once; execution is at-most-once.** Duplicate dispatches
are permitted and expected. I1 absorbs them. This is the whole safety argument, and it
does **not** depend on Kafka ordering, partition placement, or handler idempotency.

**I4 — A committed offset implies a durable outcome.** Offset *N+1* for partition *p*
is committed only after the DB transaction recording *N*'s outcome has committed.
Proven in round 2 §2.3 by Invariant II; unchanged.

**I5 — Per-tenant concurrency never exceeds the cap.** Proven only by the advisory-lock
critical section (round 2 §2.2), **not** by the `count(*)` predicate, which is unsound
under READ COMMITTED.

**I6 — Per-subject publish order is serialised.** Claimed under a subject-scoped
advisory lock; the ordering guard is evaluated inside that lock.

**I7 — A job that is never claimed terminates.** `dispatch_attempts` reaches
`max_dispatch_attempts` with zero claims ⇒ `failed` / `never_dispatched`. Reset on
claim (F4), so the counter measures *undeliverability*, not *bad payloads*.

**I8 — Unknown external outcome is never auto-retried.** A job with
`external_intent IS NOT NULL AND external_result IS NULL` is `ambiguous` and is never
dispatched automatically. Only an explicit operator force-replay leaves that state.

**I9 — Client-visible recovery always yields the original job id.** Replay with the
same `(tenant_id, idempotency_key)` returns `200` with the original job and a verified
matching `request_fingerprint`.

**I10 — Fencing bounds corruption, not duplication.** A fenced worker cannot write
state. **It cannot unsend a message or unpublish a post.** This is not fixable in
software and is stated as a permanent limitation.

---

## 3. State transitions

```
 submit ──▶ queued ◀──────────────────────────┐
              │  ▲                            │ sweeper: due, visible again,
              │  │ sweeper: retrying→queued   │ dispatch_attempts+1
              │  │                            │ last_dispatched_at=now
              ▼  │                            │ + outbox row (same tx)
          running ───────┬──────────┬─────────┤
             │           │          │         │
     handler ok         │     lease expired    │ claimed → dispatch_attempts=0
             ▼           │          │         │
        succeeded        │   ┌──────┴──────┐  │
        (terminal)       │   │ intent set? │  │
                         │   └──────┬──────┘  │
                         │   no   │  yes     │
                         │     ▼  │    ▼     │
                         │  retrying ambiguous │
                         │   │      (terminal)│
                         │   │ sweeper       │
                         │   └──▶ queued      │
                         │                    │
                    definitive failure         │
                         ▼                    │
                  blocked (429/Retry-After) ──┘  sweeper, when due
                         │
                    exhausted / non-retryable
                         ▼
                      failed  (terminal, replayable)
                         │
                    attempts >= max_attempts
                         ▼
                        dead  (terminal, force-replay)
```

**Replay** — `dead` / `failed` / `ambiguous`, one transaction, `job_attempts` untouched:

```
status='queued', attempts=0, dispatch_attempts=0,
last_dispatched_at=NULL, claimed_at=NULL, dead_at=NULL,
error_code=NULL, last_error=NULL, next_run_at=now()
+ outbox row
```

Preserved: `id`, `idempotency_key`, `request_fingerprint`, `created_at`, all of
`job_attempts`.

**`ambiguous` is reached from exactly two places**, and nowhere else:
1. Lease reaper, when `external_intent IS NOT NULL AND external_result IS NULL`.
2. The handler itself, when the provider call raises a **non-definitive** error
   (timeout, connection reset after send).

A **definitive** provider rejection (a 4xx whose meaning we know) sets
`external_result = {"definitive_failure": ...}` and transitions to `retrying` or
`blocked` — never `ambiguous`. That distinction is the whole point of I8 and is the
correction to v3 §4.4, which routed *any* reaped job with an intent to `ambiguous`
regardless of whether the outcome was knowable.

---

## 4. Test matrix

All concurrency and partial-index tests require **real PostgreSQL**. The SQLite harness
(`tests/conftest.py:36-42`) serialises writes and cannot falsify F3 or the v2 tenant-cap
race.

| ID | Setup | Injected failure | Required assertion |
|---|---|---|---|
| T1 | Real PG, 50 concurrent connections, cap 3, **advisory lock removed** | — | `max_concurrent_running > 3`. **This test must fail.** Negative control. |
| T2 | As T1, lock present | — | `≤ 3` and `total_claimed == 50` |
| T3 | Two claims, same `subject_id`, concurrent connections, publishing lane | — | Exactly one claims; the other defers |
| T4 | Job `queued`, lane consumer stopped | clock advance past `visibility_seconds` | `dispatch_attempts` ≥ 2, exactly one handler execution |
| T5 | Poison payload, consumer running | — | Job reaches `dead` via `retrying` exhaustion — **not** `never_dispatched` (F4) |
| T6 | No consumer for a lane | sweeper runs to limit | `failed` + `error_code='never_dispatched'` |
| T7 | Outbox row forced to `dead` | sweeper redispatch | Job still re-dispatched and completes (v3 `G32`) |
| T8 | Worker killed between `external_intent` commit and provider response | process death | `ambiguous`, handler **not** re-executed |
| T9 | Provider returns 400 mid-publish | definitive error | `retrying` or `blocked`; **never** `ambiguous` |
| T10 | Provider call times out | non-definitive error | `ambiguous` |
| T11 | Handler suppresses `CancelledError`, sleeps past `lease_seconds` (X1 pattern) | lease expiry | Separate-process reaper requeues; original worker is fenced; zero rows written |
| T12 | Worker A reaped, worker B completes, then A finishes | out-of-order completion | A's completion affects 0 rows; `fence_violation_total` +1 |
| T13 | Handler blocks the event loop (X2 pattern) | — | Control plane in a **different** service requeues the job; the wedged replica is not required to self-recover |
| T14 | 20 identical POSTs, same key, concurrent | — | Exactly one `202`, nineteen `200`, one job row, no 500 |
| T15 | Same key, different payload | — | `422 idempotency_key_reuse` |
| T16 | Tenant B reuses tenant A's key | — | Separate job created |
| T17 | Lost first response | client retry | `200` + original `job_id` |
| T18 | 12 posts, one listing, `scheduled_on` ascending, 4 workers | — | Domain row publishes in exactly that order |
| T19 | Real PG; claim transaction aborted while holding both locks | — | Both locks released; subsequent claim succeeds |
| T20 | Outbox `mark_failed` on a `sent` row | ack lost after send | Does not resurrect; event not republished (F6) |

T1, T3, T11, T13, T19 are the ones that cannot be waived.

---

## 5. Connection budget — corrected equation

### 5.1 The equation

```
max_connections                                    UNVERIFIED (X3)
- superuser_reserved_connections                   PG default 3
- admin_reserve                                    operational choice
- migration_reserve                                1 (alembic runs on api start)
= available_for_pool

pool_total = api_replicas    × (DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW)
           + worker_replicas × (WORKER_DB_POOL_SIZE + WORKER_DB_POOL_MAX_OVERFLOW)

require pool_total ≤ 0.7 × available_for_pool
```

Two pools, because the roles differ: the API serves request sessions, workers serve
two-millisecond claim/outcome transactions.

### 5.2 Pressure model, stated without invented constants

Per worker replica, at steady state:

```
connection_demand = assigned_partitions × session_held_fraction
                  + control_loop_concurrency     (sweeper, reaper, heartbeat timer)

session_held_fraction = (claim_tx + outcome_tx + heartbeat_tx duration)
                        / job_wall_clock_duration
```

The first term is **not measurable without timing the statements** — that is exactly
what the retracted 2 ms figure was doing. Measure it in T-family integration tests
before choosing pool sizes. What *is* structural and does not depend on the constant:
claim, outcome and heartbeat transactions are all short single-statement transactions,
and **none of them is held across an external `await`** (v3 §6.2 rule, unchanged).

The binding risk is not average demand but **burst contention**: after a rebalance, N
partitions can claim simultaneously. That is where `pool_timeout` must be short enough
to fail fast rather than hang, and where `MAX_PARTITIONS_PER_REPLICA` (§6.4 of v3)
bounds the burst.

### 5.3 Correction to the comment

`config.py:6-7` justifies the large pool with *"workers hold sessions across network
calls (Localith, Groq)"* — that describes `localith` and the publish path today. Under
this design it becomes false and must be updated, or the next reader will size the pool
for a constraint that no longer exists.

---

## 6. Ordering and retry eligibility

### 6.1 Deterministic tie-breaking

`ORDER BY priority_order, created_at, created_at` is **not** deterministic — ties are
broken arbitrarily. Add a monotonic column:

```sql
seq BIGSERIAL   -- stable insertion order; final tiebreak for every queue query
```

Every queue query orders `ORDER BY <effective_priority>, next_run_at, seq`. `seq` is
immutable and gapless-enough for ordering (sequence gaps from rollbacks are harmless
because it is only ever a tiebreak).

### 6.2 Subject guard serialisation (F3)

The guard is a predicate, and predicates do not serialise concurrent transactions —
the identical defect retracted from the tenant cap. The claim runs:

```
BEGIN
  SET LOCAL lock_timeout = '5s'
  SELECT pg_advisory_xact_lock($tenant_lock);      -- always first
  SELECT pg_advisory_xact_lock($subject_lock);     -- always second, never reversed
  count(*) check; subject NOT EXISTS check; UPDATE ... RETURNING
COMMIT
```

Lock order is fixed tenant → subject, so no cycle exists. Locks are keyed by Python-side
BLAKE2b hashes, **not** `hashtext()` — the latter is an undocumented PG internal
(`scheduling/__init__.py:45`) whose output is not guaranteed stable across major
versions.

The subject lock applies only to lanes that carry an ordering requirement
(`publishing`). Lanes without one take only the tenant lock.

### 6.3 `retrying` → `queued`

Only the sweeper performs it, inside the same transaction that creates the outbox row
(round 2 §1.3). Retry is **not** requeueing; it is the sweeper declining to select a
job whose `next_run_at` is in the future. The consumer never waits on a job.

### 6.4 `ambiguous` must not block successors

The round-2 guard listed `queued, running, retrying` as blocking and excluded
`ambiguous` — correct, and now explicit in I6's implementation:

```sql
AND NOT EXISTS (
    SELECT 1 FROM jobs p
     WHERE p.subject_type = jobs.subject_type
       AND p.subject_id   = jobs.subject_id
       AND p.status IN ('queued','running','retrying')   -- NOT 'ambiguous'
       AND p.priority_order < jobs.priority_order
)
```

Operator resolution of `ambiguous` is a three-way decision, not a retry:

| Operator choice | Effect |
|---|---|
| **Mark done** | `status='succeeded'`, `external_result` recorded as operator-confirmed |
| **Retry anyway** | `force=true`, status → `queued`, **duplicate side effect accepted** |
| **Abandon** | `status='failed'`, `error_code='ambiguous_abandoned'` |

The admin view must show the `external_intent` payload for each so the decision is
informed.

---

## 7. Migration, rollout, tests

### 7.1 `ambiguous` — no `ALTER TYPE` required

`jobs` does not exist. The enum is created once with every value it will ever need:

```python
Enum("queued","running","retrying","blocked","succeeded","failed","dead","ambiguous",
     name="job_status")
```

Inline in `op.create_table`, matching `d8e0f2a4c6b8:44-52` (V8). `downgrade()` must
drop the type: `sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)`.

**For future additions only:** on PG 16 (V7), `ALTER TYPE ... ADD VALUE` may run inside
a transaction, but the new value **cannot be used in that same transaction**. Adding a
status therefore requires two migrations — add-and-commit, then use. Recorded so it is
not rediscovered under pressure.

### 7.2 Replay-field reset

Reset: `status`, `attempts`, `dispatch_attempts`, `last_dispatched_at`, `claimed_at`,
`next_run_at`, `error_code`, `last_error`, `dead_at`, `ambiguous_at`.

Never reset, never deleted: `id`, `idempotency_key`, `request_fingerprint`,
`created_at`, `seq`, and every row in `job_attempts`. `job_attempts` is append-only and
replay writes nothing to it — the history of *why* it first failed must survive a
successful replay.

### 7.3 Rollout dependency

```
0.1 alembic/env.py import repair        (--autogenerate is unsafe today)
0.2 migration: jobs + job_attempts
0.3 control-plane worker service UP     ── must precede 0.5
0.4 sweeper + reaper
0.5 lane consumer service UP            (control plane already running)
0.6 first job type: stt.job             (no external side effects)
```

**0.3 before 0.5 is a hard ordering constraint.** F1: deploying a lane consumer with
no separate control plane means a wedged handler has no recovery path. This is the one
rollout step where the order cannot be reversed safely.

### 7.4 Test-to-issue map

| Issue | Tests |
|---|---|
| 1 dispatch dedupe | T4, T5, T6, T7, T20 |
| 2 lease / deadline | T11, T12, T13, T19 |
| 3 external outcomes | T8, T9, T10 |
| 4 idempotency | T14, T15, T16, T17 |
| 5 pool budget | F8/T-family timing measurement; **not yet specified** |
| 6 ordering / retry | T3, T18 |
| 7 migration | T5 (enum completeness), T14 (NOT NULL idempotency key) |

Gaps acknowledged: **no test covers the pool budget**, because the numbers are
unverified (X3). That test is specified in §5.2 but cannot be written until a database
is reachable.

---

## 8. Implementation blockers

### Must be resolved before implementation

| # | Blocker | Resolution |
|---|---|---|
| **B1** | Control plane must be a separate worker service from lane consumers (F1) | Config split; `workers/main.py:90-99` gains lane filtering. No new infrastructure — same image, same entrypoint |
| **B2** | Lease enforcement may not rely on in-process cancellation (F1, F2 / X1) | Treat lease expiry as the sole deadline; `wait_for` documented as best-effort |
| **B3** | Subject guard needs serialisation (F3) | Subject advisory lock in the claim critical section |
| **B4** | `dispatch_attempts` must reset on claim (F4) | One line in the claim `UPDATE` |
| **B5** | Stale `event_outbox` growth (F5, F7) | Extend cleanup to `dead`; expose `get_outbox_stats` |

All five are small. None requires new infrastructure, a new broker, or an
irreversible migration.

### Tuning assumptions — **not** blockers

Unmeasured values that affect sizing only, never correctness:

`max_connections` (unverified, no DB) · statement-pair latency · per-lane `T_p50`/`T_p95`
· partition counts · `visibility_seconds` · `max_tenant_inflight` · pool sizes ·
tenant traffic distribution.

None of the invariants I1–I10 depend on any of these. They change capacity and cost,
not behaviour under failure.

---

## 9. Final verdict

**Not ready for implementation — five blockers, all bounded.**

The architecture holds. Three claims from earlier rounds failed re-checking and are
**retracted**:

1. **v2 §2.3** — the correlated `count(*)` was unsound under READ COMMITTED. Replaced
   by an advisory-lock critical section.
2. **v2 §6.1** — the pool does not cap handler concurrency; sessions are held briefly.
   That removed v2's central scaling constraint.
3. **v3 §4.2** — `asyncio.wait_for` does not bound a handler that suppresses
   `CancelledError`. Demonstrated on the installed Python 3.14.7. The lease, not the
   in-process timeout, is the deadline.

And one new finding is structural rather than a claim error: **the control plane and
the workers that need recovering from it share a process** (V9, X2). That is why B1 is
the one ordering constraint in §7.3 that cannot be reversed safely.

The single largest caveat is unchanged and is not a defect: **I10.** Fencing prevents
state corruption; it cannot unsend a message or unpublish a Google post. That residual
window is why `ambiguous` exists and why it is never auto-retried.

Clearing B1–B5 requires no design decision — all five are implementation details
settled by this audit. The plan can proceed to Phase 0 on approval.
