# AI Visibility Research — Security and Integrity Invariants

AI Visibility powers **Sayvors Grounded AI**: an automated research brief built
from public web evidence. It is not a recording of ChatGPT, Gemini, or
Perplexity answers and must never be presented as one.

## Trust boundaries

- Search results, page content, source titles, and LLM output are untrusted.
- The LLM is a drafting aid, not an authority. A model-supplied citation,
  outcome, competitor, or action is accepted only when deterministic validation
  proves it against immutable fetched excerpts.
- Public URLs are untrusted destinations. They are checked before fetch and
  again before rendering.
- Tenant identity comes from the authenticated `TenantContext`, never from a
  request body or job payload.

## Authorization and tenant isolation

- Reads require `analytics.view`; writes require `ai.edit`.
- Every channel-addressed route checks `ctx.channel_level()`. Object-addressed
  routes load by `tenant_id` first, then check the object's channel. A `none`
  override denies reads and writes; a `view` override denies writes.
- Services repeat tenant/channel ownership checks. Job reloads match run id,
  tenant id, job id, subject id, running status, lease owner, and unexpired
  lease before external work.
- AI Visibility jobs are internal-only. The generic client job API cannot
  submit, fetch, list, or cancel them, so it cannot bypass channel permissions,
  credit preflight, or run idempotency.
- The feature is available to every plan. Execution still requires the existing
  `ai_replies` entitlement and a positive wallet balance; the LLM gateway
  rechecks both and reserves credit atomically before the provider call.
- Tenant export includes all six AI Visibility tables. Source rows are scoped
  through their tenant-owned run; generated questions are scoped through their
  tenant-owned query set. Purge deletes children before parents.

## Collector guarantees

- Search uses fixed Bing public RSS/HTML endpoints with DuckDuckGo HTML as a
  fallback when Bing is blocked, empty, or returns no branch-relevant candidate.
  No paid search key, login, or consumer-AI scraping is involved.
- At most 10 results are parsed from at most 1 MB. Queries are normalized and
  cached per tenant for six hours.
- Uncached searches have a fail-closed per-tenant limit of 10/minute and a
  project-wide provider limit of 30/minute.
- Valid cache hits are served before the provider-block check. CAPTCHA/429
  responses set a 15-minute project-wide cooldown.
- Global provider throttling propagates to the durable job runner for deferred
  retry. A tenant exceeding its own search budget receives an explicit terminal
  failure instead of consuming shared provider quota indefinitely. DuckDuckGo's
  anti-bot interstitial sets its own 15-minute cooldown and never escalates.
- Redis failures deny new collection; they never silently disable rate limits.

## Source-fetch guarantees

- Only `http` and `https` public destinations are accepted.
- `assert_public_http_url` plus DNS-pinned fetching is applied on every redirect
  hop, blocking loopback, private, link-local, and metadata addresses.
- A run selects at most five sources in quick mode or six in deep mode, at most
  two per domain. Fetches run with concurrency three, a 15-second timeout, a
  2 MB byte cap, and a fail-closed per-domain limit of two/minute.
- Only `text/html`, `application/xhtml+xml`, and `text/plain` are extracted.
  Extracted text is capped at 20,000 characters per source and 40,000 characters
  in the model prompt.
- Source rows keep their original search position. Labels are always `S<n>`
  from that position, even when earlier sources failed, so citations never
  renumber.
- Source snapshots commit before the LLM call. A reclaimed job reuses committed
  snapshots instead of fetching duplicate rows.
- Aggregate evidence counts distinct canonical URLs only when the fetch
  succeeded, an excerpt exists, and the URL is valid HTTP(S). Independent pages
  must mention a distinctive branch token; owned pages must match an owned host.
  Failed and synthetic rows never inflate coverage.

## Business-aware question generation

- The owner never supplies a universal prompt. A connected branch receives a
  versioned set of customer questions generated from its own identity,
  categories, merchant overrides, declared services, active catalog products,
  review/conversation themes, geography, website metadata, and bounded public
  context.
- Classification combines weighted signals rather than trusting the Google
  primary category. Missing or low-confidence facts are stored as uncertainties;
  the generator never invents a service that is absent from the profile or
  explicitly marked not offered.
- Questions carry a stable key, language, customer intent, industry/service
  relevance, geographic context, business relevance score, priority, origin,
  prompt link, run link, and status. Generated text is unique per tenant/branch.
- Arabic and English templates are authored per industry. Saudi profiles are
  Arabic-first; other profiles use the languages supported by their actual data.
- Real customer questions are prioritized only when they match the branch name,
  locality, an actual service/product phrase, or a relevant intent. Generic
  support chatter is excluded and cannot return through adaptive versions.
  Review asks and conversation questions are scrubbed for emails, phones,
  addresses, long identifiers, handles, known reviewer-name components, and
  conservative person-name cues while protecting branch/service terms.
- The public-context collector uses the same SSRF-safe source fetcher. Website
  and public-page excerpts are untrusted data, bounded, and stored as a
  reproducible query-set snapshot. Reviewer names, raw review text, contact
  identifiers, and other customer PII are not sent to question generation.
- The outbound research prompt serializes an allowlist of merchant/public
  business fields only. Customer questions, review themes, public context, and
  provenance fields are excluded; the research question is scrubbed again at
  the LLM and search boundaries.
- Query-set versions are immutable. Adaptive versions may add grounded
  competitor comparisons or unused real customer questions, but never rewrite
  an earlier version or its outcomes. Adaptive depth is tracked separately from
  the branch-wide version number, with at most two adaptive follow-ups per cycle.
- Query-set-linked runs cannot be deleted through the legacy single-run or
  clear-history APIs. Retention is the only eventual cleanup path.
- Partial/failed sets with pending questions resume into a new linked version
  that carries the original prompt and `carried_from_question_id`; the partial
  parent remains unchanged. Latest-history projections suppress superseded
  ancestor rows so owners see each effective question once.
- A manual new research cycle intentionally reruns the same canonical customer
  questions as linked `rerun` rows, refreshing evidence without rewriting the
  prior version. Adaptive expansion still skips redundant questions.
- Canonical question identity is enforced by a partial unique index for all
  non-resume origins; resume lineage may intentionally repeat the parent text.
- `ai_visibility.query_set` is internal-only. The generic job API cannot submit,
  inspect, or cancel it. A partial unique index permits one active set per
  tenant/branch. The global UI-jobs endpoint resolves each AI Visibility job's
  channel and applies `analytics.view` plus channel-level RBAC; UI titles are
  static and never contain raw questions or branch names.

## Grounding guarantees

- The model response is bounded structured JSON. Collections, answer length,
  source ids, and token output have hard caps.
- Every factual answer sentence must carry a mapped `[S<n>]` citation and be an
  exact normalized extractive match in at least one cited excerpt. Unmapped
  labels and URLs are rejected.
- Every claim source id must exist. One cited excerpt must contain both the
  claim text and its exact quote; support cannot be assembled from unrelated
  sources.
- Unsupported claims remain visibly labelled and never contribute to outcomes.
  Competitor mentions require a grounded quote containing the competitor name.
- Mention, citation, recommendation, and incorrect outcomes are recomputed.
  Citation requires an owned-domain source label actually used in the answer;
  recommendation requires a supported claim containing the branch name and
  recommendation wording.
- Fix-next actions are rule-ranked from validated outcomes. Model-suggested
  actions, numeric uplift, and ranking guarantees are ignored.
- Source and model text render as escaped React text. Links pass through
  `safeHref`; raw HTML is never rendered.

## Job, retry, and spend guarantees

- PostgreSQL is execution truth. AI Visibility uses the existing `bulk` lane.
- A partial unique index permits one active run per tenant/prompt. Run and job
  are created in one transaction with idempotency key `ai-visibility:{run_id}`.
- Create and retry share a channel/prompt-locked policy: at most 20 accepted
  attempts in the trailing hour, with a 5-second cooldown. An append-only
  attempt ledger survives run deletion. Prompt text becomes immutable once
  research has begun, and prompt deletion archives the row, so recreating the
  same logical prompt cannot reset the budget.
- Before the provider call, the worker durably records `llm_call_in_progress`
  and extends its lease to 15 minutes using a conditional update tied to the
  current owner. A reclaimed job with that marker becomes `ambiguous` rather
  than spending again.
- The worker rechecks run/job/lease state before search, fetch, branch lookup,
  the LLM call, and post-call persistence. Active runs cannot be deleted;
  terminal-run deletion locks the row before checking status.
- Budget exhaustion and schema/citation failures are terminal. Any uncertain
  provider or local persistence failure after the call may have spent becomes
  `ambiguous`, is reported to Sentry, and is never blindly retried.
- Unexpected exception text is logged internally but replaced with a safe
  client message. Explicit telemetry carries ids/status, not prompts or answers.
- Query-set start returns `202` after committing only the set and parent job.
  The parent generates questions and starts one child run. A periodic finalizer
  advances the queue only after the current child is terminal, so `lane_key`
  metadata is never mistaken for serialization.
- The finalizer reconciles terminal child jobs with still-active runs, updates
  aggregate counters, and stops cleanly as `partial` when quota is exhausted.
  Generating sets whose parent job is terminal are failed explicitly; handler
  re-entry never starts a second child while one is active.
- Background child-run creation takes a PostgreSQL transaction advisory lock
  keyed by tenant/depth/month, re-counts usage, and inserts atomically. Router
  preflight remains a fast fail, not the concurrency control.
- Parent and child jobs expose safe UI titles/progress through the existing
  background-operations widget; raw questions and answers are not job labels.

## Retention

- Completed runs older than 365 days are deleted in bounded batches of 500.
- Failed, insufficient-evidence, and ambiguous runs older than 30 days are
  deleted in bounded batches of 500.
- Attempt-ledger rows older than 30 days are pruned in bounded batches. Recent
  attempt evidence remains when the corresponding run is deleted.
- Source rows cascade with runs. Completed query sets older than 365 days and
  failed/partial query sets older than 30 days are deleted in bounded batches;
  generated questions are removed explicitly before their set. Active sets are
  never swept. The cleanup worker is idempotent and logs failures with a traceback.
