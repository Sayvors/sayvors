# Benchmark Slice 1: Search & Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tenants can search Google Places for any business and save it to a personal, tenant-scoped bench.

**Architecture:** New `benchmark` module with three units: `places.py` (Google Places Text Search + Details), `service.py` (bench CRUD, caps, tenant scoping), `router.py` (API). Models/migration include all three tables from the spec so later slices need no new migration. Frontend adds one Benchmark page with search, results and saved bench.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, httpx, Google Places API (New), React + TanStack Query.

---

## File map

- Create `services/api/app/modules/benchmark/__init__.py` — empty package marker
- Create `services/api/app/modules/benchmark/models.py` — BenchmarkPlace, BenchmarkSnapshot, BenchmarkConfig
- Create `services/api/app/modules/benchmark/places.py` — Places search + details, bounded, with PlacesError
- Create `services/api/app/modules/benchmark/service.py` — save/list/delete with caps and tenant scoping
- Create `services/api/app/modules/benchmark/router.py` — five endpoints
- Modify `services/api/app/main.py` — include router
- Create `services/api/alembic/versions/20261118170000_benchmark.py` — tables
- Create `services/api/tests/test_benchmark_places.py` — provider unit tests
- Create `services/api/tests/test_benchmark_bench.py` — service + API tests
- Create `apps/web/lib/api-benchmark.ts` — typed client
- Create `apps/web/app/dashboard/benchmark/page.tsx` — search + saved bench UI

## Task 1: models + migration

- [ ] Create `benchmark/__init__.py` with a one-line docstring.
- [ ] Create `benchmark/models.py`:
  - `BenchmarkConfig(id="default", place_cache_enabled=True, retention_days=2, refresh_hours=24, max_saved_places=50, updated_at)`
  - `BenchmarkPlace(id, tenant_id FK users CASCADE, place_id String(255), label String(120), notes Text, name String(255), rating Float, review_count Integer, reviews JSON, photos JSON, fetched_at DateTime, created_at, updated_at)`, unique `(tenant_id, place_id)`, index `(tenant_id, created_at)`
  - `BenchmarkSnapshot(id, place_id FK benchmark_places CASCADE, tenant_id, rating, review_count, reviews JSON, fetched_at)`, unique `(place_id, fetched_at)`
- [ ] Create migration `20261118170000_benchmark.py` with `CREATE TABLE IF NOT EXISTS` for all three and the indexes; downgrade drops them.
- [ ] Verify: `python -m py_compile <migration>` and `pytest tests/test_benchmark_bench.py -q` (will fail until Task 3 — acceptable, this task has no tests of its own).
- [ ] Commit: `git add ... && git commit -m "feat(benchmark): models and migration"`

## Task 2: Places client

- [ ] Create `benchmark/places.py` following `locations/places.py` patterns:
  - `PLACES_TEXT_SEARCH_URL`, `PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{id}"`
  - `MAX_SEARCH_RESULTS = 20`, `REQUEST_TIMEOUT_SECONDS = 15`
  - `class PlacesError(Exception)` with `status_code`
  - `async def search_places(query: str, *, language="en", region="SA") -> list[dict]` — POST with `textQuery`, `maxResultCount`, field mask `places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.types`; return list of `{place_id, name, address, rating, review_count, types}`; normalise `places/` prefix; raise PlacesError on missing key/network/non-200 using `upstream_http_error`-style generic text.
  - `async def get_place(place_id: str, *, language="en") -> dict` — GET details with field mask including `reviews`, `photos`, `rating`, `userRatingCount`.
- [ ] Add `tests/test_benchmark_places.py` with a fake httpx transport: search maps fields and strips prefix; missing key raises 503; details maps reviews/photos; non-200 raises generic PlacesError without response body.
- [ ] Run `pytest tests/test_benchmark_places.py -q` → pass.
- [ ] Commit.

## Task 3: bench service

- [ ] Create `benchmark/service.py`:
  - `class BenchError(ValueError)` — safe client messages
  - `async def get_config(db) -> BenchmarkConfig` — create default row if absent
  - `async def save_place(db, tenant_id, *, place_id, label, notes) -> BenchmarkPlace` — validate length, dedupe by `(tenant_id, place_id)`, enforce `max_saved_places`, commit
  - `async def list_saved(db, tenant_id, limit=50) -> list[dict]` — tenant-scoped, newest first
  - `async def delete_saved(db, tenant_id, place_id) -> None`
  - `def serialize(place) -> dict` — camel-free snake_case fields
- [ ] Add `tests/test_benchmark_bench.py` service tests: save, duplicate rejected, cap enforced, list tenant-scoped, delete only own.
- [ ] Run → pass.
- [ ] Commit.

## Task 4: API

- [ ] Create `benchmark/router.py` with prefix `/api/v1/benchmark`:
  - `GET /search?q=&limit=` → `search_places` (requires `benchmark.view` permission — add to permission catalog if absent)
  - `GET /places` → saved list
  - `POST /places` body `{place_id, label?, notes?}` → save (201)
  - `DELETE /places/{place_id}` → delete
  - `GET /config` → admin-only config read (later slices add admin PUT)
- [ ] Register router in `app/main.py` next to the other routers.
- [ ] Add API tests to `test_benchmark_bench.py`: search requires permission, saves scoped to tenant, cap returns 422, delete is tenant-scoped.
- [ ] Run → pass.
- [ ] Commit.

## Task 5: frontend

- [ ] Create `apps/web/lib/api-benchmark.ts` with types and `searchPlaces`, `fetchSavedPlaces`, `saveBenchmarkPlace`, `deleteBenchmarkPlace`.
- [ ] Create `apps/web/app/dashboard/benchmark/page.tsx`: search input with debounce, results list with save buttons, saved bench list with delete, empty/loading/error states, Google Maps attribution text on results. Aesthetic: editorial data desk (neutral surfaces, monospaced numbers, one accent).
- [ ] Add nav entry to the web dashboard navigation.
- [ ] Run `npx tsc --noEmit` and `npm run build`; commit.

## Task 6: full verification

- [ ] Full backend suite (models/migration = cross-cutting), web `tsc` + build.
- [ ] Update readiness report with slice 1 status.
- [ ] Commit; no push unless asked.
