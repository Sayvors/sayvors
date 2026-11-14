# Multi-Tenant Website Crawler for SaaS RAG - Research Report

**Date:** 2026-11-11 | **Scope:** FastAPI + Postgres + pgvector + Redis + existing Kafka. Target: 1000+ small-business tenant sites, JS-light, Arabic + English content, ~1h default recrawl with per-tenant toggle, bounded infra.

## 1. Executive Summary

- For this profile (small, mostly static-ish business sites, JS-light), a **self-hosted async-Python fetcher (httpx) + trafilatura main-content extraction, with an optional Playwright/Crawl4AI fallback path** beats adopting a browser-heavy crawler framework for every page: HTTP-only pipelines scrape 2-7x faster than browser-based ones and cost ~21-66% less per year in embedding+storage at scale [S14]. Crawl4AI (Apache-2.0, 87.2k stars, very active) is the best RAG-native library if you want a ready-made engine instead [S1].
- Firecrawl self-host is powerful but **AGPL-3.0** for the engine and its OSS build lacks the anti-bot/screenshot stack (Fire-engine); hosted plans run $19 (5k credits) to $749/mo (1M credits, about $0.75/1k pages), with a native **Monitor** endpoint (1 credit/page/check) that is exactly a scheduled re-check product [S2][S8][S9].
- At 1000 sites x hourly recrawl, economics only work with **conditional GETs (ETag/If-Modified-Since) + content-hash skip**: raw HTML almost never hashes equal (CSRF tokens, timestamps), so hash the *extracted text*, not the HTML [S20].
- Most small-business pages rarely change: in a year-long weekly crawl only ~15% of pages changed every week and a large fraction never changed [S16]; Bing-scale data shows churn concentrated in a minority of URLs [S17]. **Adaptive per-URL intervals** (1h to 6h to 24h for pages that never change) cut load 5-10x while the tenant's hourly "check" stays cheap (304).
- Worker architecture: **Postgres due-time table (or Redis ZSET) + SKIP LOCKED / ZPOPMIN claiming, per-domain token buckets, tenant-fair (stale-first) dispatch, jittered schedules**, Kafka for the page->chunk->embed fan-out. This mirrors LangChain Indexing API and LlamaIndex IngestionPipeline incremental sync semantics: doc_id -> content_hash, upsert changed, delete stale [S25][S26].
## 2. Key Findings

### Angle 1 - Open-source crawlers for AI/RAG

**Crawl4AI** [S1][S4]
- Python + Playwright async crawler purpose-built for LLM/RAG. **Apache-2.0**, but the LICENSE file appends an attribution condition for public use/distribution (README says attribution "recommended" via badge or one text line; third-party analysis says the license file makes it mandatory for public uses - read the file, not the GitHub badge). 87.2k stars, 9.1k forks, 1,792 commits; v0.9.5 released 14 Oct 2026 - very active.
- Markdown generation is the core feature: `result.markdown` (default), `fit_markdown` via PruningContentFilter (heuristics, no LLM) or LLMContentFilter; BM25 relevance filter; heading/code preservation; image srcset handling; external-link/image exclusion; `chunk_token_threshold` (2048-4096) parallelizes markdown processing of big pages.
- Extraction: CSS/XPath JSON strategies (no LLM), regex strategies, optional LLM strategies with schema. Deep crawling, URL seeding, robots.txt compliance + SQLite cache (since v0.4.3b1), proxy rotation, session/identity management.
- Docker/REST mode: `/crawl`, `/crawl/stream` (NDJSON), `/md/{url}`, `/llm/{url}`, `/health`, `/schema`, JWT auth. Self-host guide recommends **>=4 GB RAM** for the container; Docker requires a `.llm.env` for LLM keys.
- Crawl4AI Cloud now exists: 1,000 free credits/mo, plans from $10 (cloud pricing seen at $10 for ~10k pages) [S13].
- Caveats: fast-moving project with documented breaking changes (v0.9.0) - pin versions. Playwright-per-page is heavy for JS-light sites at 1000 domains.

**Firecrawl (open source)** [S2][S8][S9]
- **AGPL-3.0** for the engine; SDKs MIT. ~166k+ stars (sources vary 166k-180k, see Conflicting Information). 6,800+ commits, very active; hosted claims P95 3.4s/page.
- Self-host = Docker Compose: API, workers, Redis, Postgres, optional Playwright microservice; recent versions add RabbitMQ/NUQ. **Not in OSS:** Fire-engine (anti-bot/proxies), screenshots, page actions, agent/browser formats - Cloud-only, per the official self-host guide.
- **AGPL implication:** running an *unmodified* self-hosted Firecrawl as an internal microservice behind your own API is the commonly argued-safe pattern (your SaaS talks to it via the MIT SDK over HTTP, so your code is not a derivative work); if you *modify* it, AGPL sec.13 requires offering the modified source to network users. Maintainers have not ruled definitively (issue #1964 open, closed as not planned) - get a legal read before embedding it in the product [S2].
- Output: clean markdown + metadata JSON per page; `ignoreQueryParameters`; URL-level dedup within a crawl run.

**Scrapy** [S5][S12]
- ~65k stars, BSD-3-Clause, most mature framework (Twisted, single-threaded engine). Built-in benchmark: ~3,800-3,900 pages/min on commodity hardware.
- Resource-light for static sites, disk-backed scheduler (JOBDIR) for large frontiers, mature throttling (AUTOTHROTTLE, DOWNLOAD_DELAY, robots middleware default-on). Needs scrapy-playwright for JS and separate markdown conversion; no native RAG output. AutoThrottle is latency-tuned, not 429-aware - response-code backoff is on you.
- Verdict: superb engine, wrong granularity for "many small sites, one-off crawls" - you would run a spider per site and glue RAG plumbing yourself.

**Crawlee** [S6][S12]
- Apify's library; Apache-2.0; ~25k stars; TypeScript + Python port; stable 3.18.1 (Aug 2026), v4.0.0-rc.0 out.
- Cheerio/JSDOM/Playwright/Puppeteer crawler classes over shared queue+storage+proxy; **AutoscaledPool** adjusts concurrency from real CPU/memory/event-loop load. No content-extraction decisions made for you. Best if building in Node; for a Python shop it is a design reference.

**ScrapegraphAI** [S12]
- MIT, ~28-30k stars; graph-based, LLM-driven extraction. You pay LLM tokens per page - overkill and cost-inefficient for whole-site markdown ingestion.

**Jina Reader (r.jina.ai)** [S7]
- URL->markdown as a service. Without key: 500 RPM (per docs.jina.ai/api.md; 5,000 RPM premium). Every new API key includes **10M free tokens**; token-based pricing since 6 May 2025. ReaderLM-v2 (1.54B params) is their HTML->Markdown/JSON model - 3x token cost via API; also on HuggingFace for self-deploy (verify model license before commercial self-hosting).
- Good as a hosted fallback for hard pages; no per-site sync; token cost scales with content, so not the primary engine at 1000 sites.

**trafilatura / readability-lxml** [S3][S15]
- trafilatura (Apache-2.0, pure Python, no browser): best open-source main-content extractor. WCXB leaderboard (2,008 annotated pages, 7 page types) held-out F1: rs-trafilatura 0.903, **trafilatura 0.841**, resiliparse 0.817, newspaper4k 0.762, **readability 0.736**. Extractors converge on articles (0.92+) and diverge on documentation/product/other page types - which dominate small-business sites.
- readability-lxml keeps some markup but is noisier: in a fixture head-to-head it leaked 5/17 boilerplate units and 41 polluted tokens vs trafilatura 1/17 and 3.
- These are extraction libraries: pair with your own fetcher (httpx) - which IS the recommended stack for JS-light sites. trafilatura handles multilingual boilerplate (works for Arabic pages).
### Angle 2 - Hosted crawl/scrape APIs (pricing checked Sep-Nov 2026)

| Service | Free tier | Entry paid | Effective cost per 1k pages (JS-rendered unless noted) | Native incremental/scheduled |
|---|---|---|---|---|
| Firecrawl | 1,000 credits/mo, 2 concurrent | Hobby $19 = 5,000 credits; Standard $99 = 100k credits (~$0.99/1k); Growth $399 = 500k ($0.80); Scale $749 = 1M ($0.75) | $3.80 (Hobby) down to $0.75 (Scale). Scrape/Crawl = 1 credit/page; JSON extract +4 credits/page; 403/404 pages still billed | **Monitor: 1 credit/page/check** - a re-check product |
| Tavily | 1,000 credits/mo (hard stop, no card) | Project $30 = 4k credits ($0.0075/credit); PAYG $0.008/credit | Basic Extract = 1 credit per 5 URLs -> ~$1.50-1.60/1k pages; Crawl = map (1cr/10 pages) + extract credits (10-page crawl = 3 credits) | Crawl/Map endpoints; no scheduled per-site diffing |
| Exa | $10 starter credits | PAYGO only | Contents: **$1/1k pages per content type** (text, highlights, summary billed separately); Search $4-7/1k reqs; cache-first with maxAgeHours livecrawl | Monitors $2/1k scheduled-search requests (search-centric) |
| Brave Search API | $5 free credits monthly | $5/1k search requests | N/A - search/snippets only, not a site crawler | No |
| ScrapingBee | 1,000 credits once | Hobby $19 = 75k credits (JS = 5 credits -> ~15k JS pages); Startup $99 = 1M credits (~$0.99/1k JS) | 1 credit plain HTTP -> $0.099/1k; 5 JS; 25 premium+JS | No |
| Scrapfly | 1,000 credits on signup | Discovery $30 = 200k credits (JS = 6 credits); Pro $100 = 1M credits (~$1/1k JS) | $0.15/1k plain; ~$0.90/1k JS | No |
| Diffbot | 10k credits/mo | Startup **$299/mo** = 250k credits (~$1.20/1k pages) | Overpriced for this use case | Crawl spider exists (list 0 credits, extract 1/page) |
| Browserbase | 1 browser-hour, 1k fetch calls | Developer $20 = 100 browser-hrs then $0.12/hr; Fetch $1/1k plain, $4/1k with proxies/extract; Startup $99 = 500 hrs | ~2 min/page -> ~3,000 pages per 100 hrs; ~$1/1k+ plain fetch | No |
| Crawl4AI Cloud | 1,000 credits/mo | from $10 (~10k pages) | cheap tier of the OSS engine, hosted | Cloud-only features |

**Free-tier viability:** none support 1000 sites x hourly (~720k+ page-checks/day). Free tiers (Firecrawl 1k/mo, Tavily 1k/mo, Exa $10) are pilot-only. **Hosted-vs-self-host math:** with hash-skip, suppose 10% of 30 pages/site change per hour -> ~72k changed pages/day = ~2.2M paid pages/month -> Firecrawl Scale $749/mo vs self-hosted infra roughly $100-300/mo. Self-host wins decisively at this scale if sites are reachable without anti-bot infra (small business sites: yes ~95% of the time).

### Angle 3 - Politeness and scale best practices

- **robots.txt:** parse and obey; honor `Crawl-delay` (Common Crawl: `Crawl-delay: 2` = 1 req/2s); Google ignores crawl-delay - sites throttle via 429/500/503 instead [S21][S22]. Per Google's spec: 4xx robots.txt (except 429) -> allow-all; 5xx -> stop and reuse last good copy.
- **Rate norms:** AWS guidance: 1 req/10-15s for small/medium sites; 1-2 req/s only for large permitted sites [S21]. Wikimedia: <10 concurrent, <20 req/s average [S22]. For per-domain caps: **1 concurrent request/domain, >=1-2s spacing** is safe and plenty (a 30-page site takes <=1-2 min).
- **Conditional requests:** send `If-None-Match`/`If-Modified-Since`; on 304 skip body. Googlebot does this and Google recommends sites honor it - the same protocol serves you as a polite client [S23]. Critical details: **store the ETag verbatim** (quotes, W/ prefix - the #1 bug), `If-None-Match` takes precedence when both sent, **304 is success not error**, a 304 still counts against the rate budget (saves bandwidth, not request count), drop conditional headers for hosts that never 304, and 404/410 clears stored validators [S24].
- **Change frequency data:** Ntoulas et al. (WWW 2004, 150 sites weekly x51 weeks): only ~15% of pages changed at least once per week; a large fraction never changed during the year; past degree-of-change predicts future degree, frequency alone does not [S16]. Cho & Garcia-Molina: change intervals are heavy-tailed; optimal revisit rate depends on importance and change rate [S16]. Microsoft Bing-scale (NeurIPS 2019): 18.5M/26.6M URLs changed >=once in 14 weeks - but that corpus is biased toward data-rich pages; and **sitemap lastmod/changefreq was usable for only ~4% of URLs** (mostly missing/inaccurate) [S17]. Practical: start at the tenant's requested interval, lengthen for URLs observed unchanged, reset on change. The *check* stays hourly; the *re-extract/re-embed* becomes adaptive.
- **Content hashing:** SHA-256 over the **extracted text** (never raw HTML - session IDs/CSRF/timestamps make every response byte-unique); normalize Unicode NFC, collapse whitespace, strip boilerplate before hashing [S20].
- **Sitemap-first:** fetch sitemap.xml (from robots.txt `Sitemap:` directive or /sitemap.xml) to get the URL set in 1 request; complement with bounded link-following. Use sitemap for *discovery*, not freshness (see the 4% figure).
- **URL normalization** (pre-fetch dedup): lowercase scheme/host, drop default port, resolve relatives, strip tracking params (utm_*, fbclid, gclid), settle trailing slash, drop fragments; then honor `<link rel="canonical">` post-fetch. (Firecrawl exposes this as ignoreQueryParameters + in-run URL dedup.) [S20]
- **Trap avoidance:** cap pages/site (tenant-chosen), max depth, URL-pattern blocklist (/tag/, /page/N, /author/, calendar params), reject non-HTML content types, byte caps, per-run page ceiling.
- **Backoff:** 429 -> honor Retry-After else jittered exponential backoff; persistent 403 -> pause site + surface to tenant; 5xx -> backoff, mark degraded [S21][S22].
### Angle 4 - Storage format for AI + human

- **Markdown as the canonical stored format** for humans and RAG: headings/tables/code survive, renders for display, gives chunkers natural split points (this is Firecrawl/Crawl4AI's contract: per-page markdown + metadata JSON) [S4][S27]. Store raw_html (gzipped) separately only if you plan re-extraction; otherwise store extraction_version + hash so old pages can be re-processed without re-fetching.
- **Per-page metadata:** tenant_id, site_id, url (normalized), title, lang, fetched_at, http_status, etag, last_modified, content_hash, simhash, canonical_url, content_type, byte_size, extraction_version.
- **Chunking best-evidence summary:** structure-aware wins as baseline - split at H2/H3 (heading-aware), fall back to paragraphs then sentences; attach the **heading-path breadcrumb** ("Pricing > Refunds > Windows") to every chunk [S27][S28]. Size: 256-512 tokens is the well-supported sweet spot for embedding models; practical range 200-800 [S27][S28]. Overlap: 10-15% of chunk size (80-160 tokens per 800); reduce overlap when using parent-expansion [S28]. Keep tables whole; large tables split by row groups with header repetition [S28].
- **Small-to-big / parent-document retrieval:** embed small children (100-500 tokens) for precision, return the enclosing section (500-2000 tokens) to the LLM - LangChain ParentDocumentRetriever, LlamaIndex auto-merging/HierarchicalNodeParser [S28][S29]. Caveat: one 36-strategy benchmark ranked a 500-parent/100-child setup in its lower half - test on your data; for short business pages, per-section chunks with breadcrumbs are often enough [S28].
- **Chunk metadata:** tenant_id, site_id, page_id, url, title, heading_path, chunk_index/total, lang, fetched_at, content_hash, embedding_model_version. The model-version field makes future re-embedding migrations tractable [S25][S29].
- **Incremental semantics:** LangChain Indexing API (record manager: doc_id -> hash; cleanup modes full/incremental; upsert changed, delete stale) and LlamaIndex IngestionPipeline docstore (doc_id -> hash map; skip unchanged, reprocess changed, upsert) are the reference designs - copy their semantics even if implemented in Postgres directly [S25][S26]. Heading-anchored (alignment-aware) splitters keep chunk IDs stable when a page is edited slightly, minimizing re-embedding [S28].
- **Dedup - layered, cheapest first** [S20]: (1) URL normalization before fetch; (2) canonical tag check post-fetch; (3) exact hash of extracted text; (4) near-dup: **SimHash 64-bit with Hamming distance <=3** is the web-scale-proven threshold (Manku et al., Google, WWW 2007); MinHash+LSH (datasketch) for pairwise corpus dedup; (5) chunk-level exact-hash dedup at insert. Boilerplate stripping at extraction *prevents* most duplicates - strictly better than cleaning up downstream.
- **Arabic + English:** use a genuinely multilingual embedder - **multilingual-e5-large or BGE-M3 (1024-d)**. ArabicNLP 2025 results: same-language retrieval Hit@20 87-93% for Arabic, but **cross-lingual query->doc retrieval drops to 41-72%** - keep queries matching chunks in-language; do not rely on cross-language matching [S30]. For BM25 hybrid: light Arabic normalization (diacritic/tatweel stripping, alef-variant unification) helps [S31]. Store lang per page/chunk; render RTL markdown correctly in the display layer.

### Angle 5 - Multi-tenant worker architecture at 1000+ sites

- **Scale math:** 1000 sites / 1h = ~17 site-crawls/min; each crawl = robots+sitemap fetch + N conditional GETs + occasional re-extracts. With 1 req/2s per domain and ~30 pages, a site crawl takes ~1 min; global concurrency of 30-60 domains-in-flight is handled by 2-4 modest workers. Initial crawls (100+ pages/site) are the burst case.
- **Scheduling pattern:** Postgres `crawl_schedule(site_id, next_run_at, priority, state, last_result, consecutive_failures)`; a scheduler tick (asyncio loop or Celery beat) moves due rows into a **Redis ZSET** (score = due ts) or claims via `FOR UPDATE SKIP LOCKED`. Add +/-10-20% **jitter** so 1000 sites do not align on the hour. Missed-tick policy: run once, never replay N times; "skip if previous run still running" guard for overruns [S33].
- **Fairness:** Temporal's documented multi-tenant pattern is **one shared queue + tenant fairness keys (weighted round-robin)** rather than per-tenant queues - onboarding a tenant is a config value, not a new worker pool; per-tenant queues only for hard isolation [S32]. With Redis/DB queues, equivalent: rotate per-tenant sub-queues or score by priority / tenant_recent_share; monitor starvation via **oldest-job age per tenant** and realized share vs configured weight - queue depth alone hides starvation [S33]. Cheap alternative that works at this scale: **stale-first dispatch** (longest since last successful crawl first) + a small priority lane for manual re-crawls/onboarding.
- **Queue tech:** Celery beat is "a simple scheduler, not a durable workflow engine"; Celery on Redis can silently lose tasks under memory pressure (eviction) - make scheduling idempotent in Postgres regardless [S33]. BullMQ requires Redis, solid for Node. Temporal is the durable-workflow option but is new infra for marginal benefit here - your jobs are single-step and idempotent, exactly the case where a job queue (not a workflow engine) is right [S33]. **Kafka** (already in your stack) fits the *pipeline fan-out*, not scheduling: pages.fetched -> chunker -> embedder consumers, per-partition per-tenant ordering if needed.
- **Failure isolation and caps:** per-domain concurrency = 1 (Redis token bucket per domain); global fetch semaphore (50-200); per-fetch timeouts (connect 5s / total 20-30s); byte caps; per-run page ceilings. **Per-site circuit breaker:** N consecutive failed runs (DNS dead, persistent 403/5xx) -> back off to daily, mark degraded, notify tenant. Keep browser-render work in a **separate small worker pool** so JS-heavy sites cannot starve the static pool [S33].
- **How production RAG ingestion does it:** content-hash-driven idempotent sync is universal - LangChain record manager and LlamaIndex docstore both store doc_id->hash and skip/reprocess/upsert/delete accordingly [S25][S26]; hosted analogues: Firecrawl Monitor (per-page scheduled checks) and Exa Monitors (scheduled search + webhooks) [S8][S11].
## 3. Comparison - top 5 crawler options for THIS use case

| Criterion | (1) httpx + trafilatura (custom) | (2) Crawl4AI library | (3) Firecrawl self-host | (4) Firecrawl hosted | (5) Scrapy (+trafilatura) |
|---|---|---|---|---|---|
| License | MIT/Apache (both libs) | Apache-2.0 + attribution clause | **AGPL-3.0** engine, MIT SDKs | Commercial SaaS | BSD-3 |
| Language | Python (native fit) | Python (native fit) | TS/Node service + HTTP client | HTTP API | Python |
| JS rendering | Optional Playwright fallback you build | Built-in (Playwright) | Playwright microservice (OSS); anti-bot Cloud-only | Full managed | scrapy-playwright add-on |
| Markdown/main-content quality | trafilatura = best OSS extractor (0.841 held-out F1) [S3] | Very good (fit_markdown + filters) | Very good (core product) | Very good (same engine, managed) | Via pipeline glue |
| Arabic content | trafilatura multilingual; you control normalization | Works; no Arabic-specific tuning | Works | Works | Works via same pipeline |
| Resource footprint | Tiny (no browser unless fallback) | ~4GB RAM container guidance; browser per page | Heavy: API+worker+Redis+PG(+RabbitMQ) | Zero (their infra) | Low (no browser) |
| Maintenance burden | You own fetch/robots/backoff (~2-3 weeks build) | Library upgrades; pin versions; still own scheduling | You own their whole stack + AGPL compliance | Zero ops | Mature but glue-heavy |
| Incremental recrawl/diff | You build (conditional GET + hash - recommended anyway) | Partial (cache modes; no per-site scheduler) | No (Monitor is hosted-only) | **Monitor 1 credit/page/check** | You build |
| 1000-site economics | ~$100-300/mo infra | + browser fleet cost for JS pages | ~$200-500/mo infra + ops time | $749/mo at ~2.2M pages/mo | ~$100-300/mo infra |
| Fit verdict | **Recommended core** - 95% of small-business sites are JS-light | **Recommended fallback engine / alternative core** | Avoid for now (license + ops for marginal gain) | Good optional tier for hard/blocked sites | Only for spider-level maturity; over-engineered here |

Also-rans: Crawlee (TS stack mismatch), ScrapegraphAI (LLM-token cost for bulk), Jina Reader (great ad-hoc URL->markdown fallback; token economics do not fit 1000-site sync), Browserbase/ScrapingBee/Scrapfly (proxy/anti-bot products - you crawl customers' own sites, which rarely fight back), Exa/Tavily/Brave (search APIs, not site crawlers; Exa Contents $1/1k is a reasonable page-fetch utility but you still own discovery/scheduling).

## 4. Recommended stack and reasoning

**Tier 1 - Fetch and extract (workers):**
1. **httpx async fetcher** with: per-domain token bucket (Redis), robots.txt cache + compliance, conditional GET state machine (ETag/Last-Modified stored verbatim), 429/Retry-After backoff ladder, 8s connect/25s read timeouts, byte cap. HTTP-only fetching is 2-7x faster and far cheaper than browser fetching on JS-light sites [S14].
2. **trafilatura** for main-content extraction -> markdown + metadata; store extraction_version so old pages can be re-processed without re-fetching. If a page proves JS-dependent (empty-content heuristic), route to a small **Playwright-render fallback pool** - simplest form: Crawl4AI used only for flagged pages, keeping browser footprint off the hot path.
3. Pipeline events to **Kafka**: pages.fetched {tenant_id, site_id, page_id, content_hash, changed}.

**Tier 2 - Ingestion (consumers):** heading-aware chunker (H2/H3 -> paragraph -> sentence), 400-600 token target, ~10% overlap, breadcrumb "title > section > sub" prepended, tables kept whole; chunks keyed (page_id, chunk_path) for stable upserts. Dedup: URL normalization pre-fetch -> canonical check -> SHA-256(text) exact skip -> SimHash(64) column, Hamming <=3 flag [S20]. Embedder: **multilingual-e5-large or BGE-M3** (1024-d; record embedding_model_version per chunk) [S30]; chunks + vectors to pgvector (HNSW).

**Tier 3 - Scheduling (Postgres + Redis):** site_crawl_config(tenant_id, enabled, interval_seconds default 3600, max_pages, scope) + crawl_schedule(site_id, next_run_at, jittered, priority, state, consecutive_failures, backoff_until); scheduler tick pushes due jobs to Redis ZSET; workers ZPOPMIN with per-tenant in-flight counter for fairness; stale-first tiebreak. Per-site circuit breaker after N failed runs -> daily cadence + tenant-visible degraded status. **Adaptive freshness inside the tenant's interval:** every hourly tick does cheap conditional GETs; only changed pages (200 with new hash) flow to extraction/embedding; for pages unchanged K consecutive ticks, lengthen re-extract interval (1h->6h->24h cap) while keeping the check cheap - grounded in change-frequency data [S16][S17].

**Tier 4 - API surface (FastAPI):** preview-crawl-scope endpoint (fetch robots + sitemap, shallow breadth scan depth<=2, <=50 links, show count + list before committing); tenant controls (enable/disable, interval, max pages, include/exclude path globs); page list with per-page status (fresh/stale/failed/blocked).

**Tier 5 - Escape hatch (optional, paid):** keep a **Firecrawl Standard ($99/mo, 100k credits ~= $0.99/1k pages)** or **Crawl4AI Cloud** key for the minority of sites that block you or need heavy JS; route flagged sites there via the same job interface. ~95% of volume stays on the cheap path. Do **not** adopt self-hosted Firecrawl as the core: AGPL + a five-service stack, for a workload that does not need its anti-bot machinery.

**Why not Crawl4AI-as-core?** A defensible runner-up - Apache-2.0, RAG-native, maintained. Tie-breakers: (a) sites are JS-light, and Playwright-per-page multiplies RAM/CPU at 1000 domains; (b) per-domain politeness + conditional-GET state machines are custom work on top of any library anyway; (c) trafilatura has the best measured quality on the non-article page types that dominate small-business sites [S3]. If the team prefers fewer moving parts over maximum control, Crawl4AI in library mode inside the worker is the second recommendation.
## 5. Sources

| # | Title | URL | Relevance / date |
|---|---|---|---|
| S1 | Crawl4AI GitHub repo (87.2k stars, Apache-2.0, v0.9.5) | https://github.com/unclecode/crawl4ai | License, features, Docker, cloud; fetched 2026-11-11 |
| S2 | Firecrawl GitHub + self-host license issue #1964 | https://github.com/firecrawl/firecrawl ; https://github.com/firecrawl/firecrawl/issues/1964 | AGPL-3.0 engine / MIT SDKs; OSS limits; Aug-Sep 2025 |
| S3 | WCXB leaderboard; trafilatura evaluation; Hydrafetch benchmark | https://webcontentextraction.org/ ; https://trafilatura.readthedocs.io/en/latest/evaluation.html ; https://github.com/Hydrafetch/extraction-benchmark | Extractor F1 by page type; 2026 |
| S4 | Crawl4AI docs (markdown generation, LLM strategies, Docker API, v0.5.0 notes) | https://docs.crawl4ai.com/core/markdown-generation/ | fit_markdown, REST endpoints, robots compliance; 2025 |
| S5 | Scrapy docs + opensourcedex stats | https://docs.scrapy.org/en/latest/topics/benchmarking.html ; https://opensourcedex.com/compare/scrapy-vs-crawlee | ~3.8k pages/min; 65k stars; 2026 |
| S6 | Crawlee GitHub/docs | https://github.com/apify/crawlee | Apache-2.0, AutoscaledPool; v3.18.1 Aug 2026 |
| S7 | Jina Reader API/pricing docs; ReaderLM-v2 | https://jina.ai/reader ; https://docs.jina.ai/api.md ; https://huggingface.co/jinaai/ReaderLM-v2 | 500 RPM free / 5k premium; 10M free tokens; 2025-2026 |
| S8 | Firecrawl pricing + billing + rate limits | https://www.firecrawl.dev/pricing ; https://docs.firecrawl.dev/billing ; https://docs.firecrawl.dev/rate-limits | 1 credit/page; Monitor 1/page/check; effective 2026-09-04 |
| S9 | Firecrawl per-1k math + self-host checklist | https://www.proxy-compare.com/vendors/firecrawl ; https://firecrawl.space/self-host-firecrawl | $0.75-3.80 per 1k by tier; AGPL checkpoint; Sep 2026 |
| S10 | Tavily credits and pricing | https://docs.tavily.com/documentation/api-credits ; https://help.tavily.com/articles/8298987937 | 1k free/mo; extract 1cr/5 URLs; 2025-2026 |
| S11 | Exa pricing + changelog + contents docs | https://exa.ai/pricing ; https://exa.ai/docs/changelog/pricing-update ; https://exa.ai/docs/reference/get-contents | Contents $1/1k pages/type; Monitors $2/1k; Mar 2026 |
| S12 | OSS crawler surveys (licenses/stars) | https://thunderbit.com/blog/best-open-source-web-scraper-tools ; https://webcrawlerapi.com/blog/best-open-source-web-crawlers ; https://thegeocommunity.com/blogs/generative-engine-optimization/top-10-open-source-web-scrapers-github-stars | Star counts + license nuances; 2026 |
| S13 | FetchIndex cost calculator + ScrapingBee vendor page | https://fetchindex.com/calculator ; https://fetchindex.com/vendors/scrapingbee | Cross-checked per-1k prices incl. Crawl4AI Cloud $10 tier; 2026-11-04 |
| S14 | llm-crawler-benchmarks (pipeline timing, cost at scale) | https://github.com/AIMLPM/llm-crawler-benchmarks | HTTP-only 2-7x faster; cost deltas; 2025-2026 |
| S15 | Thunderbit trafilatura vs Readability fixture study | https://thunderbit.com/zh-Hant/blog/trafilatura | Boilerplate leakage 1/17 vs 5/17; May 2026 |
| S16 | Ntoulas WWW2004; Cho/Garcia-Molina; Adar WSDM09 | https://snap.stanford.edu/class/cs224w-readings/ntoulas04evolution.pdf ; https://cgi.di.uoa.gr/~ad/MDE519.docs/cho2.pdf ; https://turing.cs.washington.edu/papers/wsdm09-adar.pdf | ~15% changed weekly; heavy-tailed change; 2004-2009 |
| S17 | Microsoft Optimal-Freshness-Crawl-Scheduling (SIGIR/NeurIPS 2019) | https://microsoft.github.io/Optimal-Freshness-Crawl-Scheduling ; https://www.microsoft.com/en-us/research/wp-content/uploads/2019/05/SIGIR__Optimal_Freshness_Crawl_Under_Politeness_Constraints.pdf | 18.5M/26.6M changed in 14wks; sitemap lastmod usable ~4% |
| S18 | Brave API pricing; Diffbot pricing; Browserbase pricing | https://api-dashboard.search.brave.com/documentation/pricing ; https://www.diffbot.com/pricing ; https://browserbase.com/pricing | $5/1k search; $299/250k credits; browser-hour economics; Nov 2026 |
| S19 | ScrapingBee / Scrapfly pricing breakdowns | https://www.scrapingbee.com/pricing ; https://scrapingapiprices.com/scrapingbee-pricing ; https://scrapingapiprices.com/scrapfly-pricing | 1/5/25-credit multipliers; ~$1/1k JS pages; Oct-Nov 2026 |
| S20 | Dedup guides + Manku et al. WWW2007 | https://clawengine.ai/blog/deduplicate-pages-crawl-rag-ingestion ; https://link.sc/blog/deduplicate-pages-when-crawling ; https://www.firecrawl.dev/glossary/web-crawling-apis/deduplicate-crawl-pages-rag ; https://research.google.com/pubs/archive/33026.pdf | Layered dedup; simhash Hamming<=3; hash text not HTML |
| S21 | AWS ethical-crawler guidance; Common Crawl FAQ | https://docs.aws.amazon.com/prescriptive-guidance/latest/web-crawling-system-esg-data/best-practices.html ; https://commoncrawl.org/faq | 1 req/10-15s small sites; crawl-delay; conditional GET |
| S22 | Polite scraping patterns (Wikimedia norms, robots spec) | https://lagindicator.com/dev-tools/polite-web-scraping-design-patterns/ | <10 concurrent/<20 rps; Google no crawl-delay; Aug 2026 |
| S23 | Google crawl-budget docs + SEJ on 304s | https://developers.google.com/crawling/docs/crawl-budget ; https://www.searchenginejournal.com/google-recommends-using-304-status-code-to-conserve-crawl-budget/584543 | Conditional GET norms; 2025-2026 |
| S24 | Conditional requests deep-dive | https://www.compliant-web-scraping.com/pipeline-storage-monitoring/incremental-crawling-and-change-detection/conditional-requests-with-etag-and-last-modified ; https://patrickstox.com/technical-seo/how-search-works/crawling/crawl-budget/conditional-requests/ | ETag verbatim; INM precedence; 304 != error; 2026 |
| S25 | LangChain Indexing API blog | https://blog.langchain.com/syncing-data-sources-to-vector-stores | record manager, cleanup modes, hash dedup; 2023 |
| S26 | LlamaIndex IngestionPipeline docs | https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline | doc_id->hash skip/reprocess/upsert; current |
| S27 | Chunking guides (Olostep, PacketToSniff, Airbyte, Azure) | https://www.olostep.com/blog/rag-chunking-strategies ; https://packettosniff.com/blog/chunking-strategies-for-rag ; https://airbyte.com/agentic-data/rag-document-chunking-best-practices ; https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-chunking-phase | Structure-aware baseline; 256-512 sweet spot; metadata schema; 2026 |
| S28 | Parent-document / overlap guidance | https://aquila.network/learn/rag-chunking-strategies ; https://changegamer.ai/articles/chunking-documents-for-rag ; https://www.markitdown.de/en/guides/rag-markdown-chunks-best-practices | small-to-big; overlap 10-15%; alignment-aware splitters; 2026 |
| S29 | Production RAG ingestion engineering | https://martinuke0.github.io/posts/2026-09-05-the-hardest-rag-ingestion-problems-and-how-engineers-actually-solve-them ; https://samuelochoa.com/expertise/rag/docs/ingestion-pipeline ; https://www.sharpbyte.dev/applied-ai/rag/ingestion-pipelines | CDC reindexing, content-addressable IDs, model versioning; 2026 |
| S30 | ArabicNLP 2025 cross-lingual RAG; Arabic RAG eval | https://aclanthology.org/2025.arabicnlp-main.6.pdf ; https://arxiv.org/html/2507.07543v2 ; https://aclanthology.org/2025.abjadnlp-1.16.pdf | BGE-M3/M-E5 same-lang 87-93% Hit@20 vs cross-lang 41-72%; 2025 |
| S31 | Bilingual Arabic-English RAG implementations | https://github.com/YousefZahran1/bilingual-rag ; https://github.com/Youssef57-T/arabic-rag-qa | multilingual-e5 + Arabic-aware BM25 normalization; 2026 |
| S32 | Temporal multi-tenant patterns + fairness | https://docs.temporal.io/best-practices/multi-tenant-patterns ; https://temporal.io/blog/task-queue-priority-and-fairness-your-task-queue-your-way | Single queue + fairness keys; 2026 |
| S33 | Job-queue comparisons + fairness ops | https://codenicelystudio.com/blog/businesses/saas/celery-vs-temporal-vs-bullmq-job-queue-comparison ; https://www.task-queues.com/queue-fundamentals-architecture/priority-queues-and-job-fairness/ | Celery/Redis task-loss caveat; starvation metrics; missed-run policy; 2026 |

## 6. Conflicting Information

- **Firecrawl GitHub stars:** 166,527 (thunderbit, Sep 2026) vs "177K+" (digitalapplied, Sep 2026) vs "180K+" (firecrawl.dev's own page). Directionally identical: enormous and active. Use "~170k+ as of late 2026."
- **Crawl4AI license tone:** GitHub badge Apache-2.0; README says attribution "recommended" but the Attribution section also says "you must include one of the following attribution methods"; third-party analysis says the LICENSE file appends a mandatory attribution condition for public use/distribution. Practically a badge/credit line satisfies it; have legal read the LICENSE file.
- **Firecrawl "MIT" claim:** one comparison article (cn-sec) states Firecrawl is MIT - wrong vs the repo itself (AGPL-3.0 core, MIT SDKs). Cite the repo.
- **Jina Reader free-tier RPM:** marketing page tiers partially parsed (200-500 RPM no-key/free-key, 5k premium); docs.jina.ai/api.md plainly states r.jina.ai 500 RPM free / 5,000 premium. Use the docs figure.
- **Sitemap lastmod reliability:** SEO folklore says "use sitemap lastmod for freshness"; Microsoft's Bing-scale study found it usable for only ~4% of URLs. Modern-CMS small-business sites are often better than that, but do not build correctness on it - verify against your own crawl data.
- **Change-frequency magnitude disagrees across studies** because of corpus bias: web-wide studies (Ntoulas 2004) show most pages static; Bing's extraction-targeted corpus shows 70% changing in 14 weeks. Expect the low-churn end for small-business sites, but measure per-site.

## 7. Confidence Notes

- High: Crawl4AI license/stars/version (fetched live 2026-11-11); Firecrawl credit model and plan pricing (vendor docs, effective 2026-09-04); Tavily/Exa/Brave/ScrapingBee/Scrapfly/Browserbase/Diffbot pricing (vendor pages, Oct-Nov 2026); trafilatura extraction lead (independent benchmarks); conditional-GET semantics (RFC-aligned practitioner + Google docs); dedup thresholds (Google WWW2007 paper).
- Medium: hosted-vs-self-host cost model for your workload (depends on real change rates and page counts - measure in a pilot); Crawl4AI Cloud plan pricing (seen only via third-party calculator; verify at crawl4ai.com/docs).
- Lower / verify before relying: ReaderLM-v2 self-host license terms (not confirmed in this pass); the legal perimeter of AGPL Firecrawl as an internal microservice (issue #1964 has no maintainer ruling) - moot if you skip Firecrawl self-host.
- Postgres SKIP LOCKED claiming and Redis-ZSET due-queue patterns are standard engineering practice cited across ops sources [S33]; treat as established craft knowledge rather than single-sourced fact.

## 8. Open Questions

1. **Real page counts per tenant site** - the cost model swings on 10 vs 200 pages/site and observed change rate; run a 2-week pilot on ~20 real tenant sites before fixing the adaptive-interval ladder.
2. **Do target markets host on platforms that block datacenter IPs?** (Wix/Squarespace/WordPress.com generally do not; some Cloudflare-fronted sites 403 datacenter UAs.) If the 403 rate is material, that is the trigger to buy the Firecrawl/Crawl4AI Cloud escape hatch rather than build proxy plumbing.
3. **Embedding dimension lock-in** - pgvector index choice (1024-d e5/BGE-M3 vs 768-d vs 1536-d) affects storage cost at 1000 sites; decide with existing pgvector usage before the first big ingest.
4. **Per-tenant hourly interval vs fairness at scale** - if many tenants later pick 15-minute intervals, the stale-first ZSET design still holds but per-domain buckets need monitoring; define the starvation SLO now (e.g., "no site check delayed >2x its interval at p95").
