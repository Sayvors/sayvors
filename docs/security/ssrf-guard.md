# SSRF Guard

Server-Side Request Forgery (SSRF) protection for all tenant-supplied URLs.

## Overview

Any URL a tenant can influence must pass through `assert_public_http_url()` + `fetch_pinned()` / `fetch_pinned_status()` / `fetch_pinned_bytes()` in `app/core/pinned_http.py`. Raw `httpx`/`urllib`/`requests` fetches of tenant URLs are forbidden.

## Guard functions

| Function | Returns | Use case |
|----------|---------|----------|
| `assert_public_http_url(url)` | validated URL string | URL validation only |
| `fetch_pinned(url)` | decoded text | Crawlable pages (text/html, xhtml, text/plain) |
| `fetch_pinned_status(url)` | HTTP status code | Reachability checks (HEAD, no body) |
| `fetch_pinned_bytes(url)` | raw bytes | Image/media downloads (with size cap) |

## What the guard validates

1. **Scheme**: Must be `http` or `https`
2. **No credentials**: URL cannot contain username/password
3. **Host resolution**: Must resolve to globally routable IP (no private/rfc1918/loopback/link-local)
4. **DNS pinning**: Resolves ONCE, dials the pinned IP (no DNS rebinding TOCTOU)
5. **Per-hop redirect validation**: Each redirect target re-validated and re-pinned
6. **Max 3 redirect hops**
7. **Size cap**: 8MB for bytes, 1MB for text
8. **No status code echoing**: Generic error messages only

## Fixed vulnerabilities

### SEC-H1 — SSRF in media publishing (Fixed: cda3963)

**Location:** `app/modules/channels/meta/router.py` — `_assert_media_fetchable()`

**Issue:** The IG/FB publish probe fetched tenant-supplied URLs with raw `httpx.AsyncClient`, `follow_redirects=True`, and no SSRF guard. Upstream status codes and URLs were echoed in error responses.

**Fix:** Replaced raw httpx with `assert_public_http_url` + `fetch_pinned_status` (DNS pinning, per-hop redirect validation). Status codes no longer echoed. Called from Instagram publish (`:1600`) and Facebook publish (`:2133`).

### SEC-M5 — Reviewer-photo download SSRF (Fixed: 1a92076)

**Location:** `app/modules/analytics/review_media.py` — `_download()`

**Issue:** `_download()` called `assert_public_http_url` + `fetch_pinned_status` (reachability check) but then fetched actual bytes via `httpx.AsyncClient.get(follow_redirects=True)` — no DNS pinning, no per-hop redirect validation. A DNS rebinding or redirect could smuggle a private target through the public start URL.

**Fix:** Replaced unpinned `httpx.get()` with `fetch_pinned_bytes()` (DNS pinning + per-hop redirect validation + size cap). Removed unused `httpx` import.

## Rules

1. **Never fetch user-supplied URLs with raw httpx/urllib/requests.** Every URL a tenant can influence must pass through `assert_public_http_url()` + `fetch_pinned()` / `fetch_pinned_status()` / `fetch_pinned_bytes()`.

2. **Never echo upstream status codes, URLs, or headers in HTTP responses.** Generic messages only.

3. **Async context: run the pinned fetch in a thread pool.** `fetch_pinned*()` is sync (httpcore). Call via `asyncio.to_thread()` inside async route handlers.

4. **Validate before external services see it.** The preflight runs before `adapter.create_media_container` / `publish_photo`.

## Test coverage

- `tests/test_pinned_http.py` — 34 tests (DNS pinning, redirect validation, size caps)
- `tests/test_fetch_guard.py` — 42 tests (SSRF guard unit tests)
- `tests/test_review_media_and_removal.py` — 20 tests (review media download + removal)