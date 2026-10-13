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

import { API_BASE } from "./api-base";

const API = API_BASE;

const COOKIE = "csrf_token";
const HEADER = "X-CSRF-Token";

/**
 * Read the token from the cookie jar. Null when absent or on the server.
 *
 * LAST match wins, deliberately. A browser can legitimately hold two cookies
 * named `csrf_token` for one host — ours is host-only, but a sibling
 * environment on a sayvors.com subdomain sets `Domain=.sayvors.com`, and that
 * one is attached to every subdomain including this one. Starlette's
 * cookie_parser assigns into a dict in header order, so the server reads the
 * last; taking the first here meant the header carried a different token than
 * the cookie the server compared against and every write 403'd with two valid
 * 64-char tokens in play. Selection has to match the server's exactly.
 */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  let found: string | null = null;
  // Split on the first "=" only: the value is hex today, but the parser should
  // not silently truncate if that ever changes.
  for (const part of document.cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() !== COOKIE) continue;
    const value = part.slice(eq + 1).trim();
    if (value) found = value;
  }
  return found;
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

/** A mint must never wedge the write it is protecting. */
const MINT_TIMEOUT_MS = 5000;

/** Fetch a fresh token, which also sets the cookie via Set-Cookie. */
async function mint(): Promise<string | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MINT_TIMEOUT_MS);
  try {
    const res = await fetch(`${API}/api/v1/auth/csrf-token`, {
      method: "POST",
      credentials: "include",
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    // Prefer the jar: the cookie is what the middleware will compare against.
    return getCsrfToken() ?? (data?.csrf_token ?? null);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
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
