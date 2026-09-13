# Meta Integration — OAuth / Connection Flow

Never trust `tenant_id` from a callback parameter. The backend binds every
OAuth transaction to the authenticated tenant with a server-side row.

## Flow (all providers)

1. Tenant clicks **Connect** → frontend calls
   `POST /api/v1/meta/{provider}/connect` (authed).
2. Backend creates a `meta_oauth_transactions` row:
   `state = secrets.token_urlsafe(32)` (sha256 hash stored), tenant-bound,
   `expires_at = now + 10 min`, status `pending`.
3. Backend returns the provider entry point:
   - **WhatsApp:** Embedded Signup v4 `config_id` (+ app id, Graph version);
     frontend runs `FB.login(cb, {config_id, response_type:'code',
     override_default_response_type:true, extras:{setup:{}}})`.
     Do NOT send legacy `action` — v4 moved products/permissions into the
     Builder configuration (v2 deprecated Oct 15, 2026).
   - **Facebook/Instagram:** Login for Business dialog URL built from the
     dashboard configuration id (no `scope` param — deprecated for this flow).
4. Meta redirects to `GET /api/v1/meta/{provider}/callback?code=&state=`
   (WhatsApp JS flow posts the auth code + session payload instead).
5. Backend: hash lookup → must exist, `pending`, unexpired, single-use
   (status → `completed`/`failed` atomically) → tenant from the row.
6. Exchange code for credentials (business/system-user token), encrypt,
   persist `meta_connections` row → discover assets →
   `GET .../assets` → tenant selects → `POST .../assets/select` persists
   `meta_assets` (+ `Channel` rows for messaging assets).

## Security properties

- Cryptographically random state, hash-stored, 10-min expiry, one-time use.
- Tenant binding from the authenticated session, never from callback params.
- Redirect targets validated against relative-path allowlist (same rule as
  Google OAuth `next`).
- Failures redirect to the Channels hub with `?meta_error=<code>` (same UX
  pattern as `?google_error=`).

## Local development

- Set `META_OAUTH_REDIRECT_URI` to the public tunnel URL (Meta requires
  HTTPS, no self-signed); domain must be in the app's Allowed domains +
  Valid OAuth redirect URIs.
- Test users/numbers work before App Review; external businesses need
  Advanced access (see `whatsapp.md`).
