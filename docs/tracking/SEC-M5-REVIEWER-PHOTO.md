# SEC-M5 — Reviewer-Photo Download SSRF Fix

## Overview

Reviewer-photo download endpoint was vulnerable to Server-Side Request Forgery (SSRF). An attacker could supply a URL pointing to internal services (e.g., `http://169.254.169.254/metadata`) and the server would fetch and return the response.

## Fix

Added `fetch_pinned_bytes()` guard to the reviewer-photo download path. All external HTTP fetches must go through `assert_public_http_url()` which validates:

1. **Scheme**: Must be `http` or `https`
2. **Host**: Must resolve to a public IP (no private/rfc1918/loopback/link-local)
3. **No credentials**: URL cannot contain username/password
4. **No internal hosts**: Blocks `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, `10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`, `169.254.x.x`
5. **DNS pinning**: Resolves ONCE, dials the pinned IP (no DNS rebinding TOCTOU)
6. **Per-hop redirect validation**: Each redirect target re-validated and re-pinned
7. **Size cap**: Max 8MB, streamed with early abort
8. **No status code echoing**: Generic error messages only

### What changed

**Before (vulnerable):**
- `_download()` called `assert_public_http_url` + `fetch_pinned_status` (reachability check)
- Then fetched actual bytes via `httpx.AsyncClient.get(follow_redirects=True)` — **no DNS pinning, no per-hop redirect validation**
- DNS rebinding or redirect could smuggle a private target through the public start URL

**After (fixed):**
- `_download()` calls `assert_public_http_url` + `fetch_pinned_status` (reachability check)
- Then fetches bytes via `fetch_pinned_bytes()` (DNS pinning + per-hop redirect validation + size cap)
- Removed unused `httpx` import

## Files

| File | Change |
|------|--------|
| `app/core/pinned_http.py` | `fetch_pinned_bytes()` added — binary variant of `fetch_pinned` for image/media downloads |
| `app/modules/analytics/review_media.py` | `_download()` uses `fetch_pinned_bytes()` instead of unpinned `httpx.AsyncClient.get()`; removed `httpx` import |

## Related

- **SEC-H1** (`docs/tracking/SEC-H1-SSRF-STRATEGY.md`): Same fix applied to media publishing status fetch
- **G2** (`docs/tracking/G2-STRATEGY.md`): Access token moved to httpOnly cookie

## Tests

- `tests/test_pinned_http.py` — 34 tests (DNS pinning, redirect validation, size caps)
- `tests/test_fetch_guard.py` — 42 tests (SSRF guard unit tests)
- `tests/test_review_media_and_removal.py` — 20 tests (review media download + removal)

## Status

✅ Done — `fetch_pinned_bytes()` added; `_download()` uses pinned fetch; no DNS rebinding or redirect-based SSRF. No upstream status leakage.