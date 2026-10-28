/**
 * Edge runtime error reporting for the admin console.
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
