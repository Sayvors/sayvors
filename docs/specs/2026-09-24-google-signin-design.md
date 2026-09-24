# Google Sign-In (Sign up / Sign in / Link) — Design

**Date:** 2026-09-24
**Status:** Approved
**Approach:** Google Identity Services (GIS) ID-token flow — backend verify endpoint

## Goal

Let users sign up, register, and sign in with Google, alongside the existing
email/password flow, while storing all identity data in Sayvors' own database.
Google is consulted only at the moment of sign-in; no Google-side storage is
read or depended on afterward.

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Google email matches existing password account | **Link & sign in** — one account, both methods |
| 2 | Consent screen scope | **Minimal** — `email` + `profile` only; Google tokens discarded after verify; profile snapshot stored locally |
| 3 | Can Google users also use a password? | **No** — Google-only; no password ever; "Forgot password?" not applicable |
| 4 | Where new Google signups land | **Straight into `/onboarding`** — no extra pre-signup form; `email_verified=true`, plan `free` |
| — | Architecture | **GIS button + `POST /auth/google/verify`** — no redirect/callback/state plumbing |

## Non-goals

- No GBP/business scopes at sign-in (channel connect flow stays as-is).
- No "set a password later" for Google users.
- No multi-provider support (Apple etc.) — design keeps `google_sub` generic
  enough (`auth via sub`) but only Google ships.
- No changes to the existing GBP channel OAuth (`channels/google_reviews.py`,
  signed state in `channels/router.py`).

## 1. Data model

Migration (new Alembic revision, down_revision = current head):

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `users.google_sub` | `String(64)` | nullable, **unique index** | Google's stable subject id; non-NULL ⇒ account authenticates via Google |
| `users.avatar_url` | `String(500)` | nullable | Google profile picture URL (snapshot) |

- Google-only users receive a **random, unusable `password_hash`**
  (`hash_password(secrets.token_urlsafe(32))`) so the existing NOT NULL
  constraint holds and password login can never succeed for them.
- Email, first/last name, plan, credits, `onboarded`, `email_verified` reuse
  existing columns.
- No new tables.

## 2. Backend

New endpoint: `POST /api/v1/auth/google/verify`

Request: `{ "id_token": "<GIS credential>" }`

Flow:

1. **Rate limit** by client IP — same pattern as login:
   `rate_limit(f"google:{ip}", 30, 60)` (30 attempts / minute / IP).
2. **Config gate:** `settings.GOOGLE_CLIENT_ID` empty ⇒ `503` with wording
   consistent with the GBP flow ("Google Sign-In not configured. Set
   GOOGLE_CLIENT_ID in .env").
3. **Verify the ID token — never trust the payload alone:**
   `google.oauth2.id_token.verify_oauth2_token(token, Request(), audience=settings.GOOGLE_CLIENT_ID)`
   - validates signature against Google's certs, `aud`, `exp`
   - rejects with **401** if signature/aud/exp fail; **400** if the token is
     well-formed but `email_verified` is not true or `sub`/`email` is missing
   - `google-auth` is available transitively via `google-genai`; pin it as a
     direct dependency if import is unstable.
4. **Find-or-create** (single transaction):
   - by `google_sub` → returning user: refresh `first_name`/`last_name`/
     `avatar_url` from the token, sign in.
   - else by email (case-insensitive) → **link**: set `google_sub` +
     `avatar_url` on the existing row, sign in (Decision 1).
   - else → **create**: email, name parsed from the token's `name` (split on
     the first space; if no space → `first_name` = full name, `last_name` =
     `""`), random
     unusable `password_hash`, `email_verified=True`, `onboarded=False`,
     `google_sub`, `avatar_url`, plan `free`, `ai_credit_cents=0`.
   - On `IntegrityError` (concurrent signup race): rollback, re-select by
     `google_sub`/email, sign in.
5. **Session issuance = password-login path, identical:**
   `create_access_token` + `create_refresh_token` + `store_session`, same
   refresh-cookie/response shape as `login`.
6. **Events:** `log_signup` / `log_login` with `metadata={"via": "google"}`
   (extend callers; `log_auth_event` already accepts metadata).
   Forgot/reset flows untouched — Google users have no password to reset.

Google's tokens are **not stored** (Decision 2).

## 3. Frontend (`apps/web`)

- Load `https://accounts.google.com/gsi/client` on `(auth)` pages only
  (login + signup). Script fails to load → button hidden, password flow
  unaffected.
- `GoogleSignInButton` component: official GIS button (Google branding) placed
  under/beside the existing divider on **login and signup** forms; renders
  nothing until GIS is ready.
- `auth-context` gains `googleLogin(idToken: string)` next to
  `login`/`signup`: `POST /api/v1/auth/google/verify`, then **identical**
  token/session handling and redirect logic as password login
  (`onboarded=false` → `/onboarding`, Decision 4).
- Errors: 401/400 → inline "Google sign-in failed. Try again or use your
  password."; 503 → button hidden with the same fallback.

## 4. Security

- Signature + audience + expiry verification on every token.
- Unique `google_sub` and unique email; race handled by retry-select.
- Linking only when Google reports the email verified and it matches the
  existing account (case-insensitive).
- Rate-limited verify endpoint; CSRF middleware unchanged (endpoint is a
  normal JSON POST through existing middleware).
- No `client_secret` used by this flow (GBP-only).

## 5. Error matrix

| Condition | Response |
|-----------|----------|
| Missing/invalid/expired/wrong-audience token | 401 "Google sign-in failed" |
| `email_verified` false or missing sub/email | 400 |
| `GOOGLE_CLIENT_ID` unset | 503 (config wording) |
| Rate limited | 429 |
| Concurrent-create race | retried internally → 200 |

## 6. Testing

No live Google calls; verifier is mocked (`patch` the verify helper).

- new-user signup via Google → 200/tokens, `google_sub` set, random password
  rejects at password login
- link-existing password account → same user id, `google_sub` now set
- repeat sign-in → same user, profile snapshot refreshed
- wrong audience / expired → 401
- unverified email → 400
- missing config → 503
- response shape matches password login (field-for-field)
- frontend: `npx tsc --noEmit`

## Operational prerequisites (Google Cloud console)

- Same project as the GBP OAuth app; `GOOGLE_CLIENT_ID` already in config.
- Enable **Google Identity Services**; add Authorized JavaScript origins:
  `https://staging.sayvors.com`, `http://localhost:3000` (+ prod origin later).
- Consent screen must include `email`/`profile` scopes (already implied).
