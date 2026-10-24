# Durable AI Credit Ledger — Design

Date: 2026-10-24
Status: implemented
Scope: `services/api` billing, LLM gateway, admin reconciler, worker reaper
Owner: platform/billing

Implementation: `billing/ledger.py` (reserve/settle/reaper/cutover/reconcile),
`billing/models.py` + `alembic/versions/i4j5k6l7m8n9_add_credit_ledger.py`
(schema), `billing/budget.py` (pricing + Redis mirror), `billing/service.py`
(reads/grants), `llm/providers/base.py` + `llm/gateway.py` (call sites),
`llm/usage.py` (cost/ledger link), `admin/router.py` (reconcile endpoint),
`workers/main.py` + `app/main.py` (reaper loop), and
`scripts/backfill_credit_ledger.py` (cutover). Tests:
`tests/test_credit_ledger.py` plus the migrated `tests/test_budget.py` and
`tests/test_llm_usage.py`. Operations: `docs/operations/credit-ledger-runbook.md`.

---

## 1. Problem

The wallet hotfix made the Redis counter survive restarts, but Redis is still the
live balance. That leaves three unacceptable properties for a billing system:

- a Redis loss can erase recent spend until a cold-path rebuild runs;
- the rebuild prices historical calls with today's price table and cannot see
  usage older than the 90-day retention window;
- a top-up, a spend, and an admin repair can race through different code paths.

The durable fix is a PostgreSQL ledger that records every credit movement and a
wallet row that can only be changed under a row lock. Redis becomes a cache.

## 2. Goals and non-goals

### Goals

- The DB is the source of truth for a tenant's available AI credit.
- Deleting the Redis key never changes the true balance.
- One reservation produces exactly one final charge or refund.
- Retrying `settle` cannot double-apply a charge.
- A crashed request releases its hold through a reaper.
- A top-up never re-grants credit that was already spent.
- Existing tenants can be migrated without a manual balance calculation per user.
- Operators can see and repair Redis drift without supplying a balance.

### Non-goals

- This document does not build plans, subscriptions, entitlements, checkout, or
  the customer/admin billing UI. Those are steps 3–6 of the readiness report.
- It does not change the price table or introduce per-model billing agreements.
- It does not make Redis highly available. Redis is no longer required for
  correctness, so its HA is an availability concern, not a billing one.

## 3. Source of truth

| Store | Role | May it decide a balance? |
|---|---|---|
| `users.ai_credit_cents` | Locked wallet row: available credit after pending holds | **Yes** |
| `billing_events` | Durable ledger: grants, holds, final charges, refunds, audit baselines | **Yes**, as the audit trail behind the wallet |
| `llm_usage_events` | Per-call metering; now carries `cost_cents` and `ledger_id` | No |
| Redis `ai_balance:{tenant}` | Best-effort read cache / compatibility mirror | No |

`users.ai_credit_cents` stops being a grants-only column. It is now the available
balance. The ledger explains how it got there.

### Invariants

1. Every wallet mutation runs in a transaction that first locks the tenant's
   `users` row with `SELECT ... FOR UPDATE`.
2. A reserve holds `RESERVE_CENTS` by decrementing the wallet and inserting a
   `pending` ledger row in the same transaction.
3. A settle changes the same ledger row to `settled` or `released`, applies
   `reserved - actual` back to the wallet, and records `balance_after_cents`.
4. A released or expired hold refunds exactly the amount that was held.
5. A settled or released hold is terminal for repeated settles; the second call
   returns the recorded result.
6. An expired hold that receives a late settle is charged (the refund is
   reversed); it does not become free usage.
7. `billing_events.balance_after_cents` equals the wallet after that event.
8. Redis is written only after the DB commit. A Redis failure never rolls back
   or changes a ledger result.

## 4. Schema

### 4.1 `billing_events` extension

The existing grant/audit table becomes the ledger. Existing rows remain valid.

| Column | Type | Notes |
|---|---|---|
| `id` | varchar(36) PK | Reservation id for `ai_usage` rows |
| `tenant_id` | varchar(36) FK users.id, indexed | Wallet owner |
| `kind` | varchar(32) | `plan_grant`, `credit_topup`, `credit_adjust`, `balance_resync`, `balance_reconcile`, `ai_usage` |
| `status` | varchar(16), default `posted` | `posted`, `pending`, `settled`, `released`, `expired` |
| `amount_cents` | integer | Final signed movement; negative for a charge, positive for a grant; 0 while pending or fully refunded |
| `reserved_cents` | integer, default 0 | Amount held at reserve time |
| `balance_after_cents` | integer, nullable | Wallet after this event |
| `model_id` | varchar(100), nullable | AI model for `ai_usage` |
| `prompt_tokens` | integer, default 0 | AI usage |
| `completion_tokens` | integer, default 0 | AI usage |
| `idempotency_key` | varchar(160), nullable | Unique per tenant when non-null |
| `expires_at` | timestamptz, nullable | Hold expiry |
| `settled_at` | timestamptz, nullable | Terminal timestamp |
| `note` | text, nullable | Operator/audit note |
| `created_by` | varchar(36), nullable | Admin/system id |
| `created_at` | timestamptz | Existing |
| `updated_at` | timestamptz | New |

Indexes:

- `UNIQUE (tenant_id, idempotency_key)` — NULLs do not collide.
- `(status, expires_at)` — reaper scan.
- `(tenant_id, status)` — tenant ledger/reconcile views.

### 4.2 `llm_usage_events` extension

| Column | Type | Notes |
|---|---|---|
| `cost_cents` | integer, default 0 | Priced cost used for the charge |
| `ledger_id` | varchar(36), nullable, indexed | `billing_events.id` for the hold |

This gives the reconciler a way to recover a charge when the settle call died
after the provider returned.

### 4.3 Ledger row kinds

| Kind | Status | Meaning |
|---|---|---|
| `plan_grant` | `posted` | Plan activation/top-up credit |
| `credit_topup` | `posted` | Explicit top-up |
| `credit_adjust` | `posted` | Manual adjustment |
| `balance_resync` | `posted` | One-time opening balance or legacy baseline |
| `balance_reconcile` | `posted` | Audit row for a Redis repair (amount 0) |
| `ai_usage` | `pending` | Live hold |
| `ai_usage` | `settled` | Final charge (amount negative) |
| `ai_usage` | `released` | Provider failed before delivery; full refund |
| `ai_usage` | `expired` | Reaper refunded a crashed/abandoned hold |

A single `ai_usage` row per LLM call is the ledger entry for that call. The row
is inserted at reserve time and finalized at settle time, so a retry cannot
create a second charge.

## 5. Flows

### 5.1 Reserve

```
reserve(tenant, cents, model_id, idempotency_key?)
  open session
  SELECT users ... WHERE id=tenant FOR UPDATE
  ensure opening ledger row if this tenant predates the ledger
  if balance < cents: commit opening (if created), raise BudgetExhausted
  balance -= cents
  INSERT billing_events(kind=ai_usage, status=pending,
                        amount=0, reserved=cents, balance_after=balance,
                        expires_at=now+HOLD_TTL)
  COMMIT
  best-effort Redis SET balance
  return Reservation(id, tenant, cents)
```

`BudgetExhausted` maps to HTTP 402. A DB failure maps to `BudgetUnavailable`
(HTTP 503) and the provider is never called. This is a deliberate change from
the old fail-open Redis policy: a budget gate must fail closed.

### 5.2 Settle

```
settle(reservation, actual_cents)
  open session
  SELECT billing_events WHERE id=reservation.id FOR UPDATE
  if status in (settled, released): return recorded result
  SELECT users ... FOR UPDATE
  if status == pending: balance += reserved - actual
  if status == expired: balance -= actual      # refund is reversed
  status = settled if actual > 0 else released
  amount = -actual
  balance_after = balance
  settled_at = now
  COMMIT
  best-effort Redis SET balance
```

`actual_cents` is clamped at zero. If `actual > reserved`, the wallet may go
negative and future reserves are denied; the overage is logged. This is better
than silently capping a real provider cost.

### 5.3 Failure and reaper

- Provider failure calls `settle(reservation, 0)`; the hold is released and the
  full amount returns to the wallet.
- A process crash leaves a `pending` row. The reaper runs every 60 seconds:
  1. recover pending holds that already have a matching `llm_usage_events` row
     with `cost_cents > 0` and settle them;
  2. expire the rest after `HOLD_TTL_SECONDS`, refunding the hold.
- A settle that arrives after expiry reverses the refund and charges the actual
  cost.
- Multiple workers are safe: the reaper locks each row with
  `FOR UPDATE SKIP LOCKED`; a settle that wins the lock makes the reaper skip.

## 6. Opening balance and cutover

Existing tenants have grants in `billing_events` and spend in
`llm_usage_events`, but `users.ai_credit_cents` is grants-only. The first ledger
operation for a tenant creates a one-time opening row:

- kind `balance_resync`, amount 0, status `posted`;
- `balance_after_cents` = legacy `compute_balance()` result (grants minus
  metered non-voice spend, starting at any existing resync baseline);
- `idempotency_key = ledger-opening:{tenant_id}` so a retry cannot double-apply;
- `users.ai_credit_cents` set to the same value in the same transaction.

`compute_balance()` remains available for this bootstrap, the backfill script,
and audit reports, but it is no longer on the runtime `GET /billing/budget`
path. After the opening row exists, the wallet column and ledger are
authoritative and the computed path is never used again for that tenant.

### Backfill script

`services/api/scripts/backfill_credit_ledger.py`:

- default dry run: prints tenants that still need an opening row, their computed
  balance, and the reliability flag;
- `--apply`: creates the opening row and sets the wallet;
- `--tenant-id`: one tenant;
- `--limit`: bounded run;
- `--force`: apply a balance whose spend window predates usage retention.

Recommended cutover order:

1. Apply the migration (adds columns/indexes only; no balance writes).
2. Run the backfill dry run and review unreliable tenants.
3. Apply the backfill while the old code is still serving (the opening row is
   idempotent and the old Redis path is untouched).
4. Deploy the ledger-aware code.
5. Delete Redis keys only after verifying `GET /billing/budget` still shows the
   same balance.

The lazy opening path makes step 3 optional for small deployments, but the
script is still the auditable path.

## 7. Admin reconciler

The old `/resync-balance` recomputed the DB from usage, which is no longer safe
once the ledger is authoritative. The endpoint keeps its path for compatibility
but now reconciles **Redis to DB**:

- preview: show `db_balance_cents`, `redis_balance_cents`, and `delta_cents`;
- apply: lock the user, write a `balance_reconcile` audit row only if Redis is
  missing or differs, then sync Redis;
- never accept a client-supplied balance;
- re-running with no drift writes no audit row.

## 8. Concurrency and failure modes

| Scenario | Result |
|---|---|
| Two reserves on the last 5 cents | One locks first and succeeds; the second sees the reduced balance and gets 402 |
| Two settles for one reservation | First wins; second sees terminal status and returns the recorded result |
| Grant during a pending hold | Grant locks the same user row; it adds to available balance without releasing the hold |
| Grant during settle | Serialized by the user row lock; both effects apply exactly once |
| Redis down | DB still reserves/settles; Redis sync logs a warning; `GET /billing/budget` is correct |
| DB down | Reserve raises 503; no provider call and no free usage |
| Settle call dies after provider returns | Usage row carries `ledger_id` + cost; reaper settles it before expiry |
| Reaper crashes mid-refund | Row lock + terminal status make the next pass idempotent |
| Late settle after expiration | Refund is reversed and actual cost is charged |

## 9. Observability

- Reserve failure: tenant, amount, reason (insufficient/DB).
- Settle overage: tenant, reservation id, reserved, actual.
- Reaper: recovered count, expired count, total refunded.
- Reconcile: tenant, DB balance, Redis balance, delta, operator, audit row id.
- Redis mirror failures are warnings, never errors that break the request.

## 10. Test plan

- reserve/settle round trip updates wallet, ledger row, and Redis mirror;
- empty wallet raises 402 without creating a pending row;
- settle is idempotent;
- provider failure releases the full hold;
- expired hold refunds; late settle charges;
- deleting Redis does not change `GET /billing/budget`;
- top-up after spend does not re-grant spent credit;
- opening balance is one-time and idempotent;
- reconcile preview/apply is idempotent and writes one audit row only on drift;
- DB failure denies the provider call;
- usage row stores cost + ledger id;
- existing admin resync tests are rewritten for reconciler semantics.

Targeted commands:

```bash
cd services/api
python -m pytest tests/test_budget.py tests/test_llm_gateway_boundary.py tests/test_llm_usage.py -q
```

Run the full suite only if a shared model/config change requires it.

## 11. Acceptance mapping

| Requirement | How this design satisfies it |
|---|---|
| Deleting Redis key does not change true balance | `GET /billing/budget` and reserve/settle read/write `users.ai_credit_cents` |
| Re-running resync is idempotent | Reconciler only writes an audit row when Redis differs, then makes it match |
| Top-up never re-grants spent credit | Grants add to the locked wallet; they do not recompute from grants |
| One charge per reservation | `ai_usage` row is created once at reserve and finalized once at settle |
| Crashed request releases hold | Reaper refunds pending holds after TTL |
| Admin cannot supply a balance | Reconciler target is always the DB wallet |
