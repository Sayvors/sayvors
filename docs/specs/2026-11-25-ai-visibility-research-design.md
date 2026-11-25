# AI Visibility Research — grounded, automated decision briefs

**Date:** 2026-11-25  
**Status:** Approved for implementation planning  
**Surface:** `/dashboard/ai-visibility`

## Goal

Give a business owner a one-click, source-grounded answer to local-search questions and a prioritized list of facts to fix next. The owner chooses or creates a prompt and clicks **Run research**; Sayvors searches public web sources, reads them, validates claims, and produces a decision brief without manual answer entry.

The product is **Sayvors Grounded AI**, not a recording of consumer ChatGPT, Gemini, or Perplexity answers. The UI must say this explicitly.

## Non-goals

- No paid search API.
- No scraping of consumer AI chat interfaces.
- No claim that Sayvors measures actual ChatGPT/Gemini/Perplexity market share.
- No manual answer-entry workflow in this version.
- No opaque 0–100 visibility score.
- No invented conversion lift, ranking guarantee, or “AI visibility percentage.”
- No new charting dependency.

## User flow

1. Owner opens **AI Visibility** from the sidebar.
2. Owner selects a connected Google branch.
3. The page shows suggested prompts derived from the branch category and locality, plus the owner’s saved prompt library.
4. Owner clicks **Run research** on one prompt or **Run all active prompts**.
5. The run progresses through visible stages: searching, fetching sources, reading, validating, and writing the brief.
6. The completed brief contains:
   - A direct answer with inline citations.
   - A claim ledger with exact supporting quotes.
   - Branch visibility outcomes: mentioned, cited, recommended, incorrect.
   - Competitor evidence.
   - Ranked fix-next actions linked to evidence and relevant Sayvors screens.
7. History preserves every completed brief and its source snapshots.

## Visual direction

**Sayvors Clay Ops** — the existing dashboard system:

- White surfaces on the standard page background.
- Deep Violet and Magenta accents.
- Solid semantic status colors; no gradients or glassmorphism.
- Compact operational cards, 8 px-equivalent radius system, tight shadow stacks.
- Workflow-first layout: prompt library on the left, research brief on the right, history below.
- Fully responsive: stacked panels on mobile, two-column workspace on desktop.
- EN/AR copy and logical RTL alignment throughout.

## Information architecture

### Header controls

- Branch selector.
- Date range for summary metrics: 30, 90, 365 days, or all time.
- Credit-balance notice: research uses the existing metered LLM wallet.
- **Run all active prompts** action.

### Summary strip

Three separate rates, calculated only from completed runs in the selected range:

- Mention rate.
- Citation rate.
- Recommendation rate.

Secondary facts:

- Completed run count.
- Active-prompt coverage.
- Evidence coverage: fetched sources and validated claims.
- Insufficient-evidence and failed-run counts.

No runs renders `—`, never `0%`.

### Prompt library

- Search, active/archived filter, add, edit, archive.
- Starter suggestions are generated locally from branch name, category, and locality. They are not persisted or run until the owner chooses them.
- Maximum 100 active prompts per branch.
- Archiving preserves the prompt text snapshot on historical runs.

### Research brief

- Progress stage indicator while the job runs.
- Direct answer with source citations.
- Plain-language disclosure that this is Sayvors Grounded AI.
- Claim ledger:
  - Claim text.
  - Exact supporting or contradicting quote.
  - Source title and URL.
  - Status: supported, contradicted, unsupported, not found.
- Branch outcome badges.
- Competitor mentions with their sources.
- Fix-next actions.

### Fix-next actions

Each action contains:

- Priority: P0, P1, or P2.
- Category: fact correction, source weakness, content gap, competitor gap, or verification.
- Action title and rationale.
- Evidence links to claims and source snapshots.
- Relevant Sayvors destination, such as Locations, Posts & Media, or Databank.
- Effort: low, medium, or high.

Priority is rule-based:

1. Contradicted branch facts.
2. Incorrect information in the answer.
3. Missing authoritative sources.
4. Competitor citation advantage.
5. Content or FAQ gaps.

No action may claim a numeric lift without measured evidence.

### History

- Paginated run list with branch, prompt, date, status, outcomes, and evidence coverage.
- Filters: status, prompt, date range.
- Open a completed brief.
- Retry failed or insufficient-evidence runs.
- Delete a run with confirmation.
- Compare with the previous completed run for the same prompt.

## State coverage

### First visit

- No branch: explain that a connected Google location is required and link to Locations.
- Branch but no prompts: show starter suggestions and an add-prompt action.
- Prompts but no runs: show an empty brief panel with a clear **Run research** action.
- No summary data: rates display `—`.

### Loading

- Prompt/library reads use skeleton or quiet loading states.
- A running job shows its current stage and elapsed time.
- Reopening the page resumes the existing active run; it does not enqueue a duplicate.

### Errors

- Search provider blocked or unavailable: fail the run with a clear reason and Retry.
- No usable sources: `insufficient_evidence`, not zero visibility.
- Source fetch failures: keep successful sources and report partial coverage.
- LLM budget exhausted: terminal error with a link to credits/top-up.
- Invalid LLM JSON or citations: validation failure; no unsupported claims are published as facts.
- Ambiguous post-LLM persistence failure: `ambiguous` state surfaced to the owner/admin; no blind automatic rerun.
- Read failures preserve the last good data and show Retry.
- Save/create failures preserve the user’s input.

### Accessibility

- Keyboard-operable prompt selection, run actions, dialogs, filters, and history.
- Visible 3 px focus-visible treatment.
- Status is never communicated by color alone.
- Claim ledger and action lists use semantic headings and lists.
- Long answers are truncated visually but fully available in an accessible dialog.
- Reduced-motion preferences are respected.

## Architecture

### New domain module

`services/api/app/modules/ai_visibility/`

- `models.py` — prompts, runs, and immutable source snapshots.
- `schemas.py` — request/response contracts and validation.
- `service.py` — CRUD, metrics, prompt suggestions, and run creation.
- `search.py` — public-search adapter interface and Bing RSS/HTML adapter.
- `sources.py` — SSRF-safe source fetching and text extraction.
- `research.py` — grounded LLM prompt, structured response validation, and claim ledger.
- `decisions.py` — deterministic outcome matching and fix-next ranking.
- `router.py` — tenant-scoped API.
- `jobs.py` or job handler integration — durable run execution.

### Data model

#### `ai_visibility_prompts`

- `id` UUID string primary key.
- `tenant_id`, indexed.
- `channel_id`, indexed; must belong to the tenant.
- `title` (200 chars).
- `prompt_text` (1,000 chars).
- `normalized_prompt_hash` (SHA-256 hex) for duplicate detection.
- `intent` (80 chars; discovery, comparison, fact-check, recommendation, or custom).
- `is_active` boolean.
- `created_by`.
- `created_at`, `updated_at`.
- Unique constraint on `(tenant_id, channel_id, normalized_prompt_hash)`.

#### `ai_visibility_runs`

- `id` UUID string primary key.
- `tenant_id`, `channel_id`, `prompt_id`, indexed.
- `prompt_snapshot` — exact prompt text used.
- `locale` — workspace language used for the answer (`en` or `ar`).
- `status`: queued, searching, fetching, reading, validating, writing, completed, failed, insufficient_evidence, ambiguous.
- `job_id`.
- `search_provider`, `model`, `model_version` when available.
- `answer_text`.
- `mentioned`, `cited`, `recommended`, `incorrect` booleans, nullable until validation completes.
- `validation_status`: pending, passed, partial, failed.
- `evidence_coverage` JSON: source count, validated-claim count, unsupported-claim count.
- `source_count`, `validated_claim_count`, `unsupported_claim_count` integer columns for scalable SQL aggregation.
- `competitor_mentions` JSON: list of `{name, quote, source_ids}`.
- `claims_json` and `actions_json` store the validated claim ledger and ranked decision actions.
- `error`, `failure_code`.
- `started_at`, `completed_at`, `created_at`, `updated_at`.
- Unique partial index allowing only one active run per `(tenant_id, prompt_id)`. Active statuses are queued, searching, fetching, reading, validating, and writing.

#### `ai_visibility_sources`

- `id` UUID string primary key.
- `run_id`, indexed, cascade delete with run.
- `position`.
- `url` (2,048 chars).
- `canonical_url`.
- `title`.
- `snippet`.
- `excerpt` (bounded extracted text).
- `content_hash`.
- `http_status`.
- `fetched_at`.
- `fetch_error` nullable.

Source rows are immutable once the run reaches validation.

### Search collector

- Primary adapter: Bing public RSS endpoint, with HTML fallback.
- Adapter interface allows Google or DuckDuckGo later without changing run storage.
- Normalize and cache queries for 6 hours.
- Return at most 10 results; fetch at most 5.
- Deduplicate by canonical URL and domain; at most 2 sources per domain.
- Reject non-http(s), private, loopback, link-local, and metadata destinations.
- Use existing DNS-pinned HTTP primitives and revalidate every redirect.
- Per-domain concurrency and rate limits; block cooldowns on CAPTCHA/429 responses.
- Redis-backed cache/rate state with a bounded process-local fallback. If safe rate state cannot be established, the collector fails closed rather than risking a scrape ban.

### Source reading

- Reuse `assert_public_http_url` and DNS-pinned fetch helpers.
- Allow only text/html, application/xhtml+xml, and text/plain.
- Hard caps (implemented as named constants, not magic numbers):
  - 5 sources per run.
  - 2 MB per source.
  - 15 second timeout per source.
  - 20,000 extracted characters per source.
  - 60,000 total source characters sent to the LLM.
- Extract readable text with the existing trafilatura-based crawler utilities.
- Store source snapshots before the LLM call so evidence survives provider or validation failure.

### Grounded LLM call

- Use the existing budgeted, metered LLM gateway with `tenant_id` and a named purpose.
- Use low temperature and require structured JSON.
- Input includes branch facts, prompt, and numbered source excerpts.
- System rules:
  - Use only the supplied sources.
  - Cite source IDs for every factual claim.
  - Say when evidence is missing or contradictory.
  - Do not invent branch facts, competitors, rankings, dates, or statistics.
  - Separate direct answer, claims, outcomes, competitors, and proposed actions.
- Record model and token/cost metadata through the existing gateway.
- Validate the response against a strict schema before persistence.
- A run may reach `completed` only with at least 2 successfully fetched sources and at least 1 validated claim. Otherwise it becomes `insufficient_evidence`.
- `validation_status=partial` is allowed when some claims are unsupported, provided the minimum evidence threshold is met; unsupported claims remain visibly labelled and excluded from factual outcomes.

### Citation and claim validation

- Every claim source ID must exist in the run’s source set.
- Every URL rendered in the answer must map to a fetched source.
- Claims with missing or invalid sources become `unsupported` and are not presented as facts.
- Branch outcomes are computed deterministically where possible:
  - Mentioned: normalized branch name, owned domain, or tracked phone appears in the validated answer.
  - Cited: at least one fetched source belongs to the branch’s owned domain or Maps listing.
  - Recommended: validated structured recommendation includes a supporting quote.
  - Incorrect: a validated claim contradicts an authoritative branch fact.
- LLM-suggested outcomes cannot override deterministic contradictions without evidence.

### Durable execution

- Add job type `ai_visibility.research` to the closed job registry.
- Map it to the existing `bulk` lane.
- Add a handler to the closed handler registry.
- `POST /runs` creates the run and job in one transaction with idempotency key `ai-visibility:{run_id}`.
- Repeating the request returns the existing active run.
- Job attempts use the existing lease/retry machinery.
- Search/fetch transient failures may retry within the lane limit.
- Budget exhaustion and validation/schema failures are terminal.
- If the LLM call may have succeeded but local persistence fails, mark the run `ambiguous`; do not automatically spend again.

### Retention and bounds

- Maximum 100 active prompts per branch.
- Run and source lists are paginated and capped.
- Completed runs older than 365 days are removed by a bounded daily cleanup task; source rows cascade.
- Active, failed, insufficient-evidence, and ambiguous runs are retained until resolved or explicitly deleted.
- No unbounded in-memory queues or source accumulation.

## API contract

Base prefix: `/api/v1/ai-visibility`.

- `GET /overview?channel_id=&days=` — summary metrics and coverage.
- `GET /prompts?channel_id=&include_archived=` — bounded list.
- `POST /prompts` — create prompt.
- `PATCH /prompts/{id}` — edit/archive.
- `DELETE /prompts/{id}` — delete unused prompt; archived prompts with history are retained.
- `GET /runs?channel_id=&status=&prompt_id=&limit=&offset=` — bounded history.
- `POST /runs` — body `{channel_id, prompt_id}`; creates durable run.
- `GET /runs/{id}` — status, brief, claims, sources, and actions.
- `POST /runs/{id}/retry` — retry failed or insufficient-evidence run.
- `DELETE /runs/{id}` — delete run and source snapshots.

Reads require `analytics.view`. Prompt/run writes require `ai.edit`. All routes resolve tenant from the authenticated context and validate channel ownership. The feature is available to all plans; the LLM call still requires the existing `ai_replies` entitlement and available credits.

## Frontend structure

- `apps/web/app/dashboard/ai-visibility/page.tsx`
- `apps/web/components/ai-visibility/AiVisibilityPage.tsx`
- `PromptLibrary.tsx`
- `ResearchRunPanel.tsx`
- `DecisionBrief.tsx`
- `ClaimLedger.tsx`
- `FixNextActions.tsx`
- `RunHistory.tsx`
- `apps/web/lib/api-ai-visibility.ts`
- `apps/web/lib/ai-visibility-metrics.ts`
- Add `aiVisibility` query keys to `apps/web/lib/query-keys.ts`.
- Add EN/AR copy under `aiVisibility` in the i18n dictionaries.
- Add sidebar item and breadcrumb label.

The page uses TanStack Query. Running polls use a bounded interval while active and stop when the page is hidden or the run terminates.

## Migration

One idempotent migration:

- Adds `ai_visibility.research` to the PostgreSQL `job_type` enum using an autocommit block and `ADD VALUE IF NOT EXISTS`.
- Creates the three tables with `CREATE TABLE IF NOT EXISTS`.
- Creates tenant/channel/run/status indexes with `CREATE INDEX IF NOT EXISTS`.
- Adds unique and partial-unique constraints idempotently.
- `down_revision` must point at the verified single current head.

Models and migration ship together.

## Testing

### Backend

- Prompt CRUD, archive behavior, duplicate normalization, and branch ownership.
- Tenant isolation on every endpoint and job reload.
- One-active-run idempotency.
- Search adapter fixture tests for RSS/HTML parsing, dedupe, domain caps, cache, and block handling.
- SSRF, redirect, content-type, timeout, and byte-cap tests.
- LLM structured-output schema tests.
- Citation validation: valid, missing source, fabricated URL, unsupported claim.
- Deterministic branch outcome tests.
- Decision ranking tests.
- Metrics: no runs, partial runs, completed runs, date filtering, and prompt coverage.
- Retention bounds and pagination.
- Job retry, terminal failure, insufficient evidence, and ambiguous persistence.

### Frontend

- Starter suggestions and prompt CRUD.
- Run creation and active-run polling.
- Progress stages and resume-after-reload.
- Empty, loading, failed, insufficient-evidence, and completed briefs.
- Claim ledger and source links.
- Fix-next action deep links.
- History filters and comparison.
- Arabic labels and RTL alignment.
- Keyboard dialog behavior and focus return.
- No horizontal overflow at 390 px and 1440 px.

### Verification gate

- Focused backend tests only, unless the change touches shared core/config/database behavior.
- `npx tsc --noEmit --incremental false`.
- Focused Vitest suites.
- ESLint with zero errors.
- `npm run build`.
- Migration head and idempotency checks.
- HTML/report updates only after verified outcomes.

## Security and operational notes

- Search and source URLs are untrusted input.
- No raw HTML from sources or LLM output is rendered.
- URL schemes and destinations are validated before fetch and before display.
- Source excerpts are stored as plain text.
- Prompts, answers, and errors have hard length caps.
- Per-tenant write rate limits prevent accidental or abusive run floods.
- LLM spend is visible through the existing wallet/usage surfaces.
- A provider outage must never be presented as “business not visible.”

## Documentation and readiness updates

After implementation and verification:

- Add `docs/security/ai-visibility-research.md` describing the collector, SSRF guarantees, grounding, and validation invariants.
- Update `docs/security/plans-and-credits.md` for the new metered purpose.
- Update `readiness-report.html` only with verified outcomes.
- Keep the existing six-metric benchmark contract unchanged; AI Visibility remains a separate decision surface.

## Future connectors

The search adapter and run source model allow later addition of:

- Licensed search providers.
- Approved consumer-AI APIs.
- Scheduled recurring research.
- Competitor-specific prompt sets.

None are included in this implementation.
