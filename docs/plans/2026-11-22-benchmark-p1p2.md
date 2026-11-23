# Benchmark P1+P2 Implementation Plan (parallel execution)

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development. Four implementers run in PARALLEL on strictly file-disjoint scopes. Contracts below are binding — every agent builds exactly to them.

**Goal:** Ship P1 (action-rate KPI context, completeness score, fix-first tickets, AI summary, sparklines) and P2 (cohort tags, baseline alerts, red-cell drill-down). Search-AI visibility band stays deferred per the readiness plan.

**Binding contracts (all agents build to these exact shapes):**

1. `lib/benchmark-insights.ts` (frontend-lib agent creates; frontend-ui agent consumes):
```ts
import type { ComparisonSubject, CompareSummary, HistoryPoint } from "@/lib/api-benchmark";
export interface CompletenessPart { key: string; score: number; max: number } // key: rating|recency|sentiment|depth
export function completenessScore(subject: ComparisonSubject): { score: number; parts: CompletenessPart[] } | null; // null when subject has no data at all
export type FixMetric = "avg_rating" | "reviews_per_month" | "positive_pct";
export function rankFixFirst(summary: CompareSummary, subjects: ComparisonSubject[]): { metric: FixMetric; gap: number }[]; // actionable gaps only, worst first, max 3, gaps > 0 only
export interface BaselineDeviation { hasEnough: boolean; direction: "up" | "down" | null; delta: number; streak: number }
export function baselineDeviation(points: HistoryPoint[]): BaselineDeviation;
// completeness: rating = avg_rating/5*40; recency = min(20, reviews_last_month*2, fallback reviews_last_year/12*2); sentiment = positive_pct/100*20; depth = min(20, total_reviews/100*20). Round parts to 1dp; null parts score 0.
// baseline: rating points only (at+rating); baseline = mean of oldest half (max 8 pts), latest = newest; direction when |delta| >= 0.15; streak = consecutive trailing points on same side.
```
2. `POST /api/v1/benchmark/ai-summary` (backend-ai agent): body `{"subjects": ["own:x", "saved:y"]}` (max 6, same parse as /compare) → `{"summary": str, "source": "ai" | "template"}`. Tenant-scoped (`benchmark.view` perm). Input to the LLM is ONLY the numeric summary (rank, gaps, metric values from `summary.north_star`/`distribution` — never review text). Redis cache 10 min (`bm:ai-summary:{tenant}:{sha1(sorted subjects)}`). Any LLM failure/absence → rule-based template from the same numbers, `source: "template"`, HTTP 200 (fail-open by design, documented).
3. `compare.py` own-subject records gain `"tags": list[str]` (backend-tags agent): from `channel.metadata_json["tags"]` — lowercase/trim, max 5 tags, each ≤30 chars; missing/empty → `[]`. Saved subjects get `"tags": []`. `ComparisonSubject` TS gains `tags: string[]`.

**File ownership (hard boundaries):**
- backend-ai: `services/api/app/modules/benchmark/ai.py` (new), `router.py` (new endpoint only), `tests/test_benchmark_ai_summary.py` (new)
- backend-tags: `services/api/app/modules/benchmark/compare.py` + existing `tests/test_benchmark_compare.py` (additive tests)
- frontend-lib: `apps/web/lib/benchmark-insights.ts` (new) + `apps/web/lib/benchmark-insights.test.ts` (new, vitest — mirror `lib/notifications.test.ts` setup)
- frontend-ui: `apps/web/components/benchmark/*` (new components + OwnScorecards edit), `apps/web/app/dashboard/benchmark/compare/page.tsx`, `apps/web/lib/api-benchmark.ts`, `apps/web/lib/i18n/en.ts` + `ar.ts`

---

### Agent backend-ai: `POST /ai-summary` (TDD)

- [ ] Tests first: mock/fake the LLM seam (follow how existing tests fake LLM calls — grep `TESTING`/mock model patterns in tests); green-path returns `source: "ai"` with non-empty summary; LLM failure → `source: "template"` 200; unknown subject handled via `compare_subjects` (unavailable records fine); cache set+hit (fake redis per existing test patterns).
- [ ] `ai.py`: build compact numeric payload via `summary.north_star` + `distribution` + per-subject headline metrics; single LLM call, ~8s timeout, plain-text 1–2 sentences, length cap ~300 chars; template fallback text (en) built from rank/leader/worst gap.
- [ ] Router: endpoint per contract; reuse `admin_rate_limit`-style throttle only if a benchmark-adjacent one exists — otherwise none (tenant-gated + cached is enough).
- [ ] Scoped: `python -m pytest tests/test_benchmark_ai_summary.py tests/test_benchmark_compare.py -q -n 0` green. Commit: `Add benchmark AI summary endpoint with template fallback`.

### Agent backend-tags: cohort tags on own subjects (TDD)

- [ ] Additive tests in `tests/test_benchmark_compare.py`: own subject with tags in channel metadata → `tags` present, normalized (lowercase, ≤5, ≤30 chars); no tags → `[]`; saved subject → `[]`.
- [ ] Implement per contract in `compare.py` `_own_subject` (and `tags: []` on `_subject` blank so both kinds carry the key).
- [ ] Scoped: `python -m pytest tests/test_benchmark_compare.py -q -n 0` green. Commit: `Expose cohort tags on benchmark own subjects`.

### Agent frontend-lib: insights helpers (TDD, vitest)

- [ ] `benchmark-insights.test.ts`: pin completeness boundaries (perfect subject → 100; null-metric subject → scored parts at 0, not null), rankFixFirst ordering/exclusions (gap ≤ 0 dropped, non-actionable excluded, max 3), baselineDeviation (insufficient points → hasEnough false; up/down/streak cases; the 0.15 threshold).
- [ ] Implement to the contract; run `cd apps/web; npx vitest run lib/benchmark-insights.test.ts` green (match how `lib/notifications.test.ts` runs).
- [ ] Commit: `Add benchmark insight helpers with tests`.

### Agent frontend-ui: components + wiring

- [ ] Read contracts + `lib/benchmark-insights.ts` may not exist yet (parallel) — build against the CONTRACT types; add minimal local imports only after lib lands: if `benchmark-insights.ts` is missing at your time of wiring, still write imports as contracted and note it — the final verification round runs after all agents.
- [ ] New components: `CompletenessCard` (0–100 per own subject, part breakdown bars, solid colors, `—` for null), `FixFirstTickets` (top 3 actionable cards from `rankFixFirst`, impact-ordered, links to `/dashboard/reviews`), `Sparkline` (60×24 inline SVG polyline of rating points, `role="img"` + aria-label), `BaselineAlert` (renders `baselineDeviation` when `hasEnough && direction` — amber banner, arrow + streak text), `AiSummaryCard` (fetches `fetchAiSummary(keys)` on compare load via useQuery, renders `summary`, no source plumbing shown).
- [ ] `api-benchmark.ts`: `tags: string[]` on `ComparisonSubject`; `AiSummaryResponse` type + `fetchAiSummary(subjects: string[])`.
- [ ] Wiring in `compare/page.tsx`: mount CompletenessCard + FixFirstTickets + BaselineAlert + AiSummaryCard in the Now-tier block (alert first, AI card after NorthStarCard); Sparkline inside each OwnScorecards card (pass `historyQuery.data?.subjects` down as a key→points map); drill-down: clicking a matrix cell whose tier is the worst tier opens the existing reviews popup for that subject filtered to negative (pass an `onDrillDown` callback into `MatrixTable`; reuse existing `setReviewsPopup` state); cohort: when the own subject has `tags`, render a tag-chip filter above the picker filtering the own-locations dropdown options.
- [ ] i18n en/ar (one pass each, 4-space indent in benchmark block): completenessTitle/scoreLabel/partRating/partRecency/partSentiment/partDepth, fixFirstTitle, fixRating/fixVelocity/fixSentiment (action copy), sparklineAria, baselineUp/baselineDown (with {delta}/{streak}), aiSummaryTitle, cohortFilterLabel, drillDownHint.
- [ ] `npx tsc --noEmit` clean. Commit: `Add benchmark insight cards, drill-down and cohort filter`.

### Final round (controller, after all four): integration verification

- [ ] `python -m pytest tests/test_benchmark_ai_summary.py tests/test_benchmark_compare.py tests/test_benchmark_bench_set.py tests/test_benchmark_bench.py tests/test_benchmark_summary.py -q -n 0`; `npx vitest run lib/benchmark-insights.test.ts`; `npx tsc --noEmit`; `npm run build`
- [ ] Cross-contract check (ai-summary JSON ↔ frontend type; tags ↔ ComparisonSubject; helper signatures ↔ component usage)
- [ ] readiness-report: P1 rows (action-rate note folded into completeness, completeness, fix-first, AI summary, sparkline) + P2 rows (cohorts, baseline alerts, drill-down) → Done; visibility band stays Planned/deferred
- [ ] Combined review, fixes, commits. Never push.
