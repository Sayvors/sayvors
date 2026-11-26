# AI Visibility — result-first grounded research UX

**Date:** 2026-11-26
**Status:** Approved for implementation

## Decision

Replace the configuration-heavy workspace with a single result-first brief. The
owner chooses a location (or **All locations**), keeps their last question as a
smart default, and clicks one primary action: **Find with proof**. Repeat use
must need one click, not a second form.

## Screen order

1. **Top bar** — branch selector including **All locations**; history in a
   top-right disclosure; no second sidebar entry.
2. **Question strip** — last question pre-filled, three suggested chips, and the
   single primary **Find with proof** button.
3. **Brief** — confidence/verdict first, a one-paragraph grounded answer with
   inline numbered citations, then the top three fix-next actions with Copy and
   Open source controls. No card per claim.
4. **Evidence drawer** — one labeled disclosure: `Evidence — N claims, N sources`.
   Claim ledger is a table: claim, status, source chips, exact quote. Sources list
   stays inside the same drawer. Inline citation markers and grounding freshness
   remain visible on level 1.
5. **Run settings drawer** — one labeled disclosure for range and advanced
   scope. Two disclosure levels maximum.

## Spacing and surfaces

- 4px base grid: 8px within a row, 12px within a group, 16px between rows,
  24px between blocks, 48px between zones.
- Hairline separators instead of repeated card borders/shadows.
- Maximum two raised surfaces on screen: the brief and the evidence drawer.
- Numeric values use tabular mono figures.
- EN/AR copy, RTL layout, 3px visible focus ring, hover/active states on all
  controls, no gradients or glass.

## Long-running jobs

- Research runs show step-based progress with conceptual breadcrumbs:
  `Scanning public pages → Checking claims → Drafting brief`, plus a determinate
  progress bar and elapsed time. Skeleton placeholders only for sub-10s data
  fetches. Progress labels come from `jobs.progress_label`.
- Keep the brief panel in place while a run is active so the layout does not
  reflow.

## Failure and limit states

- Backend policy codes never appear as user text.
- A cooldown/limit message names the system state, gives the exact reset time,
  preserves the question, and offers **Run when ready** or **Notify me**.
- Failed system runs do not silently consume the user's visible budget without
  an explanation. The error sits beside the primary action, not in a modal.
- Tooltips are reserved for jargon and icon-only controls. Status legends are
  inline text.

## TanStack Query behavior

- Overview, prompts, runs, and run detail use `staleTime: 30s`, `gcTime: 5m`,
  `placeholderData: keepPreviousData`, and no window-focus refetch.
- Mutations invalidate only AI Visibility query keys after create, retry,
  update, and delete.
- Branch and range changes reuse cached data instead of blanking the page.

## Scope

This spec covers the AI Visibility page and its research lifecycle states only.
It does not redesign the global sidebar, benchmark, or chat shell.
