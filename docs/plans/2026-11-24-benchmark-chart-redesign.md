# Benchmark Chart Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the four Benchmark graph sections with owner-focused, accessible comparisons that distinguish real gaps from missing/low-sample data.

**Architecture:** Keep the existing Benchmark API contracts and BOQ/Google data pipeline. Redesign the four presentational components, pass the selected/main subject where needed, derive display-safe values (no zero-as-missing), and add focused vitest coverage plus browser verification after each section.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind, inline SVG, Vitest + Testing Library, Playwright.

---

## File structure

- Modify `apps/web/components/benchmark/DistributionStrip.tsx` — peer range/dot plot.
- Modify `apps/web/components/benchmark/SentimentVelocityBars.tsx` — separated sentiment and velocity visuals.
- Modify `apps/web/components/benchmark/TrendChart.tsx` — direct-labelled rating/review-growth small multiples.
- Modify `apps/web/components/benchmark/OwnScorecards.tsx` — branch action scorecards with sample-size awareness.
- Modify `apps/web/app/dashboard/benchmark/compare/page.tsx` — pass `subjects` and `mainKey` into redesigned components.
- Modify `apps/web/lib/i18n/en.ts` and `ar.ts` — new owner-focused labels/verdicts.
- Create focused `*.test.tsx` files next to each redesigned component.
- Create `docs/plans/2026-11-24-benchmark-chart-redesign.md` — this plan.

## Design invariants

- No new API calls or endpoint changes.
- No gradients, glassmorphism, pie/donut charts, or decorative chart junk.
- `avg_rating === 0` with `total_ratings === 0` is missing, not a real zero.
- `positive_pct === 0` with no review text/sample is missing, not a real zero.
- Low sample sizes are labelled; they never produce confident performance verdicts.
- Every chart has a text summary, accessible name, and non-color encoding.
- Verify each section with focused tests, `tsc`, ESLint, and desktop/mobile screenshots before starting the next.

---

### Task 1: Distribution strip → peer range/dot plot

**Files:**
- Modify: `apps/web/components/benchmark/DistributionStrip.tsx`
- Modify: `apps/web/app/dashboard/benchmark/compare/page.tsx`
- Modify: `apps/web/lib/i18n/en.ts`, `apps/web/lib/i18n/ar.ts`
- Create: `apps/web/components/benchmark/DistributionStrip.test.tsx`

- [x] Write failing tests for: own-subject highlight, missing-rating exclusion, sample count, tied values, accessible summary.
- [x] Run `npx vitest run components/benchmark/DistributionStrip.test.tsx` and confirm failure.
- [x] Implement the range/dot plot with direct subject dots, median tick, own highlight, gap-to-median/leader, and low-sample note.
- [x] Update compare page call site to pass `subjects` and `mainKey`.
- [x] Add English/Arabic copy.
- [x] Run focused tests, `npx tsc --noEmit`, touched-file ESLint, and screenshot desktop/mobile.
- [x] Commit `feat(benchmark): redesign peer distribution chart`.

### Task 2: Sentiment + velocity → two honest visuals

**Files:**
- Modify: `apps/web/components/benchmark/SentimentVelocityBars.tsx`
- Modify: `apps/web/lib/i18n/en.ts`, `apps/web/lib/i18n/ar.ts`
- Create: `apps/web/components/benchmark/SentimentVelocityBars.test.tsx`

- [x] Write failing tests for: sentiment/velocity separation, missing sentiment, low-sample badge, accessible labels.
- [x] Run focused tests and confirm failure.
- [x] Implement a 100% sentiment-mix panel and a separate review-velocity bar panel with shared subject order.
- [x] Add sample-size/context copy and English/Arabic labels.
- [x] Run focused tests, typecheck, ESLint, and desktop/mobile screenshots.
- [x] Commit `feat(benchmark): separate sentiment from review velocity`.

### Task 3: Trend chart → rating + review growth small multiples

**Files:**
- Modify: `apps/web/components/benchmark/TrendChart.tsx`
- Modify: `apps/web/lib/i18n/en.ts`, `apps/web/lib/i18n/ar.ts`
- Create: `apps/web/components/benchmark/TrendChart.test.tsx`

- [x] Write failing tests for: shared date domain, own-series emphasis, missing-series exclusion, cumulative review growth, accessible summary, insufficient-history state.
- [x] Run focused tests and confirm failure.
- [x] Implement two larger SVG charts: average rating (1–5) and cumulative review growth, with gridlines, start/end dates, direct end labels, and period delta badges.
- [x] Add English/Arabic labels and empty/partial states.
- [x] Run focused tests, typecheck, ESLint, and desktop/mobile screenshots.
- [x] Commit `feat(benchmark): rebuild rating and review growth trends`.

### Task 4: Own scorecards → branch action scorecards

**Files:**
- Modify: `apps/web/components/benchmark/OwnScorecards.tsx`
- Modify: `apps/web/lib/i18n/en.ts`, `apps/web/lib/i18n/ar.ts`
- Create: `apps/web/components/benchmark/OwnScorecards.test.tsx`

- [x] Write failing tests for: no-rating branch not flagged, low-sample badge, median delta, top problem/action, sparkline accessibility.
- [x] Run focused tests and confirm failure.
- [x] Implement structured branch scorecards with rating vs own median, velocity, five-star share, sample-size badge, sparkline, and one action.
- [x] Add English/Arabic labels and empty/partial states.
- [x] Run focused tests, typecheck, ESLint, and desktop/mobile screenshots.
- [x] Commit `feat(benchmark): redesign own-branch scorecards`.

### Final verification

- [x] Run all four focused test files together.
- [x] Run `npx tsc --noEmit`.
- [x] Run touched-file ESLint with zero errors.
- [x] Run `npm run build`.
- [x] Render Compare at 1440px and 390px; inspect screenshots and console.
- [x] Run axe on the Compare page; fix chart-specific violations.
- [x] Review `git diff` and ensure only intended files changed.
