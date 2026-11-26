# Dynamic Business-Aware AI Visibility

**Date:** 2026-11-26  
**Surface:** `/dashboard/ai-visibility`  
**Plan:** `docs/plans/2026-11-26-dynamic-business-aware-ai-visibility.md`

## Goal

Replace the universal one-question flow with versioned customer question sets
generated from each connected branch's real business data, researched durably
in the background, and expanded adaptively without rewriting history.

## Owner experience

1. Owner selects a connected branch.
2. Owner clicks **Research my branch**.
3. The API returns `202 Accepted`; the owner can leave the page.
4. A quiet status banner says research is running and shows version/progress.
5. The dashboard shows owner-first evidence cards, charts, and the exact
   customer questions researched.
6. Owner opens any completed question to see its grounded brief and fix-next
   actions.

There is no prompt library, prompt editor, depth selector, or blocking progress
screen in the owner UI.

## Business classification inputs

- Branch name, address/locality, country, service area, categories, attributes.
- Merchant location override name/categories/services.
- Declared and offered `BusinessService` rows only.
- Active `CatalogItem` products.
- Workspace business identity and edited `BusinessProfile` card.
- Review topics/products/problems and structured customer asks.
- Conversation insight questions/topics/intents.
- Website title/description/excerpt and relevant public pages.

Reviewer names, raw review text, contact identifiers, and customer PII are not
sent to generation. Public text remains untrusted data.

## Question generation

- Weighted multi-signal industry classification; primary Google category alone
  is insufficient.
- Industry-specific EN/AR intent templates for hospital, restaurant, school,
  hotel, retail, e-commerce, automobile dealership, law firm, salon, real estate,
  software, recruitment, and conservative local services.
- Service-specific intents are removed when the service is absent or explicitly
  not offered.
- Real customer questions are prioritized only when they match the branch name,
  locality, an actual service/product phrase, or a relevant intent. Generic
  support chatter is excluded from initial and adaptive sets.
- Every question stores intent, language, geography, industry/service relevance,
  business score, priority, origin, prompt/run links, and status.

## Versioning and adaptation

- One active query set per tenant/branch; each set has a monotonic version.
- Generated question text is unique per tenant/branch.
- Initial research runs one child run at a time.
- After all children are terminal, grounded competitor mentions or unused real
  customer questions may create one follow-up version.
- At most two adaptive versions are created.
- Parent versions and their outcomes are immutable.

## Background execution

- `ai_visibility.query_set` is an internal-only bulk job.
- The parent loads/classifies the branch, persists questions/prompts, and starts
  the first child `ai_visibility.research` run.
- `ai-visibility-finalizer` reconciles child jobs, advances the queue, aggregates
  outcomes, and creates adaptive versions.
- Child creation uses a tenant/depth/month PostgreSQL advisory lock plus a fresh
  quota count, closing the concurrent batch quota race.
- Parent/child jobs appear in the existing background-operations widget.

## API

- `POST /api/v1/ai-visibility/query-sets` → `202` with query-set status.
- `GET /api/v1/ai-visibility/query-sets/latest?channel_id=...` → latest cycle,
  version chain, generated questions, outcomes, aggregate metrics, and evidence
  coverage.
- Existing run-detail endpoint remains the per-question brief API.

## Data model

- `ai_visibility_query_sets`: version, parent, status/phase, classification,
  source snapshot, generation metadata, counters, error, job id.
- `ai_visibility_questions`: stable key/text/hash, language/intent/relevance,
  geography/score/priority/origin, prompt/run links, status.
- `ai_visibility_runs.query_set_id` and `.question_id` are nullable so legacy
  single-prompt runs remain valid.

## Review hardening

- Customer asks/questions are PII-scrubbed at ingestion and again at outbound
  search/LLM boundaries. The LLM receives an allowlist of business fields, not
  the full profile snapshot. Known reviewer-name components, handles, and
  conservative person-name cues are redacted while business terms are protected.
- Global UI jobs apply channel RBAC and use static titles without raw questions.
- First-child quota failures terminalize the set; dead parent jobs are
  reconciled; handler re-entry cannot create duplicate children.
- Partial/failed sets resume pending questions into a new linked version with
  `carried_from_question_id`, preserving the parent unchanged. Latest-history
  projection suppresses superseded ancestors. Manual new cycles create linked
  `rerun` rows for the same canonical questions so evidence can be refreshed.
- Query-set-linked runs are protected from legacy deletion APIs.
- Canonical punctuation/diacritic-insensitive identity is enforced by a partial
  unique index for non-resume rows. Service alias roots cover finance/financing,
  deliver/delivery, booking/reservation, and related morphology in exclusions
  and service matching.
- Adaptive depth is separate from branch version; adaptive origin and parent
  classification are preserved.
- Aggregate evidence counts distinct canonical source URLs that were
  successfully fetched, have excerpts, and pass branch relevance/ownership
  checks; failed and synthetic rows are excluded.

## Retention and portability

- Completed query sets: 365 days; failed/partial: 30 days; active sets never
  swept.
- Questions are deleted explicitly before their set.
- Tenant export/purge includes all six AI Visibility tables.
