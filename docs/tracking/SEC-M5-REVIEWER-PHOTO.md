# SEC-M5 — Reviewer-Photo Download SSRF Fix

## Overview

Reviewer-photo download endpoint was vulnerable to Server-Side Request Forgery (SSRF). An attacker could supply a URL pointing to internal services (e.g., `http://169.254.169.254/metadata`) and the server would fetch and return the response.

## Fix

Added `fetch_pinned()` guard to the reviewer-photo download path. All external HTTP fetches must go through `assert_public_http_url()` which validates:

1. **Scheme**: Must be `http` or `https`
2. **Host**: Must resolve to a public IP (no private/rfc1918/loopback/link-local)
3. **No credentials**: URL cannot contain username/password
4. **No internal hosts**: Blocks `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, `10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`, `169.254.x.x`

## Files

| File | Change |
|------|--------|
| `app/core/pinned_http.py` | `fetch_pinned_status()` added; `_assert_media_fetchable()` rewritten with SSRF guard |
| `app/modules/channels/meta/consumer.py` | Reviewer-photo download uses `fetch_pinned` guard |

## Related

- **SEC-H1** (`docs/tracking/SEC-H1-SSRF-STRATEGY.md`): Same fix applied to media publishing status fetch
- **G2** (`docs/tracking/G2-STRATEGY.md`): Access token moved to httpOnly cookie

## Status

✅ Done — `fetch_pinned_status()` added; `_assert_media_fetchable()` rewritten; no upstream status leakage.
