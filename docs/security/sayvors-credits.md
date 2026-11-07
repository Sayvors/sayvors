# Sayvors Credits pricing (v1.0)

Last updated: 2026-11-07.

## The formula

- 1,000 SC = $1 → 1 SC = $0.001 (admin-editable).
- Target gross margin 60% → price = delivery cost ÷ (1 − 0.60) = cost × 2.5.
- Credits per $1 of delivery cost = rate × multiplier (1,000 × 2.5 = **2,500 SC**).

Everything is configurable from **Admin → Pricing → Sayvors Credits & margin**:

| Setting | Default | Meaning |
|---|---|---|
| `sc_per_usd` | 1,000 | Credits per US dollar |
| `margin_bp` | 6,000 | Target margin in basis points (60%) |
| `infra_cost_micro_usd` | 0 | Attributable infrastructure added to every call |

Changing any of them applies to the next metered call — no deploy, no migration.

## Where it is calculated

`billing/pricing.py`:

- `llm_provider_cost_micro_usd()` — tokens × rate card, in micro-USD (1e-6).
- `llm_cost_micro_usd()` — provider cost + infrastructure.
- `charge_micro_usd()` — cost × multiplier, using integer basis points.
- `credits_micro_for()` — charge × `sc_per_usd`, in micro-SC (1e-6 SC).
- `llm_cost_cents()` — the wallet charge; it applies the margin and rounds
  **once per call** to the ledger's current cent unit.

## Audit trail

Every `llm_usage_events` row now stores integers:

`provider_cost_micro_usd`, `infrastructure_cost_micro_usd`,
`delivery_cost_micro_usd`, `charge_micro_usd`, `credits_micro`,
`margin_bp`, `sc_per_usd`, `pricing_version`.

No float is persisted, so any call can be replayed against the rate card that
priced it. The tenant wallet is still stored in cents (existing holds/grants);
the API exposes `credits_per_usd` and `balance_credits` for display.

## Margin reality

60% is a gross-margin target, not net profit. Salaries, marketing, fixed
hosting, tax and promotional credits are outside this calculation. Promotional
grants reduce realized revenue and should be included in any margin report.

## Known limit

The durable ledger settles in cents, so a single call rounds up to the next
cent (at most $0.01). The usage row retains the exact micro-USD charge; a
future ledger migration to micro-USD can remove the residual rounding.
