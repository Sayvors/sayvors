"use client";

/*
 * Double-submit CSRF helpers, shared by every API client.
 *
 * The backend sets an unsigned `csrf_token` cookie at login/refresh and
 * requires it back in the `X-CSRF-Token` header on every write
 * (services/api/app/main.py). Four modules had their own copy of the cookie
 * parser, which is how they drifted; this is the only one now.
 *
 * The cookie is minted as a side effect of auth, so it can legitimately be
 * absent: it expires with the session, a stale Secure-flagged cookie from
 * before COOKIE_SECURE was made configurable cannot be overwritten over plain
 * http, and a browser that was logged out and back in on a different origin
 * may never have received one. Every one of those states produced a silent
 * 403 on every write in the app -- "CSRF validation failed" in places the
 * user never touched. So rather than omitting the header when the cookie is
 * missing, we mint one on demand from POST /api/v1/auth/csrf-token, which is
 * on the middleware's exempt list and needs no token of its own.
 */

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const COOKIE = "csrf_token";
const HEADER = "X-CSRF-Token";

/** Read the token from the cookie jar. Null when absent or on the server. */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  // Split on the first "=" only: the value is hex today, but the parser should
  // not silently truncate if that ever changes.
  for (const part of document.cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() !== COOKIE) continue;
    const value = part.slice(eq + 1).trim();
    return value || null;
  }
  return null;
}

/**
 * True for a 403 from the CSRF middleware. The body is not readable
 * synchronously, and the middleware is the only component that answers 403 on
 * these routes in practice, so this keys on the status alone. The consequence
 * of a false positive is one redundant replay of an idempotent request.
 */
export function isCsrfFailure(res: Response): boolean {
  return res.status === 403;
}

/** In-flight mint, so a burst of parallel writes triggers one request. */
let inFlight: Promise<string | null> | null = null;

/** Fetch a fresh token, which also sets the cookie via Set-Cookie. */
async function mint(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/v1/auth/csrf-token`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    // Prefer the jar: the cookie is what the middleware will compare against.
    return getCsrfToken() ?? (data?.csrf_token ?? null);
  } catch {
    return null;
  }
}

/**
 * Return a usable token, minting one if the jar is empty. Resolves to null
 * only when the mint itself failed, in which case the caller surfaces a real
 * error rather than silently sending a request that cannot succeed.
 */
export async function ensureCsrfToken(): Promise<string | null> {
  const existing = getCsrfToken();
  if (existing) return existing;
  if (!inFlight) {
    inFlight = mint().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

/**
 * Best-effort preflight for a write: no-op when a token is already present.
 * Never throws -- a failed mint surfaces as a CSRF error on the request itself,
 * which is a clearer place for it than an exception before the call.
 */
export async function prefetchCsrfToken(): Promise<void> {
  await ensureCsrfToken().catch(() => null);
}

export { API as CSRF_API_BASE, HEADER as CSRF_HEADER };
