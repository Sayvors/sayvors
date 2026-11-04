# Plans, entitlements and AI credits

This document describes how a tenant's plan is resolved, how the free trial is
funded, where the plan is enforced, and which parts are deliberately not built
yet. It is the durable implementation reference; dated audit notes live in
`readiness-report.html`.

## 1. Plan catalog

Plans live in the `plans` table, not in application branches.

| Column | Meaning |
|---|---|
| `slug` | Stable identifier used by code (`free-trial`, `starter`, `pro`, `growth`, `enterprise`). |
| `price_cents` | Monthly price shown to the tenant. |
| `included_credit_cents` | AI credit bundled when the plan is activated. |
| `max_channels`, `max_messages_per_month` | Usage limits (null = unlimited). |
| `features` | JSON map of feature flags (`ai_replies`, `reviews`, `analytics`, ...). |
| `is_active`, `sort_order` | Catalog visibility and ordering. |

The launch rows are seeded by migration `1043cfd670ba`; migration
`a1c2e3f4b5d6` sets the free-trial credit to $10. Operators can edit the
catalog through `/api/v1/admin/plans` and the admin **Plans** page. Runtime
code must not add `if plan == "pro"` checks for entitlement decisions.

## 2. Resolution and enforcement

`billing/entitlements.py` is the only resolver:

1. Read the tenant's `tenant_subscriptions` row.
2. If a future `granted_until` exists, use the granted plan while it is active.
3. Otherwise use the subscription's base plan.
4. If there is no subscription, fall back to the active `free-trial` plan.

`get_entitlements()` returns the plan slug/name, status, limits, merged feature
flags, and the per-tenant override. `features_override` on the subscription is
merged over the plan per key; a tenant override never mutates the plan row.

Enforcement points:

- **AI calls:** `check_feature(tenant_id, "ai_replies")` plus the wallet
  reserve/settle gate in `llm/gateway.py`. The gate is fail-closed on an
  unreadable wallet and returns `402` when credit is exhausted.
- **Messaging:** `_ensure_messaging_quota()` counts human outbound messages
  against `max_messages_per_month`.
- **Channel/location connects:** the connect path checks the plan's channel
  limits before creating rows.

The resolver takes the tenant id from the authenticated context, never from a
request body, so a tenant cannot ask for another tenant's plan or override.

## 3. Free trial

`config.TRIAL_CREDIT_CENTS` defaults to `1000` ($10).

`billing/service.grant_trial_credit()` runs inside the signup transaction for
password, Google and Facebook signups, after the user id exists. It:

- writes one `billing_events` row with `kind=plan_grant` and the idempotency
  key `trial:<tenant_id>`;
- increases `users.ai_credit_cents` by the same amount;
- sets `users.plan` to `free-trial` when the user was on `free`;
- creates the `free-trial` subscription if the tenant has none.

The unique `(tenant_id, idempotency_key)` index is the duplicate boundary. A
retried signup, a duplicate social callback or a repeated backfill cannot grant
the credit twice. The signup is rolled back if the grant fails, so a tenant is
never created silently without the trial credit.

Existing accounts are handled by `scripts/backfill_trial_credits.py`. It is a
dry run by default, skips tenants that already have the trial event or a paid
subscription, and can target one email:

```bash
python -m scripts.backfill_trial_credits --email user@example.com --apply
```

## 4. Wallet and ledger

`users.ai_credit_cents` is the available wallet. It is changed only while the
user row is locked. `billing_events` is the audit trail:

- `plan_grant`, `credit_topup`, `credit_adjust` add credit;
- `ai_usage` rows are holds/settlements for one provider call;
- `balance_resync` is the one-time opening baseline for a tenant that predates
  the ledger.

`billing/ledger.py` reserves before the provider call and settles exactly once
afterward. A crash releases the hold through the reaper. Redis
`ai_balance:{tenant}` is only a cache; deleting it does not change the true
balance. A DB failure returns `503` and the provider call is not made.

## 5. Plan changes

There are two operator paths:

- `POST /api/v1/admin/tenants/{id}/plan` — legacy grant that sets
  `users.plan`, writes the wallet/ledger and syncs Redis. It now also updates
  the subscription so entitlements and the wallet agree.
- `POST /api/v1/admin/tenants/{id}/grant-plan` — changes the subscription row
  only. It is intended for support overrides and does not move credit.

Both require an admin session (`require_admin`), are rate-limited, and are
recorded in the admin audit middleware. A customer cannot call either route.

The customer-facing plans page is read-only. There is **no downgrade action**;
the current plan is disabled. Starter/Pro/Growth are disabled until a real
payment provider and webhook exist. Enterprise opens an email to
`it@sayvors.com` rather than pretending to charge a card.

## 6. Payment data

- Full card numbers and CVCs never reach the API. The browser validates the
  number locally and the stub tokenization route receives only brand, last
  four digits, expiry and cardholder name.
- Saved payment methods store brand/last4/expiry, never PAN or CVC.
- OAuth tokens, provider API keys and connection secrets use the credential
  encryption key; they are not stored in plan or billing rows.
- The current charge route is a stub. It moves no money, creates no
  subscription and grants no credit. Enabling real checkout requires a
  provider adapter plus a signature-verified, idempotent webhook.

## 7. Known gaps

1. Real payment checkout and webhook are not implemented.
2. Trial expiry is not enforced; the trial remains until an operator changes
   the plan, matching the current product decision.
3. The legacy grant endpoint accepts only `free` and `pro`; a full catalog
   grant should use plan slugs and the plan's `included_credit_cents`.
4. WABA/Meta conversation cost attribution is not tracked per tenant.
5. `features_override` changes are audited by the admin middleware, but there
   is no dedicated per-feature change history table.
