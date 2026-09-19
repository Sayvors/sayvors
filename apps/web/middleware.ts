import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const rateLimit = new Map<string, { count: number; last: number }>();
const RATE_LIMIT_WINDOW = 60_000;
const RATE_LIMIT_MAX = process.env.NODE_ENV === "production" ? 100 : 500;

function checkRateLimit(ip: string): boolean {
  const now = Date.now();
  const entry = rateLimit.get(ip);
  if (!entry || now - entry.last > RATE_LIMIT_WINDOW) {
    rateLimit.set(ip, { count: 1, last: now });
    return true;
  }
  if (entry.count >= RATE_LIMIT_MAX) return false;
  entry.count++;
  return true;
}

export function middleware(request: NextRequest) {
  const ip = request.headers.get("x-forwarded-for") || request.headers.get("x-real-ip") || "unknown";

  if (!checkRateLimit(ip)) {
    return new NextResponse("Too many requests", { status: 429, headers: { "Retry-After": "60" } });
  }

  // NOTE: no server-side auth gate here on purpose. The session cookies
  // (refresh_token / csrf_token) live on the API origin, which the frontend
  // middleware can never see cross-domain — gating on them would bounce every
  // /dashboard visit to /login. The client-side <AuthGuard> is the real gate.

  const response = NextResponse.next();
  const isProd = process.env.NODE_ENV === "production";
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");

  // Next.js injects inline bootstrap scripts and allows no per-request nonce
  // yet — without 'unsafe-inline', every production page renders with dead
  // JS (all inline scripts blocked). Nonce-based CSP is the proper follow-up.
  const scriptExtras = isProd ? " 'unsafe-inline'" : " 'unsafe-eval' 'unsafe-inline'";
  const csp = [
    "default-src 'self'",
    // API host: serves the proxied Meta SDK script (cross-origin script tag).
    `script-src 'self' ${apiUrl}${scriptExtras}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    // Meta SDK subresources (graph calls, dialog/popup channel frames).
    `connect-src 'self' ${apiUrl} https://graph.facebook.com https://connect.facebook.net`,
    "frame-src 'self' https://www.facebook.com https://web.facebook.com",
    "frame-ancestors 'none'",
  ].join("; ");
  response.headers.set("Content-Security-Policy", csp);

  return response;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
