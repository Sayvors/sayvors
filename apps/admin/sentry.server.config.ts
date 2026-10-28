/**
 * Server-side (Node.js runtime) error reporting for the admin console.
 * DSN is server-only (GLITCHTIP_DSN), never exposed to the browser bundle.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.GLITCHTIP_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.ENVIRONMENT ?? "development",
    release: process.env.VERSION,
    tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 0,
  });
}
