# Benchmark provider strategy

This document describes the production provider order for benchmark place
facts and reviews. It replaces the earlier "free Google stack only" default.

## Provider order

1. **Google Places (New)** is authoritative for place facts: name, address,
   rating, review count, coordinates, types, and a bounded review sample.
   It is used when `GOOGLE_PLACES_API_KEY` is configured.
2. **BOQ** supplies deep, recent review history from Google's public Maps
   endpoints. It is also the complete fallback when Places has no key or a
   Places call fails.
3. **Outscraper** remains an explicit paid alternative when configured.

`benchmark/provider.py` is the single seam. `benchmark/scraper.py` calls it for
every due place; compare read handlers keep BOQ cache-only and never page
reviews inside a request.

Deep reviews require the canonical Maps URL captured at save time. A row
without a `0x…:0x…` feature ID is skipped only when BOQ is the sole available
provider; official Places can still refresh its facts.

## Search

Search stays on `mapsearch`, Google's own `tbm=map` RPC, because it is the only
path that returns the canonical Maps URL/feature ID BOQ needs. Official Places
Text Search does not return that ID. Search is listings-only and never pages
reviews.

## Proxy routing (optional)

`GOOGLE_SCRAPER_PROXIES` is optional and comma-separated:

- **No proxies configured:** requests go direct, exactly as before.
- **Proxies configured:** one route is chosen stickily per place/query and kept
  for the whole BOQ paging sequence; a blocked route is rested for five
  minutes and never falls back to the server IP.
- Supported schemes: `http://`, `https://`, `socks5://`, `socks5h://`.

Use licensed residential/mobile proxies if blocking becomes frequent. Datacenter
IPs are usually blocked quickly. Proxies reduce blocks; they do not change
Google's terms or make an undocumented endpoint reliable.

## Full-history review rating (opt-in)

Admin `PUT /api/v1/admin/benchmark/config` controls:

- `review_history_mode`: `recent` (default, 30-day sample) or `full`.
- `max_reviews_per_place`: hard ceiling, 10–20,000 (default 2,000).
- `full_history_batch`: places per worker pass, 1–10 (default 1).

`boq.MAX_PAGES_FULL` allows the deeper paging but `MAX_REVIEWS_FULL = 20,000`
remains an absolute ceiling. One place per pass by default stops a 22k-review
listing from occupying the shared worker.

Theme analysis uses all cached reviews in full mode (up to the config ceiling),
but the LLM still sees only the first 50 reviews. Above that, the deterministic
local extractor owns counts and the analysis source is `local_full_history`, so
large samples are never sent to a model prompt.

## Production configuration

- Set `GOOGLE_PLACES_API_KEY` for authoritative facts and a stable 10-review
  sample.
- Set admin `source=google_places` (the migration default); with no key, the
  worker automatically falls back to BOQ.
- Set `refresh_hours`, `retention_days`, `max_saved_places`, and keep
  `place_cache_enabled=true`. Respect the collector capacity warning.
- Keep `GOOGLE_SCRAPER_PROXIES` empty until blocks are observed; then add a
  small licensed pool.
- Monitor `benchmark_places.last_scrape_error` and scrape pass counters.
- Re-save any legacy place without a canonical Maps URL before expecting deep
  BOQ reviews.
- Geo-grid rank remains a licensed purchase, not a BOQ/Places feature.

## Boundaries

- BOQ endpoints are undocumented and can change without notice; the parsers
  validate shape and fail closed rather than storing plausible wrong numbers.
- Proxying does not grant permission or remove ToS risk; that remains a
  product/legal decision.
- Deep review paging runs only in the bounded worker, never in a read handler.
