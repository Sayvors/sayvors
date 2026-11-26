# Benchmark metric scope

**Date:** 2026-11-25
**Status:** Accepted

## Decision

The primary benchmark comparison stays at six reputation metrics:

1. Total reviews
2. Average rating
3. Reviews in the last 30 days
4. Reviews in the last 12 months
5. Five-star share
6. One-star share

Secondary evidence (review themes, response coverage, sentiment, history, completeness, and branch actions) remains below the primary matrix. This prevents metric sprawl and keeps the client-facing comparison readable.

## Deferred capabilities

### Action-rate KPI

Deferred until “actions” has a defined, measurable numerator. Calls alone are not actions, and dividing an undefined action count by impressions would create a false KPI.

### AI-search visibility band

Deferred until a licensed data source or approved API exists. Sayvors will not infer AI-answer visibility from review or listing data.

## Guardrails

- No national or synthetic average is presented as the headline benchmark.
- Every chart answers a named owner question and shows its comparison basis.
- Missing evidence stays blank or explicitly unavailable, never zero.
- No new charting dependency is introduced.
- `apps/web/lib/benchmark-rows.test.ts` pins the six-metric contract.
