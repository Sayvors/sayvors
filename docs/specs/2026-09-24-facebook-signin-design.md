# Facebook Sign-In Design ("Continue with Facebook")

Date: 2026-09-24. Mirrors the Google Sign-In design
(`docs/specs/2026-09-24-google-signin-design.md`) with stricter UX requirements.

## Goal

One-click user authentication with Facebook on `/login` and `/signup`,
indistinguishable in behavior from "Continue with Google", but with no silent
failures: every loading / blocked / error state is visible to the user.

## Decisions (approved)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Same identity semantics as Google (link-and-sign-in) | Consistency; user approved "yes like google" |
| 2 | Approach: client FB SDK + server token verify (`POST /auth/facebook/verify`) | Same shape as GIS flow; tokens never stored |
| 3 | Minimal scope: `email` only (`public_profile` is implicit) | Least privilege; avatar via `picture` field |
| 4 | Facebook-only users get a random unusable `password_hash` | Same as Google-only users; no password, no forgot-pw |
| 5 | New social signups land on `/onboarding` | Decision 4A carried over |
| 6 | Welcome email on every new social signup, incl. retrofitting Google | User choice A; email already verified by the IdP, send immediately |
| 7 | Custom button (own style + local logo), `FB.login` on click | Matches form aesthetics; reuses `MetaConnections.tsx` SDK pattern |
| 8 | Delete the GitHub "coming soon" stub | User request; Facebook replaces it |

## Identity rules

- `users.facebook_id` (String, unique, nullable, indexed) identifies the login.
- Lookup order: `facebook_id` → verified email match (link) → create.
- Linking adopts Facebook only if `facebook_id` is unset; never overwrites another link.
- Profile snapshot on every sign-in: first/last name (split on first space,
  fallback to email local-part), `avatar_url` from `picture.data.url` (if present).
- `email_verified=true` on creation (Meta verified the address).
- Signup event metadata: `{"via": "facebook"}`; login event likewise.
- `facebook_login()` reuses the shared `_issue_session()` (same cookies, refresh
  row, Redis session, events as password + Google login).

## Backend

- Migration: add `users.facebook_id` (unique index). No other schema change
  (`avatar_url` reused).
- `security.py::verify_facebook_token(access_token) -> dict`:
  1. `GET graph.facebook.com/debug_token?input_token=...&access_token={app_id}|{app_secret}`
     (app token, never the user token). Require `data.is_valid is True` and
     `data.app_id == <login app id>` → else `ValueError("invalid_token")`.
  2. `GET /me?fields=id,name,email,picture.type(large)` with the user token.
     Missing `id`/`email` → `ValueError("unverified_email")`
     (Facebook emails are verified, but users can hide them).
  3. Network/Graph errors → `ValueError("invalid_token")` (log cause server-side).
- `auth/service.py::facebook_login(profile, db, user_agent, ip)`:
  find-or-create per identity rules; `_issue_session(..., metadata={"via": "facebook"})`;
  on `event == "signup"`, fire-and-forget `send_welcome_email` (never fail signup).
- `auth/router.py::POST /auth/google/verify`-shaped endpoint
  `POST /auth/facebook/verify {access_token: str(min 10)}`:
  rate-limit `facebook:{ip}` 30/60 → 429; missing login app id → 503;
  `invalid_token` → 401 "Facebook sign-in failed";
  `unverified_email` → 400 "No verified email on this Facebook account."
  Refresh token leaves via httpOnly cookie only (never in JSON body).
- `main.py` CSRF exempt list += `/api/v1/auth/facebook/verify` (pre-session endpoint).
- Config: `META_LOGIN_APP_ID`, `META_LOGIN_APP_SECRET` (both default `""`);
  helper `login_app_id` / `login_app_secret` fall back to `META_APP_ID` / `META_APP_SECRET`
  when empty. Same values for now; split later by changing env only.

## Frontend

- `AuthForm.tsx`: delete GitHub stub; add Facebook button in the same visual
  style (own markup + new `public/facebook.svg` "f" logo, full-width, h-11).
- `auth-context.tsx`: `facebookLogin(accessToken): Promise<User>` mirroring
  `googleLogin` (POST `/api/v1/auth/facebook/verify`, set token + user, return user).
- SDK loader (mirrors `MetaConnections.tsx`): inject the same-origin proxy
  `${API_URL}/api/v1/meta/connect-sdk` (established ad-blocker mitigation in
  `channels/meta/router.py`, already allowed by CSP `script-src`), then
  `FB.init({appId: NEXT_PUBLIC_META_LOGIN_APP_ID, version: "v26.0", xfbml: false, cookie: false})`
  (same Graph version default as the channel code).
- Click: `FB.login(cb, {scope: "email", auth_type: "rerequest"})` synchronously in
  the gesture (popup-blocker safe); on `authResponse.accessToken` → `facebookLogin`
  → redirect by `onboarded`.

### UX state matrix (the "better UX" requirement — no silent states)

| State | UI |
|-------|----|
| No `NEXT_PUBLIC_META_LOGIN_APP_ID` | Button hidden entirely (same as Google) |
| SDK loading | Disabled skeleton button with spinner, same dimensions (no layout shift) |
| SDK blocked/failed (ad-blocker, tracking protection, offline) | Button replaced by an inline warning: "Facebook couldn't load — check your ad-blocker, or continue with password." Password form unaffected |
| Popup closed/cancelled by user | Transient note: "Facebook sign-in cancelled." No error styling |
| Declined `email` permission / no email on account | Note: "We need your email to create your account. Please allow email access and try again." |
| Backend 401/400/503 | Note with the server message, same slot as Google failures |
| Success, new account | → `/onboarding`; welcome email sent |
| Success, existing/linked | → `/dashboard` |

## Email

- `send_welcome_email` (existing template) on Facebook signup, fire-and-forget.
- Retrofit: same call on Google signup in `google_login()` (currently sends nothing).
- Both depend on Resend config; failures warn-logged only (existing behavior).

## CSP / headers

- No change needed: the SDK loads same-origin (API host already in `script-src`);
  `frame-src` already covers `facebook.com`; `connect-src` already covers
  `graph.facebook.com`. Verified via live headers in the plan.
- COOP stays `same-origin-allow-popups` (already fixed for Google popup).

## Testing

- Backend (mock Graph, no network): verify helper (valid / wrong-app-id /
  invalid / missing-email / network-error), service (create / link / snapshot
  refresh / welcome-email fired once on signup only), endpoint
  (200 shape incl. no refresh in body / 401 / 400 / 503). TDD: red before green.
- Full suite must show only the 4 known pre-existing failures. `tsc --noEmit` clean.
- Manual (Meta app in Dev mode → listed test user): login click → consent →
  `/onboarding` + welcome email received; second click → `/dashboard`; password
  account + same email → links; ad-blocker on → warning state visible;
  no app id → button hidden.
- App Review note: `email` permission needs review (or Live mode + Business
  verification) before the general public can use it; Dev mode is test-users only.

## Out of scope

- Facebook channel/Pages connections (existing `MetaConnections.tsx` untouched).
- OAuth redirect/code flow (rejected approach #2).
- Changing password-login enumeration behavior (generic error stays).
