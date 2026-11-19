# Benchmark & History — Design Specification

Date: 2026-11-19
Status: design approved for planning

## Goal

One enterprise-facing surface for competitor benchmarking and business history:
search for any business, save it to a personal bench, see live comparison
cards, drill into a detail inspection with AI-written analysis and charts, and
view saved places on a map. Saved places are refreshed on a schedule so trends
accumulate over time.

## Scope

Five ordered slices, each with its own implementation plan:

1. Search + bench (find a business, save it, list saved places)
2. Bench cards (live values, colour-coded comparison against the tenant)
3. Detail inspection (reviews, AI analysis, charts)
4. Collector (scheduled refresh, snapshots, trends)
5. Map (saved-place markers + density layer)

## Architecture

Backend units, each independently testable:

- `places/search.py` — Places Text Search with location bias. Bounded 20 results.
- `places/details.py` — Place Details by `place_id`, field-masked to the fields
  the UI renders.
- `benchmark/service.py` — bench CRUD, snapshot append, trend computation,
  comparison colours, tenant scoping.
- `benchmark/collector.py` — durable refresh jobs, one per place; claims with
  `FOR UPDATE SKIP LOCKED`; per-tenant in-flight cap; lease-based retries.
- `benchmark/ai.py` — review/photo analysis through the existing metered LLM
  gateway.
- `benchmark/retention.py` — prunes snapshots past the configured window using
  the existing batched retention framework (2000 rows/statement, 20 runs).

Frontend: a new Benchmark page holding search, saved bench, detail view, map
and charts, plus a small "add to bench" action where relevant.

## Data model

- `benchmark_place` — tenant-scoped row: `place_id` (always stored), tenant's
  own label and notes, cached provider fields (name, rating, review count,
  reviews, photos, fetched_at).
- `benchmark_snapshot` — timestamped copy of those fields, unique on
  `(place_id, fetched_at)` so retries cannot double-insert.
- `benchmark_config` — single admin row:
  - `place_cache_enabled` (default true in this build) — whether snapshots and
    cached provider fields are written
  - `retention_days` (default 2; admin-settable 1/2/10/30)
  - `refresh_hours` (default 24; 1/6/24/72)
  - `max_saved_places` (default 50 per tenant)

When `place_cache_enabled` is false, only `place_id` and tenant-authored notes
persist; provider fields are fetched live and discarded after the response.

## Data flow

1. Tenant types a query → API calls Places Text Search with location bias →
   results returned with Google attribution.
2. Tenant saves a result → only `place_id` + tenant label/notes are committed;
   cached fields are written if enabled.
3. Bench page loads saved places → one detail request per place, bounded and
   parallel; cards show current rating/review count and comparison colour.
4. Clicking a card opens detail → reviews, photos, trend charts, AI summary.
5. Collector refreshes saved places on schedule → append snapshot, compute
   trend; failures retry then dead-letter.
6. Retention prunes snapshots older than `retention_days`.

## Comparison colour

Colour is computed against the tenant's own business for the same category
and city:
- green — competitor materially worse than you (rating lower by >= 0.3, or
  review count lower by >= 20% at similar rating)
- amber — within the same band
- red — competitor materially better

The formula is a named function with tests; no magic numbers in components.

## Aesthetic direction

"Editorial data desk": dense, factual, tabular, restrained. Neutral surfaces,
one accent reserved for comparison colour, monospaced numbers, visible source
labels. No gradients, no decorative cards, no competing colours.

## UX state coverage (required)

- empty bench (search prompt)
- search loading skeleton
- search failure with retry
- no results
- place with no reviews
- trend with one snapshot ("history starts here")
- collector failure (last-known badge with age)
- saved-place cap reached
- slow connection (stream/placeholder, never blank)

All states are implemented with the first version of each screen.

## Error handling

- Provider failure → last-known values with an explicit age badge; never
  present stale data as fresh.
- AI failure → summary absent, reviews and charts still shown.
- Snapshot write failure → job retry with backoff, dead-letter after cap.
- Tenant scoping enforced in every query by construction.
- Every provider call goes through the existing rate limiter and field masks.

## Testing

- Unit: colour computation, trend math, snapshot idempotency, retention.
- API: tenant scoping, save/list/detail, config flag behaviour, caps.
- Integration: search → save → bench card → detail → charts → map.
- Static guard: no provider field is persisted when the flag is off.
- Full backend suite + web `tsc` + build before each slice is committed.

## Out of scope for this design

- Local search rank history (not available from any source)
- OpenStreetMap for provider-sourced points (Google Maps required)
- Training models on provider content
- Calling / voice features
