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

  const isProd = process.env.NODE_ENV === "production";
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // SEC-M8: nonce-based CSP. Next.js 16 reads the x-nonce request header
  // and applies it to its own inline bootstrap scripts automatically.
  // 'strict-dynamic' lets scripts loaded by trusted (nonced) scripts run
  // without listing every CDN host — the Meta SDK loaded via a nonced
  // script tag is trusted transitively.
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  // Google Identity Services: gsi/client script, sign-in button iframe,
  // and its account/status fetches all live on accounts.google.com.
  const gsi = "https://accounts.google.com";
  // Dev tunnel chain (ngrok -> Next /api rewrite -> API): the proxied Meta SDK
  // bootstrap rewrites its bundle URL to the API's local address
  // (http://localhost:8000 — same destination as next.config.ts rewrites),
  // which neither 'self' (tunnel page origin) nor apiUrl (tunnel origin)
  // covers. Mixed-content is exempt for localhost; only CSP needed the entry.
  // Prod loads the SDK straight from the API host, so no entry there.
  const devSdk = isProd ? "" : " http://localhost:8000";
  // The realtime inbox socket dials ws:// / wss:// — browsers refuse to
  // match an https:// host source against a wss:// URL, so connect-src
  // carries the API host in both spellings.
  const wsApiUrl = apiUrl.replace(/^http/, "ws");
  // Uploaded media (avatars, covers, post photos) is served by the object
  // store, whose host is deployment-specific: S3 virtual-hosted URLs
  // (<bucket>.s3.<region>.amazonaws.com), a custom CDN base
  // (S3_MEDIA_PUBLIC_BASE_URL), or GCS. Local dev serves /media-files/*
  // straight from the API instead. Mirrors the image remotePatterns in
  // next.config.ts — keep the two lists in step. img-src cannot execute
  // script, so a host wildcard here is far cheaper than a broken avatar.
  const mediaSrc = [
    apiUrl,
    "https://*.sayvors.com",
    "https://*.amazonaws.com",
    "https://storage.googleapis.com",
    "https://*.googleusercontent.com",
    "https://*.ggpht.com",
    ...(isProd ? [] : ["http://localhost:8000", "http://127.0.0.1:8000"]),
  ].join(" ");
  const scriptSrc = isProd
    ? `'self' 'nonce-${nonce}' 'strict-dynamic' ${apiUrl} ${gsi}${devSdk}`
    : `'self' 'nonce-${nonce}' 'strict-dynamic' 'unsafe-eval' ${apiUrl} ${gsi}${devSdk}`;
  const csp = [
    "default-src 'self'",
    // API host: serves the proxied Meta SDK script (cross-origin script tag).
    `script-src ${scriptSrc}`,
    `style-src 'self' 'unsafe-inline' ${gsi}`,
    // Contact avatars come straight from Meta's CDNs (Instagram profile_pic,
    // Messenger lookaside) — temporary links by design, refreshed weekly.
    // WhatsApp business profile photos are served from pps.whatsapp.net.
    // Uploaded profile media comes from the object store (see mediaSrc).
    `img-src 'self' data: blob: ${gsi} https://www.gstatic.com https://*.cdninstagram.com https://*.fbcdn.net https://*.fbsbx.com https://*.whatsapp.net ${mediaSrc}`,
    "font-src 'self' data:",
    // Meta SDK subresources (graph calls, dialog/popup channel frames)
    // plus the realtime inbox WebSocket (wss:// form of the API host).
    `connect-src 'self' ${apiUrl} ${wsApiUrl} ${gsi} https://graph.facebook.com https://connect.facebook.net`,
    `frame-src 'self' ${gsi} https://www.facebook.com https://web.facebook.com`,
    "frame-ancestors 'none'",
  ].join("; ");

  // Next.js 16 extracts the nonce from the Content-Security-Policy header on
  // the request (not just x-nonce) and applies it to its inline bootstrap
  // scripts. Without this on the request, strict-dynamic blocks every inline
  // script and the page renders with dead JS — login/signup never hydrate.
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  response.headers.set("Content-Security-Policy", csp);

  return response;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)", "/api/:path*"],
};
