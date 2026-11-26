# Dynamic Business-Aware AI Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the universal one-question AI Visibility flow with versioned, business-specific customer question sets generated from the connected branch's real data, researched durably in the background, and expanded adaptively without changing historical results.

**Architecture:** A new query-generation module classifies each branch from categories, descriptions, services/products, website text, reviews, and location data; it produces scored, deduplicated, multilingual questions stored in versioned query sets. A durable location-research job creates child research runs, while a periodic finalizer aggregates outcomes and creates follow-up query-set versions only when evidence reveals useful new intents or competitors. The API returns immediately with a background status, and the UI shows aggregate evidence cards/charts plus per-question briefs.

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic, PostgreSQL, existing durable job runner, existing LLM gateway, React/Next.js, TanStack Query, Vitest, pytest.

---

## Phase boundaries

1. **Business profile + question generation** — deterministic classification, industry-specific intents, multilingual question templates, scoring/deduplication, and real customer-voice prioritization.
2. **Versioned query sets + background execution** — new models/migration, batch job, child runs, quota/rate-limit safety, adaptive finalizer, tenant-scoped API.
3. **Owner-first aggregate UI** — non-blocking status, aggregate evidence cards/charts, per-question results, EN/AR states, accessibility and verification.

## File structure map

### New backend modules

- `services/api/app/modules/ai_visibility/taxonomy.py` — industry definitions, category aliases, intent templates, service vocabulary, Arabic/English templates.
- `services/api/app/modules/ai_visibility/profile.py` — tenant-scoped business fact loading, website/review evidence, deterministic industry classification, uncertainty reporting.
- `services/api/app/modules/ai_visibility/questions.py` — dynamic question generation, language/geography adaptation, deduplication, relevance scoring, priority assignment, adaptive follow-ups.
- `services/api/app/modules/ai_visibility/query_sets.py` — versioned query-set lifecycle, question persistence, child-run creation, aggregation, historical immutability.
- `services/api/app/modules/ai_visibility/batch_jobs.py` — background location-research handler and adaptive finalizer integration.

### Modified backend files

- `services/api/app/modules/ai_visibility/models.py` — query-set/question models and nullable run links.
- `services/api/app/modules/ai_visibility/schemas.py` — classification, question, query-set, status, and aggregate contracts.
- `services/api/app/modules/ai_visibility/service.py` — batch preflight, latest query set, aggregate reads, retention/export support.
- `services/api/app/modules/ai_visibility/router.py` — start/status/latest endpoints with channel RBAC.
- `services/api/app/modules/ai_visibility/jobs.py` — run-to-question/query-set association and child lane key.
- `services/api/app/modules/ai_visibility/research.py` — reusable bounded structured-LLM call for question generation.
- `services/api/alembic/versions/<new>_ai_visibility_query_sets.py` — idempotent tables/indexes/columns.
- `services/api/app/modules/jobs/types.py` — internal batch job type and bulk lane.
- `services/api/app/modules/jobs/handlers/__init__.py` and `handlers/ai_visibility_research.py` — handler registration pattern.
- `services/api/app/modules/jobs/router.py` — keep batch/internal job types out of the generic client API.
- `services/api/app/workers/main.py` — adaptive finalizer loop registration.
- Tenant export/purge/retention integrations for the new tables.
- `docs/security/ai-visibility-research.md` and `readiness-report.html`.

### New frontend files

- `apps/web/components/ai-visibility/ResearchStatus.tsx` — non-blocking background status banner.
- `apps/web/components/ai-visibility/QuestionResults.tsx` — per-question status/outcome list and brief selection.
- `apps/web/components/ai-visibility/IntentCoverageChart.tsx` — accessible aggregate intent/evidence chart.
- Focused Vitest files for each new component.

### Modified frontend files

- `apps/web/components/ai-visibility/AiVisibilityPage.tsx` — one-click background batch start and aggregate dashboard.
- `apps/web/lib/api-ai-visibility.ts` — new request/response types and endpoints.
- `apps/web/lib/query-keys.ts` — latest query set/status keys.
- `apps/web/lib/i18n/en.ts` and `ar.ts` — background, classification, question, and aggregate copy.

## Task outline

### Task 1: Industry taxonomy and deterministic intent templates

**Files:**
- Create: `services/api/app/modules/ai_visibility/taxonomy.py`
- Test: `services/api/tests/test_ai_visibility_taxonomy.py`

- [x] **Step 1: Write failing tests**

```python
from app.modules.ai_visibility.taxonomy import classify_industry, select_intents

def test_classification_combines_name_category_and_description():
    match = classify_industry({
        "name": "MenteE",
        "categories": ["Software company"],
        "description": "AI research lab building language models and recruitment software",
        "services": ["AI research", "software engineering"],
    })
    assert match.industry == "software_company"
    assert match.confidence >= 0.8
    assert match.matched_signals

def test_restaurant_and_hospital_receive_different_intents():
    restaurant = select_intents(classify_industry({
        "name": "Al Narjes Restaurant", "categories": ["Restaurant"],
        "description": "Mandi and grilled dishes with family dining and delivery",
    }))
    hospital = select_intents(classify_industry({
        "name": "Noor Medical City", "categories": ["Hospital"],
        "description": "Emergency care, maternity, pediatrics and diagnostics",
    }))
    assert "cuisine" in {row.key for row in restaurant}
    assert "emergency_care" in {row.key for row in hospital}
    assert "cuisine" not in {row.key for row in hospital}

def test_service_specific_intent_is_skipped_without_the_service():
    match = classify_industry({
        "name": "Smile Dental", "categories": ["Dental clinic"],
        "description": "General dentistry and teeth cleaning",
    })
    assert "maternity" not in {row.key for row in select_intents(match)}
```

- [x] **Step 2: Run the failing test**

Run: `python -m pytest tests/test_ai_visibility_taxonomy.py -q -n 0 -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: app.modules.ai_visibility.taxonomy`.

- [x] **Step 3: Implement taxonomy skeleton and classifier**

```python
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class IndustryMatch:
    industry: str
    business_type: str
    subcategories: tuple[str, ...]
    confidence: float
    matched_signals: tuple[str, ...]
    uncertainties: tuple[str, ...]

INDUSTRY_ALIASES = {
    "software_company": ("software", "ai lab", "technology company", "software development"),
    "restaurant": ("restaurant", "cafe", "coffee shop", "food", "mandi", "grill"),
    "hospital": ("hospital", "medical center", "clinic", "emergency care", "maternity"),
    # Remaining industries are added in Step 4 with the same bounded shape.
}

def classify_industry(profile: dict) -> IndustryMatch:
    fields = (
        ("categories", 5), ("name", 3), ("description", 2),
        ("services", 2), ("products", 2), ("website_title", 2),
        ("review_themes", 1),
    )
    scores: dict[str, float] = {}
    signals: dict[str, list[str]] = {}
    for field, weight in fields:
        text = " ".join(str(profile.get(field) or "")).casefold()
        for industry, aliases in INDUSTRY_ALIASES.items():
            for alias in aliases:
                if alias in text:
                    scores[industry] = scores.get(industry, 0.0) + weight
                    signals.setdefault(industry, []).append(f"{field}:{alias}")
    if not scores:
        return IndustryMatch("local_services", "unknown", (), 0.2, (), ("industry_unclear",))
    industry = max(scores, key=scores.get)
    confidence = min(0.95, 0.35 + scores[industry] / 20)
    return IndustryMatch(industry, industry, (), confidence, tuple(signals[industry]), ())
```

- [x] **Step 4: Add industry definitions and intent selection in bounded chunks**

Each industry entry contains aliases, service vocabulary, default target segments/problems, and `IntentSpec` templates with `key`, `priority`, `en`, `ar`, and optional `required_service`. `select_intents(match, profile)` filters service-specific intents when the required term is absent, then returns the industry's relevant intent list. Cover hospital, restaurant, school, hotel, retail, e-commerce, automobile dealership, law firm, salon, real estate, software, recruitment, and a conservative local-services fallback.

- [x] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_ai_visibility_taxonomy.py -q -n 0 -p no:cacheprovider`
Expected: PASS. Commit `feat(ai-visibility): add business industry taxonomy`.

### Task 2: Business profile loading and classification

**Files:**
- Create: `services/api/app/modules/ai_visibility/profile.py`
- Modify: `services/api/app/modules/ai_visibility/sources.py` only if reusable public-context extraction needs a helper.
- Test: `services/api/tests/test_ai_visibility_profile.py`

- [x] Write failing tests proving classification uses name + categories + description + services/products + website + reviews + location, not category alone.
- [x] Implement tenant-scoped fact assembly and bounded public website/search context.
- [x] Implement deterministic classification, confidence, and uncertainty output.
- [x] Run focused tests and commit.

### Task 3: Dynamic question generation and quality control

**Files:**
- Create: `services/api/app/modules/ai_visibility/questions.py`
- Modify: `services/api/app/modules/ai_visibility/research.py` for reusable structured generation.
- Test: `services/api/tests/test_ai_visibility_questions.py`

- [x] Write failing tests for industry-specific questions, multilingual output, geography, deduplication, unsupported-service filtering, metadata, scoring, and priority.
- [x] Implement deterministic candidate generation.
- [ ] **Deferred:** optional bounded LLM refinement. The shipped generator uses deterministic industry templates plus real customer voice, avoiding an extra metered model call.
- [x] Implement final question-set validation and adaptive follow-up generation.
- [x] Run focused tests and commit.

### Task 4: Versioned query-set models and migration

**Files:**
- Modify: `services/api/app/modules/ai_visibility/models.py`
- Create: `services/api/alembic/versions/<new>_ai_visibility_query_sets.py`
- Test: `services/api/tests/test_ai_visibility_query_sets.py`

- [x] Write failing model/API tests for versioning, immutable history, unique question IDs, and one active set per channel.
- [x] Add query-set/question models and nullable run links.
- [x] Add idempotent migration and verify upgrade/downgrade/upgrade.
- [x] Run focused tests and commit.

### Task 5: Background batch execution and adaptive finalizer

**Files:**
- Create: `services/api/app/modules/ai_visibility/query_sets.py`
- Create: `services/api/app/modules/ai_visibility/batch_jobs.py`
- Modify: job registry/worker wiring, `service.py`, `jobs.py`, retention/export/purge.
- Test: `services/api/tests/test_ai_visibility_batch_jobs.py`

- [x] Write failing tests for idempotent start, child-run creation, quota exhaustion, one-child-at-a-time queue advancement, finalization, meaningful-query detection, competitor discovery, and adaptive versioning.
- [x] Implement query-set lifecycle and child-run orchestration.
- [x] Implement durable handlers and periodic finalizer.
- [x] Implement aggregation and historical version reads.
- [x] Run focused tests and commit.

### Task 6: Tenant-scoped start/status/latest API

**Files:**
- Modify: `services/api/app/modules/ai_visibility/schemas.py`, `router.py`, `service.py`
- Test: `services/api/tests/test_ai_visibility_api.py`

- [x] Write failing API tests for `202` start, RBAC, tenant isolation, idempotency, status, latest aggregate, and version history.
- [x] Implement schemas and routes.
- [x] Run focused tests and commit.

### Task 7: Owner-first aggregate UI and non-blocking status

**Files:**
- Create: `ResearchStatus.tsx`, `QuestionResults.tsx`, `IntentCoverageChart.tsx` under `apps/web/components/ai-visibility/`
- Modify: `AiVisibilityPage.tsx`, `api-ai-visibility.ts`, `query-keys.ts`, EN/AR i18n.
- Test: focused Vitest files.

- [x] Write failing tests for immediate `202` handling, background banner, aggregate cards/chart, per-question states, version display, and empty/error states.
- [x] Implement API client/types and query keys.
- [x] Implement non-blocking status and aggregate components.
- [x] Replace fixed-prompt flow with batch dashboard.
- [x] Run Vitest, TypeScript, ESLint, production build, and mocked Playwright; commit.

### Task 8: Documentation and readiness verification

**Files:**
- Modify: `docs/security/ai-visibility-research.md`, `readiness-report.html`, relevant spec docs.

- [x] Document classification provenance, question-set immutability, adaptive versioning, quota behavior, and background-job security invariants.
- [x] Run all AI Visibility backend tests, frontend tests, migration round trip, and scoped lint/build gates.
- [x] Review diff, update readiness report, and commit without pushing.

## Core design decisions

- **One active query set per channel.** Starting research while a set is running returns the existing set; it never duplicates work.
- **Every question becomes an immutable prompt + run.** Existing prompt/run history remains intact; generated questions are not editable in the owner UI.
- **Default quick depth, optional deep depth.** Each child run counts against the existing monthly depth quota and wallet; the batch stops cleanly as `partial` if quota/credit is exhausted.
- **One active child run per query set.** A periodic finalizer advances the queue only after the current child reaches a terminal state; `lane_key` is metadata and is not relied on for serialization.
- **Atomic tenant/month quota guard.** Child-run creation takes a PostgreSQL transaction advisory lock keyed by tenant/depth/month, re-counts runs, and inserts atomically; router preflight remains only a fast fail.
- **Visible background jobs.** Parent and child jobs set `ui_visible`, `ui_title`, `ui_kind`, and progress fields so the existing global background-operations widget reports real status.
- **Stale-child reconciliation.** If a child job is terminal but its run is still active, the finalizer terminalizes the run with a safe failure code so the queue cannot wedge.
- **Public context snapshot.** The query set stores a bounded snapshot of the branch website, relevant public snippets, review themes, classification confidence, and uncertainties for reproducibility.
- **Adaptive versions carry history forward.** Version N+1 references original questions/runs and adds only non-redundant follow-ups; old versions and outcomes are never rewritten.
- **No fake business facts.** Unsupported services are filtered out; missing profile data is marked uncertain; LLM output is validated and falls back to deterministic industry templates.
- **Non-blocking API.** `POST` returns `202` with query-set/job IDs. The existing global background-operations widget remains the progress surface; the page shows a quiet “research is running, come back later” banner.

## Required persisted contracts

### Business classification snapshot

- `industry`, `business_type`, `subcategories`
- `products`, `services`
- `target_customer_segments`, `customer_problems`, `purchase_intentions`
- `geographic_coverage`, `competitive_market`, `unique_selling_propositions`
- `confidence`, `uncertainties`, `source_fields`

### Generated question metadata

- `question_key` (unique within the set), `question_text`
- `customer_intent`, `industry_relevance`, `service_or_product_relevance`
- `language`, `geographic_context`
- `business_relevance_score`, `research_priority`
- `origin` (`initial` or `adaptive`), `carried_from_question_id`
- `prompt_id`, `run_id`, `status`

### Query-set lifecycle

`generating` → `running` → `completed` | `partial` | `failed`

- `version`, `parent_query_set_id`, `status`, `phase`
- `classification_json`, `source_snapshot_json`, `generation_meta_json`
- timestamps, child job id, aggregate counters

## Bounded generation policy

- `MAX_INITIAL_QUESTIONS = 8` (Arabic-first for Saudi profiles, plus English).
- `MAX_FOLLOWUP_QUESTIONS = 4` per adaptive version.
- `MAX_ADAPTIVE_VERSIONS = 2`; after that, the latest set is finalized even if gaps remain.
- `MAX_PROFILE_CONTEXT_CHARS = 30_000` across website/public/review evidence.
- `MAX_GENERATED_QUESTION_CHARS = 240`.
- Intent coverage uses round-robin selection so one high-scoring intent cannot fill the whole set.
- Zero-result queries do not spawn redundant generic variants; follow-ups require a grounded new competitor, service, or customer need.
- Customer-voice questions require branch/locality/service/intent relevance; generic support chatter is excluded from initial and adaptive sets.

## Classification strategy

- Weighted deterministic signals: primary/secondary categories (5), business name (3), description/services/products (2), website title/description (2), review themes (1).
- Alias matches choose industry and subcategory; the score becomes confidence. Low confidence is explicitly stored as uncertainty.
- Industry defaults provide target segments, problems, purchase intentions, and USP candidates; explicit branch facts override defaults.
- The shipped generator does not make an extra LLM call. A future optional refinement layer must validate against the same profile snapshot and cannot override the deterministic industry or invent services.

## Implementation record

- Taxonomy/profile/question generation: `0a857467`, `d96b2a02`, `4fe9f1a9`, `c5f45628`.
- Query-set models/migrations: `46e9b6da`.
- Background generation/finalizer/adaptive versions: `14c44e26`, `4e5406ac`.
- Start/latest API: `9df34b46`.
- Non-blocking aggregate UI: `3d793dc1`.
- Verification: full backend suite `3170 passed, 4 skipped` (one unrelated auth test flaked under xdist and passed in isolation); focused review-hardening suite `219 passed`; frontend AI Visibility/API tests `28 passed`; TypeScript and ESLint clean; web production build clean; migration round trips clean; mocked Playwright desktop/mobile/Arabic RTL with axe and keyboard checks passed.
- Independent review hardening: PII scrubbing/allowlists, channel-RBAC UI jobs, lifecycle reconciliation and resume, immutable history, canonical dedup/exclusions, adaptive depth/provenance, and distinct-source aggregation.
