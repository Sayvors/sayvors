# G2 — Access Token in JSON Body (Strategy + Constraints)

## The vulnerability

`access_token` is returned in JSON response body on:
- `POST /api/v1/auth/signup` — `services/api/app/modules/auth/router.py:148-151`
- `POST /api/v1/auth/login` — `services/api/app/modules/auth/router.py:182`
- `POST /api/v1/auth/refresh` — `services/api/app/modules/auth/router.py:208`
- `POST /api/v1/auth/google/verify` — `services/api/app/modules/auth/router.py:342-345`
- `POST /api/v1/auth/facebook/verify` — `services/api/app/modules/auth/router.py:396-399`
- `POST /api/v1/auth/verify-otp` — `services/api/app/modules/auth/router.py:398`

An XSS vulnerability anywhere on the frontend can read `result.access_token` from the response JSON and exfiltrate it. The refresh token already travels as httpOnly cookie — access token should too.

## The fix (non-negotiable rules)

**Rule 1 — Access token travels as httpOnly cookie, not JSON body.**
Same transport as the refresh token: `httponly=True`, `secure=COOKIE_SECURE`, `samesite=COOKIE_SAMESITE`, `max_age=ACCESS_COOKIE_MAX_AGE` (15 min).

**Rule 2 — `get_current_user` reads from cookie OR Bearer header.**
Cookie first (SPA), Bearer fallback (mobile/API clients). Both paths enforce G1 blacklist + token_version checks.

**Rule 3 — Frontend stops reading `result.access_token` from JSON.**
The browser sends the httpOnly cookie automatically with `credentials: "include"`. The JS `_accessToken` variable and `Authorization: Bearer` header become unnecessary for the web app.

**Rule 4 — Tests updated: assert cookie is set, assert `access_token` NOT in JSON body.**

## Files to touch

| File | Change |
|------|--------|
| `services/api/app/config.py` | Add `ACCESS_COOKIE_NAME`, `ACCESS_COOKIE_MAX_AGE` |
| `services/api/app/core/deps.py` | `get_current_user` reads cookie first, Bearer fallback |
| `services/api/app/modules/auth/router.py` | `_set_session_cookies` accepts `access_token`; all 6 endpoints pop `access_token` from JSON and set as cookie |
| `apps/web/lib/auth-context.tsx` | Remove `setAccessToken()` calls, remove `Authorization: Bearer` from `buildHeaders`, update `refreshSession` |
| `tests/test_google_signin.py` | `test_google_signup_creates_user` line 58, `test_verify_endpoint_success` line 121 |
| `tests/test_facebook_signin.py` | `test_facebook_signup_creates_user` line 107, `test_fb_verify_endpoint_success` line 157 |
| `docs/tracking/G2-STRATEGY.md` | This document |

## Tests that need updating

| Test file | Line | Current assertion | New assertion |
|-----------|------|-------------------|---------------|
| `test_google_signin.py` | 58 | `"access_token" in result` | `"access_token" not in result` |
| `test_google_signin.py` | 121 | `"access_token" in data` | `"access_token" not in data` + cookie set |
| `test_facebook_signin.py` | 107 | `"access_token" in result` | `"access_token" not in result` |
| `test_facebook_signin.py` | 157 | `"access_token" in data` | `"access_token" not in data` + cookie set |

## Test clients in conftest

`conftest.py` overrides `get_current_user` with `_override_user` (bypasses auth entirely for most tests), so endpoint tests that hit real auth flows (`/api/v1/auth/login`, etc.) will exercise the cookie path. Cookie jar is shared across requests in TestClient, so subsequent requests automatically send the httpOnly cookie.
