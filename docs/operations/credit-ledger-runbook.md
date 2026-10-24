# AI Credit Ledger — Operations Runbook

Date: 2026-10-24
Applies to: `services/api`, `billing_events`, `llm_usage_events`, `users.ai_credit_cents`
Design: `docs/specs/2026-10-24-durable-credit-ledger-design.md`

---

## 1. What is authoritative

| Store | Role |
|---|---|
| `users.ai_credit_cents` | Available credit after pending holds. Locked with `FOR UPDATE` on every change. |
| `billing_events` | Ledger: grants, holds, final charges, refunds, opening/reconcile audit rows. |
| `llm_usage_events` | Per-call metering. `cost_cents` + `ledger_id` let the reaper recover a charge. |
| Redis `ai_balance:{tenant}` | Cache mirror. Never decides a charge. No TTL. |

If Redis and Postgres disagree, **Postgres wins**. The admin reconcile endpoint
overwrites Redis with the DB value; it never accepts a balance from the caller.

---

## 2. Deploy order

1. **Back up the database.** The migration only adds columns/indexes, but a
   restore point makes rollback boring.
2. **Apply the migration.**
   ```bash
   cd services/api
   python -m alembic upgrade head
   ```
   Verify the single head first:
   ```bash
   python -m alembic heads
   # i4j5k6l7m8n9 (head)
   ```
3. **Run the backfill dry run.**
   ```bash
   python scripts/backfill_credit_ledger.py
   ```
   Review every `UNRELIABLE` tenant. That flag means the spend window predates
   `USAGE_EVENT_RETENTION_DAYS` (90 days), so old spend was pruned and the
   computed balance is an upper bound.
4. **Apply the backfill.**
   ```bash
   python scripts/backfill_credit_ledger.py --apply
   # one tenant:
   python scripts/backfill_credit_ledger.py --apply --tenant-id <uuid>
   # review-only batches:
   python scripts/backfill_credit_ledger.py --apply --limit 500
   ```
   `--force` is required to open a tenant with a retention gap. Do not force a
   tenant you have not reviewed.
5. **Deploy the ledger-aware API and worker.** The worker must run the
   `credit-hold-reaper` loop (it is in the default loop set). If `WORKER_LOOPS`
   is an allowlist, add `credit-hold-reaper`.
6. **Verify the cutover.**
   - `GET /api/v1/billing/budget` returns the same balance the backfill
     reported.
   - Delete one tenant's Redis key; the endpoint still returns the same number.
   - Run one AI call; the wallet decreases by the real cost and a `settled`
     `ai_usage` row exists.
7. **Only then** treat Redis as disposable.

The API also lazily opens a tenant on its first wallet read/reserve/grant, so a
missed tenant is not stranded. The script is still the auditable path.

---

## 3. Reaper

Loop name: `credit-hold-reaper` (worker), also started in the API process when
`RUN_BACKGROUND_WORKERS=true` for local/dev.

Every 60 seconds:

1. **Recover priced holds.** A hold with a matching `llm_usage_events` row
   (`ledger_id`, `cost_cents > 0`) is settled to that cost. This is the crash
   window where the provider returned but `settle` died.
2. **Expire the rest.** Pending holds older than `HOLD_TTL_SECONDS` (15 min) are
   marked `expired` and the full hold is refunded.

Safe to run twice or on many replicas: each row is re-selected under
`FOR UPDATE` and a terminal status is skipped.

### Manual run

There is no admin endpoint for the reaper (it is not a money-moving API). Use a
one-off shell inside the API container:

```bash
cd services/api
python - <<'PY'
import asyncio
from app.modules.billing.ledger import reap_once
print(asyncio.run(reap_once()))
PY
```

Expected output: `{'recovered': n, 'expired': m}`.

---

## 4. Admin reconciliation

Endpoint: `POST /api/v1/admin/tenants/{user_id}/resync-balance`

- Default `{"dry_run": true}`: reports `db_balance_cents`,
  `redis_balance_cents`, and `delta_cents`.
- Apply `{"dry_run": false}`: locks the user, writes one zero-amount
  `balance_reconcile` audit row **only if the cache is missing or differs**,
  then overwrites Redis with the DB balance.
- Re-running with no drift writes no audit row.

The old behavior (recompute the DB from grants minus usage) is gone. If a
tenant's DB balance is wrong, use the backfill report and fix the data
explicitly; do not use this endpoint to invent a balance.

---

## 5. Useful SQL

```sql
-- Available wallet + active holds for one tenant
SELECT u.id, u.ai_credit_cents,
       COALESCE(SUM(b.reserved_cents) FILTER (
           WHERE b.kind = 'ai_usage' AND b.status = 'pending'), 0) AS held_cents
FROM users u
LEFT JOIN billing_events b ON b.tenant_id = u.id
WHERE u.id = :tenant_id
GROUP BY u.id, u.ai_credit_cents;

-- Pending holds, oldest first
SELECT id, tenant_id, reserved_cents, expires_at, created_at
FROM billing_events
WHERE kind = 'ai_usage' AND status = 'pending'
ORDER BY expires_at
LIMIT 100;

-- Charges whose usage row exists but the hold is still pending (reaper input)
SELECT b.id, b.tenant_id, b.reserved_cents, u.cost_cents
FROM billing_events b
JOIN llm_usage_events u ON u.ledger_id = b.id
WHERE b.kind = 'ai_usage' AND b.status = 'pending'
  AND u.cost_cents > 0;

-- Ledger for one tenant
SELECT created_at, kind, status, amount_cents, reserved_cents,
       balance_after_cents, model_id, idempotency_key
FROM billing_events
WHERE tenant_id = :tenant_id
ORDER BY created_at DESC, id DESC
LIMIT 100;

-- Tenants that still have no opening row
SELECT u.id
FROM users u
LEFT JOIN billing_events b
  ON b.tenant_id = u.id
 AND b.idempotency_key = 'ledger-opening:' || u.id
WHERE b.id IS NULL;
```

---

## 6. Failure playbook

### Redis is down

- Reserve/settle still work; the DB is authoritative.
- Logs show `AI budget cache sync failed ... (DB remains authoritative)`.
- When Redis returns, run the admin reconcile for affected tenants, or just let
  the next reserve/settle overwrite the mirror.
- Do not roll back the ledger because the cache is down.

### Postgres is down or a lock times out

- Reserve raises `BudgetUnavailable` → HTTP 503; the provider is not called.
  This is intentional fail-closed behavior.
- Do not switch the code back to a Redis-only reserve as a "temporary" fix; it
  would create spend with no durable record.

### A hold never expires

1. Check the worker is running the `credit-hold-reaper` loop.
2. Run the manual reaper command above.
3. If the row is still pending, check `expires_at` and the row lock:
   ```sql
   SELECT id, status, reserved_cents, expires_at, settled_at
   FROM billing_events WHERE id = :hold_id;
   ```
   A live settle may be holding the row lock. Do not force-update the row while
   a request may still settle; wait for the request deadline.

### A wallet is negative

This is a real overage: the provider cost exceeded the hold. Future reserves
are denied until a top-up covers the debt. Do not clamp the DB value to zero;
that would give away the overage. The customer-facing budget endpoint returns
the debt as a negative balance so support can see it.

### A settle failed after the provider returned

The usage row carries `ledger_id` and `cost_cents`. The reaper settles it on the
next pass. If you need to recover immediately:
```python
from app.modules.billing.ledger import settle, Reservation
await settle(Reservation(id=hold_id, tenant_id=tenant_id, amount_cents=reserved), cost_cents)
```
Settle is idempotent; a second call returns the recorded result.

### A duplicate charge is suspected

Settle changes the existing `ai_usage` row; it never inserts a second charge.
Check for two `ai_usage` rows with the same `idempotency_key` (should be
impossible under the unique index) or two provider calls sharing one hold.
The ledger row's `id` is the reservation id; use it in the provider logs.

---

## 7. Rollback

- **Before traffic uses the ledger:** downgrade the migration and redeploy the
  old code. The columns are additive; no balance data was moved unless the
  backfill ran.
- **After traffic uses the ledger:** prefer a forward fix. The old code treats
  Redis as the balance, so a code rollback after ledger traffic would ignore
  pending holds and could re-spend held credit. If rollback is unavoidable:
  1. Stop AI traffic and the worker.
  2. Run the reaper until `pending` holds are zero.
  3. Reconcile every affected tenant's Redis mirror to the DB.
  4. Deploy the old code.
  5. Leave the migration in place (it is additive); re-upgrade later.

Do not drop `billing_events` columns while any ledger-aware process is running.

---

## 8. Acceptance checklist

- [ ] `alembic heads` reports exactly one head (`i4j5k6l7m8n9`).
- [ ] Backfill dry run reviewed; every `UNRELIABLE` tenant either forced with a
      reason or left for manual review.
- [ ] `GET /billing/budget` matches the backfill balance.
- [ ] Deleting one tenant's `ai_balance:` key does not change the endpoint.
- [ ] One AI call produces a `pending` hold that becomes `settled`, and the
      wallet decreases by the real cost.
- [ ] A provider failure produces a `released` hold and a full refund.
- [ ] Re-running the admin reconcile with no drift writes no audit row.
- [ ] The worker runs `credit-hold-reaper`.
