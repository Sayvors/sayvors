/**
 * Browser-side error reporting.
 *
 * GlitchTip is a self-hosted Sentry-compatible server, so this is the standard
 * Sentry client SDK pointed at our own DSN. Nothing is sent to sentry.io --
 * the only destination is NEXT_PUBLIC_GLITCHTIP_DSN, which the deployment sets
 * to our own host.
 *
 * See sentry.server.config.ts for server-side, and instrumentation.ts for the
 * registration hook.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_GLITCHTIP_DSN;

// Unset locally (or in any environment without the DSN): stay a no-op rather
// than throwing, so a missing env var can never break the dashboard.
if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_GLITCHTIP_ENVIRONMENT ?? "development",
    release: process.env.NEXT_PUBLIC_GLITCHTIP_RELEASE,
    // Production-only by default. Sends traces from every localhost reload,
    // which is noise nobody reads.
    tracesSampleRate:
      process.env.NODE_ENV === "production" ? 0.1 : 0,
  });
}