# Analytics — messaging-first upgrade for Overview / Growth / Insights / Benchmark

Created 2026-10-10, branch `development`. Research basis: 3 background studies (competitor
feature catalog across Hootsuite/Sprout/Buffer/Iconosquare/Metricool/Emplifi/SocialBee/Zoho/
Later/Sendible; SMB owner pains + wishes from Reddit/G2/Trustpilot 2024–2026; published
benchmark numbers from Socialinsider/Rival IQ/BrightLocal/Sprout Index/Birdeye/SOCi).
Full findings summarized in session 2026-10-10; this file is the build plan.

## ARCHITECTURE RULE (user's explicit rule — never violate)

**Nothing computes at request time. Every number the UI shows is stored in the database
first.** Background jobs precompute daily rollups; AI analyses run in workers and persist
their output; endpoints read stored rows only. No LLM calls, no cross-thread SQL
derivations, no live Meta calls in the analytics request path. This mirrors existing
patterns: `location_daily_metrics` (Google daily ingest), Localith daily ingest,
review-intelligence persistence.

Corollaries:
- A new endpoint that runs a window function over `channel_messages` at request time is a
  BUG, not a shortcut. The rollup job computes it; the endpoint reads the rollup row.
- Rollup jobs are idempotent: upsert per (channel_id, date), and each run RECOMPUTES the
  last 2 days so late replies / late webhooks land in the right bucket.
- Medians over an empty set store NULL; the UI shows "—" (honest empty state, like
  Benchmark's "no estimates" stance).

## The white space (why this exists)

All four pages are Google-reviews-centric. The product's core data — conversations
(WhatsApp/IG/FB) — is invisible in analytics. No competitor suite leads with DM analytics;
WhatsApp Business app has NO response-time analytics at all; no tool compares response
times between businesses. Owner pains that motivate each P0: missed messages = lost sales;
"is my response speed good?"; distrust of Meta Business Suite's contradictory numbers
(Sayvors computes from its own DB = the trust position).

## Phase 0 — foundations (backend, ends green)

1. **Migration**: new table `channel_daily_metrics` — one row per channel per day:
   - `id`, `tenant_id`, `channel_id`, `date` (unique index `channel_id + date`)
   - `messages_in`, `messages_out` (ChannelMessage direction counts)
   - `conversations_in` (distinct contact_phone with inbound that day),
     `conversations_replied` (≥1 outbound in thread)
   - `median_first_response_seconds`, `p90_first_response_seconds`
     (FRT = inbound → next outbound in same thread: `channel_id + contact_phone`)
   - `unanswered_open` (inbound conversations with no outbound at snapshot time)
   - `comments_in`, `comments_replied` (ChannelComment direction counts)
   - `ai_handled_out` (outbound rows with `handled_by="ai"`)
   - `contacts_new` (first-ever inbound contact that day, via contact_profiles /
     first message per contact_phone)
   - `followers_count`, `posts_count` (daily snapshots, nullable until job has data)
   - `by_hour_in` (JSON array of 24 ints — heatmap feed), bucketed in the tenant's
     timezone (single-market product: Asia/Riyadh unless a tenant tz exists — DECIDE in
     phase, UTC bucketing would make the heatmap lie by 3h)
   - `computed_at`
2. **Migration**: `channel_messages.handled_by` — Enum("human","ai","unknown",
   name="message_handled_by"), default "unknown". Consumer sets `"ai"` wherever the AI
   sends (WhatsApp consumer send path ~line 387 area, IG consumer send path); human sends
   from inbox set `"human"`. Old rows stay "unknown" (no backfill — honest).
3. **Daily rollup job**: idempotent, per active channel; recomputes D-1 and D-2 on every
   run (late-reply correction), then today's partial row.
4. **Follower/post snapshot job**: daily per active MetaAsset — FB `fan_count` +
   IG `followers_count` via the existing profile-read methods (token from
   `asset_metadata["page_access_token"]` / IG equivalent); upserts into the day's row.
   Skips channels whose reads fail (row stays NULL, job never throws).
5. **Decision baked in**: AI replies COUNT as responses for response-rate/time (they are
   the tenant's configured behavior, and Meta excludes only *instant auto-acknowledgments*;
   Sayvors' AI is conversational). The `handled_by` split lets Insights show human vs AI
   performance separately.

Tests: rollup math (median/p90/unanswered/late-reply correction), handled_by set on both
AI paths, snapshot job upsert + failure isolation, idempotent second run = same row.

## Phase 1 — Overview page: response health + message scorecard

New endpoint `GET /api/v1/analytics/messaging/overview?days=&channel_id=` — reads stored
`channel_daily_metrics` ONLY, returns period aggregates + vs-previous-period deltas.
Frontend cards on the Overview tab (existing `analytics/page.tsx` OverviewPanel):

1. **Response health card** — median first response time + response rate, goal line =
   Meta's own "Very responsive" gate (90% answered, <15 min median). Meta gives owners
   the badge pressure without tooling; this is the tooling. **P0**
2. **Cross-channel message scorecard** — messages in/out per channel (WA/IG/FB) with
   previous-period deltas (Buffer aggregate-top pattern). **P0**
3. **Unanswered & aging** — count of inbound conversations with no reply (from the day
   rows' `unanswered_open`, latest snapshot). Copy: customers message a competitor within
   15–60 min of silence. **P0**
4. **AI takeaway card** — one plain-language weekly summary. Generated by the SAME
   off-path pattern as review intelligence: worker LLM pass over stored dailies, output
   persisted (a `messaging_takeaways` row per week), UI renders stored text. **P1**

## Phase 2 — Growth page: add the social side under the GBP side

GrowthPage already owns Google visibility/acquisition/keywords/opportunities — untouched.
Add sections that read stored dailies:

1. **Customer growth** — new unique contacts who messaged per week (`contacts_new`).
   Sayvors-native; no competitor has it. This is "leads," not followers — exactly what
   owners say they'd pay for over vanity metrics. **P0**
2. **Follower growth per channel** — line chart + net change + rate % from
   `followers_count` snapshots (needs Phase 0 job running ~a week for a real curve — the
   UI states honestly "collecting history" until 7+ rows exist). Net = end − start;
   rate = net ÷ start (Sprout's formulas). **P1**
3. **Review velocity trend** — reviews/month over time (Google side already syncs). **P1**
4. **Posting frequency vs growth** — posts/week annotation on the growth curve
   (`posts_count` snapshots; Iconosquare/Hootsuite pair these to show "post more → grow
   faster"). **P2**

## Phase 3 — Insights page: mine conversations, not just reviews

InsightsPage's review mining (topics/problems/products) is untouched. Add:

1. **"What customers ask" mining** — worker job over inbound ChannelMessage +
   ChannelComment content (tenant-scoped, rolling window): top questions/intents with
   counts + samples, persisted to a `conversation_insights` table (same persistence
   pattern as review intelligence; UI reads stored JSON only, NEVER calls the LLM in the
   request). Actionable: feeds FAQ, auto-reply templates, menu fixes. **P0**
2. **Best-time heatmap** — day × hour grid (SocialBee's proven UX) summed from
   `by_hour_in` arrays over the window; second toggle shows "median reply speed by hour"
   so owners see when THEY answer fastest. **P1**
3. **AI performance card** — conversations handled by AI vs human (`ai_handled_out` +
   `handled_by` split), deflection framing ("AI handled N of M conversations").
   Hootsuite's proven metric. **P1**
4. **Metric-definition tooltips** — every number gets a plain-language "what to do with
   it" tooltip (frontend only). IG renamed reached→views and owners openly distrust
   platform analytics; cheap trust. **P0 (trivial)**

## Phase 4 — Benchmark page: inline industry bands + market response ranking

BenchmarkPage's branch-vs-branch + Sayvors-cohort ranking stays; extend:

1. **Industry benchmark bands** — hardcoded constants table IN CODE with source + formula
   labels, rendered as "you vs market" rows (W6: the "is 2% good?" pain answered
   in-product):
   - IG engagement median ~0.4–0.5% BY FOLLOWERS (Socialinsider 0.48–0.50% / Rival IQ
     0.36%); FB ~0.06–0.15%. "Good" = 2× median.
   - Follower growth: 1–2%/mo is solid SMB IG.
   - Response: 90% rate + <15 min median (Meta's own gate); 73% of consumers expect a
     reply within 24h (Sprout Index 2025).
   - Reviews: 89% of consumers expect a response (BrightLocal 2026); average business
     answers 75.5% (Birdeye 2025) in 2.1 days (SOCi 2024); every +25% response rate ≈
     +4.1% GBP conversions (SOCi).
   **CRITICAL: label the formula on every band.** ER-by-followers vs ER-by-reach differ
   7–10× (Hootsuite's 3.5% IG is its own user base, not a market median). Use
   median-based sources only; never mix scales on one chart. **P1**
2. **Response-time vs market** — new `market_benchmarks` table (date, scope
   market/network, metric, median/p25/p75, business_count) filled by a cross-tenant job
   reading all tenants' stored dailies (aggregates only — cross-tenant queries stay out
   of the request path too). UI: "your median first reply vs other Sayvors businesses in
   your market" — extends the existing market-ranking pattern. Confirmed: NO tool does
   competitor response-time comparison. **P1** (after Phase 1 metrics exist)
3. **Review-response benchmark row** — you vs 75.5% average + the +4.1% conversions
   payoff as the nudge copy. **P1**

## Parked (deliberately NOT in phases)

- **PDF monthly report export** — owners lose 3–5 hrs/month copy-pasting; Metricool's
  most-loved feature; agencies pay specifically to kill it. Big lift; do after phases 1–4.
- **Competitor watchlist** (Hootsuite-style per-competitor tracking) — needs its own
  ingestion design; park.
- **IG/FB reach & impressions widgets** — BLOCKED on `instagram_manage_insights`
  (+ `read_insights` if Page-level) — add to the CURRENT App Review submission. When
  granted: daily insights-sync job → new columns/table in the SAME `channel_daily_metrics`
  pattern, then widgets read stored rows. Note: Meta removed post-level demographic
  breakdowns March 2024 — demographics are audience-level only.
- Nothing auto-posts, nothing vanity-only (likes without outcomes), analytics stay in the
  base plan (Sprout's paywall resentment is the positioning opening).

## Non-goals / honesty rules (same as every Sayvors surface)

- No live AI in any analytics request path (architecture rule above).
- No synthetic industry "averages" where Sayvors cohort data exists — cohort medians with
  business_count shown (Benchmark page's existing stance, matches Emplifi's median-based
  method).
- Empty data = explicit empty state, never 0-as-if-real.
