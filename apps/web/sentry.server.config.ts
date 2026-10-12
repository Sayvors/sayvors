/**
 * Server-side (Node.js runtime) error reporting -> our self-hosted GlitchTip.
 *
 * Kept separate from the client config: the server DSN is not NEXT_PUBLIC_*
 * and must never be exposed to the browser bundle.
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