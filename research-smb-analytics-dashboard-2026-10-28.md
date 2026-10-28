# What Real SMB Owners Want from a Business Analytics Dashboard

### Evidence review + per-page product spec for Overview, Insights, Growth, and Benchmark

**Prepared:** 28 October 2026  
**Scope:** SMB and multi-location retail, restaurants, clinics, and services; review management, messaging, and local-marketing SaaS (Birdeye, Reputation.com, Podium, Looker Studio templates, and adjacent tools)  
**Evidence base:** 46 sources — 27 Reddit threads (owner/operator/practitioner voices), 5 G2/Capterra review pages, 6 Local Search Forum threads, 3 vendor documentation pages, and 5 surveys/vendor datasets.

---

## Executive Summary

The strongest signal across 46 sources is not "owners want better charts." It is: **owners want a small number of numbers they trust, delivered where they already are, with a clear next action.** The owners and operators in these threads do not ask for more dimensions, more filters, or more AI. They ask for sales, guests, labor, reviews, messages, and repeat customers — and they ask to know whether those numbers are real.

Four conclusions shape the page specs:

1. **Five to ten metrics beat a dashboard.** SMB clients "just want the key numbers" and do not want to "log into a portal, find the right tab, filter five times" [S5]. Agency reporting guidance is a one-page summary with 3–5 metrics and 3 takeaways [S7]. A metric that cannot change a decision is vanity [S6].
2. **Trust is provenance, not polish.** Owners reconcile platform numbers to the bank and CRM [S4]. They notice when Google calls are really call-button clicks [S33], when Toast net sales do not match another report [S34], when GBP data disappears or lags [S40][S41], and when a "directions" stat is obviously wrong [S26]. Once one number is wrong, they question all of them.
3. **Absolute numbers first, percentages second, trend third.** A restaurant operator describes sales up 5% while guest count fell because of a 10% price increase [S1]. Toast pairs dollar totals with percent change, not percent alone [S34]. Review thresholds are absolute: 20 reviews, 4.5 stars, 90 days [S31].
4. **AI is a draft, not an analyst.** Only 46% of people globally are willing to trust AI systems [S36]; 54% of AI users do not trust the data used to train AI [S37]. Practitioners say AI review replies "stand out like a sore thumb" and can "mangle" the response [S39]. AI is useful for summarizing and drafting, but every AI claim needs sources, a sample size, and human approval.

The commercial wedge is reputation. Review generation alone is commoditized [S11], and owners already get review requests from their POS, CRM, or booking tool [S11]. What they will pay for is **review volume that converts, protection when a bad or fake review lands, and a unified inbox that prevents lost leads** [S8][S9][S11][S43]. Messaging is the habit; reviews are the emergency.

---

## How to Read the Evidence

- **Reddit:** Live Reddit pages and the JSON API returned HTTP 403 in this environment. Threads were retrieved verbatim through the PullPush Reddit archive API by thread ID. Scores and dates are as archived at retrieval. Reddit is self-selected and anecdotal; it is used for voice-of-customer language, not prevalence.
- **G2 and Capterra:** Live pages are Cloudflare-protected. Reviews were read from Wayback Machine snapshots dated in the source table. G2 labels many reviews "Incentivized" or "Seller invite"; Capterra includes vendor responses. Ratings skew positive, so negative reviews were prioritized for failure modes.
- **Quora:** Quora returned HTTP 403/Cloudflare and had no usable Wayback snapshots for the target questions. Quora is therefore omitted rather than quoted from search snippets. This is a coverage gap, not a claim that Quora has no relevant answers.
- **Vendor documentation:** Google, Toast, Reputation, and Birdeye docs are treated as primary evidence for what the data actually means and what the product does — not as independent proof that the product works.
- **Adjacent tools (Sprout Social, HubSpot):** both were scoped but are not represented as owner-voice sources here. Accessible G2 snapshots were either marketing-team dominated or stale, and the owner threads in this sample cluster around review, messaging, and POS tools. Their absence is a scope limitation, not evidence that owners do not use them.
- **Surveys:** BrightLocal (1,002 US adults), KPMG (48,000 people, 47 countries), and Salesforce (≈6,000 knowledge workers) are large but not SMB-specific unless stated. Vendor datasets (Birdeye, Reputation) are marketing assets with undisclosed sampling; ReplyOnTheFly discloses its scan methodology but is still a vendor.

---

## The 10 Findings That Should Drive the Product

1. **Five to ten numbers, pushed, not a portal.** SMB clients want the key numbers; they do not want another login, tab, or filter chain [S5]. Agency reporting should be one page, 3–5 metrics, 3 takeaways [S7]. If a metric moves and no action follows, it is vanity [S6].
2. **Trust is provenance.** Every number needs source, period, comparison, denominator, and last-sync time. The owner check is to reconcile to the bank/CRM [S4]; BI consultants define KPIs and run freshness/reconciliation checks [S17]. Google calls are clicks [S33]; Toast net sales can differ by report [S34]; GBP data can vanish or lag [S40][S41].
3. **Absolute first, percentage second, trend third.** "Sales up 5%" can hide falling guest counts after a price increase [S1]. Show dollars, guests, review counts, and messages; add percent change only with a same-length comparison [S34].
4. **AI is a draft, not an analyst.** Trust in AI is conditional [S36][S37]. Use AI to summarize themes and draft replies, always with citations, sample size, confidence, and an approve/edit step [S39].
5. **Mobile is for glance, alert, respond; desktop is for setup and deep dives.** Operators check phones during service [S9]; marketers want a fast spend/CPA/ROAS glance [S13]. Looker/AgencyAnalytics mobile is "hell" [S13]; Looker reviewers also complain about slow loads with many charts [S29]; Podium's app lacks desktop admin capabilities [S27]; Birdeye's app lags [S26].
6. **Alerts must be severity-based, not event-based.** Push bad reviews, waiting customers, missed calls, and sync failures — not every five-star review. Owners already drown in push noise [S5]. Response expectations are fast: 19% expect same-day, 32% next-day, 81% within a week [S31].
7. **Reviews are the wedge; messaging is the habit.** Review requests are commoditized [S11]; owners pay for bad/fake review help, alert-plus-assignment, and theme tracking [S11]. Messaging sticks when it is the unified inbox for texts, reviews, and calls [S9][S27].
8. **Benchmarks are trusted only when local, peer-based, recent, and transparent.** Broad industry averages are "mostly BS" [S14]; analytics practitioners say "you don't" get accurate benchmarks [S15]. Owners want similar-sized/local peers and their own history [S14][S16][S44].
9. **Multi-location needs roll-up + drill-down + bulk action.** A 7-office dental director toggles offices and applies changes across all [S26]; an agency manages 20+ clients from one dashboard [S23]; listings sync assumptions cause silent errors [S30].
10. **Pricing and contract trust affect adoption as much as features.** Owners report 1 review/month/location at $130/location [S8], 13 reviews in a year [S20], 90-day cancellation notices, and auto-renewal traps [S8][S20][S30]. A dashboard cannot recover trust lost to billing.

---

## Part 1 — Cross-Cutting Evidence

### 1.1 The five-number rule: owners want a decision surface, not a data surface

The most consistent complaint is cognitive load, not missing data.

- A BI consultant with 10 years of SMB work says his clients "just want the key numbers. They don't want to log into a portal, find the right tab, filter five times just to see if sales are up" [S5].
- An agency reporting thread recommends a single-page summary with one revenue goal, two or three KPIs, and three takeaways, framed as "inputs → outcomes" rather than activity [S7].
- One operator's rule is three weekly numbers: cash flow this week, contribution margin per sale, and lead-to-client conversion [S3].
- A restaurant manager's actual report list is five things: sales summary, PMIX, labor vs sales, voids/comps, and guest counts/average check [S2]. Restaurant owners also complain about disconnected POS, marketing, and reservation tools, and about analytics tools that are overkill with a steep learning curve [S19].
- A marketing practitioner's test is sales, cost per acquisition versus customer lifetime value, and whether the platform number matches the bank [S4].
- The sharpest formulation: "If a metric can move up or down and no one knows what action follows, it's vanity. Even if it's technically important" [S6].

**Product implication:** the Overview page should have a hard cap of 6 KPI tiles, 3 action cards, and 1 "one thing that changed" insight. Everything else belongs in drill-down.

### 1.2 What "real facts" means to owners

Owners do not use the language of data governance, but they describe its failure modes precisely.

| What they ask | What they mean | Evidence |
|---|---|---|
| "Where does this number come from?" | Source system, definition, filters, exclusions | The recommended owner check is to reconcile ad-platform CPA to bank/CRM; the platform number is "a forecast, not a receipt" [S4]; BI consultant defines 10–20 KPIs in plain English and implements them once [S17] |
| "Is this current?" | Last sync, data-through date, known lag | GBP searches update monthly with up to 5 days' lag [S33]; GBP call data disappeared and June 2025 reporting sat at zero or below expected [S40][S41]; reviews sometimes "pop up later than the review date" [S26] |
| "How many is this based on?" | Denominator and sample size | Theme tracking needs counts, not adjectives [S11]; BrightLocal reports exact n and methodology [S31] |
| "Compared to what?" | Prior period, same period last year, peer set, target | Toast compares to prior week, same week last year, or two years ago [S34]; restaurant operators use YOY and week-by-week sales-by-hour targets [S1][S2] |
| "Does it reconcile?" | Same number across reports | Toast explicitly warns net sales may not match another report because refunds/fees/unpaid orders are handled differently [S34]; Capterra reviewer assumed listings were synced to all directories and they were not [S30] |
| "Is the metric even what it says?" | Construct validity | Google calls are call-button clicks, not calls [S33]; a Birdeye reviewer's "directions" stat showed ~48 requests/month while nobody showed up, making her "question other stats" [S26] |

**Product implication:** every card needs a "data card" (info popover) with: source, definition, period, filters, denominator/n, last successful sync, known exclusions, and a "report a data issue" link. Show "No data" and "Delayed" states explicitly. Never render a failed sync as zero.

### 1.3 Absolute numbers, percentages, or trends?

Owners want all three, but in a fixed hierarchy:

1. **Absolute number is the headline.** Dollars, guests, review count, messages waiting. This is what they can reconcile and act on [S1][S3][S34].
2. **Percentage is the comparison.** Same-length period, clearly labeled. "+6.2% vs same week last year" is useful; "+6.2%" alone is not [S34].
3. **Trend is the context.** A sparkline or 12-week line shows direction without forcing a calculation.

The clearest evidence is a restaurant operator who found sales up 5% year over year while customer count had slightly dropped — the gain came from a 10% menu price increase [S1]. A percentage-only dashboard would have hidden the volume problem. Toast's own design pairs dollar totals with percent change and lets the operator choose the comparison period [S34]. BrightLocal's thresholds are absolute: 20 reviews, 4.5 stars, 90 days [S31].

**Product implication:** default card format is `$48,210  +6.2% vs same week LY` with a 12-week sparkline. Never show a percentage without the absolute base and the comparison period. Suppress percentages when the denominator is under 10; show the raw counts instead.

### 1.4 AI-generated insights versus raw numbers

The evidence does not support a binary "owners trust AI" or "owners don't." It supports a **trust hierarchy**:

| Layer | Trust level | Evidence | Product use |
|---|---|---|---|
| Raw number + source + timestamp | High | Owners reconcile to bank/CRM [S4]; Google/Toast docs show how easily metrics are misread [S33][S34] | Headline KPI |
| Deterministic calculation (sum, rate, delta) | High | BI consultants define metrics once and reconcile [S17] | KPI, funnel, benchmark gap |
| AI summary with citations and n | Medium | 82% of consumers read AI review summaries, but only 23% would rely solely on them [S31] | "What changed" card, theme summary |
| AI recommendation / root cause | Low–medium | "Generic AI... will hand you a confident root cause it can't actually support" [S45]; AI review replies "stand out like a sore thumb" [S39] | Suggest only; human approves |
| AI auto-publish / auto-action | Low | Podium reviewers report AI accuracy struggles and customers frustrated when they cannot reach a human [S27] | Avoid for negative/sensitive; require approval |

The macro surveys explain why: only 46% of people globally are willing to trust AI systems, and 70% believe AI regulation is needed [S36]. At work, 54% of AI users do not trust the data used to train AI, and 82% say accurate data is critical to trust [S37]. The lesson is not "don't use AI." It is "show the data behind the AI, and keep the human in the loop."

**Product implication:** AI insight cards must be labeled, cite the underlying reviews/transactions, show `n`, show the date range, and offer "Show sources / Edit / Approve." For review replies, AI drafts only; no auto-publish on 1–3 star reviews. For themes, show the count and two representative quotes, not just a narrative.

### 1.5 Mobile versus desktop expectations

The evidence splits cleanly by job, not by person.

| Job | Mobile expectation | Desktop expectation |
|---|---|---|
| Glance | 3–5 numbers, fast load, no filters | Full dashboard, multi-metric comparison |
| Respond | One-tap reply, templates, inbox | Bulk reply, assignment, AI drafts |
| Request reviews | QR/share link, send from phone | Campaign setup, triggers, templates |
| Alerts | Push with deep link to the exact review/message | Alert-rule configuration |
| Benchmark | View-only | Peer-group builder, export |
| Reports | Read/forward | Build, schedule, export |

Evidence:

- A single-store operator uses Podium "almost exclusively... from my phone" every day and calls it "the best $300/mo+ marketing I spend" [S9].
- A marketer wants a mobile "glance view" of spend/CPA/ROAS because switching between Shopify, Meta, and Google Ads all day is "death by a thousand alt-tabs" [S13].
- The same thread calls Looker Studio on mobile "hell" and says Looker/AgencyAnalytics are "built for desktop reports, not quick checks while you're out" [S13].
- A 30-year tech/marketing veteran pushes back: "I've never seen anybody use a mobile device to gather insight" [S13]. That is true for deep analysis; it is not true for alerts and replies.
- Podium reviewers say the app lacks desktop admin capabilities and the app/desktop states do not refresh consistently [S27]. Birdeye reviewers say the mobile app lags and side menus are confusing [S26]; Capterra reviewers call the mobile app "clunky" and slow [S30].
- A BI consultant notes leadership wants "a scrollable splash of everything important" on mobile, not granularity [S5].

**Product implication:** design mobile as a separate "operator console," not a responsive shrink of the desktop dashboard. Above the fold: 3 KPI cards, "who is waiting," and "needs attention." Bottom nav: Home, Inbox, Reviews, Growth, More. Push deep-links into the exact item. Desktop remains the place for setup, bulk actions, peer groups, and exports.

### 1.6 Alerting and threshold expectations

Owners do not want a notification for every event. They want to be interrupted only when something is broken, risky, or waiting on them.

| Priority | Trigger | Default threshold | Recipient | Channel |
|---|---|---|---|---|
| P0 | New 1–2 star review | Immediately | Location manager + owner | Push + SMS/email |
| P0 | Suspected review bombing | 3+ negative reviews in 24h, or 2x baseline | Owner + marketing | Push + email |
| P0 | Customer waiting | Message unanswered >15 min during business hours | Assigned staff + manager | Push |
| P0 | Missed call | Immediately, during business hours | Front desk + manager | Push |
| P0 | Sync failure | No successful sync >2h during business hours | Admin | Email + in-app |
| P1 | Review awaiting reply | >24h old | Location manager | Push digest |
| P1 | Rating threshold | Below 4.5, or below peer median | Owner | Push |
| P1 | Negative theme spike | n ≥ 5 and 2x prior 4-week baseline | Owner + ops | Push + email |
| P1 | Review request conversion drop | >20% week-over-week | Marketing | Email |
| P1 | Listing error | Hours/phone/address mismatch | Admin | In-app |
| P2 | Daily digest | 7am local | Owner | Email/app |
| P2 | Weekly report | Monday 8am | Owner + managers | Email |

Evidence: 19% of consumers expect a same-day review response, 32% by the next day, and 81% within a week [S31]. Podium's alert "clearly shows which customers are still waiting for a response" [S27]. Reputation offers notifications via platform, email, or mobile with customizable alert frequency [S35]. A business owner received five fake 1-star reviews in one evening and needed a crisis path, not a weekly report [S43]. But push can become noise: "Those push notifications turn into noise" when everything is pushed [S5].

**Product implication:** severity tiers, per-location thresholds, quiet hours, escalation after acknowledgment timeout, snooze, and a "why am I seeing this?" link. Never push every five-star review; put positives in the daily digest.

### 1.7 Review, messaging, and local-marketing specifics

**Review generation is a funnel, not a count.** Owners and operators report wildly different conversion rates: 3% from happy med-spa clients [S12], 1 review per 20–30 requests for a service business [S38], and 83% of consumers saying they left a review when asked [S31]. The last number is a survey of consumer willingness, not an operational benchmark. Plan for 3–10% and measure your own baseline.

What works, according to owners: ask at peak satisfaction, in person, with a QR code or one-tap link; follow up by SMS; make it effortless [S12][S31]. Automated requests work, but manual processes quietly reduce volume [S9]. Do not build review gating (only sending happy customers to Google) into the funnel; it creates authenticity and policy risk, and BrightLocal finds consumers already punish fake or incentivized reviews [S31]. Owners also want the negative feedback routed privately first so they can fix it before it becomes public [S12][S26].

**Messaging is sticky when it is the unified inbox.** Owners use only 2–3 features of expensive platforms [S9], but the ones who stay cite the unified inbox, POS integrations, and automation [S9][S27]. A single-store operator uses Podium daily from the phone for reviews and texts [S9]. A multi-unit operator says the $300/month is a "convenience tax" that pays for itself when staff can manage every text, review, and chat from one screen [S9]. The pain is missed calls and waiting customers, not a lack of channels [S27].

**Local marketing data is uniquely untrustworthy.** Google calls are clicks [S33]; directions are requests, not visits [S26]; searches update monthly [S33]; GBP call reporting has disappeared for agencies [S40][S42]; listings sync assumptions cause silent errors [S30]. The product should show the limitation in the UI, not hide it in a help article.

**Multi-location is a different product.** The daily job is roll-up, exception finding, and bulk action. A 7-office dental director toggles between offices or applies updates across all [S26]. An agency managing 20+ clients wants one dashboard, sub-accounts, and white-label [S23]. Citation changes can take up to a week and are a support complaint [S8]. Location-level permissions and audit trails are table stakes.

**Pricing and contract trust are part of the UX.** Owners describe 12-month contracts, 90-day cancellation notices, auto-renewal, and 8% renewal increases [S8][S20]. A Capterra reviewer calls the platform "impossible to cancel" [S30]. Even a good dashboard cannot overcome the feeling of being trapped. If the product is sold to SMBs, month-to-month or clear renewal terms are a trust feature.

---

## Part 2 — Per-Page Specification

### 2.1 OVERVIEW — "Is the business okay this week, and what needs me now?"

**Job to be done:** replace the Monday morning scramble across POS, Google, Yelp, the inbox, and a spreadsheet with one trusted weekly view and a short action queue.

#### Top 5–8 things owners explicitly ask for

| # | What they ask for | Evidence |
|---|---|---|
| 1 | **Five to ten numbers I trust, not a portal** | SMB clients "just want the key numbers"; they do not want to log in, find a tab, and filter five times [S5]. Agency reporting should be one page with 3–5 metrics and 3 takeaways [S7]. If a metric cannot change a decision, it is vanity [S6]. |
| 2 | **Money, labor, guests, and check average** | Restaurant operators track YOY sales, guest count, labor, voids, and third-party reviews/credits [S1]; POS report list is sales summary, PMIX, labor vs sales, voids/comps, guest counts, PPA [S2]; Toast's weekly overview is sales, labor, guest count, top items [S34]. |
| 3 | **A review pulse, not a review portal** | Owners want new reviews, rating, response rate, and what is unanswered [S26][S31]. 89% of consumers expect a response; 80% are likely to use a business that responds to all reviews [S31]. Birdeye's benchmark response rate is 75.5% [S32]. |
| 4 | **"Who is waiting on me?"** | Podium's alert "clearly shows which customers are still waiting for a response" [S27]; Reputation reports response time and response rate by team member [S35]; owners stay for the unified inbox [S9]. |
| 5 | **Compare to last week and last year, not a random date range** | Toast defaults to this week/last week and compares prior week, same week last year, or two years ago [S34]; restaurant operators use YOY and week-by-week sales-by-hour targets [S1][S2]. |
| 6 | **One roll-up, then the location** | A 7-office dental director toggles offices or applies changes across all [S26]; an agency manages 20+ clients from one dashboard [S23]; listings sync confusion is a common multi-location failure [S30]. |
| 7 | **Tell me what to do next** | Owners want alert + owner assignment, theme tracking, and a weekly operational report [S11]; Reputation's Actions product assigns tickets with SLAs and queues [S35]; the analytics test is decision, threshold, and owner [S45][S6]. |
| 8 | **Let me check it from my phone** | A single-store operator uses the Podium app daily [S9]; marketers want a fast spend/CPA/ROAS glance [S13]; Podium's app/desktop gap is a top complaint [S27]. |

#### Top 5–7 things they say are useless or confusing

| # | What is useless/confusing | Why | Evidence |
|---|---|---|---|
| 1 | **Impressions, views, followers, clicks as headline metrics** | They do not map to money or a decision; owners call them vanity metrics and say agencies hide behind them | [S4][S6] |
| 2 | **Another login, tab, and filter chain** | The cognitive tax of "go find the report" is the complaint; push/pull is the preference | [S5] |
| 3 | **Opaque composite scores** | Owners cannot tell what moved the score or what to do; G2 reviewers flag "Scoring Issues" for Reputation | [S28][S35] |
| 4 | **Stale data with no timestamp** | Missing/delayed GBP data and late-arriving reviews destroy confidence in every other number | [S40][S41][S26] |
| 5 | **Percent-only changes** | Sales up 5% can hide falling guest counts after a price increase; owners need the absolute base | [S1][S34] |
| 6 | **Thirty-column reports** | A Birdeye reviewer says the reports have "too many columns, and the labels are very confusing" and she has to call support to interpret them | [S26] |
| 7 | **Real-time COGS / real-time P&L** | "You can't calculate COGS in real time in a dashboard"; daily P&L is not the job of an operations dashboard | [S1] |

#### What "real facts" means on this page

Every tile must answer five questions in one click: **source, period, comparison, denominator, last sync.** Examples:

- `Net sales $48,210 · +6.2% vs same week last year · as of 9:14 AM, Oct 28 · excludes refunds`
- `4.6★ · 18 new reviews in 30 days · Google 14 / Facebook 3 / Yelp 1 · synced 8 min ago`
- `5 texts waiting · 2 missed calls · median first reply 14 min · business hours 8am–6pm`

Do not show a green/red state without the threshold that produced it. Do not show "0" when the sync failed; show "Data delayed — last success 6:12 AM." Do not compare a partial week to a full week without labeling it.

#### Card and widget ideas (exact metrics + copy)

| Card | Metrics | Exact copy | Primary action |
|---|---|---|---|
| **This week** | `net_sales`, `guest_count`, `avg_check`, `labor_pct` | **Net sales $48,210** · +6.2% vs same week last year<br>**1,284 guests** · −1.8%<br>**$37.55 avg check** · +8.1%<br>**Labor 28.4%** · +0.6 pts<br><small>As of 9:14 AM, Oct 28 · Sales exclude refunds · Labor = payroll + estimated taxes</small> | View sales report |
| **Reputation pulse** | `avg_rating`, `new_reviews_30d`, `response_rate`, `awaiting_reply`, `oldest_wait_days` | **4.6★** · +0.1 vs prior 30 days<br>**18 new reviews** · 82% responded<br>**3 awaiting reply** · oldest 2 days<br><small>Google 14 · Facebook 3 · Yelp 1 · 90-day review count: 54</small> | Reply to 3 |
| **Who's waiting** | `unanswered_texts`, `missed_calls`, `median_first_response_min`, `waiting_over_1h` | **5 texts waiting** · 2 missed calls<br>**14 min** median first reply<br>**2 customers waiting >1 hour**<br><small>After-hours leads: 4 · Business hours 8am–6pm</small> | Open inbox |
| **Needs attention** | prioritized `severity`, `location`, `issue`, `owner`, `due` | **Downtown:** 2 new 1★ reviews mention wait time. Assign to GM.<br>**Westside:** 6 reviews unanswered >48h.<br>**Listing:** hours mismatch on Google.<br><small>3 items · sorted by revenue at risk</small> | Assign / Reply / Fix |
| **Location league** | `location`, `rating`, `new_reviews`, `response_rate`, `unanswered`, `sales_vs_ly` | **Downtown** 4.1★ · 6 new · 68% responded · 5 unanswered · +2.1% sales<br>**Westside** 4.7★ · 9 new · 91% responded · 1 unanswered · +7.4% sales<br>**North** 4.4★ · 3 new · 74% responded · 4 unanswered · −1.2% sales<br><small>3 of 8 locations below 4.5★</small> | View location |
| **One thing that changed** | `theme`, `mentions`, `delta`, `location`, `example_quote` | **Wait time mentions up 38% at Downtown.** 14 of 24 mentions are from the last 14 days. "Waited 25 minutes for a table."<br><small>Based on 78 reviews · Sep 29–Oct 28 · [See 24 reviews]</small> | See reviews |

#### Common failure modes on Overview

- **Vanity metrics:** impressions, views, followers, clicks as hero numbers [S4][S6].
- **No comparison:** a number without prior period, same period last year, or target [S34].
- **No action:** a red tile with no owner, threshold, or next step [S5][S6].
- **Stale data:** failed sync shown as zero or a drop [S40][S41].
- **Too many metrics:** 20 tiles, 30 columns, labels only support can explain [S26].
- **Unrealistic real-time:** real-time COGS/P&L, or daily P&L for an operations user [S1].
- **Mobile afterthought:** a desktop dashboard squeezed into a phone, with pinch-zoom charts [S13][S27][S29].

---

### 2.2 INSIGHTS — "What are customers telling us, where, and what should we do?"

**Job to be done:** turn reviews, surveys, messages, and complaints into a short list of themes with counts, locations, quotes, and owners — not a sentiment score or a word cloud.

#### Top 5–8 things owners explicitly ask for

| # | What they ask for | Evidence |
|---|---|---|
| 1 | **Themes with counts and representative quotes** | The thread's buyer wedge is theme tracking by location/staff/service and a weekly report of what reviews revealed operationally [S11]; Reputation's Experience Insights tracks topics, sentiment, and "Big Movers" [S35]; BrightLocal says consumers look for consistent sentiment across multiple reviews, not one glowing review [S31]. |
| 2 | **Is it getting better or worse?** | Operators ask "is something off?" and want the diagnostic cut underneath the headline [S5][S45]; contextual AI cards should sit next to the relevant data and trigger on anomalies [S18]; Reputation tracks sentiment trends and location-level progress [S35]. |
| 3 | **Show me the reviews behind the claim** | A Birdeye reviewer questions every stat after one obviously wrong directions metric [S26]; the owner check is to reconcile platform numbers to source systems [S4]; Google calls are clicks [S33]. |
| 4 | **Who owns the fix?** | Reputation's Actions turns feedback into tickets with rules, SLAs, queues, and overdue states [S35]; the decision test is decision + threshold + owner [S45]. |
| 5 | **Is this fresh?** | 74% of consumers only care about reviews from the last 3 months [S31]; late-arriving reviews are a top complaint [S26]. |
| 6 | **Use AI to summarize, but show your work** | Only 46% trust AI systems [S36]; 54% do not trust training data [S37]; AI review replies "stand out like a sore thumb" [S39]; consumers read AI summaries but only 23% rely solely on them [S31]. |
| 7 | **Break it down by location, staff, and service** | Theme tracking by location/staff/service is a named buyer wedge [S11]; multi-location dashboards need office-level toggles [S26]; Reputation reports by location and group [S35]. |
| 8 | **Compare to our own baseline and peers** | Own history is the benchmark owners trust [S14]; Reputation compares to industry peers [S35]; G2 reviewers flag reporting and scoring issues with Reputation [S28]. |

#### Top 5–7 things they say are useless or confusing

| # | What is useless/confusing | Why | Evidence |
|---|---|---|---|
| 1 | **Word clouds without counts** | They look analytical but do not say how many, how negative, where, or what to do; the vendor feature list includes "Word Cloud," but owners need theme counts [S35][S7]. | [S35][S7] |
| 2 | **A single sentiment score** | It hides volume, recency, source, and location; G2 reviewers flag reporting and scoring issues [S28]; BrightLocal says consistency across reviews matters, not one score [S31]. | [S28][S31] |
| 3 | **AI root cause with no evidence** | "Generic AI... will hand you a confident root cause it can't actually support" [S45]; AI review replies can "mangle" the response [S39]. | [S45][S39] |
| 4 | **Themes without location/staff attribution** | "Wait time is up" is not actionable; "wait time at Downtown, 14 mentions, 4 of 6 negative reviews" is [S11][S35]. | [S11][S35] |
| 5 | **No action or owner** | A dashboard that says "underperforming" but does not change the quarterly priority list is useless [S5]; if no action follows, it is vanity [S6]. | [S5][S6] |
| 6 | **Stale or late reviews** | Reviews "pop up later than the review date"; GBP data can lag or disappear [S26][S40]. | [S26][S40] |
| 7 | **Generic "customers love us" fluff** | Owners want outcomes and next steps, not a narrative that could have been written without the data [S7]. | [S7] |

#### What "real facts" means on this page

An insight is trustworthy when a skeptical owner can click from the sentence to the evidence in one step. Each insight must show:

- **Claim:** "Wait time mentions are up 38% at Downtown."
- **Count and denominator:** "24 mentions out of 78 reviews; 14 in the last 14 days."
- **Source mix:** "Google 18, Yelp 4, Facebook 2."
- **Date range and comparison:** "Sep 29–Oct 28 vs Aug 30–Sep 28."
- **Sample warning:** "Low sample: 6 mentions at Westside; treat as directional."
- **Evidence links:** "See 24 reviews" with the exact quotes.
- **AI disclosure:** "AI-generated summary; reviewed by [name] on Oct 28" or "Unreviewed."
- **Action:** owner, next step, due date.

Do not present a sentiment percentage without the underlying counts. Do not compare a 5-review location to a 500-review location without a low-sample warning. Do not let AI write "because" unless the cause is directly supported by the reviews or another data source.

#### Card and widget ideas (exact metrics + copy)

| Card | Metrics | Exact copy | Primary action |
|---|---|---|---|
| **Top themes** | `theme`, `mentions`, `pct_of_negative`, `delta_vs_prior`, `top_location`, `sample_quote` | **Wait time** — 24 mentions (31% of negative reviews) — +38% vs prior 30 days — Downtown (14)<br>"Waited 25 minutes for a table."<br>**Staff friendliness** — 42 mentions (mostly positive) — +6% — all locations<br>**Parking** — 11 mentions — −12% — Westside (7)<br><small>Based on 78 reviews, Sep 29–Oct 28 · 2 low-sample themes hidden</small> | See 24 reviews |
| **What changed this week** | `negative_reviews_7d`, `prior_7d`, `theme`, `location` | **6 new 1★ reviews this week, up from 1.**<br>4 mention cold food on pickup at **Location B**.<br><small>Compared with Oct 14–20 · 6 reviews · [See all 6]</small> | Review 6 / Assign to ops |
| **Sentiment by location** | `location`, `rating`, `trend_90d`, `top_negative_theme`, `response_rate`, `unanswered` | **Downtown** 4.1★ · −0.2 (90d) · wait time · 68% responded · 5 unanswered<br>**Westside** 4.7★ · +0.1 · parking · 91% responded · 1 unanswered<br>**North** 4.4★ · −0.3 · online orders · 74% responded · 4 unanswered<br><small>Ratings from Google/Yelp/Facebook · last 90 days</small> | Open location |
| **AI summary with receipts** | `summary_bullets[]`, `n_per_bullet`, `confidence`, `source_links[]` | **What customers are saying**<br>• Staff are praised for being friendly and helpful (n=42).<br>• Wait times are the main complaint, mostly Downtown (n=24).<br>• Pickup order accuracy is a new theme this month (n=9).<br><small>Based on 78 Google/Yelp/Facebook reviews, Sep 1–Oct 28. AI-generated; verify sources. Confidence: medium (n=78; 24 mention wait time).</small> | Show sources / Edit / Approve |
| **Action plan / close the loop** | `theme`, `owner`, `action`, `due`, `status` | **Wait time → GM Downtown → add 2nd host Fri–Sun → due Nov 3 → open**<br>**Pickup accuracy → Ops B → audit 10 orders/day → due Nov 1 → open**<br>**Parking → Landlord → ask for signage → due Nov 15 → waiting**<br><small>2 overdue · 1 waiting on external</small> | Update status |

#### Common failure modes on Insights

- **AI hallucination:** a confident narrative with no source, or a root cause the data cannot support [S45][S39].
- **Sentiment without volume:** "sentiment is 72%" with no n, date range, or source mix [S28][S31].
- **Word cloud as insight:** pretty, unactionable, no counts or locations [S35][S7].
- **Stale data:** late reviews, delayed GBP data, or a sync failure shown as a trend [S26][S40].
- **No owner:** a theme list with no assignment, SLA, or follow-up [S35][S5].
- **Over-aggregation:** one brand-level score that hides the one location that is bleeding [S26][S35].
- **Negativity bias:** only surfacing complaints, ignoring what is working and should be repeated [S31][S7].

---

### 2.3 GROWTH — "Where do customers come from, what converts, and what should we do more of?"

**Job to be done:** show the acquisition-to-review-to-repeat loop in a way an owner can act on this week: ask more customers, fix the leak, double down on the channel that produces paying customers.

#### Top 5–8 things owners explicitly ask for

| # | What they ask for | Evidence |
|---|---|---|
| 1 | **The whole review funnel, not just the review count** | Reputation reports Requests Sent, Emails Delivered, Emails Opened, Surveys Completed, and attributed reviews [S35]; Birdeye tracks SMS/email request mix and click-through [S32]; owners need to see where the funnel leaks [S11]. |
| 2 | **A realistic conversion rate, not a vendor promise** | A med-spa owner got 2 reviews from 67 treatments and 64 satisfied clients — 3% [S12]; a service business owner gets 1 review per 20–30 requests [S38]; BrightLocal finds 83% of consumers who were asked left a review [S31] (survey willingness, not an operational rate). |
| 3 | **Where customers actually come from** | Service businesses struggle to attribute ad → form → CRM → closed deal; "how did you hear about us" is unreliable; UTM/CRM is the fallback [S24]; owners use UTM, unique codes, and asking at booking [S25]. |
| 4 | **Are they coming back?** | Restaurant operators track returning-guest rate and loyalty stats [S1]; small businesses track signups/attrition and recurring income vs recurring costs [S3][S44]. |
| 5 | **Which location/staff is generating reviews?** | Multi-location reviewers manage 11 transmission shops and 7 dental offices [S26]; Reputation has a review-request leaderboard by requester/location/division [S35]. |
| 6 | **What action creates more reviews?** | Owners report in-person asks and QR codes outperform next-day texts/emails [S12]; a text link right after service gets reviews on the spot [S22]; automated requests work when they are actually sent [S9]; BrightLocal says ask at the right moment and make it easy [S31]. |
| 7 | **What does each review or customer cost?** | A 15-location operator paid $130/location/month for ~1 review/month/location [S8]; a Podium user reports $399+/month and a 12-month contract [S21]; owners compare CPA to LTV and to the bank, not the platform [S4]. |
| 8 | **Referrals** | This is the thinnest evidence area in the sample. Owners talk about word of mouth and reviews far more than referral dashboards. Treat referral as an optional experiment, not a headline page (see Open Questions). |

#### Top 5–7 things they say are useless or confusing

| # | What is useless/confusing | Why | Evidence |
|---|---|---|---|
| 1 | **Review count alone** | 1 review/month/location at $130/location is a bad outcome even if the count is "up"; 2 reviews from 67 treatments is a 3% conversion problem, not a review-count problem [S8][S12]. | [S8][S12] |
| 2 | **Blast campaigns with no targeting or timing** | SMS click-through is only 6.2% in Birdeye's dataset [S32]; manual/untimed asks quietly reduce volume [S9]; owners want the right moment, not more messages [S12][S31]. | [S32][S9][S12] |
| 3 | **Last-click attribution presented as truth** | "How did you hear about us" is unreliable; long consideration cycles and offline touchpoints break last-click [S24]; owners need source + confidence, not a false-precision pie chart [S25]. | [S24][S25] |
| 4 | **A dashboard with no send/respond workflow** | Automated review requests are already built into POS/CRM/booking tools; the dashboard alone is not the product [S11]; owners keep platforms for the unified inbox and automation [S9]. | [S11][S9] |
| 5 | **Broad industry benchmarks disconnected from the funnel** | A conversion rate benchmark does not tell you which trigger, channel, or location to fix [S14]; benchmark the funnel against your own history first [S14]. | [S14] |
| 6 | **"We got 100 reviews" without recency or rating** | 74% of consumers only care about reviews from the last 3 months; 31% require 4.5+ stars [S31]. | [S31] |

#### What "real facts" means on this page

Growth is where false precision does the most damage. Every funnel step needs a denominator and a time window:

- **Requests sent** (not "review invites" in the abstract), split by SMS/email/in-person QR.
- **Delivered / opted out / failed**, so the conversion rate is not inflated by undelivered messages.
- **Clicked / landed**, if the platform can measure it.
- **Reviews received**, split by source and rating.
- **Attribution window** and **source** for acquisition; "unknown" is a valid and important category.
- **Cohort definition** for retention: first visit month, repeat within 30/60/90 days, revenue.
- **Sample size** and **confidence**: do not call a 2-review week a trend.

The key discipline: **count the denominator.** "21 reviews" is not a result; "21 reviews from 420 requests (5.0%)" is. "18% referrals" is not a result unless you also show "15% unknown."

#### Card and widget ideas (exact metrics + copy)

| Card | Metrics | Exact copy | Primary action |
|---|---|---|---|
| **Review engine** | `requests_sent`, `delivered`, `clicked`, `reviews`, `conversion`, `avg_rating` | **420 requests → 405 delivered (96%) → 38 clicked (9.4%) → 21 reviews (5.0%) → 4.7★**<br><small>Last 30 days · SMS 54% / email 46% · 3 opt-outs · 12 failed</small> | See request log |
| **Where customers come from** | `new_customers`, `source`, `unknown_pct` | **Google 42% · Referral 18% · Walk-in 15% · Instagram 10% · Unknown 15%**<br><small>Based on 186 new customers · Oct 1–28 · 15% unknown — ask at booking to improve</small> | Add source to booking |
| **Retention cohort** | `cohort_month`, `first_time`, `repeat_30/60/90`, `repeat_revenue` | **38% of January first-timers rebooked within 90 days**<br>$18,420 repeat revenue from a 142-customer cohort<br><small>Excludes gift cards · compared with 31% for December cohort</small> | View cohort |
| **Ask timing** | `trigger`, `requests`, `reviews`, `conversion` | **In-person QR 12% · SMS 2h 6% · Next-day email 3%**<br><small>Based on 420 requests · in-person QR converts 2× SMS and 4× email</small> | Shift requests to QR |
| **Growth actions** | `action`, `audience`, `channel`, `expected_reviews` | **Ask 24 happy customers** (5★, last 7 days) · SMS + QR<br>**Win back 12 lapsed 90-day customers** · SMS<br>**Fix 5 unanswered reviews at Location B** · assign to GM<br><small>Estimated impact: +8–12 reviews this month</small> | Start / Assign |
| **Referral loop (experiment)** | `referral_customers`, `referral_revenue`, `asks_sent` | **18% of new customers came from a referral.**<br>Ask 24 promoters for one intro this month.<br><small>Based on 186 new customers · referral source self-reported</small> | Create referral ask |

#### Common failure modes on Growth

- **Counting requests, not reviews:** "we sent 1,000 requests" is activity, not outcome [S32][S11].
- **No denominator:** a conversion rate without delivered/opted-out/failed counts [S35].
- **Attribution overreach:** claiming causality from last-click or a self-reported source [S24].
- **Review gating:** routing only happy customers to Google; creates authenticity/policy risk and hides fixable problems [S12][S31].
- **Blasting:** more messages, worse timing, lower conversion [S32][S12].
- **Vanity followers/impressions:** social reach without a path to booking [S4][S6].
- **No follow-through:** a growth insight without a send/assign action [S11][S9].

---

### 2.4 BENCHMARK — "How do we compare, and where should we improve?"

**Job to be done:** answer "are we normal?" without lying with averages. Give owners a peer set they recognize, a gap they can close, and the sample/method behind every number.

#### Top 5–8 things owners explicitly ask for

| # | What they ask for | Evidence |
|---|---|---|
| 1 | **Compare me to businesses like mine, nearby** | A wedding-venue client cannot map to a broad industry category [S14]; business buyers want market-level data, not just national IBIS averages [S16]; Reputation's competitive intelligence compares at brand, location, and industry level [S35]. |
| 2 | **Similar size and business model** | Owners want to compare to similar-sized companies, not enterprises [S44]; a former WordStreamer explains the benchmark data was ~80% US and SMB-skewed, which limits generalization [S14]. |
| 3 | **Rating, review count, recency, and response rate** | BrightLocal's decision factors are consistency, positivity, recency, star rating, and owner response [S31]; Birdeye's benchmark covers volume, rating, response, and comments [S32]; Reputation tracks rating, volume, sentiment, response time [S35]. |
| 4 | **Use my own history first** | PPC practitioners say past account results are the only benchmark worth trusting; broad industry data is "mostly BS" [S14]; Toast compares the same week to prior week/last year/two years ago [S34]. |
| 5 | **Show the math, the sample, and the date** | Analytics practitioners warn that benchmarks are meaningless without methodology and sample size [S15]; the WordStream ex-employee discloses US/SMB skew and broad 10–15 industry buckets [S14]. |
| 6 | **Which location is lagging?** | Birdeye offers relative location rank for multi-location accounts [S26]; Reputation reports under- and over-performing locations [S35]. |
| 7 | **How many reviews to reach 4.5?** | BrightLocal's thresholds are absolute and decision-relevant: 47% won't use <20 reviews, 31% require 4.5+ [S31]. |
| 8 | **Let me pick the peer group** | Reputation compares to a defined competitor set [S35]; owners distrust black-box peer sets [S14][S15]. |

#### Top 5–7 things they say are useless or confusing

| # | What is useless/confusing | Why | Evidence |
|---|---|---|---|
| 1 | **Broad industry averages** | A wedding venue is not "professional services"; 10–15 broad categories do not map to real businesses [S14]; analytics practitioners say "you don't" get accurate industry benchmarks [S15]. | [S14][S15] |
| 2 | **Average of averages** | "Let's average the averages and giggle about it" — the methodology is often meaningless [S15]. | [S15] |
| 3 | **Opaque composite scores** | Reputation Score is a 0–1000 composite; G2 reviewers flag "Scoring Issues" and reporting issues [S28][S35]. Owners need subcomponents and weights. | [S28][S35] |
| 4 | **National data for a local business** | National averages hide local market density, competition, and category mix [S14][S16]. | [S14][S16] |
| 5 | **Stale benchmarks** | A yearly report used as a live target; analytics practitioners warn about methodology and recency [S15][S14]. | [S15][S14] |
| 6 | **No sample size or confidence** | A median with no n is not a benchmark; 12 competitors with 3 having <20 reviews is directional at best [S15]. | [S15] |
| 7 | **Enterprise comparisons** | SMB budgets, bid strategies, and sales cycles differ; comparing a micro-budget local account to enterprise data is misleading [S14]. | [S14] |

#### What "real facts" means on this page

A benchmark is only as good as its peer set and its math. Show:

- **Peer definition:** category, subcategory, radius, size band, channel mix.
- **n:** number of competitors/locations in the peer set; how many have enough reviews to be included.
- **Date:** when the data was pulled; benchmark data ages quickly.
- **Source and definition:** Google-only vs all review sites; rating vs recency-weighted rating; response rate denominator.
- **Your own history:** the primary comparison; peers are context, not a target.
- **Confidence:** "Directional — 12 competitors, 3 with <20 reviews" or "Low sample — 4 competitors."
- **Gap math:** how the target was calculated and what assumptions it makes.

Do not show a percentile without the distribution. Do not show a "Reputation Score" without the components and weights. Do not compare a 4.3-star restaurant to a 4.9-star chiropractor and call it a gap.

#### Card and widget ideas (exact metrics + copy)

| Card | Metrics | Exact copy | Primary action |
|---|---|---|---|
| **You vs nearby** | `your_rating`, `your_reviews`, `your_recency`, `your_response`, `peer_median_*` | **You:** 4.6★ · 212 reviews · 38% last 90 days · 82% responded<br>**Peer median:** 4.5★ · 180 reviews · 52% last 90 days · 61% responded<br><small>12 competitors within 5 miles · Google only · as of Oct 28, 2026 · 3 peers have <20 reviews (directional)</small> | Edit peer group |
| **Gap to 4.5** | `current_rating`, `review_count`, `five_star_needed`, `pace_per_month` | **4.3★ from 84 reviews.**<br>**34 new 5★ reviews** needed to reach 4.5, assuming no new negative reviews.<br>At your current pace (8/month), that is ~4.3 months.<br><small>Math: (4.5 × 118 − 4.3 × 84) ÷ 5 ≈ 34 five-star reviews</small> | Create review campaign |
| **Review recency** | `pct_reviews_last_90d`, `peer_median`, `rank` | **38% of your reviews are from the last 90 days.**<br>Peer median: 52%. You rank 8th of 12 nearby.<br><small>74% of consumers only care about reviews from the last 3 months.</small> | Ask recent customers |
| **Industry context** | `category_avg_rating`, `listing_count`, `date` | **Restaurants average 4.50★** (5,131 restaurant listings; 67,969 total sample, 2026)<br>Chiropractors 4.93★ · Plumbers 4.81★ · Hotels 4.08★<br><small>Industry context only — use nearby peers for decisions. Source: ReplyOnTheFly scan of 67,969 Google Maps listings, 2026 [S46].</small> | See category |
| **Peer group builder** | `category`, `radius`, `size_band`, `sources` | **Compare to 10 similar businesses within 5 miles.**<br>We will show the peer set and let you remove outliers before calculating the median.<br><small>Default: same category, 1–3 locations, Google + Yelp, last 90 days.</small> | Edit peer group |

#### Common failure modes on Benchmark

- **Fake precision:** a percentile or composite score with no sample size or method [S15][S28].
- **Broad categories:** "professional services" for a wedding venue; "restaurants" for a fine-dining concept [S14].
- **Opaque composite:** a 0–1000 score without weights, inputs, or subcomponents [S28][S35].
- **Stale data:** a yearly benchmark used as a live target [S15][S14].
- **National averages:** irrelevant to a local market with different density and competition [S14][S16].
- **No action:** "you are below average" with no gap math or next step [S14][S31].
- **Enterprise comparisons:** SMB budgets and sales cycles compared to enterprise data [S14].

---

## Part 3 — Cross-Page Design Rules

These rules apply to all four pages and are the difference between a dashboard owners use and one they abandon.

1. **One card, one decision.** Every card must name the decision it supports, the threshold that would change the decision, and the owner. If those three cannot be filled in, the card is context, not a headline [S45][S6].
2. **Absolute + delta + trend.** Headline is the absolute number; the delta is a same-length comparison; the trend is a sparkline or 12-week line [S34][S1].
3. **Show your work.** Source, period, filters, denominator/n, last sync, known exclusions, and a "why this number?" link [S17][S33][S34].
4. **No silent zeros.** A failed sync is "Data delayed," not "0" [S40][S41].
5. **Action or dismiss.** Every alert and insight card has a primary action (reply, assign, request, fix) and a dismiss/snooze. No dead ends [S35][S11].
6. **Color must have a threshold.** Red/amber/green is meaningless without the rule that produced it. Show the rule in the tooltip [S5][S6].
7. **Drill-down from every number.** A number that cannot be opened is a dead end. The drill-down should land on the underlying reviews, transactions, messages, or locations [S26][S4].
8. **Mobile is a console, not a canvas.** Three KPI cards, "who's waiting," and "needs attention" above the fold. No pinch-zoom charts. Push deep-links to the exact item [S13][S27].
9. **AI is labeled and editable.** "AI-generated," "based on N," "show sources," "edit," "approve." Never auto-publish a negative-review response [S39][S36][S37].
10. **Benchmarks are peer-reviewed by the owner.** Show the peer set, let the owner remove outliers, and label directional/low-sample results [S14][S15][S35].
11. **Permissions match the org chart.** Owner sees all locations; manager sees their location; front desk sees inbox/reviews; marketing sees campaigns and themes. Audit bulk actions [S26][S35].
12. **Empty, loading, and error states are product surfaces.** A new location with no reviews should see "No reviews yet — send your first 10 requests," not a blank chart [S31][S35].
13. **Time zones and business hours are per location.** "Waiting >1 hour" is meaningless without the location's open hours [S27][S35].
14. **Do not ship a metric you cannot reconcile.** If the data team cannot tie it to the source system, it does not belong on the Overview [S17][S34].

---

## Part 4 — What Conflicts in the Evidence

### 4.1 Review-request conversion: 83% vs 3%

BrightLocal's 2026 survey finds that 83% of consumers who were asked to leave a review went on to leave one, and 28% say they "always" write a review if asked [S31]. Operational threads tell a very different story: a med-spa owner got 2 reviews from 67 treatments and 64 satisfied clients (3%) [S12]; a service business owner gets 1 review per 20–30 requests (3–5%) [S38].

**Resolution:** the BrightLocal number measures stated willingness in a survey, not completed requests in a live workflow. Use 3–10% as a planning range and measure the owner's own funnel. Show the denominator. Do not promise 83%.

### 4.2 Review volume outcomes: +406% vs 1 review/month/location

A Birdeye reviewer at 11 transmission shops reports reviews increasing ~406% [S26]. A 15-location operator reports ~1 review/month/location at $130/location/month and cancels [S8]. Another Podium user reports 13 Google reviews in a year [S20].

**Resolution:** both can be true. Review generation depends on customer volume, trigger timing, staff compliance, and integration health. The product should show request volume, delivery, and conversion by location so a low-volume location is diagnosed, not blamed on the software.

### 4.3 Mobile: essential vs useless

One camp says mobile is essential: a single-store operator uses Podium from the phone daily [S9]; a marketer wants a mobile spend/CPA/ROAS glance [S13]; leadership wants a scrollable mobile splash [S5]. The other camp says mobile is useless for insight: a 30-year tech/marketing veteran has "never seen anybody use a mobile device to gather insight" [S13].

**Resolution:** both are right about different jobs. Mobile wins for glance, alert, respond, and request. Desktop wins for setup, bulk actions, peer groups, and deep analysis. Do not force one surface to do both.

### 4.4 Benchmarks: owners ask for them vs practitioners call them useless

Owners repeatedly ask for benchmarks to justify performance and know "what good looks like" [S14][S16]. Practitioners say broad benchmarks are "mostly BS" and "you don't" get accurate ones [S14][S15].

**Resolution:** owners trust **local, similar-size, recent, transparent** benchmarks and their own history. They distrust broad national averages, opaque composites, and averages of averages. The page should be a peer-set tool, not an industry-report viewer.

### 4.5 AI: consumers read summaries vs practitioners distrust outputs

Consumers read AI review summaries (82%) and 40% trust AI recommendations, but only 23% would rely solely on a summary [S31]. Practitioners say AI review replies "stand out like a sore thumb" and can "mangle" the response [S39]; only 46% of people globally are willing to trust AI systems [S36].

**Resolution:** AI is a summarization and drafting layer, not an autonomous analyst. Keep the raw reviews and the "show sources" path. Require human approval for negative/sensitive responses.

### 4.6 Review trust: 97% read vs 42% trust

BrightLocal finds 97% of consumers read reviews [S31], while Birdeye's dataset reports consumer trust in online reviews fell from 79% in 2020 to 42% in 2025 [S32]. These are not contradictory: usage is high, trust is lower, and authenticity/recency matter more. The product should emphasize recency, verification, and response quality, not just volume.

### 4.7 Dashboards are dead vs dashboards are the shared frame of reference

Some BI consultants say SMBs no longer want dashboards and want pushed KPIs [S5]. Others say dashboards remain valuable as a shared reference for monitored metrics, especially for larger clients [S5].

**Resolution:** the dashboard is not dead; the **default** is wrong. For SMB owners, push the few numbers and keep the dashboard for drill-down and shared context. For multi-location operators and analysts, the dashboard remains the control room.

---

## Part 5 — Confidence Notes

| Claim | Confidence | Why |
|---|---|---|
| Owners want 5–10 key numbers, not 30 | **High** | Repeated across Reddit, agency, BI, and restaurant threads [S5][S6][S7][S2] |
| Provenance/freshness drives trust | **High** | Owners and practitioners describe reconciliation failures; primary docs confirm metric ambiguity [S4][S17][S33][S34][S40] |
| Absolute numbers first, % second | **High** | Restaurant operator example + Toast design + BrightLocal thresholds [S1][S34][S31] |
| AI is trusted as a draft, not an analyst | **High** | Large surveys + practitioner threads + review-site complaints [S36][S37][S39][S27] |
| Mobile is for glance/alert/respond | **Medium–high** | Consistent qualitative pattern, but contradictory on "insight"; segment-dependent [S13][S27][S9] |
| Review conversion is 3–10% | **Medium** | Two operational data points (3%, 3–5%) and one survey (83%); wide variation by business [S12][S38][S31] |
| Local/peer benchmarks are trusted | **Medium–high** | Consistent owner/practitioner preference, but small sample of benchmark-specific threads [S14][S15][S16] |
| Referral is a priority | **Low** | Almost no owner thread asked for referral tracking; reviews/repeat dominate. Treat as an open question. |
| AI trust numbers generalize to SMB owners | **Medium** | KPMG/Salesforce are broad population/workforce surveys, not SMB-specific [S36][S37] |
| Review-site ratings represent the market | **Low–medium** | G2/Capterra reviews are incentivized and skew positive; negative reviews were prioritized [S26][S27][S30] |

**Additional caveats:**

- Reddit threads are self-selected and often low-score. They are strong for language and pain points, weak for prevalence.
- Several Reddit threads contain vendor employees, competitors, and obvious shill comments (especially review-software threads). Quotes used here are from owners/operators or clearly labeled practitioners; vendor comments were not used as proof of demand.
- G2/Capterra snapshots may differ from live pages; dates are in the source table.
- Birdeye and Reputation statistics are vendor marketing datasets with undisclosed sampling. They are used as benchmarks/context, not independent validation.
- BrightLocal is a vendor survey but discloses its panel (1,002 US adults via SurveyMonkey) and is the most methodologically transparent review survey in this set.
- The mobile/desktop evidence is qualitative; no representative usage telemetry was available.

---

## Part 6 — Open Questions

1. **Referral tracking:** Do owners actually want a referral funnel, or do they treat referrals as word-of-mouth that shows up in reviews and repeat customers? The sample had almost no direct demand. Test before building a referral page.
2. **Alert thresholds by industry:** Is 15 minutes the right "waiting" threshold for restaurants, clinics, and home services? Probably not. Needs per-vertical research.
3. **AI trust by role:** Do owners trust AI summaries more or less than front-desk managers? The surveys are population-level, not role-level.
4. **Willingness to pay for insights vs reviews:** Owners pay for review generation/crisis help [S11]; will they pay separately for benchmark/insight modules, or is that a retention feature?
5. **Absolute vs percentage by vertical:** Restaurants clearly need guest counts and dollars; marketing agencies may prefer rates. Test the default card format by segment.
6. **Benchmark sample-size display:** How much methodology can an owner absorb before the benchmark feels like a statistics lecture? Test "n=12, directional" vs a full methodology panel.
7. **Multi-location vs single-location:** The strongest review/messaging demand comes from multi-location operators and agencies [S8][S23][S26]. Single-location owners often prefer DIY or a cheap point tool [S10]. The product may need two packaging tiers, not one UI.
8. **Quora:** Quora was inaccessible in this environment. A follow-up pass with authenticated access could add owner answers, especially for "what reports should a small business owner review monthly?"

---

## Part 7 — Source List

> **Note:** Reddit links are canonical thread URLs; quotes were read from PullPush archive data because live Reddit blocked this environment. G2/Capterra links are live product pages; reviews were read from the Wayback snapshots noted in the date column. Vendor pages are primary documentation, not independent validation.

| # | Source and who is speaking | URL | Date | Concrete want / complaint |
|---|---|---|---|---|
| S1 | **r/restaurantowners — "Are restaurant dashboards actually helpful?"** OP is a restaurant operator; comments from restaurant operators/managers | https://www.reddit.com/r/restaurantowners/comments/1m98uk9/ | 2025-07-25 | Wants YOY sales, guest count, labor, voids, third-party reviews/credits. "Dashboard inside the four walls" matters more than iPads; "you can't calculate COGS in real time in a dashboard." |
| S2 | **r/Restaurant_Managers — "What POS Reports Do You Actually Use?"** OP runs a small diner; operators/managers reply | https://www.reddit.com/r/Restaurant_Managers/comments/1l7cqjm/ | 2025-06-09 | Uses sales summary, PMIX, labor vs sales, voids/comps, guest counts, PPA. Wants daily theft checks and week-by-week sales-by-hour vs targets ("$8k every weekday with 70% post 5pm"). |
| S3 | **r/smallbusiness — "What metric is important in small business?"** SMB owners and advisors | https://www.reddit.com/r/smallbusiness/comments/1nlmpff/ | 2025-09-20 | Wants three weekly numbers: cash flow, contribution margin per sale, lead-to-client conversion. "Data that doesn't make you do something is performative at an early company." |
| S4 | **r/smallbusiness — "What's your go-to way to check if your marketing is on track?"** SMB owners; ads/agency commenters | https://www.reddit.com/r/smallbusiness/comments/1o6fuj8/ | 2025-10-14 | Wants sales, CPA vs LTV, bank/CRM reconciliation. Complains agencies show impressions/clicks; "the reported performance metric is a forecast the algorithm often misses, not a receipt." |
| S5 | **r/BusinessIntelligence — "Anyone else seeing fewer dashboard requests this year?"** BI consultant (10 years, SMB clients); BI/ops leaders | https://www.reddit.com/r/BusinessIntelligence/comments/1qulihh/ | 2026-02-03 | SMB clients "just want the key numbers"; no login/tabs/filters. Wants 5–10 trusted metrics pushed to Slack/email, decision + threshold + owner, mobile scrollable splash; warns push becomes noise. |
| S6 | **r/BusinessIntelligence — "What BI metrics looked important at first but turned out to be noise?"** BI practitioners | https://www.reddit.com/r/BusinessIntelligence/comments/1q4qccv/ | 2026-01-05 | Raw volume metrics (records, sessions, dashboard views, storage) are noise. "If a metric can move up or down and no one knows what action follows, it's vanity." |
| S7 | **r/digital_marketing — "How do you report results to small business clients without overwhelming them?"** Agency owners/consultants | https://www.reddit.com/r/digital_marketing/comments/1o9cs2d/ | 2025-10-17 | Wants one-page summary, 3–5 metrics, 3 takeaways, outcomes not activity; simple text/PDF/Loom; avoid full dashboards and data dumps. |
| S8 | **r/smallbusiness — "Birdeye for reviews - has anyone had a positive experience?"** SMB owner (OP); 15-location operator (jruid99) | https://www.reddit.com/r/smallbusiness/comments/1jw5hja/ | 2025-04-10 | Wants review volume/ROI. Complains 1 review/month/location at $130/location/month, 90-day cancellation notice, auto-renewal, 8% increase. |
| S9 | **r/localseo — "People using expensive platforms like Birdeye or Podium what keeps you using them?"** Local SEO/agency; single-store operator; multi-unit operator; vendor founders | https://www.reddit.com/r/localseo/comments/1q514g3/ | 2026-01-05 | Wants automation, unified inbox, POS integrations. Single-store operator uses Podium from phone daily; "best $300/mo+ marketing I spend." Most only use 2–3 features. |
| S10 | **r/smallbusiness — "Do small businesses pay for reputation management software?"** SMB owners; HVAC owner (8 employees) | https://www.reddit.com/r/smallbusiness/comments/16t2ma1/ | 2023-09-26 | HVAC owner does reviews himself ~30 min/week; pays only for fake-review removal; software is overkill unless multi-location. |
| S11 | **r/SaaS — "People Don't Want To Buy Reputation Management Software?"** SaaS founder; SMB owners; reputation consultants | https://www.reddit.com/r/SaaS/comments/1cnqqfj/ | 2024-05-09 | Review requests are commoditized (POS/CRM already does it). Owners pay for bad/fake review help, bad-review alert + owner assignment, theme tracking by location/staff/service, weekly operational report. |
| S12 | **r/MedSpa — "What's your actual success rate getting reviews from happy clients?"** Med-spa owner; clinic operators | https://www.reddit.com/r/MedSpa/comments/1mhoj02/ | 2025-08-04 | 2 reviews from 67 treatments / 64 satisfied clients = 3%. Wants in-person ask, QR, SMS; NPS first, then review link; private negative feedback before public review. |
| S13 | **r/DigitalMarketing — "Digital Marketing Dashboard APP"** Marketer/agency; marketers; 30-year tech/marketing veteran | https://www.reddit.com/r/DigitalMarketing/comments/1scohuw/ | 2026-04-04 | Wants a mobile glance view: spend/CPA/ROAS, fast, no bloat. Looker/AgencyAnalytics mobile is "hell"/"a pain"; counterpoint: "never seen anybody use a mobile device to gather insight." |
| S14 | **r/PPC — "How do you answer clients asking for benchmarks?"** Small UK agency; former WordStreamer; PPC practitioners | https://www.reddit.com/r/PPC/comments/qrp24c/ | 2021-11-11 | Clients ask for benchmarks to justify spend. Complains broad categories, US/SMB skew (~80% US), wedding venue cannot map; "mostly benchmarks are BS"; own history is best. |
| S15 | **r/analytics — "How do you get accurate industry benchmarks?"** Analytics practitioners | https://www.reddit.com/r/analytics/comments/r9wxz1/ | 2021-12-06 | "You don't"; warns averaging averages, methodology/sample size, vertical specificity; best bet is a company with many clients in the industry. |
| S16 | **r/smallbusiness — "Do You Benchmark Your Business? Do You Care To?"** BizBuySell team; business buyers/owners | https://www.reddit.com/r/smallbusiness/comments/1jeb1ie/ | 2025-03-18 | Wants industry averages for acquisition, local market data, similar-size companies; IBIS is high-level, Bizminer localizes; competitive density matters. |
| S17 | **r/BusinessIntelligence — "I've helped dozens of small businesses fix their reporting chaos AMA"** BI consultant | https://www.reddit.com/r/BusinessIntelligence/comments/1oo99zi/ | 2025-11-04 | Trust via KPI definitions, data marts, row counts, freshness checks, reconciliation. Dashboards break when data changes; Excel remains the backbone; clients want reliable numbers, not more tools. |
| S18 | **r/analytics — "What's your approach for surfacing AI-generated insights in dashboards?"** Analytics builder; vendor practitioner | https://www.reddit.com/r/analytics/comments/1nts3d6/ | 2025-09-29 | Wants contextual AI cards next to relevant data, anomaly-triggered, subtle badges; do not overwhelm users with all insights at once. |
| S19 | **r/restaurateur — "To all restaurant owners, how do you guys perform business analytics?"** Restaurant owners/managers | https://www.reddit.com/r/restaurateur/comments/4xztai/ | 2016-08-16 | Wants historical comparisons; complains too many disconnected tools (POS/marketing/reservations); CTUIT overkill with steep learning curve; managers need easy reports. |
| S20 | **r/smallbusiness — "Anyone using Podium for text message or reviews?"** SMB owners/Podium users | https://www.reddit.com/r/smallbusiness/comments/18b272b/ | 2023-12-05 | Text review requests work; complains price/contract/auto-renewal; "only received 13 Google reviews in a year"; app drops calls; support issues. |
| S21 | **r/smallbusiness — "Podium.com"** SMB owners/Podium users | https://www.reddit.com/r/smallbusiness/comments/148oqsy/ | 2023-06-13 | Reviews/texting work; complains $399+/month, 12-month contract, auto-renewal, features beyond SMB needs; "go all in to justify the cost." |
| S22 | **r/restaurateur — "Has anyone used something like Birdeye/Podium to increase qty + quality of Google reviews?"** Restaurateurs | https://www.reddit.com/r/restaurateur/comments/10ery3w/ | 2023-01-17 | Text link after service works; customers tap and review on the spot; reviews stack up; quality feels natural. |
| S23 | **r/agency — "Reputation Management at Scale"** Agency owner managing 20+ clients | https://www.reddit.com/r/agency/comments/1n2me81/ | 2025-08-28 | Wants one dashboard for 20+ accounts, sub-accounts/white-label, review responses, multi-location; Birdeye expensive at 20+ locations. |
| S24 | **r/smallbusiness — "How do service businesses track which ads actually lead to closed deals?"** Data consultant; wedding-services operators; marketers | https://www.reddit.com/r/smallbusiness/comments/1oehvyu/ | 2025-10-23 | Wants ad → form → CRM → closed deal. "How did you hear about us" is unreliable; last-click fails; long consideration cycles; UTM/CRM needed. |
| S25 | **r/Tech4LocalBusiness — "How to track your marketing results without fancy tools"** Local business owners/helpers | https://www.reddit.com/r/Tech4LocalBusiness/comments/1qoyj9d/ | 2026-01-28 | Wants simple attribution: ask customers, UTM, unique codes, spreadsheets. Consideration period 3 days–3 months; AI search referrals often invisible. |
| S26 | **G2 — Birdeye reviews (4.7/5, 4,264 reviews)** Marketing Director/SEO (7 dental offices); Internet Marketing Manager/SEO Consultant (11 transmission shops); veterinary practice manager; admin specialist; communications specialist | https://www.g2.com/products/birdeye/reviews | Snapshot 2026-10-19; reviews 2021–2026 | Wants multi-location toggles, AI replies, integrations, central dashboard. Complains reports confusing/too many columns, GBP directions inaccurate, mobile app lag, AI response extra step, reports late. |
| S27 | **G2 — Podium reviews (4.5/5, 2,155 reviews)** Controller; office managers; small-business users | https://www.g2.com/products/podium/reviews | Snapshot 2026-10-23; reviews 2026 | Wants dashboard, call log, alerts for waiting customers, AI replies. Complains app/desktop gap, browser refresh, price, AI accuracy, customers frustrated when no human. |
| S28 | **G2 — Reputation reviews (4.5/5, 2,469 reviews)** Digital Marketing Specialist (mid-market); multi-location reviewers | https://www.g2.com/products/reputation/reviews | Snapshot 2026-08-24; review 2022 | Wants centralized reviews/listings/surveys. Complains social reports are separate/buggy/slow with little customization; G2 surfaces "Reporting Issues" and "Scoring Issues." |
| S29 | **G2 — Looker Studio reviews (4.4/5, 450 reviews)** Global Digital Marketing Expert (small business); BI/analytics reviewers | https://www.g2.com/products/looker-studio/reviews | Snapshot 2026-02-07; review 2026-01-31 | Wants cross-channel dashboards, free, shareable. Complains slow with large data/many charts, limited customization, unreliable connectors. |
| S30 | **Capterra — Birdeye reviews (4.7/5, 704 reviews)** Director (health/wellness, 2–10 employees); Marketing Manager (hospital/health care); Owner (automotive); VP (health/wellness) | https://www.capterra.com/p/152997/Birdeye/reviews/ | Snapshot 2026-05-14; reviews 2024–2026 | Wants review requests, listings, reporting. Complains <10 reviews in 5 months, booking integration failure, duplicate requests, clunky mobile app, listings sync assumption, price/contract. |
| S31 | **BrightLocal — Local Consumer Review Survey 2026** Vendor survey; 1,002 US adults via SurveyMonkey; Rosie Murphy | https://www.brightlocal.com/research/local-consumer-review-survey | 2026-02-11 | 97% read reviews; 41% always; 47% won't use <20 reviews; 74% only care about last 3 months; 31% require 4.5+; 89% expect response; 19% same day/32% next day/81% within week; 80% use business that responds to all; 50% put off by generic replies; 78% asked, 83% of asked left review; 82% read AI summaries, 23% rely solely; 40% trust AI recommendations. |
| S32 | **Birdeye — State of Online Reviews 2026** Vendor dataset; multi-location brands | https://birdeye.com/blog/state-of-online-reviews | 2026-05-19 | 75.5% response rate; SMS 54.6% of requests; email open 53.7%; SMS CTR 6.2%; 79.8% reviews with comments; review volume +30.7%; consumer trust in reviews 42%; responses 60% human/40% automated. |
| S33 | **Google Business Profile Help — "Understand your Business Profile performance & insights"** Google primary documentation | https://support.google.com/business/answer/9918094?hl=en | Current 2026 | Calls = clicks on the call button, not calls; views are unique visitors; searches update monthly with up to 5 days' lag; only metrics that apply appear; performance data only for verified profiles. |
| S34 | **Toast — "Toast Reporting Dashboard: Weekly Overview"** Toast primary documentation | https://support.toasttab.com/en/article/How-to-Use-the-Toast-Reporting-Dashboard | Updated 2026-09-17 | Weekly cadence, hourly refresh; compare prior week/same week last year/2 years ago; dollar totals + percent change; net sales may not match other reports; no weekly guest counts for a full year. |
| S35 | **Reputation.com — Product Offering Details** Vendor documentation | https://reputation.com/legal-information/product-offering-details | 2026 | Notifications via platform/email/mobile with customizable frequency; report types (Executive Summary, Star Ratings, Sentiment, Reputation Score, Under/Over-Performing Locations); mobile app; Experience Insights (topics, Word Cloud, Sentiment Map, Big Movers); Reputation Score with weighted subcomponents; Actions with rules/SLAs/queues; response time by team member. |
| S36 | **KPMG — Trust, attitudes and use of AI: global study 2025** 48,000+ people, 47 countries; University of Melbourne/KPMG | https://kpmg.com/xx/en/our-insights/ai-and-technology/trust-attitudes-and-use-of-ai.html | 2025-04-29 | Only 46% of people globally are willing to trust AI systems; 70% believe regulation is needed; 66% use AI regularly; 56% report making mistakes at work due to AI. |
| S37 | **Salesforce — "Your Data, Your AI"** ~6,000 knowledge workers, 9 countries, YouGov | https://www.salesforce.com/news/stories/trusted-ai-data-statistics/ | 2024-04-18 | 56% of AI users struggle to get what they want; 54% don't trust the data used to train AI; 82% say accurate data is critical; 71% say consistently inaccurate outputs break trust. |
| S38 | **Local Search Forum — "Review management for past customers"** Service business owner Timur (1,500 customers, 87 reviews) | https://localsearchforum.com/threads/review-management-for-past-customers.60950/ | 2024-01-09 | Gets 1 review per 20–30 requests; wants software to reach past customers; needs SMS consent/10DLC; goal should be steady reviews, not the most reviews. |
| S39 | **Local Search Forum — "Experiences/Tips for Using Birdeye's BirdAI feature?"** Hospitality client manager; local SEO practitioner fisicx | https://localsearchforum.com/threads/experiences-tips-for-using-birdeyes-birdai-feature.62969/ | 2025-12-18 | Wants AI auto-replies with brand tone/SEO. Practitioner: "Don't do it!" AI responses "stand out like a sore thumb" and can "mangle" the response. |
| S40 | **Local Search Forum — "Calls Missing from Performance Tab"** Local SEO practitioners | https://localsearchforum.com/threads/calls-missing-from-performance-tab.61727/ | 2024-08-06 | GBP calls disappeared from performance; poor Google communication; agencies need third-party call tracking. |
| S41 | **Local Search Forum — "GBP Performance Reporting Issues for June 2025?"** Local SEO practitioners | https://localsearchforum.com/threads/gbp-performance-reporting-issues-for-june-2025.62532/ | 2025-06-10 | Client reporting at 0 or below expected; data delay; makes pacing/SERP decisions nervous. |
| S42 | **Local Search Forum — "Call Tracking Software for GBP (Lost Reporting on Dozens of Clients)"** Agency practitioner | https://localsearchforum.com/threads/call-tracking-software-for-gbp-lost-reporting-on-dozens-of-clients.61729/ | 2024-08-07 | Lost call reporting across dozens of clients; needs affordable call tracking (CallRail/Call Tracking Metrics). |
| S43 | **Local Search Forum — "1-star review extortion"** Business owner chriscc | https://localsearchforum.com/threads/1-star-review-extortion.62885/ | 2025-11-08 | Five fake 1-star reviews in one evening; obvious extortion; needs fast flag/report/removal path and crisis alerts. |
| S44 | **r/smallbusiness — "What benchmarks do you use in your Small Business?"** SMB owners | https://www.reddit.com/r/smallbusiness/comments/1dljt4w/ | 2024-06-22 | Wants labor/overhead/EBITDA percentages; uses an industry benchmarking company that compares to similar-sized companies; tracks cash flow and recurring income vs costs. |
| S45 | **r/analytics — "A dashboard can be accurate and still be the wrong thing"** Analytics practitioners (thread ID 1vxvx2e; exact post date unavailable in archive) | https://www.reddit.com/r/analytics/comments/1vxvx2e/ | Undated in archive (thread ID 1vxvx2e) | "Making the decision, threshold, and owner explicit" filters vanity metrics; "generic AI... will hand you a confident root cause it can't actually support." |
| S46 | **ReplyOnTheFly — "Average Google Review Rating by Industry (2026 Benchmarks)"** Vendor scan of 67,969 Google Maps listings; methodology disclosed (8,520 scans, 401 businesses, 1,469 search terms, Mar 11–Oct 15, 2026; ~25% US) | https://www.replyonthefly.com/blog/average-google-review-rating-by-industry | 2026-04-07; updated 2026-10-16 | Industry averages: restaurants 4.50★ (5,131 listings), chiropractors 4.93★ (107), plumbers 4.81★ (392), hotels 4.08★ (1,264); overall average 4.56★. Warns to compare to local competitors, not national averages. |

---

## Part 8 — Bottom Line for the Product

If the team builds only four things, build these:

1. **A trustworthy weekly Overview** with six numbers, three actions, and a "data card" on every tile.
2. **A theme engine with receipts** — counts, locations, quotes, and owners, not a sentiment score.
3. **A review engine that shows the denominator** — requests → delivered → clicked → reviews → rating, by trigger/channel/location.
4. **A peer benchmark that lets the owner inspect the peer set** — local, similar-size, dated, with n and gap math.

Everything else — AI copilots, composite scores, word clouds, maps, vanity dashboards — is optional. The evidence says owners will reward the product that tells them the truth and tells them what to do next.

---

*Report compiled 28 October 2026. All quotations are from the sources listed above; Reddit quotes are verbatim from archived thread data. Vendor statistics are labeled as vendor claims, not independent research.*
















