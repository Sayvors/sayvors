# AI Visibility Result-First UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crowded AI Visibility workspace with one result-first, one-click grounded research brief with clear progress, spacing, and human failure states.

**Architecture:** Keep the existing tenant-scoped APIs and durable bulk job pipeline. Rebuild only the page composition: a compact question/run strip, one primary brief, and two disclosure drawers. Centralize error copy and query caching in small frontend modules.

**Tech Stack:** Next.js 16, React, Tailwind CSS, TanStack Query, Vitest, Playwright, FastAPI, pytest.

---

## File structure

- Modify: `apps/web/components/ai-visibility/AiVisibilityPage.tsx` — compose the result-first screen.
- Create: `apps/web/components/ai-visibility/ResearchBrief.tsx` — verdict, answer, top fixes.
- Create: `apps/web/components/ai-visibility/EvidenceDrawer.tsx` — claim table and sources.
- Create: `apps/web/components/ai-visibility/ResearchProgress.tsx` — step breadcrumbs and determinate bar.
- Create: `apps/web/lib/ai-visibility-errors.ts` — human-readable failure mapping.
- Modify: `apps/web/app/globals.css` — 4px spacing tokens and hover states.
- Modify: `apps/web/components/ai-visibility/{PromptLibrary,ResearchRunPanel,RunHistory}.tsx` — integrate with new composition.
- Modify: `apps/web/lib/i18n/{en,ar}.ts` — new copy.
- Modify: `services/api/app/modules/ai_visibility/router.py` — `Retry-After` on cooldown/limit errors.
- Test: `apps/web/components/ai-visibility/*.test.tsx`, `services/api/tests/test_ai_visibility_runs.py`.

## Tasks

### Task 1: Human-readable failure and cooldown state

**Files:** Create `apps/web/lib/ai-visibility-errors.ts`; modify `apps/web/components/ai-visibility/ResearchRunPanel.tsx`, `apps/web/components/ai-visibility/RunHistory.tsx`; modify `services/api/app/modules/ai_visibility/router.py`.

- [ ] **Step 1: Write failing frontend test**

In `apps/web/components/ai-visibility/ResearchRunPanel.test.tsx`, assert that a `retry_limit_reached` error renders `Research is busy for this question. It will be ready again shortly.`, not the raw code.

- [ ] **Step 2: Run it and verify failure**

Run: `cd apps/web && npx vitest run components/ai-visibility/ResearchRunPanel.test.tsx --no-cache`
Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement the mapping**

Create `apps/web/lib/ai-visibility-errors.ts` exporting `researchErrorMessage(raw: string | null | undefined): string`. Map `retry_limit_reached`, `retry_cooldown`, `tenant_search_rate_limited`, `search_blocked`, `search_unavailable`, `invalid_research_json`, `no_llm_model_configured`, and `budget_exhausted` to plain-language messages. Default to `Research could not finish. Your question is saved. Try again.`

- [ ] **Step 4: Use it in both panels**

Replace raw `copy.loadError`/`detail.error` display with `researchErrorMessage(actionError ?? detail.error)` in `ResearchRunPanel.tsx` and the catch banner in `RunHistory.tsx`.

- [ ] **Step 5: Add Retry-After**

In `services/api/app/modules/ai_visibility/router.py`, set `headers={"Retry-After": "60"}` on `429` for `RetryCooldown` and `"3600"` on `409` for `RetryLimitReached`.

- [ ] **Step 6: Run tests and commit**

Run: `cd services/api && python -m pytest tests/test_ai_visibility_runs.py -q -n 0 -p no:cacheprovider`
Then: `cd apps/web && npx vitest run components/ai-visibility --no-cache`
Commit: `fix(ai-visibility): replace raw limit codes with clear guidance`.

### Task 2: Result-first page composition and one-click run

**Files:** Create `apps/web/components/ai-visibility/ResearchBrief.tsx`; modify `apps/web/components/ai-visibility/AiVisibilityPage.tsx`; modify `apps/web/lib/i18n/{en,ar}.ts`.

- [ ] **Step 1: Write failing test**

In `AiVisibilityPage.test.tsx`, assert the page renders a `Find with proof` button and an `All locations` option, and that the question input is pre-filled with the last prompt.

- [ ] **Step 2: Run it and verify failure**

Run: `cd apps/web && npx vitest run components/ai-visibility/AiVisibilityPage.test.tsx --no-cache`
Expected: FAIL because the new controls do not exist.

- [ ] **Step 3: Add copy**

Add `allLocations`, `findWithProof`, `lastQuestion`, `questionLabel`, `resultFirstHint`, and `runAgain` to EN and AR `aiVisibility` dictionaries.

- [ ] **Step 4: Build the compact top strip**

In `AiVisibilityPage.tsx`, replace the large header/prompt-library split with one row: branch select (`All locations` + channels), question input pre-filled from the last active prompt or suggestion, and `Find with proof` primary button. Remove the separate guide card; keep guidance as one muted line under the button.

- [ ] **Step 5: Build the brief component**

Create `ResearchBrief.tsx` that renders, in order: grounding freshness, confidence/verdict, one-paragraph answer with inline citation links, and the top three fix-next actions with `Copy` and `Open source` buttons. It accepts `detail` and `copy` props and reuses `safeHref`.

- [ ] **Step 6: Run tests and commit**

Run: `cd apps/web && npx vitest run components/ai-visibility --no-cache && npx tsc --noEmit --incremental false`
Commit: `feat(ai-visibility): build one-click result-first brief`.

### Task 3: Evidence drawer and claim table

**Files:** Create `apps/web/components/ai-visibility/EvidenceDrawer.tsx`; modify `apps/web/components/ai-visibility/DecisionBrief.tsx`; modify `apps/web/lib/i18n/{en,ar}.ts`.

- [ ] **Step 1: Write failing test**

Add a test asserting `Evidence — N claims, N sources` is a labeled disclosure and the claim ledger is a table with columns `Claim`, `Status`, `Sources`, `Quote`.

- [ ] **Step 2: Run it and verify failure**

Run: `cd apps/web && npx vitest run components/ai-visibility/EvidenceDrawer.test.tsx --no-cache`
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the drawer**

Create `EvidenceDrawer.tsx` using native `<details>/<summary>` with a single summary label containing counts. Render claims as `<table>` rows with status text, source label chips linked through `safeHref`, and the exact quote. Below the table, render the source list with `S<n>`, title, and fetch error.

- [ ] **Step 4: Integrate**

In `DecisionBrief.tsx`, remove the inline claim ledger and source list; render `<EvidenceDrawer detail={detail} copy={copy} />` after the fix-next section. Keep inline citation markers in the answer.

- [ ] **Step 5: Add inline legend**

Render the status legend as plain text under the verdict: `Supported · Mixed · Unsupported`, never tooltip-only.

- [ ] **Step 6: Run tests and commit**

Run: `cd apps/web && npx vitest run components/ai-visibility --no-cache && npx tsc --noEmit --incremental false`
Commit: `feat(ai-visibility): add single evidence drawer`.

### Task 4: Progress, spacing, and hover states

**Files:** Create `apps/web/components/ai-visibility/ResearchProgress.tsx`; modify `apps/web/app/globals.css`; modify `apps/web/components/ai-visibility/ResearchRunPanel.tsx`.

- [ ] **Step 1: Write failing test**

Add a test asserting an active run renders `Scanning public pages`, a determinate progress bar with `aria-valuenow`, and no raw stage code.

- [ ] **Step 2: Run it and verify failure**

Run: `cd apps/web && npx vitest run components/ai-visibility/ResearchProgress.test.tsx --no-cache`
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement progress**

Create `ResearchProgress.tsx`. Map stages to 3 steps: `queued/searching/fetching → Scanning public pages`, `reading/validating/writing → Checking claims`, `completed → Brief ready`. Render `<progress value={percent} max={100}>` plus the breadcrumb text and elapsed seconds. Use stage from `copy.stages`.

- [ ] **Step 4: Enforce the spacing grid**

In `globals.css`, define `--ai-space-1` through `--ai-space-7` in 4px multiples and use them for `.ai-panel`, `.ai-metric`, `.ai-control`, `.ai-btn-primary`, and drawer sections. Remove arbitrary 10/13/14/18/22px padding from AI Visibility components by replacing with the closest token utility.

- [ ] **Step 5: Hover and focus**

Ensure `.ai-control:hover`, `.ai-btn-primary:hover`, `[data-evidence-row]:hover`, and `.ai-status-dot[data-tone=active]` have visible transitions. Keep 3px focus outline from the existing `.ai-visibility-ui :focus-visible` rule.

- [ ] **Step 6: Run tests and commit**

Run: `cd apps/web && npx vitest run components/ai-visibility --no-cache && npx tsc --noEmit --incremental false`
Commit: `feat(ai-visibility): add research progress and spacing system`.

### Task 5: Verification and commit

**Files:** Modify `readiness-report.html`, `docs/security/ai-visibility-research.md`.

- [ ] **Step 1: Run focused backend gate**

Run: `cd services/api && python -m pytest (Get-ChildItem tests/test_ai_visibility_*.py).FullName tests/test_job_foundations.py tests/test_jobs_pipeline.py tests/test_job_tenant_isolation.py tests/test_post_delete.py tests/test_admin_tenant_controls.py -q -n 0 -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 2: Run focused frontend gate**

Run: `cd apps/web && npx vitest run components/ai-visibility lib/api-ai-visibility.test.ts lib/ai-visibility-metrics.test.ts --no-cache && npx tsc --noEmit --incremental false && npx eslint app/dashboard/ai-visibility components/ai-visibility lib/api-ai-visibility.ts lib/ai-visibility-metrics.ts lib/ai-visibility-errors.ts && npm run build`
Expected: tests pass, zero TypeScript errors, zero ESLint errors, production build succeeds.

- [ ] **Step 3: Browser verification**

Run the mocked Playwright script at 1440×900 and 390×844 with Arabic RTL. Assert one-click run, branch/all-location selection, evidence disclosure, progress state, human limit message, no horizontal overflow, and visible focus.

- [ ] **Step 4: Update readiness**

Add the verified commit hash, test counts, and the explicit note that authenticated staging plus live provider verification remain blocked. Do not claim staging completion.

- [ ] **Step 5: Final diff review and commit**

Run: `git diff --check && git status --short`

## Implementation update — 2026-11-28

- [x] All-locations aggregate view using existing per-branch latest-result APIs.
- [x] Dedicated `ResearchBrief`, `EvidenceDrawer`, and `ResearchProgress` components.
- [x] Result-first modal composition with top fixes, inline citations, source domains, and one evidence disclosure.
- [x] EN/AR copy, responsive layout, keyboard/focus behavior, and evidence-row hover state.
- [x] Frontend gate: 37 tests, TypeScript, ESLint, and production build pass.
- [x] Browser verification through the existing dev tunnel after integration.
- [ ] Authenticated staging and live-provider verification remain pending.

Deviation from the original Task 2 sketch: the current backend accepts one `channel_id` per research job, so **All locations is a read-only aggregate**. Research remains branch-specific; no custom-question input or backend endpoint was added.
