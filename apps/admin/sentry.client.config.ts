/**
 * Browser-side error reporting for the admin console.
 *
 * Mirrors apps/web/sentry.client.config.ts: GlitchTip is self-hosted and
 * Sentry-compatible. No-op when the DSN is unset, so local dev and
 * environments without monitoring never break.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_GLITCHTIP_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_GLITCHTIP_ENVIRONMENT ?? "development",
    release: process.env.NEXT_PUBLIC_GLITCHTIP_RELEASE,
    tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 0,
  });
}
