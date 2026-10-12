/**
 * Next.js instrumentation hook.
 *
 * Runs once when the server runtime boots. Sentry's SDK requires its config to
 * be registered before any route handler executes, which this hook guarantees.
 */
import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

/**
 * Called when a request could not be served at all (no matching route, or a
 * middleware crash). Distinct from app/error.tsx, which handles render errors
 * inside a route that did match.
 */
export const onRequestError = Sentry.captureRequestError;