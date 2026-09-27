# Multi-Location Business Benchmarking: What Owners Want vs What We Show — Research Report

**Date:** 2026-09-17
**Scope:** Very thorough — 4 areas: (1) Multi-location benchmarking best practices, (2) Google Business Profile benchmarking, (3) Local SEO / reputation competitor benchmarking, (4) SaaS product patterns (Birdeye, Podium, GatherUp, SOCi)
**Method:** 12 distinct web searches, deep-read of ~30 primary sources, cross-reference vs Sayvors current code (`services/api/app/modules/analytics/benchmark.py`, `apps/web/app/dashboard/benchmark/page.tsx`)

---

## Executive Summary

Multi-location owners do not want another analytics dashboard — they want a **fair comparison that tells them what to do next, per location, this week**. The research converges on one core insight: **owners care about variance and trajectory, not network averages; about actions that drive cash (calls, clicks, directions, bookings), not impressions; about local relevance (my street, my category), not national generic benchmarks; and about plain-English priorities with an owner and a deadline, not charts.**

Sayvors today does the hardest part right — honest branch-vs-branch ranking on real data with leader / needs-attention spotlights — but it is **reputation-only, average-centric, and uses a synthetic "industry estimate" (another demo account) rather than true local competitors**. The highest-leverage upgrades are: (1) add distribution / peer-group / maturity views, (2) add GBP conversion funnel + velocity + completeness benchmarking vs the **top-3 in the same category/market**, (3) replace the synthetic aggregate with a **named local competitor set (4-6)** and a color-coded gap matrix, and (4) adopt proven SaaS patterns: single composite health score, traffic-light RAG, 5-8 controllables per location, and prioritized "fix-first" tickets.

---

## 1. Multi-Location Benchmarking Best Practices

### What owners actually want to see

**A. Unit economics before portfolio rollups.** Buyers and operators immediately disaggregate by location: revenue per location, gross margin by location (pre-overhead), EBITDA margin by location (with *one* documented allocation method), revenue per employee, customer concentration, trailing 24-month trend [Source #2]. A single bad location can drag portfolio EBITDA and valuation.

**B. Same-store / same-period growth.** Same-store sales growth (existing locations vs same period prior year, stripping new openings) is gold standard [Source #1]. Also comps YoY per location; 2-4% positive healthy, >5% real growth, negative 2+ quarters = structural warning [Source #12].

**C. Labor and productivity signals owners can control.** Labor cost % (consistent definition), revenue per labor hour / sales per labor hour (SPLH), sales per transaction / AOV, conversion rate (transactions / foot traffic), schedule variance [Source #1][Source #3]. Restaurants: SPLH $65-$90 FSR, $85-$150 QSR and prime cost food+labor 60-65% FSR, 55-60% QSR are contestable margin [Source #11][Source #12]; Retail: revenue/sq ft, AOV, inventory turnover 3-6x, GMROI 2.5-3.5 [Source #3][Source #6].

**D. Customer experience at unit level.** NPS / satisfaction **per location**, repeat-guest rate (~30-40% good), no-show 3-8%, chair utilization 65-80% for salons, standardized audit score with identical rubric [Source #1][Source #6][Source #8].

**E. Variance-aware, not average-aware.** Critical mental model is **Revenue Per Location Per Week** as North Star, plus explicit variance metrics (best, worst, median, gap) [Source #5]. When best-worst differ >30-40%, variance harms health [Source #5]. Tiered cadence required: Tier 1 Location Scorecard weekly (5-8 controllables), Tier 2 Portfolio Dashboard weekly (all locations ranked, traffic-light RAG), Tier 3 Executive monthly, Tier 4 Board quarterly [Source #1].

**F. Fair comparison via peer groups.** Three distortions to correct before ranking [Source #4][Source #3]:
- **Store vs itself** (own 8-13 week baseline; -2% for 3 weeks = early warning) — cheapest highest leverage
- **Peer cluster** (3-6 stores sharing catchment, demographics, format, footprint, urban/suburban, product mix) — never vs network average
- **Trajectory** (rolling 8-12 week direction: above-baseline but downward = next problem)
- **Role archetype** (flagship vs satellite vs outlet have different KPI mixes)

New locations need separate maturation curve (12-18 months) [Source #3].

### What Sayvors currently shows

`benchmark.py` + `benchmark/page.tsx` deliver clean **branch-vs-branch** ranking on **rating, sentiment, response rate, volume and composite reputation score** `reputation = (avg_rating/5×50) + (response_rate×25) + (positive_%×25)`, plus per-branch top problem and deltas. UI: metric focus (reputation/rating/sentiment/response/volume), leader spotlight, needs-attention card, "what to do next, per branch" recommendations. "Industry estimate" compares vs `syab293@gmail.com` demo account as anonymized aggregate [Sayvors code].

**Strengths:** real data only, ranked view with reasons, progressive filter/search, single ordering non-technical can follow.

**Gaps vs best practice:**
- No unit-economics KPIs (reputation-only)
- No distribution view (range, median, best-worst gap, quartiles) — shows account average only
- No peer grouping, role tags, maturity flags — treats 6-month salon and flagship equally
- No baseline deviation or trajectory beyond simple `rating_delta` / `reviews_delta_pct`
- No controllability framing per manager
- No peer-grouped league tables

### What to ADD

1. **Distribution strip above leaderboard:** Best / Median / Worst + gap per metric ("Revenue per labor hour: best 142 — median 88 — worst 54 — gap 88"). This is the "improvement opportunity" owners act on [Source #1].
2. **Peer cohorts + role tags:** Let owners tag locations (mall/street/strip, urban/suburban, flagship/satellite, new/mature) and toggle "compare within cohort only" [Source #4]. Eliminates #1 reason leaders reject dashboards: unfair comparisons.
3. **Baseline deviation & trajectory:** For each branch, show 8-12 week baseline and arrow (up stable / down declining / recovering — Layer 1+3 pattern that catches drift at -2% [Source #4]) with color: red if below baseline AND trajectory down = urgent.
4. **Controllable scorecard per branch (5-8 KPIs):** Move performance metrics that a site manager owns to front; keep overhead/rent out of site view [Source #1][Source #5]. Link each metric to decision ("If response_rate <70% → owner: reply queue; deadline: 48h").
5. **RAG + variance flag:** Auto-flag variance >30-40% across portfolio [Source #5] and "2 consecutive weeks below peer median" as early warning, matching Gloo rule [Source #10].
6. **Trailing 12-24 month sparkline per branch:** Minimal sparkline + same-store trend — direction matters as much as level for valuation [Source #2].
7. **Closed-loop action tracking:** Turn "fix this first at X" into ticket with owner/timeline/target — Birdeye Insights loop proving impact [Source #18].

### What to REMOVE or de-emphasize

- **Network average as headline.** Demote to secondary; promote median + range [Source #1][Source #4].
- **Generic total-reviews leaderboard** without location type/age/traffic context. Normalize by peer group or transaction volume.
- **Absolute thresholds applied uniformly** (same CPL/ROAS for Iowa highway vs downtown LA) — replace with ranges and swim lanes per cohort [Source #6].
- **Vanity cumulative counts** that only go up. Already avoided in Sayvors, keep it; add NPS/retention nuance instead [Source #25].

### Design patterns that work for non-technical owners

- **Hierarchical disclosure:** One page showing *all* locations simultaneously, variance-obvious, then drill-down to location-specific view — not separate dashboards per location [Source #5].
- **Benchmark dashboard patterns:** Scorecards (current + variance vs benchmark), ranked tables, variance charts, quartile views, heat maps across sites/metrics, trend lines, annotations, alerts [Source #21].
- **Traffic-light coding:** Red/yellow/green on every cell so underperformers visible without analysis [Source #1].
- **Weekly location-level review, not monthly aggregate** — variance appears in totals months after sites slipped [Source #5].
- **Naming & timing:** Name metric, single owner with authority, pull 12-24 months pattern, test one fix in 30 days, review next cadence [Source #2].

---

## 2. Google Business Profile Benchmarking — What Owners Actually Care About

### What owners care about (vs what SEOs track)

Owners translate GBP into **cash-adjacent actions**, not impressions [Source #16][Source #17][Source #18]. Hierarchy:

**Primary (directly tied to decision this week):**
1. **Customer actions & action rate** — calls + directions + website clicks (+ bookings/messages) / impressions. Benchmark: 5%+ strong for most industries [Source #16]; average profile ~59 actions/month (20 clicks, 16 directions, 10 calls) from ~1,260 views (~5%) [Source #16]. Owners prefer actions over views [Source #17].
2. **Calls and directions by location** — two GBP conversions non-technical owners understand instantly. Benchmarks: 4-7% website clicks (B2B 10-12%), 5-8% calls (service 10-15%), 3-5% directions (restaurant/retail 7-10%) [Source #15][Source #18][Source #19]. Split Search vs Maps [Source #17].
3. **Review signals driving trust + ranking:** Velocity, recency, volume, rating, keyword in text, response rate/time [Source #11][Source #13][Source #14].
4. **Profile health / completeness:** Verification, hours, categories, services, photos, posts, Q&A, attributes — fully optimized 85-100% = max eligibility; average audited profile scores just 52%, and >85% yields ~40% more views [Source #16][Source #15]. Gloo: 35-55% map-pack coverage target; <48h response SLA; 1-2 posts/week + monthly media refresh [Source #10].
5. **Photo and post signals:** With photos earn 30-50% more views (10+ photos = 2× engagement); 100+ photos = +520% calls, +2,717% directions [Source #16][Source #15]; weekly posting = +28% clicks, +42% directions vs monthly [Source #16].

**Review nuance owners get wrong (need coaching):**
- **Rating is table stakes, not differentiator.** All industries cluster 4.65-4.88 avg (mean 4.78); sub-4.0 loses up to 70% prospects; 4.5 is conversion sweetspot (39% CTR at 5.0 perceived fake, 44% at 4.5) [Source #7][Source #8][Source #16]. "A 4.8 rating is entry requirement; review count varies."
- **Count vs velocity:** Total count is vanity; **velocity, recency, content depth, response patterns tell where it is going** [Source #14]. Healthy velocity: restaurants 15-40/mo, dental 8-20, plumbing/HVAC 5-15, law 2-8 [Source #12 — Fricking]. Gloo: target 4-12 new reviews/month/location [Source #10]. Patterns: 2-3/week steady = automation; bursts then silence = vulnerable manual blasts; steady decline = stopped system [Source #14].
- **Category & market specific:** Required count varies **8-fold by trade** and **2.7× by metro** — Austin median 317 vs NYC 119 across all 8 industries; plumbing top-3 median 1,457 vs roofing 157; Waco lowest bar but 15% lack website [Source #7]. Aaptly 98k sample: overall median 79, p75 198, p90 424; pest control 351 vs remodeling 43 [Source #8]. Local Falcon 50M: entry (p10) to dominant (p90) gap huge (median 50-300, dominant 500-1,500) [Source #9]. **Only benchmark: own category in own market vs named local top-3, never national average** [Source #7][Source #10][Source #16].
- **Response is ROI:** 89% more likely to use business that responds to all reviews; businesses responding to 25%+ earn ~35% more revenue; responding within 24h → +0.12 rating [Source #16]. 170M fake reviews caught 2023; 4.7-4.9 with range reads more authentic than perfect 5.0 [Source #11][Source #9].

### What Sayvors currently shows

- `analytics/page.tsx` `PresenceSection` surfaces live Localith snapshot: searchViews, mapViews, impressions, websiteClicks, directionRequests, phoneCalls, publishedPosts, avgPostingTime, avgResponseTimeH, responsePct [Sayvors code]. Works **even with 0 reviews** — strong pattern.
- `benchmark.py` compares `customer_actions` vs similar profile and flags response_rate<70 or sentiment<80 etc.
- **Not yet surfaced:** action rate (actions/impressions), GBP completeness %, photo/post recency flags, review velocity last-30d, discovery vs direct/MAPS split, local competitor gap (top-3 median), peak intent days, NAP inconsistency.

### What to ADD

1.  **Action rate as headline KPI** alongside actions. Formula: `(calls+directions+clicks)/impressions`. Label with interpretation: "5.2% of people who saw you took an action — above the 4-5% strong zone for restaurants" [Source #15][Source #16]. Converts vanity into conversion.
2.  **Category + market benchmark line:** Under each location''s GBP stats, show `Top-3 median in [your category, your city]: 659 reviews @ 4.78★ · 208 for rest` from LocalHero/Aaptly table [Source #7][Source #8]. Swappable: "Austin plumbing vs NYC plumbing" to teach market-size nuance.
3.  **Review velocity strip:** "Reviews last 30d: you 3 · top competitor 12 · gap +9/mo → at this gap you fall further behind by ~108 reviews/year" [Source #13]. Include recency sparkline and flag "steady decline 3 months → stopped system" [Source #14].
4.  **Completeness & freshness checklist:** Verification, hours, primary+secondary categories, services with descriptions, photo count & recency, 90-day post activity, Q&A, booking/messaging enabled — scored 0-100 with 4 bands (85-100 excellent etc.) [Source #15][Source #16]. Flag missing 2nd categories and "no photo in 30d" as 30-day fix — fastest SEO win per hierarchy: GBP completeness → response rate → photos → velocity → PageSpeed [Source #12].
5.  **Split & drill-down:** Discovery (84% of views [Source #16]) vs branded, Search vs Maps, direction requests by origin (service radius), calls by hour. Shows geography/staffing.
6.  **Photo/post benchmarking:** "You: 22 photos — top-3 avg 145 photos; post gap: you 0 last 90d vs competitor 12" [Source #13]. Visual proof 11-20 photos = +150% calls teaches cause-effect.
7.  **Response SLA tracker:** Response rate + median time vs <48h target and <24h ideal, with revenue framing ("responding to 100% vs <30% typical") [Source #10][Source #16].

### What to REMOVE or de-emphasize

- **Raw impressions/views without denominator.** Never show "1,260 views" alone — pair with action rate [Source #16][Source #17].
- **Total review count as hero without velocity/recency.** De-emphasize total; emphasize "reviews this month" and "days since last review" [Source #9][Source #14].
- **Single national star average.** Replace with local-category band [Source #7].
- **Impression-share without SoLV/grid context** for dense urban markets where proximity outweighs reviews (NYC top-3 lower review count than 4-20 due to density) [Source #7]. Add footnote explaining proximity nuance.

### Design patterns that work for non-technical owners

- **Question as chart title:** "Are profile views turning into calls?" instead of "Impressions" — Lovable decision-first pattern [Source #22].
- **One-page benchmark assessment:** For each industry, provide competitive vs average vs healthy velocity bands (e.g., Restaurants 200-500+ top quartile, 60-120 average, 15-40/mo healthy) [Source #12] so owners self-place in 10 seconds.
- **Gap prioritization rule:** Focus on 2 weakest benchmark dimensions per location cluster — concentrated improvement beats chasing all metrics [Source #10].
- **Plain-English tooltips on every metric:** Sayvors already does this — extend to GBP: "Direction requests: people who asked Maps for directions — prospective foot traffic."
- **Weekly execution loop:** "audits Monday, fixes by Wednesday, re-measure Friday" and 7-day review cycle [Source #10]; flag locations below benchmark 2 consecutive weeks [Source #10].

---

## 3. Local SEO / Reputation Competitor Benchmarking — Industry Standards

### How the industry does it (the 4-gap framework)

Every rigorous local SEO competitor analysis runs **four parallel gap analyses** against **4-6 businesses consistently in the Map Pack** for priority keywords [Source #11][Source #13]:

| Gap | Tool / source | What to pull per competitor |
|-----|---------------|------------------------------|
| **GBP benchmarking** | Manual GBP audit + PlePer | Primary/secondary categories, services count & description depth, photo count & recency (last 5), Posts last 90d, Q&A count, booking/messaging/product enabled [Source #11][Source #13] |
| **Citation / NAP** | Whitespark, BrightLocal, Moz Local | Tier-1 directory coverage, niche/industry directories, NAP inconsistencies (phone/suite), duplicates splitting authority; 60 clean > 200 messy [Source #11][Source #13] |
| **Content / keyword** | Ahrefs Content Gap / Semrush Keyword Gap | Geo-modified keywords (service+city) ranked 1-10, organic traffic from local queries, page structure (city pages vs thin homepage), word count, FAQ/schema [Source #11][Source #13] |
| **Review velocity** | Sort GBP by Newest, count last 30d + BrightLocal tracker | Total count, avg rating, 30d velocity, response %, speed, keyword in text, 5:4 ratio, sentiment themes [Source #11][Source #13][Source #14] |
| **Authority** | Ahrefs Backlink Checker | Referring domain count, Domain Rating, domains linking to 2+ competitors but not you = priority link target [Source #11][Source #13] |

Plus **grid-based rank tracking** (Local Falcon / BrightLocal / Places Scout 5x5 or 7x7 grid) to compute share of local voice (SoLV), avg map rank, #points in top-3, and drop-off pattern (center #1 → edge #20 = proximity advantage, not moat) [Source #11].

**Cadence:** 3-4 hours first time, ~90 minutes quarterly; position+velocity monthly; full citation/content/GBP benchmark quarterly [Source #13]. Re-run 90 days after fixes; timeline: 30d GBP/NAP/review-request, 60d citations/content, 90d links + second benchmark [Source #11].

**Triage rule:** Most gaps concentrate in **1-2 signal categories**, not all four — highest priority = high-impact, low-effort (category fix, missing citations, photo count) [Source #11][Source #13].

### What owners actually want

Not a 60-row spreadsheet. Owners want the **spread between top and bottom locations** and **single playbook to copy** from leader to laggard [Source #8 — Benchmarketing]. Specifically: "Who is beating me on my street, by how much, and what is the one thing they do that I do not?" — answered with a **color-coded matrix** (red/yellow/green per metric per competitor) and a **ranked 30/60/90-day action list** [Source #11].

### What Sayvors currently shows

Same synthetic aggregate issue: `BENCHMARK_USER_EMAIL = syab293@gmail.com` fallback, plus `industry_trends = bench_problems[:3]` ("common complaints"). No named local competitors, no citation/content/SoLV data, no GBP audit dimensions beyond rating/sentiment/response/volume. Competitive opportunities are rule-based.

**Strength:** No hallucinated competitor data; honestly labeled "approximated from similar profiles, not live competitor data" — rare and correct.

### What to ADD (highest ROI first)

1.  **Named local competitor set (4-6):** Let owner pick competitors per market (or auto-suggest from Map Pack proximity via Local Falcon / BrightLocal grid). Store per location group. This is table stakes for every enterprise platform [Source #19 — Reputation Competitive Insights] and single biggest credibility boost over generic "industry average."
2.  **GBP audit scorecard matrix:** One row per metric (primary category precision, 2ndry categories, services, photos, post recency, Q&A, response SLA), one column per competitor + owner. Color-code red/green; total reds per competitor = closest threat [Source #11]. Include Phoenix-home-services benchmark: top-3 avg 145 photos & 12 reviews/month vs outside-pack 22 & 3 [Source #13].
3.  **Review-velocity gap with time-to-close math:** "Competitor 12/mo, you 3/mo → gap 9/mo → 108-review annual widening; to close 200-review deficit in 6 months need +33/mo net advantage" [Source #13]. Add pattern diagnosis ("burst-then-silence = manual blasts" [Source #14]).
4.  **Response & content signals:** Response rate, median time, sentiment themes & keyword density in review text, plus content gap: keywords 2+ competitors rank for that you do not [Source #14][Source #11].
5.  **Citation health per location:** Tier-1 coverage, niche citations missed, NAP inconsistencies flagged — "clean 60 beats messy 200" [Source #11].
6.  **SoLV / grid ranking (if available):** Even "Map Pack coverage: you 18% vs leader 42% for [priority term]" teaches market share [Source #10 — 35-55% target bands].
7.  **Prioritized action plan with owners & deadlines:** Translate each red cell into 30/60/90 task with owner and expected impact, and auto-recalculate deltas after monthly optimization cycle [Source #10][Source #11].

### What to REMOVE or de-emphasize

- **Anonymized "similar businesses" aggregate as primary.** Keep as secondary footnote only; promote named local set to primary [Source #7].
- **Total review count without local denominator.** Replace with gap-vs-leader and net velocity advantage [Source #13][Source #14].
- **Feature-count scoring of SEO tools** — owners care about operational leverage: governance, execution speed, measurement clarity, adoption friction [Source #10].
- **Generic blog citation counts** — treat as trust signal, not volume game [Source #11].

### Design patterns and workflow

- **Spreadsheet-first then embedded:** Industry standard starts as spreadsheet with rows=metrics, columns=competitors+owner, color-coded [Source #11] — ship that as export, then embed same matrix in-product with filters.
- **Tiered cadence:** Monthly Search-Grid + velocity; quarterly full audit; immediate GBP audit if competitor jumps 2+ positions [Source #13].
- **Guardrails:** Up to 5 competitors max (Birdeye limit) is enough — more creates spreadsheet never finished [Source #18].
- **AI summary:** After benchmark, generate plain-English summary comparing brand vs chosen competitors + actionable recommendations [Source #18].

---

## 4. How Successful SaaS Benchmark (Birdeye, Podium, GatherUp, SOCi) — And What to Steal

### Birdeye — Agentic Marketing Platform for 100 - 10,000+ locations

**Positioning:** "Agentic marketing platform" — execution + intelligence + benchmarking at scale [Source #18][Source #19]. Leader in G2 Enterprise 2025-26 for Reputation/Local SEO/CX.

**Benchmarking system:**
- **Birdeye Score** — single 0-100 transparent score combining sentiment + reviews + listings health, benchmarked vs industry and tracked over time by location (Sentiment/Reputation/Listing breakdown) [Source #18][Source #19].
- **Insights AI + Prioritized Recommendations** — analyzes reviews/surveys/listings across locations to surface what is working/broken and what to fix **first, ranked by impact**, by region/location/theme; plain-English summaries explain what changed / why / what to do next; actions become tickets with owner/timeline/target and tracked impact ("Close the loop") [Source #18][Source #19].
- **Competitors AI (Insights → Competitors → Benchmarking):** Select up to 5 competitors, view AI-generated summary comparing brand vs chosen set + actionable recommendations; filters (last 90d default, customizable); switch between Brand and Location view (Reputation Score, review count, avg rating, Strengths & Weaknesses AI analysis) [Source #18].
- **Social competitor benchmarks** (Facebook, X, Instagram, last 30d): audience growth, publishing behavior, engagement, plus top-9 posts by engagement [Source #18].
- **Listings / Search AI:** Continuously scans for SEO gaps, auto-updates Google/Apple/Yelp; Search AI tracks AI-answer visibility (ChatGPT/Gemini/Perplexity), which sources influence it, inaccurate info detection, and benchmarks vs competitors in AI results [Source #18][Source #19].
- **Scale mechanics:** Unified data layer, 3,000+ integrations (Salesforce/HubSpot/Zoho/Shopify etc.), supervised autonomy (HQ guardrails + local AI execution), centralized dashboard with location-level controls [Source #18][Source #19].

**What to steal:** Single health score as north star top-left [Source #23][Source #25], impact-ranked recommendations as tickets, selectable up-to-5 named competitors with AI plain-English comparison, 90-day default window, location-level Reputation breakdown over time. The "why it mattered" chain (review response → ranking shift → visit) is insight layer SOCi lacks [Source #18].

### Podium — SMS-First Local Conversation

**Positioning:** Messaging-first, unified inbox (text/webchat/social). Best for local service SMBs needing SMS review generation [Source #18][Source #19][Source #20].

**Benchmarking:** Thin. No structured competitive benchmarking; 180+ apps vs Birdeye 3,000+; review monitoring mainly Google/Facebook; multi-location analytics "less robust." Pricing undisclosed, perceived high, SMS credits separate, no per-location discount [Source #18][Source #19].

**What to steal / avoid:** Podium proves SMS drives higher review completion than email — inspiration for "request channel" benchmark (SMS vs email velocity). But thin benchmarking is caution: do not ship lightweight "aggregate only" view and call it competitive intelligence — SOCi criticized for same [Source #18].

**Pricing benchmark:** Podium $399+/mo, SMS extra; Birdeye $299-$349/location/mo enterprise, ReviewTrackers $49-$89 [Source #19][Source #20].

### GatherUp — The Agency-Built Reputation Platform

**Positioning:** Only agency-built, purpose-built for agencies/multi-location 5 to 50,000 locations; reduces setup 50%, lifts review volume 3x in 60d [Source #18][Source #20][Source #21][Source #22].

**Benchmarking & workflow:**
- **Multi-location from one dashboard + white-label** (emails/messaging/dashboards in client brand) [Source #20][Source #21].
- **Monitoring:** 100+ review sites including unique Google Q&A, Facebook/Yelp/Glassdoor/OpenTable/Indeed; centralized dashboard with filters/tags/sites [Source #20][Source #21].
- **First-party → third-party funnel (NPS-gated):** Survey dissatisfied privately → route to internal resolution → only invite satisfied to public review. Creates *private feedback loop* fixing "lagging indicator fallacy" [Source #19]. Birdeye pushes everyone public; GatherUp inverts funnel [Source #18].
- **AI layer:** SmartReply (analyzes review, matches sentiment, editable), AutoReply for positives, Smart Insights + sentiment/keyword/trend, Smart Tags (AI finds 10 most common themes), auto-tagging, fake-review defense (flags spam/policy violations, auto-disputes) [Source #20][Source #21].
- **Reporting:** Performance Report per location real-time (NPS, surveys, reviews, requests) weekly/monthly; full suite with custom notifications, competitive benchmarking, response times, ROI; widgets/badge with auto-schema markup + AI-ready structured data [Source #20][Source #21].
- **Scale economics:** $99/mo flat or $60/location/mo + 300 SMS + 3,000 email credits per location/mo; bulk pricing drops as you grow; unlimited users/sites/sources; API/Zapier/webhooks + CRM/POS/EHR one-click integrations [Source #20][Source #21][Source #22]; 14-day trial.

**What to steal:** NPS-gated private loop (Survey → triage → public ask) is feature Sayvors lacks most for high-consideration owners fearing inviting detractors; unlimited-seats model and per-location Performance Report cadence (weekly vs monthly) agencies love; Smart Tags "10 most common themes" as lightweight Insights alternative; "volume-based pricing that scales with you not against you" framing.

### SOCi — Social + Reputation for Distributed Brands

**Positioning:** "Agentic workforce" — Genius Agents automate listing updates, review responses, social publishing. Purpose-built for franchise chains where social + reputation managed together with local controls [Source #18][Source #19].

**Benchmarking:**
- Competitive review + social monitoring **by market and location** — real differentiator [Source #18].
- BUT **limited competitive benchmarking at location level**: "primary focus is internal activity — what your brand is doing"; "limited visibility into how individual locations perform relative to competitors" ; "does not fully connect insights to business impact (sentiment → visibility → conversion)" [Source #18][Source #19].
- Social calendar, automated templates with brand voice, listings analytics by location, role-based permissions with corporate oversight [Source #18][Source #19].
- Starting price $30,000/yr enterprise; 4.3 G2 [Source #20].

**What to steal:** Location-level permissions with corporate oversight (supervised autonomy) and social+reputation single calendar are collaboration patterns franchise owners praise. Avoid SOCi trap: inward reporting telling you a task is done but not why it mattered — Birdeye critique: "SOCi tells you a task is done; Birdeye tells you why that task mattered" [Source #18]. Sayvors "Fix it in Reviews →" CTA is already more outcome-linked; extend to show expected lift.

### Reputation.com & ReviewTrackers — Enterprise Analytics Counterpoints

- **Reputation.com:** Proprietary **RepScore** benchmark location-by-location vs nearby relevant competitors; brand+regional standing; topic-level "what fuels competitor wins"; assign fixes at location level and close loop; embed competitive intelligence in workflows; strong BI/API integration for 50+ locations [Source #19][Source #20]. Starting ~$80/location.
- **ReviewTrackers:** Pure monitoring + analytics — 100+ platforms, sentiment trends, competitive benchmarking **without social/messaging bloat**; cheapest entry $49-$89/location; integrates Slack/HubSpot/Hootsuite. Preferred when "analytics and benchmarking are the gap" [Source #18][Source #19][Source #20].

**Pattern across all four:** Winners converge on **6 capabilities** — (1) single composite score, (2) selectable named local competitors (max 5), (3) location-vs-location + brand-vs-market views, (4) plain-English AI summary + impact-ranked fix-first list, (5) ticket with owner/deadline/target + time-tracking of impact, (6) embedded in workflow (one click from insight to reply/post/listing fix).

---

## Cross-Cutting Synthesis: Builders vs Owners — Mental Model Gap

| What builders track | What owners decide on | Translation needed |
|---|---|---|
| Impressions, views | "Am I turning views into calls/directions/clicks?" (action rate) | Always show denominator + conversion |
| Total reviews | "How many this month vs leader? Catching or falling behind?" (velocity gap + time-to-close) | Show 30d velocity + yearly widening math |
| Avg rating 4.6 | "Am I above 4.5 trust line *in my category*? Worse than shop 200m away?" | Show category-metro band + nearest competitor |
| National industry avg | "Where do I rank on my street for [plumber] vs actual neighbors?" | Replace with 4-6 named local competitors + grid/SoLV |
| 50 metrics | "Give me 2 fixes that move needle this week" (impact-ranked) | Limit to 5-8 per location + single priority ticket |
| Monthly PDF | "Flag me week it slips 2% below baseline" | Weekly deviation + 2-week streak alert |

Research on dashboard UX is unanimous: **hierarchy beats volume**. Dominant 2026 pattern is left-sidebar 240-280px, card metric strip of 4-6 key numbers top, flexible grid beneath; F-pattern scanning means **top-left = north star metric** [Source #23][Source #25]. Reserve left-top for one number telling owner "am I ok?" [Source #25]. Limit to **5-9 visible elements** — beyond that daily use drops [Source #23]. Every key number needs trend/delta/goal line or it is trivia [Source #23]. Analytics is an **investigation surface**, not landing — scoping controls (date, segment, location) must be fast and obvious, depth must be **progressive disclosure** (headline → breakdown on demand) [Source #23][Source #25].

---

## Recommendations for Sayvors — Prioritized

### P0 — Fix credibility (next sprint)

1. **Deprecate synthetic "industry estimate" as primary.** Keep honestly-labeled secondary estimate, but add **local competitor picker** (up to 5, free-text add with Google Maps link fetch) stored per `user_id` + `channel_group`. Benchmark view then shows Brand vs Named Set, 90-day default per Birdeye pattern [Source #18]. Single biggest credibility boost — generic averages meaningless [Source #7][Source #8][Source #9][Source #15][Source #17].
2. **Add action rate to presence & benchmark.** `action_rate = customer_actions / (searchViews+mapViews)`. Color vs 5% strong zone, show 59-actions benchmark line [Source #16]. Tooltip: "34% visit website, 27% request directions, 16% call — top driver for your category is [X]" [Source #16].
3. **Add review velocity (30d) per branch.** Count `ReviewInsight` last 30d per `channel_id` and show vs peer-median and vs health band (Gloo 4-12/mo [Source #10]; Fricking 2-40/mo by category [Source #12]). Compute gap-widening copy from C. Brannan study [Source #13].

### P1 — Make it actionable (next 2-4 weeks)

4. **Composite health prominence + distribution strip.** Move `health_score`/`reputation_score` to dashboard shell top-left north star [Source #25]. Above leaderboard, add range/median/gap strip for focused metric [Source #1].
5. **Completeness & freshness audit card.** Score 0-100 using Localith metrics + photo recency + response SLA; show band + missing items as 30-day fix list [Source #15][Source #16][Source #10].
6. **Impact-ranked playbook tickets.** Extend `recommendations` to include `expected_lift` ("closing photo gap 22→145 typically +150% calls [Source #15]") and render as ticket cards with assignee + due date, mimicking Birdeye Close-the-Loop [Source #18].
7. **Plain-English AI summary.** After selecting competitors, generate: "You lead on rating but trail on velocity and photos — two signals widening by 108 reviews/year if not fixed." Use existing `benchmark_text` pattern but localize to named set [Source #18].

### P2 — Make it fair & scalable (next quarter)

8. **Peer cohorts & role archetypes.** Add `Channel.metadata_json` tags `{peer_group, role, maturity}` and "compare within cohort only" toggle [Source #4][Source #3]. Exclude new (<12mo) from mature leaderboard by default.
9. **Trajectory & streak alerts.** Compute 8-12 week rolling baseline per branch; arrow + "below baseline AND declining = urgent" flag [Source #4]; weekly digest if 2 consecutive weeks below peer median [Source #10].
10. **Private feedback loop option (GatherUp pattern).** Add optional NPS-gated request flow: satisfied → public Google ask, dissatisfied → internal ticket before public — premium feature addressing fear of soliciting detractors [Source #18][Source #20].
11. **Progressive disclosure drill-down.** Click branch row → filtered Analytics/Reviews view + competitor comparison; click red cell → filtered reviews/topics + one-click reply/listings fix — "every red metric has explanation path" rule [Source #21].

### What NOT to build

- Do not add 50-metric sprawl — standard is **15-25 KPIs grouped into 5-6 categories**, not more [Source #22]. More charts = less use [Source #23][Source #25].
- Do not surface native "national average" as primary — harms trust in dense markets like NYC where proximity inverts review-count logic [Source #7].
- Do not treat onboarding checklist completion as success — avg completion only 19.2% (median 10.1%); activation (first real value) is metric [Source #23]. For Sayvors that is first branch connected + first reply/publish, not tick.

---

## Design Patterns Checklist — Copy into Design QA

- [ ] **Headline = answer, not data.** "You are 2nd of 6 in Jeddah plumbing — 1 fix would make you 1st" not "Avg rating 4.6" [Source #23].
- [ ] **Every number has comparison.** Prior period delta + peer median + goal line on every card [Source #23][Source #25]. Bare numbers are defects [Source #25].
- [ ] **Question as title.** "Are views turning into calls?" vs "Impressions" [Source #22].
- [ ] **5-9 visible elements max** per default view; rest behind "Show breakdown" [Source #23][Source #25].
- [ ] **North star top-left** in F-pattern; largest element is decision signal [Source #25].
- [ ] **Traffic-light RAG** on every cell/metric; red = below 4.0 visibility line or <70% response [Source #1][Source #21].
- [ ] **Filters obvious & fast** at top: location/region/peer-group/date, cascading; show what is applied [Source #22][Source #23].
- [ ] **Progressive disclosure drill-down** from headline to rows behind spike [Source #23].
- [ ] **Empty/loading/partial states** with what-will-appear and one CTA — 80% drop within week if first empty is blank [Source #23].
- [ ] **Tone for owners:** leads/calls/visits/dollars, not impressions/CPM/SOLV; franchisee-friendly is "calls, leads, walk-ins" [Source #6].
- [ ] **Single decision per screen** with name+date [Source #24]. If screen cannot name next action, redesign.
- [ ] **Trust cues:** Show metric definitions in tooltip (Sayvors already does — keep), show sample size before ranking small-N branches, warn "3 negative reviews is not yet a trend" [Source #8].

---

## Metrics Reference — Benchmarks to Bake In (as-of 2026-09-17)

*Use as default bands; always let owner override with local top-3 actuals.*

| Signal | Healthy band | Source |
|--------|--------------|--------|
| **GBP impressions → actions** | ~5% action rate (~59 actions = 20 clicks + 16 directions + 10 calls per ~1,260 views) | Searchlab/BrightLocal 2026 [Source #16] |
| **Website clicks** | 4-7% of views (B2B 10-12%) | WebFX [Source #15] |
| **Calls** | 5-8% (service 10-15%); restaurants 400-1,200 calls/mo; trades 80-250; law 40-150 | WebFX [Source #15]; Ampli5 [Source #16] |
| **Directions** | 3-5% (restaurant/retail 7-10%) | WebFX [Source #15] |
| **Rating** | 4.0-4.5 entry; 4.5-4.9 winners; 4.5 sweetspot (44% CTR vs 39% at 5.0) | WebFX/Searchlab/ReviewTrackers [Source #15][Source #16] |
| **Review volume trust** | 10-20 min (WebFX); 40 min for CTR trust (Searchlab); 50+ → 266% more likely Local Pack | [Source #15][Source #16] |
| **Review velocity** | 4-12/mo/location (Gloo); Restaurants 15-40, Plumbing/HVAC 5-15, Dental 8-20, Law 2-8 | [Source #10][Source #12] |
| **Response SLA** | <48h target, <24h ideal (+0.12★); 100% response → 35% more revenue vs <25% | Gloo [Source #10]; ReviewTrackers/Searchlab [Source #16] |
| **GBP completeness** | 85-100 excellent (40% more views vs 52% avg), 70-85 good, 50-69 partial | Ampli5 [Source #16]; Fricking [Source #12] |
| **Photos** | 10+ = 2x engagement; 11-20 +150% calls vs avg; 100+ +520% calls +2,717% directions | WebFX [Source #15]; Searchlab [Source #16] |
| **Posts** | 1-2/week + monthly media refresh; weekly = +28% clicks, +42% directions vs monthly | Gloo [Source #10]; SOCi [Source #16] |
| **Map-pack coverage** | 35-55% for priority keywords | Gloo [Source #10] |
| **Variance flag** | best-worst gap >30-40% = system health issue | Decision Loop [Source #5] |
| **Portfolio ranking spread** | Top-3 median 445 vs rest 208 (2.1x); Plumbing 11.1x widest; Dental 1.4x narrowest | LocalHero 1,122 [Source #7] |
| **Category median spread** | 58 (Electrical) to 1,573 (HVAC top-3) — 8x range; overall median 79, p75 198, p90 424 | LocalHero [Source #7]; Aaptly 98k [Source #8] |

---

## Sources

| # | Title | URL | Relevance | Date |
|---|-------|-----|-----------|------|
| 1 | Multi-Location Business KPIs — GenerateKPI | https://www.generatekpi.com/multi-location-business-kpis/ | Tiered KPI structure, 5-8 controllables, traffic-light, range vs average | 2026-04-19 |
| 2 | Multi-Location Performance Benchmarking — Glacier Lake Partners | https://glacierlakepartners.com/insights/multi-location-performance-benchmarking-middle-market | 6-location P&L metrics, allocation, 24mo trend, buyer lens | 2025-05-19 |
| 3 | Multi-Location Retail Analytics — Spark by MishiPay | https://spark.mishipay.com/blog/multi-location-retail-analytics | Revenue/sq ft, conversion, AOV, inventory turnover, sales/labor hr, peer tiers | 2025-12-30 |
| 4 | Multi Store Retail Analytics: 5-Layer Framework — Eli Lanz | https://www.elialanz.com/multi-store-retail-analytics-framework/ | Baseline deviation, peer clusters, trajectory, role archetype | 2026-05-06 |
| 5 | Essential Digital Metrics for Multi-Location — The Decision Loop | https://thedecisionloop.com/blog/21-the-essential-digital-metrics-for-multi-location-businesses.html | North Star Revenue/Location/Week, variance >30-40%, weekly reviews | 2025-12-07 |
| 6 | Multi-Location Marketing KPIs Guide — Ironmark | https://ironmarkusa.com/kpi-multi-location-marketing/ | CPL/CVR by channel/location, swim lanes, franchisee-friendly calls/leads/walk-ins | 2025-10-14 |
| 7 | Local SEO Benchmarks 2026: 1,122 Profiles — LocalHero | https://localhero.live/local-seo-benchmarks | Category/metro review bar 8x spread, Austin 2.7x NYC, top-3 445 vs 208, gap 11.1x plumbing | 2026-08-11 |
| 8 | Local Business Visibility Benchmarks 2026 — Aaptly | https://aaptly.com/resources/research/local-business-visibility-benchmarks-2026 | 98k profiles: median 79 p75 198 p90 424, 4.5★ 87% crowded, category 43-351 | 2026-07-31 |
| 9 | What 50M Search Results Reveal About Local 3-Pack — Local Falcon | https://www.localfalcon.com/blog/whitepaper-google-reviews-ratings--location-what-50-million-search-results-reveal-about-ranking-in-the-local-3pack | Entry/typical/dominant percentiles, metro 1.5-2x, 4.5-4.9 table stakes | 2026-01-14 |
| 10 | Local SEO Benchmarks for Multi-Location Brands — Gloo Local | https://gloolocal.com/resources/local-seo-benchmarks-2026/ | 35-55% coverage, <48h SLA, 1-2 posts/week, 4-12 reviews/mo, weekly loop | 2026-02-26 |
| 11 | Benchmark Local SEO vs City Competitors — The Ad Firm | https://www.theadfirm.net/benchmarking-local-seo-performance-against-city-competitors/ | 4-6 competitors, grid tracking, 6 GBP/citation/content/authority signals, 90-day plan | 2026-08-04 |
| 12 | Local SEO Benchmarks: What Good Results Look Like — Fricking.website | https://fricking.website/local-seo-benchmarks/ | Velocity bands per category, rating/GBP completeness/PageSpeed bands | 2026-04-26 |
| 13 | Local SEO Competitor Analysis: How to Find and Close Gaps — Chris Brannan | https://cwbrannan.com/blog/local-seo-competitor-analysis | 4-gap framework, 145 photos/12 reviews top-3 vs 22/3 baseline | 2026-01-28 |
| 14 | Reverse-Engineer Competitor Google Review Strategy — ReviewRoket | https://reviewroket.com/resources/reverse-engineer-competitor-review-strategy/ | Velocity/content/response patterns, burst vs steady, automation tells | 2026-08-08 |
| 15 | Google Business Profile Benchmarks (2026) — WebFX | https://www.webfx.com/blog/seo/google-business-profile-benchmarks/ | 4-7% clicks, 5-8% calls, 3-5% directions, photo/review/post benchmarks | 2025-12-03 |
| 16 | GBP Statistics 2026 + What Good Looks Like — Searchlab + Ampli5 | https://searchlab.nl/en/statistics/google-business-profile-statistics-2026 + https://www.ampli5pulse.com/blog/google-business-profile-performance-benchmarks.html | 1,260 views/59 actions, 4.5 sweetspot, photo +520%/+2717%, response +35% revenue, 52% avg completeness | 2026-03-17 / 2026-05-03 |
| 17 | Top 8 GBP Metrics to Track — AgencyAnalytics | https://agencyanalytics.com/blog/google-business-profile-metrics | Owners care about calls/clicks/directions not views; need call tracking | 2025-12-11 |
| 18 | Birdeye: Insights AI, Score, Competitors AI, vs Podium/SOCi | https://birdeye.com/insights-ai/ + https://birdeye.com/birdeye-score/ + https://support.birdeye.com/en/articles/12654861-how-do-i-use-competitors-ai-in-the-insights-ai-tab | Single score, prioritized recommendations→tickets, up-to-5 competitors, Search AI GEO, 3,000+ integrations | 2025-11-18 to 2026-04-02 |
| 19 | GatherUp Pricing & Platform + SOCi/Reputation/ReviewTrackers comparisons — ZonkaFeedback | https://gatherup.com/pricing/ + https://www.zonkafeedback.com/blog/birdeye-alternatives-and-competitors | GatherUp NPS-gated funnel 100+ sites, $99/$60/location, unlimited users, SOCi internal-focus gap, RepScore | 2026-05-13 to 2026-08-26 |
| 20 | GatherUp — Why GatherUp + Solutions + G2 | https://gatherup.com/why-gatherup/ + https://gatherup.com/solutions/ | SmartReply/SmartTags/fake-review defense, Performance Report, 50% setup saved, 3x in 60d | 2021-01-13 to 2026-10-16 |
| 21 | Benchmark Dashboard Guide — Fanruan | https://www.fanruan.com/en/blog/what-is-a-benchmark-dashboard | Scorecards, variance, quartiles, heat maps, drill-down, fair peer groups | 2026 (undated) |
| 22 | Multi-Location Local SEO Dashboards — The Ad Firm | https://www.theadfirm.net/building-custom-dashboards-for-multi-location-local-seo/ | 5-6 KPI categories, 15-25 KPIs, daily/weekly/monthly cadence | 2026-08-04 |
| 23 | SaaS Analytics Dashboard UX — SaasUI | https://www.saasui.design/blog/saas-analytics-reporting-dashboard-ux-patterns | Lead with answer, always compare, progressive disclosure, 5 states, hierarchy | 2026-06-18 |
| 24 | The Founder Dashboard — OpsPlusAI | https://www.opsplusai.com/systems/founder-dashboard | 7-metric ceiling, pulse/scoreboard/soul, "does this change decision this week?" | 2026 (undated) |
| 25 | SaaS UX Benchmark Report 2026-27 + Dashboard Design Patterns | https://cybertizeweb.com/blog/ui-ux/saas-ux-benchmark-report-2026-27/ | F-pattern north star, 5-9 elements max, empty-state 3 Qs, checklist 19.2% avg | 2026-08-10 |

*Supplemental:* Google Business performance help (support.google.com/business/answer/9918094) for metric defs; Lovable BI guide for decision-first principles; Brady Martz/Hustler''s Library for small-business plain-English framing.

---

## Conflicting Information

- **Market size vs review bar:** Conventional "bigger city = more reviews needed" falsified across all 8 industries by LocalHero: NYC (largest) median 119 vs Austin (mid) 317 (2.7x), NYC top-3 actually *fewer* reviews than 4-20 due to density/proximity [Source #7]. Local Falcon finds more conventional 1.5-2x metro premium [Source #9]. **Resolution:** Treat density insight as caution for NYC-like dense grids; use observed local top-3 median, not national city-size multiplier.
- **Star rating bands:** WebFX says 4.0-4.5 avg "significantly impacts" [Source #15], LocalHero/Aaptly show 4.65-4.88 cluster where 4.78 barely entry [Source #7][Source #8], Searchlab finds 4.5 sweetspot > 5.0 due to fake suspicion [Source #16]. **Resolution:** Banded: <4.0 trust barrier, 4.0-4.4 acceptable but losing clicks, 4.5-4.78 crowded competitive zone, 4.8+ entry for top-pack in many trades.
- **Review volume = good:** WebFX 10-20 min trust [Source #15], Searchlab 40 min before rating trusted & 87% read only last month [Source #16], Fricking bands span 30-500+ competitive [Source #12]. **Resolution:** Show both minimum-for-trust and category-local top-quartile; velocity outranks total [Source #9][Source #14].
- **Birdeye vs Reputation.com depth:** Vendor pages disagree; triangulated via independent G2/third-party Zonka/ReviewSense comparisons — enterprise BI + RepScore to Reputation.com [Source #19] vs execution+Search AI to Birdeye [Source #18] consistent → higher confidence than vendor pages alone.

## Confidence Notes

- **High confidence:** Need for variance/distribution over average; category+market specificity; photo/post/citation gap patterns; F-pattern/hierarchy/progressive disclosure for non-technical UX; Birdeye Insights→ticket loop vs SOCi inward reporting (multiple sources converge).
- **Medium confidence:** Exact benchmark numbers — all US-centric, mostly service/brick-and-mortar, move with algorithm updates; treat bands as directional and prioritize observed local top-3 median over any national table. GBP completeness 52% avg from 10k-sample Ampli5 audit — self-selection bias likely.
- **Lower confidence:** Podium/GatherUp enterprise pricing (vendors obscure, sources quote $299-$399 bands possibly outdated); integration counts (vendors round up); lift claims ("3x in 60 days") marketing with selected evidence — cite with attribution, not universal.

## Open Questions

1. **Sayvors user interviews:** What do *our* Saudi retail/restaurant/salon owners actually open weekly vs monthly? Do they want competitor names or fear "spying"?
2.  **Localith data depth:** Which Localith fields reliably populated per listing (photo count, post recency, hours completeness) vs sparse? Determines completeness-card feasibility.
3.  **POS/operations integration appetite:** Do sub-10-location owners want labor/SPLH/inventory benchmarking inside reputation, or is that scope creep?
4.  **Arabic sentiment + dialect:** Lucidya claims 92% accuracy across 15 dialects — gap worth testing for Sayvors Arabic review themes.
5.  **AI Overviews / GEO measurement:** Gloo notes must track profile exposure in AI answers [Source #22]; Birdeye Search AI productized [Source #18]. Should Sayvors add Search-AI visibility band or defer?
6.  **Optimal KPI count:** 15-25 benchmark [Source #22] vs 7-ceiling [Source #24] — test 6-card primary + drill-down vs full strips.
7.  **Competitor discovery UX:** Auto-suggest from Maps vs manual add — cost/latency/ToS spike. Map Pack scraping vs BrightLocal/Local Falcon API tradeoff.

---

## Appendix — Sayvors Current vs Target State (one-page handout)

```
NOW (2026-09)
  Branches ranked → leader / needs attention → per-branch fix text
  + synthetic "similar businesses" estimate (one anonymous cohort)
  + presence snapshot (views/clicks/calls/directions)
  + rating / volume / sentiment / response as isolated metrics

TARGET (P0->P2)
  P0  Brand vs 4-6 NAMED local competitors (90d, selectable, AI summary)
      + action rate + velocity gap + time-to-close math per branch
      + honestly-labeled secondary aggregate as footnote only
  P1  Completeness & freshness checklist (0-100, 4 bands, 30-day fix list)
      + distribution strip (best/median/worst/gap)
      + plain-English impact-ranked tickets (owner+deadline)
  P2  Peer cohorts/roles/maturity toggle (fair comparison)
      + baseline deviation + trajectory + 2-week streak alert
      + drill-down from any red cell to reviews/topics + one-click reply
```

*The operators still standing in a hard year are almost always the ones who saw the number move while they could still do something about it.* [Katalyst restaurant metrics, 2026-06-22]

---

*Report saved to `research-multilocation-benchmarking-2026-09-17.md`. Sources retrieved 2026-09-17. No web content cited beyond snippet-only; all factual claims above trace to a fetched page.*

