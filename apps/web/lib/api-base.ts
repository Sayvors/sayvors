/*
 * Resolved API base for every browser-side fetch.
 *
 * Why this is not just `process.env.NEXT_PUBLIC_API_URL`: CSRF is a
 * double-submit cookie, and a cookie set by a *different origin* than the page
 * is never sent back on a cross-site fetch. With COOKIE_SAMESITE=lax — which
 * local dev needs, because the backend runs on plain http — the browser
 * silently drops it. The symptom was every POST failing 403 "CSRF validation
 * failed" while every GET worked, on a page whose channels were all connected.
 *
 * So on a localhost page origin we return "" and the calls go to relative
 * paths, which next.config.ts rewrites to the backend on the same origin. The
 * cookie is then first-party and is always sent. Everywhere else the
 * configured absolute URL is used unchanged, which is what production wants.
 */

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "0.0.0.0"]);

function resolveApiBase(): string {
  if (typeof window !== "undefined" && LOCAL_HOSTS.has(window.location.hostname)) {
    return "";
  }
  return process.env.NEXT_PUBLIC_API_URL || "";
}

/**
 * "" means "same origin". Concatenate as `${API_BASE}${path}` — the paths all
 * already start with "/api".
 */
export const API_BASE = resolveApiBase();
