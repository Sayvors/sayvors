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
- Tenant export includes all four AI Visibility tables. Source rows are scoped
  through their tenant-owned run; purge deletes children before parents.

## Collector guarantees

- Search uses fixed Bing public RSS and HTML fallback endpoints. No paid search
  key, login, or consumer-AI scraping is involved.
- At most 10 results are parsed from at most 1 MB. Queries are normalized and
  cached per tenant for six hours.
- Uncached searches have a fail-closed per-tenant limit of 10/minute and a
  project-wide provider limit of 30/minute.
- Valid cache hits are served before the provider-block check. CAPTCHA/429
  responses set a 15-minute project-wide cooldown.
- Global provider throttling propagates to the durable job runner for deferred
  retry. A tenant exceeding its own search budget receives an explicit terminal
  failure instead of consuming shared provider quota indefinitely.
- Redis failures deny new collection; they never silently disable rate limits.

## Source-fetch guarantees

- Only `http` and `https` public destinations are accepted.
- `assert_public_http_url` plus DNS-pinned fetching is applied on every redirect
  hop, blocking loopback, private, link-local, and metadata addresses.
- A run selects at most five sources, at most two per domain. Fetches run with
  concurrency three, a 15-second timeout, a 2 MB byte cap, and a fail-closed
  per-domain limit of two/minute.
- Only `text/html`, `application/xhtml+xml`, and `text/plain` are extracted.
  Extracted text is capped at 20,000 characters per source and 60,000 characters
  in the model prompt.
- Source rows keep their original search position. Labels are always `S<n>`
  from that position, even when earlier sources failed, so citations never
  renumber.
- Source snapshots commit before the LLM call. A reclaimed job reuses committed
  snapshots instead of fetching duplicate rows.

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
- Create and retry share a channel/prompt-locked policy: at most three accepted
  attempts in the trailing hour, with a 60-second cooldown. An append-only
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

## Retention

- Completed runs older than 365 days are deleted in bounded batches of 500.
- Failed, insufficient-evidence, and ambiguous runs older than 30 days are
  deleted in bounded batches of 500.
- Attempt-ledger rows older than 30 days are pruned in bounded batches. Recent
  attempt evidence remains when the corresponding run is deleted.
- Source rows cascade with runs. The cleanup worker is idempotent and logs
  failures with a traceback.
