"use client";

import { useReportWebVitals } from "next/web-vitals";
import * as Sentry from "@sentry/nextjs";

/**
 * Reports Core Web Vitals (LCP, INP, CLS, TTFB, FCP) to the configured
 * GlitchTip/Sentry DSN. No-op when no DSN is set, so it never breaks local
 * dev or environments without monitoring configured.
 *
 * Each metric is sent as an info-level message with the value and rating as
 * tags, which keeps the dashboard queryable ("show me pages with LCP > 2.5s")
 * without requiring a backend endpoint or a tracing integration.
 */
export default function WebVitalsReporter() {
  useReportWebVitals((metric) => {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.debug("[web-vitals]", metric.name, metric.value, metric.rating);
    }
    const dsn = process.env.NEXT_PUBLIC_GLITCHTIP_DSN;
    if (!dsn) return;
    try {
      Sentry.captureMessage(`web-vital:${metric.name}`, {
        level: "info",
        tags: {
          metric: metric.name,
          rating: metric.rating ?? "unknown",
          navigationType: metric.navigationType ?? "unknown",
        },
        contexts: {
          webVital: {
            name: metric.name,
            value: metric.value,
            id: metric.id,
            delta: metric.delta,
            rating: metric.rating,
          },
        },
      });
    } catch {
      /* never let vitals reporting break the page */
    }
  });

  return null;
}