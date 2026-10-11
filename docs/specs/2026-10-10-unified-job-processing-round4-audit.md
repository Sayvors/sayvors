# Unified Job Processing — Round 4: Final Correctness Gaps

Date: 2026-10-10
Reviews: `...-review.md` (v2) → `...-final-review.md` (v3) → `...-round3-audit.md` (v4) → this
Mode: design audit only — no code, no migrations, no schema changes

---

## 0. Evidence added this round

### Verified from source

| # | Fact | Evidence |
|---|---|---|
| V10 | `notify()` inserts a `Notification` row via `db.add()` + `flush()` inside a SAVEPOINT in the **caller's** session | `notifications/service.py:36-50` |
| V13 | That SAVEPOINT swallows failures and returns `None` — it is an availability guard, **not an ownership fence** | `notifications/service.py:51-58` |
| V14 | `event_outbox.payload` is `sa.JSON`, **not** JSONB | `outbox/models.py`; `ceab557d4a2e:29` `sa.Column('payload', sa.JSON(), nullable=False)` |
| V15 | No `dedupe_key`, `lease_owner`, `hard_deadline_at` or `claim_token` exists anywhere in `app/` | grep across `services/api/app` — zero matches |

**V14 is load-bearing:** `payload->>'job_id'` cannot be indexed because the column is
`JSON`, not `JSONB`. Any per-job lookup of outbox rows requires a **dedicated column**,
not an expression index.

### Carried from round 3

X1 `asyncio.wait_for` does not enforce its timeout when the handler suppresses
`CancelledError` (Python 3.14.7). X2 A loop-blocking handler starves every other task
in the process, including heartbeats and the reaper. X3 `sayvors-postgres` is not
running; `max_connections` is **UNVERIFIED**.

---

## 1. Findings

| ID | Sev | Defect | Failure scenario | Correction |
|---|---|---|---|---|
| **G1** | **Blocker** | Invariant I1 (*"at most one worker executes a job's handler at any instant"*) is **false and not fixable**. A worker that loses its lease keeps executing. | A claims J. A is descheduled (cgroup CPU throttle, VM pause, OOM-swap) for longer than the lease. Reaper requeues; B claims and completes. A resumes and makes a customer-facing send. Two executions overlapped. | Replace I1 with C1/C2/C3 (§2). Execution overlap is a **permanent, accepted** property; bound its *effects*, not its occurrence. |
| **G2** | **Blocker** | `notify()` runs inside the completion transaction and is not fenced. | A zombie worker reaches `notify(db, user_id, "post_published", ...)` (`posts/service.py:406-412`) before its fence check, and inserts a duplicate "Published to Google" notification. The SAVEPOINT (V13) permits it. | Fence-check must be the **first** statement; all subsequent writes gated on its rowcount in Python. Enumerated in §2.3. |
| **G3** | **Blocker** | Heartbeat extends `lease_expires_at` unconditionally — a live-but-hung worker holds a job forever. | Handler is alive and heartbeating but wedged on a retry loop that never returns. Every heartbeat pushes the lease out. The job is never reclaimed. | `hard_deadline_at` with `LEAST()` clamping **in SQL** (§4). Application logic cannot exceed it. |
| **G4** | **High** | `dispatch_attempts` reaching its limit cannot distinguish an undeliverable job from a **lane outage, broker outage, outbox backlog, or consumer lag**. | Kafka is down for an hour. Every queued job's visibility timeout expires repeatedly. All reach `max_dispatch_attempts` and are failed as `never_dispatched` — a fleet-wide outage is reported as thousands of bad jobs, and each is now replayable by an operator. | Three-part positive evidence required before failing a job (§3.3). A stale lane heartbeat means **do not fail the job**. |
| **G5** | **High** | Each redispatch inserts a **new** outbox row (V15, round-3 V1/V3). No way to ask "is a dispatch already in flight for this job?" | Outbox backlog exceeds the visibility timeout. The sweeper redispatches on top of an undelivered dispatch, doubling Kafka traffic and doubling the blast radius of a backlog. | One reusable row per job via `dedupe_key` + `UNIQUE`, and a `NOT EXISTS` guard on the redispatch predicate (§3.1–3.2). |
| **G6** | **Medium** | `event_outbox.payload` is `JSON` (V14), so the per-job dispatch lookup cannot be indexed. | Sweeper's `NOT EXISTS` over `payload->>'job_id'` sequential-scans `event_outbox` on every batch — O(n) per sweep, growing without bound. | Resolved by G5's `dedupe_key` column (indexed, standard — also SQLite-testable, unlike a partial index). |
| **G7** | **Medium** | The `failed / never_dispatched` transition is not specified as concurrency-safe against a simultaneous claim. | Sweeper decides to fail J; a consumer claims J in the same window. Both write. Job is `running` and `failed` depending on commit order; a live execution is masked. | Conditional `UPDATE ... WHERE status='queued'`; the claim's own `WHERE status='queued'` makes exactly one winner (§3.4). |

---

## 2. Revised invariants

### 2.1 Replacement for I1

**C1 — Claim exclusivity.** At most one worker holds the **current lease** at any
instant. *Enforced by* the claim's single-row `UPDATE ... WHERE id=$1 AND
status='queued'` under row lock. *True by construction; no timing assumption.*

**C2 — Write authority.** At most one worker may persist a terminal outcome, a domain
projection, an attempt record, or a notification. *Enforced by* the ownership predicate
plus a Python-side rowcount gate that guards every later write in the transaction.
*True.*

**C3 — Execution exclusivity. NOT GUARANTEED. Permanently out of scope.**
Executions of the same job **can and will overlap**. No mechanism in this design prevents
it, and none can:

- the claim cannot preempt a worker already running (G1)
- `asyncio.wait_for` does not fire when the handler suppresses `CancelledError` (X1)
- a loop-blocked handler receives no cancellation at all (X2)
- the process may be frozen by the OS with no cooperation from userspace

The design bounds C3's **effects**, not its occurrence:

| Effect | Bounded by | Residual |
|---|---|---|
| Job row corruption | C2 | none |
| Domain projection applied twice | C2 + domain status predicate | none |
| Duplicate notification | C2 | none |
| **Duplicate external call** | `assert_lease()` immediately before the call | **The window between a passing assert and the call completing. Not closeable.** |
| Duplicate LLM spend | cost only — LLM completion has no side effect | billed twice |
| AI budget ledger | self-balancing: 2 reserves, 2 settles, net zero (`billing/budget.py:113-144`) | none |

### 2.2 Where provider idempotency and reconciliation exist

| Provider | Idempotency key | Reconciliation | Residual harm if C3 overlaps |
|---|---|---|---|
| LLM completion | n/a — **no external side effect** | n/a | cost only |
| Meta Graph send (`consumer.py:583`, `:1290`) | **No** | **No lookup API** | duplicate customer message |
| EmbedSocial / Localith publish (`posts/service.py:363`) | **No** | **No lookup API** | duplicate Google post |
| Google GBP reply | **No** | `confirm_reply_live` (`google_reviews.py:465-476`) is a *verification* poll, not a lookup | duplicate review reply |

**Only the LLM path is free of correctness harm.** The design consequence is
structural: **split generation from delivery.** Generation runs under cost control and
is safe to duplicate; delivery is preceded by `assert_lease()` and is the only call
that can harm a customer.

### 2.3 Every write requiring ownership fencing

Completion transaction, in this exact order:

| # | Write | Fence | File precedent |
|---|---|---|---|
| 1 | `jobs.status` → `succeeded`/`retrying`/`blocked`/`ambiguous`/`dead` | `WHERE id=$1 AND lease_owner=$2 AND status='running'` | new |
| 2 | `jobs.result`, `jobs.external_result`, terminal timestamps | same statement as #1 | new |
| 3 | `job_attempts` INSERT | same transaction, gated on #1 rowcount | new |
| 4 | Domain projection (`location_posts.status`, `published_at`, `google_post_id`, `localith_response` — `posts/models.py:46-73`) | gated on #1 rowcount **and** `WHERE status='scheduled'` | `posts/service.py:396-404` |
| 5 | `Notification` INSERT via `notify()` | gated on #1 rowcount | `posts/service.py:406-412`, `notifications/service.py:36-50` |
| 6 | `billing/budget.settle()` Redis `INCRBY` | **not fenceable** — not a DB write | `billing/budget.py:144-158` |

Row 6 is deliberately excluded: `reserve`/`settle` are balanced per call, so a duplicated
execution produces two reserves and two settles. Net zero. The *provider* is billed
twice; the ledger is not corrupted.

### 2.4 Preserved invariants from round 3

I2 (stale worker cannot persist state) — retained, now enumerated as §2.3.
I3 (at-least-once dispatch, at-most-once authoritative execution) — retained, with
"authoritative" defined by C2 rather than by I1.
I4 (committed offset implies durable outcome) — unchanged.
I5 (tenant cap) and I6 (subject order) — unchanged, both resting on advisory locks.
I7 → superseded by §3.3.
I8 (unknown outcome never auto-retried) — unchanged.
I9 (idempotent recovery yields the original job) — unchanged.
I10 (fencing cannot reverse an external side effect) — retained and is the direct
consequence of C3.

---

## 3. `never_dispatched` — safe delivery accounting

### 3.1 One reusable dispatch row per job

```sql
ALTER TABLE event_outbox ADD COLUMN dedupe_key VARCHAR(200) NULL;
CREATE UNIQUE INDEX uq_event_outbox_dedupe_key ON event_outbox (dedupe_key);
```

`UNIQUE` on a nullable column: PostgreSQL treats NULLs as distinct, so existing events
(`auth-events`, `google-business-events`) are **unlimited** and unaffected, while a
non-null key yields exactly one row. A standard unique index, not a partial one — so it
is exercised by the SQLite harness, unlike the round-3 partial index.

Sweeper upsert (one row per job per time, replacing the append-per-attempt behaviour):

```sql
INSERT INTO event_outbox (id, event_type, payload, status, attempts,
                          next_retry_at, topic, dedupe_key)
VALUES (gen_random_uuid(), 'job.dispatch', $payload, 'pending', 0, now(), $topic,
        'job.dispatch:' || $job_id)
ON CONFLICT (dedupe_key) DO UPDATE
   SET status='pending', attempts=0, next_retry_at=now(), last_error=NULL
RETURNING id;
```

`ON CONFLICT DO UPDATE` also removes the duplicate-dispatch race between concurrent
sweepers: the loser updates the same row rather than inserting a second one.

Fixes G5 (unbounded growth) and G6 (needs an indexed column, per V14).

### 3.2 Redispatch predicate — an in-flight dispatch blocks redispatch

```sql
WITH due AS (
    SELECT j.id, j.lane
      FROM jobs j
     WHERE j.status = 'queued'
       AND j.next_run_at <= now()
       AND (j.last_dispatched_at IS NULL
            OR j.last_dispatched_at < now() - make_interval(secs => $visibility))
       AND NOT EXISTS (
             SELECT 1 FROM event_outbox e
              WHERE e.dedupe_key = 'job.dispatch:' || j.id
                AND e.status IN ('pending','failed'))
     ORDER BY <effective_priority>, j.next_run_at, j.seq
     LIMIT $batch
     FOR UPDATE SKIP LOCKED
)
UPDATE jobs SET last_dispatched_at = now(),
                dispatch_attempts = dispatch_attempts + 1
  FROM due WHERE jobs.id = due.id
RETURNING jobs.id, jobs.lane;
```
then the §3.1 upsert per returned id, **in the same transaction**.

This is strictly stronger than the round-3 time-only predicate. A pending or failing
dispatch is never duplicated, so an outbox backlog or a slow broker stops producing
traffic instead of amplifying it.

### 3.3 Failing a job requires positive evidence

`failed / never_dispatched` fires **only** when all four hold:

| # | Condition | Why it is necessary |
|---|---|---|
| 1 | `dispatch_attempts >= max_dispatch_attempts` | enough attempts |
| 2 | No `event_outbox` row with `dedupe_key = 'job.dispatch:'||id` in `('pending','failed')` | nothing in flight |
| 3 | That row is `sent` or `dead` — never `pending` | the transport finished, one way or another |
| 4 | `EXISTS (SELECT 1 FROM job_lane_heartbeats WHERE lane=$lane AND last_seen > now() - interval '60 seconds' AND total_lag <= 0)` | **a consumer is alive and caught up** |

New table, maintained by each lane consumer every ~10 s:

```sql
CREATE TABLE job_lane_heartbeats (
    lane                 TEXT PRIMARY KEY,
    consumer_id          TEXT NOT NULL,
    last_seen            TIMESTAMPTZ NOT NULL,
    total_lag            BIGINT NOT NULL,
    assigned_partitions  INTEGER NOT NULL,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**When (4) fails, the job is NOT failed.** It stays `queued` and a `lane_unavailable`
alert fires. This is the correction to G4: a broker outage, a lane outage, or consumer
lag must never be recorded against a job, because every such job becomes falsely
replayable and an operator replaying thousands of them during an outage would be the
actual incident.

### 3.4 Concurrency safety

The transition is a single conditional write:

```sql
UPDATE jobs
   SET status='failed', error_code='never_dispatched',
       dead_at=now(), next_run_at=NULL
 WHERE id=$1 AND status='queued' AND dispatch_attempts >= $max
RETURNING id;
```

A claim racing this write takes the row lock first or loses it. The claim's own
`WHERE status='queued'` predicate means exactly one of the two observes the
`status='queued'` state, so exactly one wins and the loser writes 0 rows (G7).

`dispatch_attempts = 0` is reset by a successful claim, so the counter measures
**undeliverability**, not bad payloads — carried from round 3 F4.

### 3.5 State additions

```sql
last_dispatched_at  TIMESTAMPTZ NULL     -- sweeper only
dispatch_attempts   INT NOT NULL DEFAULT 0
claimed_at          TIMESTAMPTZ NULL     -- consumer only, on claim
hard_deadline_at    TIMESTAMPTZ NOT NULL -- consumer only, on claim
```

---

## 4. Non-extendable execution deadline

### 4.1 The correction (G3)

```sql
-- at claim
hard_deadline_at   = now() + make_interval(secs => $hard_timeout)
lease_expires_at   = LEAST(now() + make_interval(secs => $lease), hard_deadline_at)

-- heartbeat
UPDATE jobs
   SET lease_expires_at = LEAST(now() + make_interval(secs => $lease),
                               hard_deadline_at)
 WHERE id=$1 AND lease_owner=$2 AND status='running'
RETURNING lease_expires_at, hard_deadline_at;
```

**`LEAST()` is the enforcement point, and it is in SQL.** A heartbeat can shorten the
lease but can never push it past `hard_deadline_at`, regardless of what the application
code computes or how many times it runs. Correctness does not depend on application
discipline — which is the whole point, given X1 showed application-level cancellation
is unenforceable.

### 4.2 Relationship

```
lease_seconds      = 60      -- crash-reclaim latency; tolerates ~40s of loop stall
heartbeat_interval = 20      -- lease_seconds / 3
hard_timeout       = per lane: realtime 120, publishing 300, media 900, bulk 3600
invariant          hard_timeout > lease_seconds
```

`media` at 900 s spans 15 leases. A wedged media handler is still reclaimed within 60 s
of the last successful heartbeat, while a legitimately slow one keeps its lease — and
cannot keep it past 900 s.

### 4.3 Control-plane behaviour at expiry

The reaper (a **separate process**, round 3 B1) treats deadline expiry identically to
lease expiry:

```sql
... WHERE status='running' AND (lease_expires_at < now() OR hard_deadline_at < now())
```

- intent set, no result → `ambiguous` (a worker that ran past its deadline may well
  have completed the provider call)
- otherwise → `retrying`

Running in a separate process is what makes this work at all. X2 showed a blocked loop
starves its own heartbeat; only a foreign process can reclaim.

### 4.4 A worker resuming after reclamation

| Check | Result | Action |
|---|---|---|
| Next heartbeat | 0 rows (owner changed) | mark self fenced |
| `assert_lease()` before a delivery call | no row | **abort, make no external call** |
| Completion transaction | 0 rows on the fence | discard result, discard projection, discard notification |
| Already inside a provider call | — | **cannot be interrupted.** C3. |

`assert_lease()`:

```sql
SELECT 1 FROM jobs
 WHERE id=$1 AND lease_owner=$2 AND status='running'
   AND lease_expires_at > now() AND hard_deadline_at > now();
```

PK-indexed, one read per irreversible delivery call. Required immediately before
**every** provider send/publish — not merely before the handler's completion write.

---

## 5. New tests

Real PostgreSQL required for U2, U4, U11–U15.

| ID | Setup | Injected | Required assertion |
|---|---|---|---|
| U1 | 1 job, 2 consumers, concurrent claim | — | Exactly one claim; C1 holds |
| U2 | A claims, blocks; B reclaims and completes; A unblocks | lease expiry between | A's fence UPDATE, domain UPDATE and `notify()` each affect **0 rows**; `fence_violation_total` +1 |
| U3 | A fenced; provider mock counts calls | — | `assert_lease()` returns 0 rows and **provider call_count unchanged** |
| U4 | A passes `assert_lease()`, then lease expires before the send | deliberate race | Send occurs — **asserting C3's residual window exists**. Documents the limit; must not be "fixed" |
| U5 | Outbox row `pending`, visibility timeout elapsed, heartbeat stale | outbox backlog | **No redispatch** (§3.2 `NOT EXISTS`); job stays `queued` |
| U6 | Outbox `dead`, heartbeat **stale**, attempts at max | lane down | Job **stays `queued`**; `lane_unavailable` alert; **not** `never_dispatched` (G4) |
| U7 | Outbox `sent`, heartbeat fresh, `total_lag=0`, attempts at max | — | `failed / never_dispatched` |
| U8 | 2 sweepers, same due job | concurrency | One `event_outbox` row; second sweeper updates via `ON CONFLICT` (G5) |
| U9 | Claim racing the `never_dispatched` update | concurrency | Exactly one wins; the loser writes 0 rows (G7) |
| U10 | Poison-payload job, consumer healthy, claimed every time | — | Reaches `dead` via retry exhaustion; **never** `never_dispatched` (dispatch_attempts reset on claim) |
| U11 | `hard_deadline_at` 30 s out, lease 60 s; heartbeat every 1 s for 10 s | — | `lease_expires_at <= hard_deadline_at` at every sample; deadline never passes (G3) |
| U12 | Control plane separate; handler suppresses `CancelledError` past lease (X1 pattern) | — | Reclaimed by the foreign process within `lease_seconds` |
| U13 | Hard deadline expires, `external_intent` set, no result | — | `ambiguous`, **not** `retrying` |
| U14 | Hard deadline expires, no intent | — | `retrying`, `next_run_at` set |
| U15 | CPU-blocking handler > lease (X2 pattern) | loop starvation | Foreign control plane reclaims; the blocked replica is not required to self-recover |
| U16 | `dedupe_key` NULL on existing events; 100 inserts | — | All succeed (Postgres NULL semantics); no regression to `auth-events` |
| U17 | Two sweepers, `payload` is `sa.JSON` (V14) | — | Lookup uses the indexed column, not `payload->>`; query plan uses `uq_event_outbox_dedupe_key` |

U6 and U11 are the two that encode the corrections. U4 deliberately asserts a *defect*
exists, so it cannot be silently "fixed" by over-claiming C3.

---

## 6. Readiness verdict

### Correctness blockers — all resolved by this audit

| # | Blocker | Resolution | New surface |
|---|---|---|---|
| B1 | I1 unachievable | Replaced with C1/C2/C3; C3 explicitly permanent | none |
| B2 | Fenced-write enumeration unknown | §2.3, six writes; `notify()` now included | none |
| B3 | Heartbeat unbounded | `hard_deadline_at` + SQL `LEAST()` | 1 column |
| B4 | `never_dispatched` unsafe | §3.3 four-part evidence; lane outage never blamed on a job | 1 table |
| B5 | Redispatch duplicates in-flight sends | `dedupe_key` + `UNIQUE` + `NOT EXISTS` | 1 column, 1 index |

All five are additions to the Phase 0 migration. None is irreversible, none requires
new infrastructure, and none alters the architecture.

### Not blockers — capacity tuning, all UNVERIFIED

`max_connections` (no database reachable, X3) · statement latency · per-lane
`T_p50`/`T_p95` · partition counts · `visibility_seconds` · `max_tenant_inflight` ·
pool sizes · tenant traffic distribution.

These change capacity and cost. **None appears in C1–C3 or in any transition guard.**

### Verdict

**Ready for Phase 0 implementation.**

The one thing this document will not claim: **Sayvors will not double-post to Google,
and will not double-message a customer, under lease expiry during an in-flight provider
call.** C3 and U4 state that as a permanent limitation of any design that does not
control the provider. What *is* guaranteed is that the duplication is bounded to one
in-flight call, is recorded as `ambiguous`, never auto-retries, and surfaces to an
operator with the intent payload attached.

That is the honest ceiling, and it is reached without new infrastructure.
