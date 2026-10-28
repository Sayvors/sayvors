# Analytics redesign plan — Overview, Insights, Growth, Benchmark

**Date:** 2026-10-28
**Basis:** 46-source voice-of-customer review (27 Reddit threads, 5 G2/Capterra
review pages, 6 Local Search Forum threads, 3 vendor docs, 5 surveys). Full
evidence: `research-smb-analytics-dashboard-2026-10-28.md`.
**Status:** plan only — no code changes in this document.

---

## 1. The verdict from owners

Owners do not want more charts. They want **a small number of numbers they
trust, with a clear next action**, delivered where they already work.

1. **Five to ten numbers beat a dashboard.** SMB clients "just want the key
   numbers" and do not want to "log into a portal, find the right tab, filter
   five times." One page, 3-5 metrics, 3 takeaways.
2. **Trust is provenance.** Every number needs source, period, comparison,
   denominator, and last-sync time. Owners reconcile to the bank/CRM. Once one
   number is wrong, they question all of them.
3. **Absolute first, percentage second, trend third.** "Sales up 5%" can hide
   falling guest counts after a price increase. Show dollars, guests, reviews;
   add % only with a same-length comparison.
4. **AI is a draft, not an analyst.** Only 46% trust AI systems; 54% do not
   trust the data behind it. AI summaries need citations, `n`, confidence, and
   human approval. Never auto-publish a negative-review reply.
5. **Mobile is a console, desktop is a workbench.** Mobile: 3 KPIs, "who is
   waiting," "needs attention." Desktop: setup, bulk actions, peer groups,
   exports.
6. **Alerts are severity-based.** Push 1-2 star reviews, review bombing,
   waiting customers, missed calls, sync failures. Digest the positives.
7. **Benchmarks are trusted only when local, peer-based, recent, and
   transparent.** Broad industry averages are "mostly BS."

---

## 2. Current state vs. what owners want

| Page | What we show today | What owners actually want | Gap |
|---|---|---|---|
| **Overview** | Rating, review count, response rate, messaging volume, presence chart | 5-10 trusted numbers: reputation pulse, who is waiting, location roll-up, one thing that changed, action queue | Missing absolute-first cards, action queue, provenance, location league |
| **Insights** | Topics/problems/products + momentum + messaging cards | Themes with counts, quotes, location/staff attribution, trend vs prior period, owners/actions, AI with receipts | No source receipts, no owner/action, complaint card just added but no quotes/location split |
| **Growth** | Acquisition, keywords, visibility, opportunities, messaging growth | Review-request funnel (sent → delivered → clicked → reviews → rating), realistic conversion, source attribution with "unknown," retention cohort, ask timing, cost per review | Missing the funnel entirely; no denominators; no cohort/retention |
| **Benchmark** | Reputation composite, rating/sentiment/response/volume vs market medians, branch ranking | Local peer set the owner can edit, similar size/model, recency + response rate, own history first, gap math, `n` and date | Composite score is opaque; peer set not editable; no gap-to-4.5 math; no low-sample warnings |

---

## 3. Per-page specification

### 3.1 Overview — "Is the business okay this week, and what needs me now?"

**Hard cap:** 6 KPI tiles, 3 action cards, 1 "one thing that changed" insight.

**Cards:**

| Card | Metrics | Copy pattern | Action |
|---|---|---|---|
| Reputation pulse | `avg_rating`, `new_reviews_30d`, `response_rate`, `awaiting_reply`, `oldest_wait_days` | **4.6★** +0.1 vs prior 30d · **18 new reviews** · 82% responded · **3 awaiting** · oldest 2d · *Google 14 / FB 3 / Yelp 1 · synced 8 min ago* | Reply to 3 |
| Who's waiting | `unanswered_texts`, `missed_calls`, `median_first_response_min`, `waiting_over_1h` | **5 texts waiting** · 2 missed calls · **14 min** median first reply · 2 waiting >1h · *business hours 8am-6pm* | Open inbox |
| This week (if POS wired) | `net_sales`, `guest_count`, `avg_check`, `labor_pct` | **$48,210** +6.2% vs same week LY · **1,284 guests** · **$37.55** avg check · labor 28.4% | View sales |
| Location league | `location`, `rating`, `new_reviews`, `response_rate`, `unanswered` | Downtown 4.1★ · 6 new · 68% · 5 unanswered · Westside 4.7★ · 9 new · 91% · 1 unanswered | View location |
| One thing that changed | `theme`, `mentions`, `delta`, `location`, `example_quote` | **Wait time mentions up 38% at Downtown.** 14 of 24 mentions in the last 14 days. "Waited 25 minutes for a table." *Based on 78 reviews · [See 24]* | See reviews |
| Needs attention | prioritized `severity`, `location`, `issue`, `owner`, `due` | Downtown: 2 new 1★ reviews mention wait time. Assign to GM. | Assign / Reply / Fix |

**Rules:**
- Every tile: absolute → delta → trend. Delta label names the comparison.
- No silent zeros: failed sync = "Data delayed — last success 6:12 AM".
- No colour without the threshold that produced it (tooltip shows the rule).
- Every number drills down to the underlying reviews/messages/locations.

### 3.2 Insights — "What are customers telling us, where, and what should we do?"

**Cards:**

| Card | Metrics | Copy pattern | Action |
|---|---|---|---|
| Complaints by area (shipped) | `category`, `mentions`, `trend_pct`, `staff_named`, `serious`, `top_terms` | **Waiting time** — 24 mentions · +38% vs prior 30d · 14 staff named · 6 serious · "long wait, cold food" | See 24 reviews |
| Top themes | `theme`, `mentions`, `pct_of_negative`, `delta`, `top_location`, `quote` | **Wait time** — 31% of negative reviews — +38% — Downtown (14) + a verbatim quote | See reviews |
| What changed this week | `negative_reviews_7d`, `prior_7d`, `theme`, `location` | **6 new 1★ this week, up from 1.** 4 mention cold food on pickup at Location B. | Review 6 / Assign |
| Sentiment by location | `location`, `rating`, `trend_90d`, `top_negative_theme`, `response_rate`, `unanswered` | Downtown 4.1★ · -0.2 (90d) · wait time · 68% responded · 5 unanswered | Open location |
| AI summary with receipts | `summary_bullets[]`, `n_per_bullet`, `confidence`, `sources[]` | "Staff are praised (n=42). Wait time is the main complaint, mostly Downtown (n=24)." *AI-generated; verify sources. Confidence: medium (n=78).* | Show sources / Edit |
| Action plan | `theme`, `owner`, `action`, `due`, `status` | Wait time → GM Downtown → add 2nd host Fri-Sun → due Nov 3 → open | Update status |

**Rules:**
- Every claim shows `n`, denominator, date range, source mix, and a sample warning when `n < 10`.
- Every theme links to the exact reviews behind it.
- AI is labeled, editable, and never auto-published for 1-3 star reviews.
- Themes break down by location and staff (staff-named reviews surfaced separately).

### 3.3 Growth — "Where do customers come from, what converts, and what should we do more of?"

**Cards:**

| Card | Metrics | Copy pattern | Action |
|---|---|---|---|
| Review engine (funnel) | `requests_sent`, `delivered`, `clicked`, `reviews`, `conversion`, `avg_rating` | **420 requests → 405 delivered (96%) → 38 clicked (9.4%) → 21 reviews (5.0%) → 4.7★** *SMS 54% / email 46% · 3 opt-outs · 12 failed* | See request log |
| Where customers come from | `new_customers`, `source`, `unknown_pct` | Google 42% · Referral 18% · Walk-in 15% · Instagram 10% · **Unknown 15%** *Based on 186 new customers · Oct 1-28* | Add source to booking |
| Retention cohort | `cohort_month`, `first_time`, `repeat_30/60/90`, `repeat_revenue` | **38% of January first-timers rebooked within 90 days** · $18,420 repeat revenue from 142 customers | View cohort |
| Ask timing | `trigger`, `requests`, `reviews`, `conversion` | In-person QR 12% · SMS 2h 6% · Next-day email 3% *Based on 420 requests* | Shift requests to QR |
| Growth actions | `action`, `audience`, `channel`, `expected_reviews` | Ask 24 happy customers (5★, last 7d) · Win back 12 lapsed 90-day customers · Fix 5 unanswered reviews | Start / Assign |

**Rules:**
- Count the denominator. "21 reviews" is not a result; "21 from 420 requests (5.0%)" is.
- Plan for **3-10%** request→review conversion (never promise the survey's 83%).
- "Unknown" is a first-class attribution bucket, not a rounding error.
- No review gating (sending only happy customers to Google).
- No headline referral page until tested; referral is an experiment row.

### 3.4 Benchmark — "How do we compare, and where should we improve?"

**Cards:**

| Card | Metrics | Copy pattern | Action |
|---|---|---|---|
| You vs nearby | your `rating/volume/recency/response` vs peer median | **You:** 4.6★ · 212 reviews · 38% last 90d · 82% responded · **Peer median:** 4.5★ · 180 · 52% · 61% *12 competitors within 5 mi · Google only · as of Oct 28 · 3 peers <20 reviews (directional)* | Edit peer group |
| Gap to 4.5 | `current_rating`, `review_count`, `five_star_needed`, `pace_per_month` | **4.3★ from 84 reviews.** 34 new 5★ needed to reach 4.5 (assuming no new negatives). At 8/month ≈ 4.3 months. *Math: (4.5×118 − 4.3×84) ÷ 5 ≈ 34* | Create review campaign |
| Review recency | `pct_reviews_last_90d`, `peer_median`, `rank` | 38% of your reviews are from the last 90 days. Peer median 52%. You rank 8th of 12. | Ask recent customers |
| Industry context | `category_avg_rating`, `listing_count`, `date` | Restaurants average 4.50★ (5,131 listings, 2026). *Context only — use nearby peers for decisions.* | See category |
| Peer group builder | `category`, `radius`, `size_band`, `sources` | Compare to 10 similar businesses within 5 miles. Remove outliers before median. *Default: same category, 1-3 locations, Google + Yelp, last 90d.* | Edit peer group |

**Rules:**
- No composite score without components and weights. Drop the 0-100
  "Reputation" black box or expose its inputs.
- Show peer definition, `n`, date, source, and a confidence label.
- Own history is the primary comparison; peers are context.
- Never compare a 4.3★ restaurant to a 4.9★ chiropractor and call it a gap.

---

## 4. Cross-cutting design rules

1. **One card, one decision.** Name the decision, the threshold, and the owner.
2. **Absolute + delta + trend.** Headline absolute; delta is same-length; trend
   is a sparkline or 12-week line.
3. **Show your work.** Source, period, filters, denominator, last sync,
   exclusions, "why this number?" popover.
4. **No silent zeros.** Failed sync = "Data delayed", never `0`.
5. **Action or dismiss.** Every alert/insight has a primary action and a
   snooze/dismiss. No dead ends.
6. **Colour needs a threshold.** Tooltip shows the rule.
7. **Drill-down from every number.** Land on the underlying rows.
8. **Mobile is a console.** 3 KPIs + "who's waiting" + "needs attention" above
   the fold; push deep-links to the exact item.
9. **AI is labeled and editable.** "AI-generated", "based on N", "show
   sources", "edit", "approve".
10. **Benchmarks are owner-reviewed.** Show the peer set, allow outlier
    removal, label low-sample results.
11. **Permissions match the org chart.** Owner → all; manager → location;
    front desk → inbox/reviews; marketing → campaigns/themes.
12. **Empty/loading/error are product surfaces.** New location: "No reviews
    yet — send your first 10 requests."
13. **Time zones and business hours are per location.**
14. **Do not ship a metric you cannot reconcile.**

---

## 5. Implementation phases

### Phase 0 — Trust layer (1 week)
- Add a `DataSource`/provenance shape to analytics responses: `source`,
  `period_start/end`, `comparison_period`, `denominator`, `last_sync`,
  `exclusions`.
- Add "Data delayed" state handling to every analytics card.
- Add a shared `<Provenance>` popover component.
- Replace percent-only deltas with absolute + delta + comparison label.

### Phase 1 — Overview rebuild (1-2 weeks)
- Cap Overview at 6 KPI tiles.
- Add Reputation pulse, Who's waiting, Location league, One thing that
  changed, Needs attention.
- Add drill-down links from every tile.
- Mobile console layout (3 KPIs + waiting + attention).

### Phase 2 — Insights (1 week)
- Extend the shipped "Complaints by area" card with top quotes + location
  split + sample warnings.
- Add "What changed this week" and "Action plan / close the loop".
- Add "Show sources" drill-down to the exact reviews.
- Label AI summaries with `n`, confidence, and "AI-generated".

### Phase 3 — Growth funnel (2 weeks)
- Build the review-request funnel: requests → delivered → clicked → reviews →
  rating, split by channel.
- Add source attribution with an explicit "Unknown" bucket.
- Add retention cohort (30/60/90) and ask-timing cards.
- Add growth actions (ask happy customers, win back lapsed, fix unanswered).
- Instrument the request pipeline so denominators are real.

### Phase 4 — Benchmark (1-2 weeks)
- Replace the opaque composite with component sub-scores + weights.
- Add editable peer group (category, radius, size band, sources).
- Add gap-to-4.5 math and pace.
- Add `n`, date, source, and low-sample/directional labels.

### Phase 5 — Alerts + mobile (1 week)
- Severity tiers: P0 (1-2★, review bombing, waiting >15m, missed call, sync
  failure), P1 (awaiting >24h, rating below threshold, theme spike), P2
  (daily digest, weekly report).
- Quiet hours, escalation, snooze, "why am I seeing this?"
- Mobile deep links into the exact review/message.

---

## 6. Backend/data requirements

- **Provenance envelope** on every analytics response (source, period,
  comparison, denominator, last sync, exclusions).
- **Review-request events** persisted (sent, delivered, clicked, review) with
  channel and trigger — needed for the Growth funnel.
- **Customer source** field + "unknown" bucket (booking/CRM/manual).
- **Cohort query** for first-visit → repeat 30/60/90 and repeat revenue.
- **Peer group** model: category, radius, size band, sources, member list,
  snapshot date.
- **Gap math** helper for rating thresholds.
- **Business hours + timezone** per location for "waiting" thresholds.
- **Alert rules** table with severity, threshold, recipient, channel, quiet
  hours.

---

## 7. Open decisions

1. **POS integration:** the "This week" sales card needs POS data. Ship
   reputation-only Overview first, then add POS when connected.
2. **Referral:** thin evidence; keep as an experiment, not a headline page.
3. **Composite score:** expose components or remove. Recommend remove from
   Benchmark and keep raw metrics.
4. **Conversion promise:** set expectations at 3-10% request→review, not 83%.
5. **Peer data source:** need a local competitor dataset (Google Places scan)
   with a disclosed method and snapshot date.

---

## 8. Acceptance criteria

- Overview has ≤ 6 KPI tiles, 3 action cards, 1 "one thing changed".
- Every number has a provenance popover and a drill-down.
- No failed sync renders as `0`.
- Every Insight claim shows `n`, date range, source mix, and a sample warning
  when `n < 10`.
- Growth funnel shows every denominator (sent/delivered/clicked/reviews).
- Benchmark shows peer definition, `n`, date, source, and a confidence label.
- Mobile above the fold: 3 KPIs + "who's waiting" + "needs attention".
- Alerts are severity-tiered with quiet hours and deep links.
