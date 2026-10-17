/*
 * Resolved API base for every browser-side fetch.
 *
 * Why this is not just `process.env.NEXT_PUBLIC_API_URL`: CSRF is a
 * double-submit cookie, and a cookie set by a *different origin* than the page
 * is not sent back on a cross-site fetch. The symptom was every POST failing
 * 403 "CSRF validation failed" while every GET worked, on a page whose
 * channels were all connected.
 *
 * The fix depends on the scheme, not on the hostname:
 *
 *   http  -> return "" so calls go to relative paths, which next.config.ts
 *            rewrites to the backend on the page's own origin. The cookie is
 *            then first-party and always sent. This is the only option that
 *            can work: SameSite=None requires Secure, and Secure cookies are
 *            refused over plain http, so a cross-origin call on http could
 *            never carry the token no matter how it is configured. Keying on
 *            "localhost" alone missed access from a LAN IP or any other http
 *            hostname, which is the same failure with a different name.
 *
 *   https -> use the configured absolute URL. Production deliberately runs the
 *            SPA and the API on different origins (api.staging.sayvors.com vs
 *            staging.sayvors.com) and carries CSRF across them with
 *            COOKIE_DOMAIN=.sayvors.com plus SameSite=None over TLS, which is
 *            valid there.
 */

function resolveApiBase(): string {
  // Runs in the browser only. On the server there is no page origin to be
  // relative to, so fall through to the configured value.
  if (typeof window !== "undefined") {
    if (window.location.protocol === "http:") {
      return "";
    }
    // https dev on tunnel URLs (dev-web.sayvors.com etc.): use same-origin
    // proxy so the httpOnly cookie set by the API (domain .sayvors.com) is
    // sent on every request. Only point at the absolute API URL when
    // NEXT_PUBLIC_API_URL is explicitly set (production or explicit tunnel).
    if (process.env.NEXT_PUBLIC_API_URL) {
      return process.env.NEXT_PUBLIC_API_URL;
    }
    return "";
  }
  // SSR / build time: use configured API URL or default localhost.
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

/**
 * "" means "same origin". Concatenate as `${API_BASE}${path}` — the paths all
 * already start with "/api".
 */
export const API_BASE = resolveApiBase();
