# SEC-H1 — SSRF in Media Publishing (Strategy + Constraints)

## The vulnerability

`_assert_media_fetchable()` in `services/api/app/modules/channels/meta/router.py:1507`
fetches tenant-supplied image URLs with raw `httpx.AsyncClient`, `follow_redirects=True`,
and no SSRF guard. It:

- Fetches arbitrary URLs (including `http://127.0.0.1`, `http://169.254.169.254`,
  `http://internal-services`) — SSRF
- Follows redirects without validating the redirect target — open redirect chain to private IPs
- Echoes raw upstream status codes and full URLs in HTTP error details — information disclosure
- Is called from Instagram publish (`:1600`) and Facebook publish (`:2133`)

## The fix (non-negotiable rules)

**Rule 1 — Never fetch user-supplied URLs with raw httpx/urllib/requests.**
Every URL a tenant can influence must pass through `assert_public_http_url()` +
`fetch_pinned()` in `app/core/pinned_http.py`. That module already exists and is
the single source of truth for SSRF-safe fetching (DNS pinning, per-hop redirect
validation, size caps, content-type checks).

**Rule 2 — Never echo upstream status codes, URLs, or headers in HTTP responses.**
Generic messages only: "media URL could not be verified" or "media fetch failed".
Attackers use reflected status codes to probe internal network topology.

**Rule 3 — Async context: run the pinned fetch in a thread pool.**
`fetch_pinned()` is sync (httpcore). Call it via `asyncio.to_thread()` inside
async route handlers. Do NOT rewrite it as async — the sync httpcore pinning
logic is already audited and correct.

**Rule 4 — Validate before Meta sees it.**
The preflight runs before `adapter.create_media_container` / `publish_photo`.
If the URL fails validation, return 400/422, never 502 with Meta's message.

## Files touched

| File | Change |
|------|--------|
| `services/api/app/modules/channels/meta/router.py` | Replace `_assert_media_fetchable` body; import `fetch_pinned`, `UnsafeUrlError` from `....core.pinned_http`; wrap in `asyncio.to_thread` |
| `docs/tracking/SEC-H1-SSRF-STRATEGY.md` | This document |

## What `fetch_pinned` already provides (do not reimplement)

- Scheme must be http(s), no embedded credentials
- Host must resolve to globally routable IP (all addresses must be public — kills DNS rebinding round-robin)
- Each redirect hop re-validated and re-pinned
- Max 3 redirect hops
- Max 8 MB body
- Only crawlable content types (text/html, xhtml, text/plain) — images return non-HTML content-type, so `_read_text` raises; the fix only needs to confirm the URL is *reachable and public*, not read the body
- 10s connect / 20s read timeouts

## Test coverage needed

| Test | What it verifies |
|------|-----------------|
| `http://127.0.0.1/` image URL | Rejected (loopback) |
| `http://169.254.169.254/` image URL | Rejected (link-local metadata) |
| `http://internal.sayvors.com/` image URL | Rejected (private DNS) |
| Public URL that redirects to `http://127.0.0.1/` | Rejected (redirect hop not validated) |
| Public image URL (200, image/jpeg) | Accepted |
| Public URL returning 404 | Rejected (generic 502, no leaked status) |
| URL with `user:pass@host` embedded | Rejected (credentials) |
| `file:///etc/passwd` URL | Rejected (scheme) |

## Effort

~1 day (code + tests).
