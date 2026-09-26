# Business Health Scorecard + Competitive Differentiation Design

Date: 2026-09-26. Extends the existing Review Intelligence feature
(`services/api/app/modules/analytics/intelligence_ai.py`, UI in
`apps/web/app/dashboard/reviews/page.tsx`).

## Problem

1. The heuristic fallback (`_fallback_from_rows`) emits **raw words** as "themes"
   ("version", "things", "really", "awesome", "thanks") because it tokenizes
   review text and filters through a 40-word stopword list. With few reviews,
   garbage wins. Business owners get nothing actionable.
2. The LLM path already produces grounded themes, but there is **no standard
   business-dimension scorecard** — no answer to "how is my business doing on
   credibility, support, speed, quality, value, cleanliness?", and no
   competitive differentiation view.
3. **Time filtering is broken**: `_load_reviews` computes `since` and discards it
   (`_ = since`, line 143). `days` is only a cache key, not a data filter. A user
   selecting "September" still gets all-time analysis.

## Decisions (approved)

| # | Decision |
|---|----------|
| 1 | LLM judges a **fixed standard dimension set** (6), each with cited evidence, bidirectional (positive AND negative) |
| 2 | LLM may add **up to 4 extra dimensions** discovered in the reviews, grounded in evidence or dropped by validation |
| 3 | Frontend renders **only dimensions with mentions > 0** |
| 4 | Heuristic fallback becomes a **rule-based version of the same scorecard** — never raw words |
| 5 | A **competitive differentiation** section ("where you win" / "where rivals beat you") from existing cohort benchmark facts |
| 6 | **Interval-scoped**: presets `7d/30d/90d/12m/All` + custom month/year. Whole analysis (counts, scorecard, everything) respects the interval. Custom ranges are cached too |
| 7 | Runs on "Analyze with AI" click, cached per `(user, channel, interval)` — reuse the existing report table + upsert-on-analyze behavior |
| 8 | Scorecard + Competitive panels are **added** to Review Intelligence; existing theme cards stay, cleaned of raw words |

## Standard dimensions

| Key | Label | Keyword seeds (fallback + LLM guidance) |
|-----|-------|------------------------------------------|
| `credibility` | Credibility & Trust | honest, reliable, trustworthy, promise, kept, scam, overcharged |
| `support` | Customer Support & Staff | staff, service, waiter, waitress, friendly, helpful, professional, rude, ignored |
| `speed` | Responsiveness & Speed | fast, quick, slow, wait, waiting, queue, delay, prompt |
| `quality` | Product/Service Quality | quality, fresh, delicious, tasty, cold, stale, portion, craft, well made |
| `value` | Value for Money | price, value, expensive, cheap, worth, affordable, portion size, fair |
| `environment` | Cleanliness & Environment | clean, dirty, messy, spotless, tidy, atmosphere, ambience, decor, noisy |

Source of truth for the fallback: `_TOPIC_RULES` in `analytics/enrichment.py`,
extended with credibility/ethics keywords. Single shared constant module:
`analytics/dimensions.py` (new).

## Backend

### `analytics/dimensions.py` (new)
- `STANDARD_DIMENSIONS: list[DimensionDef]` (key, label, keywords)
- `classify_reviews(rows) -> list[dict]` — per review: which dims matched,
  positive/negative side derived from rating (>=4 positive, <=2 negative, 3 neutral)
- `score_dimensions(rows) -> list[dict]` — heuristic scorecard: for each dim,
  `mentions`, `positive`, `negative`, `positive_pct`, `avg_rating`,
  `confidence` (low/medium/high from mention count), `verdict` (rule-based
  sentence), `evidence` (up to 2 trimmed quotes + ratings)

### `intelligence_ai.py`
- **Fix the interval filter**: `_load_reviews(db, user_id, channel_id, since, until)`
  actually applies `ReviewInsight.review_updated_at >= since` and `< until`.
- **New contracts** (strict Pydantic, same discipline as existing):
  ```python
  class AIEvidence(BaseModel):
      quote: str = Field(..., min_length=2, max_length=200)
      rating: int = Field(..., ge=1, le=5)

  class AIDimension(BaseModel):
      key: str = Field(..., max_length=40)        # standard key, or slug for extras
      label: str = Field(..., min_length=2, max_length=60)
      standard: bool = True                        # False = LLM-discovered
      mentions: int = Field(..., ge=0)
      positive: int = Field(..., ge=0)
      negative: int = Field(..., ge=0)
      avg_rating: float = Field(..., ge=1.0, le=5.0)
      verdict: str = Field(..., min_length=2, max_length=240)
      evidence: list[AIEvidence] = Field(default_factory=list, max_length=3)

  class AICompetitive(BaseModel):
      wins: list[str] = Field(default_factory=list, max_length=4)
      gaps: list[str] = Field(default_factory=list, max_length=4)
  ```
  Added to `AIIntelligence`: `dimensions: list[AIDimension]` (max 10),
  `competitive: AICompetitive`.
- **Prompt**: extend `SYSTEM_PROMPT` with the dimension schema + rules
  (6 standard always evaluated; ≤4 extras only when genuinely new; fold
  overlapping content into the standard dim; every dimension needs evidence;
  counts must match provided verified numbers; no invention).
- **Verification** (`_verify`): clamp `mentions`/`positive`/`negative` to
  `stats.total`; drop dimensions with `mentions == 0`; drop extras with no
  evidence; force `mentions == positive + negative` unless neutral exists.
- **Fallback** (`_fallback_from_rows`): use `score_dimensions(rows)` instead of
  raw-word themes. Keep raw-word scan ONLY in `_overview_query` (retrieval query,
  not user-facing) and expand `STOPWORDS`.
- **Competitive facts**: pass cohort comparison from `benchmark.py` into the
  prompt (my avg vs cohort avg, response rate gap, industry complaints I don't
  have, competitive_opportunities) — computed with the same `days` interval.
- **Interval**:
  - `get_review_intelligence(..., days, date_from, date_to)` — presets map to
    `days`; custom ranges pass explicit dates.
  - `_scope_key(days, date_from, date_to) -> str` e.g. `"90"`, `"all"`,
    `"2026-09-01..2026-09-30"` stored in the report's `days`-equivalent column.
- **Storage**: migration adds `dimensions` (JSON) and `competitive` (JSON)
  columns to `review_intelligence_reports`. Reuse existing `days` column for the
  scope key (String semantics already; but it's `Integer` — **new column
  `scope_key` String(40)**, keep `days` for back-compat, unique constraint
  switches to `(user_id, channel_id, scope_key)`).

### Router
- `GET /analytics/intelligence` and `POST /analytics/intelligence/analyze`
  accept `days` (int, presets) **or** `date_from`/`date_to` (ISO dates for the
  month picker). Response gains `dimensions`, `competitive`, `scope`
  (`{label, from, to}`), `interval_key`.

## Frontend (`apps/web/app/dashboard/reviews/page.tsx`)

1. **Interval selector** in the intelligence header: preset chips
   `7d · 30d · 90d · 12m · All` + `<input type="month">` for a specific month.
   Selection re-fetches the stored report for that scope; everything below
   re-renders for that interval. Header shows the interval + its review count.
2. **Business Health Scorecard** panel (above existing theme cards):
   - Standard dimensions in fixed order, then LLM extras by mentions
   - **Hidden when `mentions === 0`**
   - Each card: label, bidirectional pill (`Strong` / `Mixed` / `Weak`),
     verdict, `👍 n · 👎 n · avg x.x★`, confidence chip, evidence quotes
   - Empty state: "Not enough reviews to assess yet"
3. **Competitive differentiation** panel: "Where you win" / "Where rivals beat
   you" lists; hidden when empty; honest note that competitors = anonymized
   platform cohort until named-competitor tracking exists.
4. **Fix theme merging**: heuristic mode uses the local `THEME_DEFS` taxonomy
   only; AI mode uses backend themes (now taxonomy-validated). Raw words can no
   longer reach the UI.

## Testing

- `tests/test_review_scorecard.py` (new):
  - dimension classifier: positive/negative/neutral split, no match → 0 mentions
  - heuristic scorecard: never emits a non-dimension name; hides 0-mention dims
  - `_verify` clamping: mentions > total clamped, 0-mention dropped, evidence-less
    extras dropped
  - interval filter: reviews outside `[since, until)` excluded
  - endpoint: `days=30` vs `date_from/date_to` return different scopes; cached
    report served per scope; analyze twice updates the same scope row
- Existing intelligence tests keep passing (no regression in the 4 known failures).
- `tsc --noEmit` clean.

## Out of scope

- Named competitor tracking (cohort anonymized comparison only, disclosed in UI)
- Auto-run on page view (button + cache only, per decision 7)
- Owner-configurable dimension lists (taxonomy is a single constant module so
  this is easy to add later)
