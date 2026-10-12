/**
 * Edge runtime error reporting -> our self-hosted GlitchTip.
 *
 * The edge runtime cannot use Node APIs, so it needs its own SDK instance.
 * Without this, errors thrown inside edge middleware/route handlers are lost.
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