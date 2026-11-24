# Review Keyword Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract repeatable praise and complaint themes from cached BOQ/own reviews, store them durably per business, and show an evidence-backed comparison grid on the Benchmark compare page.

**Architecture:** A bounded extractor builds a normalized review sample and sample hash. A durable job runs LLM extraction with strict schema validation and a local frequency-based fallback. Results are stored per tenant/subject and reused until the sample hash changes. The compare API returns cached/pending status plus cross-business theme rows; the UI polls pending jobs and opens real review quotes from each theme cell.

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic, existing jobs worker, existing LLM gateway, Redis, React/Next.js, Vitest/Testing Library, Playwright.

---

## Non-negotiable invariants

- No predefined domain keyword list; themes come from review text.
- Mention counts are distinct-review counts, never raw substring occurrences.
- A theme needs at least two distinct reviews and a minimum sample share.
- Counts are labelled as sampled evidence, not Google lifetime totals.
- Extraction is asynchronous and durable; compare page loads never wait on an LLM.
- Results are tenant-scoped, bounded, cached by sample hash, and idempotent.
- LLM output is schema-validated; invalid/provider-failed output falls back to local extraction.
- English and Arabic text are normalized without changing the displayed original quote.
- Every theme cell links to real source reviews.
- No gradients, glassmorphism, word clouds, or color-only meaning.

---

## File structure

- Create `services/api/app/modules/benchmark/theme_extraction.py` — pure local extractor, normalization, validation, comparison grouping.
- Create `services/api/app/modules/benchmark/theme_jobs.py` — durable job handler and LLM orchestration.
- Create `services/api/app/modules/benchmark/theme_service.py` — sample building, hashing, cache read/enqueue, API response assembly.
- Modify `services/api/app/modules/benchmark/models.py` — durable theme analysis row.
- Modify `services/api/app/modules/benchmark/router.py` — theme status/comparison endpoint.
- Modify `services/api/app/modules/benchmark/compare.py` — shared review-sample access where needed.
- Create Alembic migration — analysis table and job-type enum value.
- Create `services/api/tests/test_benchmark_themes.py` — extractor, validation, fallback, scoping, hash reuse, API/job tests.
- Create `apps/web/components/benchmark/ReviewKeywords.tsx` — evidence grid, filters, summary, quote drawer.
- Create `apps/web/components/benchmark/ReviewKeywords.test.tsx` — rendering, pending/error/empty, filters, quote drill-down.
- Modify `apps/web/lib/api-benchmark.ts` — theme contracts and fetch/poll function.
- Modify `apps/web/app/dashboard/benchmark/compare/page.tsx` — mount section and poll while pending.
- Modify `apps/web/lib/i18n/en.ts` and `ar.ts` — theme section copy.
- Create `docs/plans/2026-11-24-review-keyword-extraction.md` — this plan.

---

## API contract

`GET /api/v1/benchmark/themes?subjects=...` and `POST /api/v1/benchmark/themes/retry` return:

```ts
{
  subjects: [{
    key, name, kind, status: "ready" | "pending" | "unavailable" | "error",
    sample_size, sample_hash, analyzed_at, source?, error_code?, error_message?
  }],
  rows: [{
    key, label, sentiment: "positive" | "negative" | "mixed",
    cells: Record<subjectKey, {
      mentions, sample_size, percentage, positive, negative,
      quotes: [{ review_id, quote, review_text, rating, author,
                 author_photo, reviewed_at, review_url }]
    }>,
    own_pct, peer_median_pct, gap_pct, max_mentions
  }]
}
```

- `mentions` counts distinct reviews.
- `percentage = mentions / sample_size × 100`.
- Quotes are verbatim substrings of `review_text`.
- Pending/unavailable/error are never rendered as zero.
- The selected left subject may be a saved competitor; the API receives `main` explicitly.

---

## Tasks

### Task 1: Pure extraction and validation

**Files:**
- Create: `services/api/app/modules/benchmark/theme_extraction.py`
- Create: `services/api/tests/test_benchmark_theme_extraction.py`

- [x] Write failing tests for distinct-review counting, single-mention rejection, Arabic normalization, LLM count/index validation, real evidence selection, and cross-business grouping.
- [x] Run `python -m pytest tests/test_benchmark_theme_extraction.py -q -n 0` and confirm the expected failures.
- [x] Implement `normalize_theme_key`, `_token_pairs`, `extract_local_themes`, `_build_theme`, `validate_llm_themes`, and `group_theme_comparison`.
- [x] Keep only function-word and generic-filler stoplists (never domain keywords); require multi-word themes so names, religious phrases, and single filler words do not become rows.
- [x] Count document frequency per review, sort bigram/trigram tokens for order-insensitive matching, preserve original surface labels/quotes, and compute sentiment from real review ratings/classification.
- [x] Validate LLM `mentions` and `review_indices` against the real bounded sample; reject the whole payload on invented counts/indices.
- [x] Run the focused tests and confirm all eight pass.

### Task 2: Durable storage and job pipeline

**Files:**
- Modify: `services/api/app/modules/benchmark/models.py`
- Modify: `services/api/app/modules/jobs/types.py`
- Modify: `services/api/app/modules/jobs/handlers/__init__.py`
- Create: `services/api/app/modules/jobs/handlers/benchmark_theme_extract.py`
- Create: `services/api/app/modules/benchmark/theme_service.py`
- Create: `services/api/app/modules/benchmark/theme_jobs.py`
- Create: `services/api/alembic/versions/20261124110000_benchmark_theme_analysis.py`
- Modify: `services/api/alembic/env.py`
- Modify: `services/api/migration_guard.py`
- Modify: `services/api/app/modules/benchmark/service.py`

- [x] Add `BenchmarkThemeAnalysis` with unique `(tenant_id, subject_type, subject_id)` and fields for sample hash/JSON, themes, status, source, model, error, job, and timestamps.
- [x] Add the idempotent table/index migration and `job_type` enum value under an autocommit block.
- [x] Register `benchmark.theme_extract` on the bulk lane and register its thin handler.
- [x] Implement cache-only sample building, stable hashing, idempotent analysis/job creation, hash reuse, and tenant-scoped status assembly.
- [x] Implement the job core with tenant/job/hash guards, commit-before-LLM, strict JSON prompt, bounded input, gateway call, validation/fallback, and stale-write protection.
- [x] Delete saved-place analyses in the same transaction as saved-place deletion.
- [x] Run focused job/migration tests and confirm no regressions.

### Task 3: Benchmark theme API

**Files:**
- Modify: `services/api/app/modules/benchmark/router.py`
- Modify: `services/api/app/modules/benchmark/compare.py`
- Create: `services/api/tests/test_benchmark_themes.py`

- [x] Add bounded `GET /themes` and `POST /themes/retry` routes using `benchmark.view`.
- [x] Ensure GET only reads/enqueues durable work and never calls the LLM or a live review provider.
- [x] Return per-subject ready/pending/unavailable/error status and grouped cross-business rows with real quotes.
- [x] Cache response assembly briefly in Redis, fail open to Postgres, and never cache pending long-term.
- [x] Test sample scoping/bounds/hash stability, idempotent enqueue, handler guards, LLM success/fallback, retry, deletion cleanup, API bounds, and tenant isolation.

### Task 4: Compare-page evidence grid

**Files:**
- Create: `apps/web/components/benchmark/ReviewKeywords.tsx`
- Create: `apps/web/components/benchmark/ReviewKeywords.test.tsx`
- Modify: `apps/web/lib/api-benchmark.ts`
- Modify: `apps/web/lib/query-keys.ts`
- Modify: `apps/web/app/dashboard/benchmark/compare/page.tsx`
- Modify: `apps/web/components/dashboard/media/Modal.tsx` (localized close label if needed)
- Modify: `apps/web/lib/i18n/en.ts` and `ar.ts`
- Modify: `apps/web/lib/api-benchmark.test.ts`

- [x] Add typed theme API contracts and abort-aware fetch/retry functions.
- [x] Add the selection-keyed query and visibility-aware 3s polling only while a subject is pending.
- [x] Build the semantic evidence grid with All/Positive/Negative filters, sample percentages, mini-bars, low-sample badges, selected-column highlight, peer median, and gap.
- [x] Implement loading, partial pending, unavailable, error/retry, empty, zero-mention, and background-refresh states.
- [x] Add an accessible quote modal with focus trap, Escape, focus restoration, verbatim highlighting, Arabic `dir="auto"`, and safe Google links.
- [x] Add English/Arabic copy and focused API/component tests.
- [x] Run frontend tests, `tsc`, touched-file ESLint, and production build.

### Task 5: Verification and rollout

- [x] Run all focused backend and frontend tests together.
- [x] Run the full backend suite because this changes models, migrations, jobs, and worker infrastructure.
- [x] Run `npx tsc --noEmit`, touched-file ESLint with zero errors, and `npm run build`.
- [x] Render Compare at 1440px and 390px with ready, pending, empty, and quote-open states; inspect screenshots.
- [x] Run axe on the new section and fix section-specific violations.
- [x] Review `git diff`, update `readiness-report.html`, and commit without pushing.
