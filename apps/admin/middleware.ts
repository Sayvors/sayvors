import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Security headers for the admin console.
 *
 * The console has no public auth surface of its own, but it renders tenant
 * data and holds an operator session in an httpOnly cookie. A nonce-based CSP
 * keeps injected markup from executing, and frame-ancestors 'none' stops a
 * clickjacking page from wrapping the console. Next.js 16 reads the nonce from
 * the request's CSP header and applies it to its inline bootstrap scripts;
 * app/layout.tsx also nonces its theme-init script.
 */
export function middleware(request: NextRequest) {
  const isProd = process.env.NODE_ENV === "production";
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const scriptSrc = isProd
    ? `'self' 'nonce-${nonce}' 'strict-dynamic'`
    : `'self' 'nonce-${nonce}' 'strict-dynamic' 'unsafe-eval'`;

  // Tenant avatars and profile media can come from the object store, Google,
  // or the API host; keep the image allowlist aligned with the web app.
  const mediaSrc = [
    apiUrl,
    "https://*.sayvors.com",
    "https://*.amazonaws.com",
    "https://storage.googleapis.com",
    "https://*.googleusercontent.com",
    "https://*.ggpht.com",
  ].join(" ");

  const connectSrc = [
    "'self'",
    apiUrl,
    apiUrl.replace(/^http/, "ws"),
    "https://*.sentry.io",
    "https://*.glitchtip.com",
  ].join(" ");

  const csp = [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${mediaSrc}`,
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    "frame-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set(
    "Strict-Transport-Security",
    "max-age=63072000; includeSubDomains; preload",
  );
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set(
    "Referrer-Policy",
    "strict-origin-when-cross-origin",
  );
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
