import type { ComparisonSubject } from "./api-benchmark";

export type HeadlineMetricKey =
  | "avg_rating"
  | "reviews_per_month"
  | "total_reviews"
  | "positive_pct";

/** Below this, a gap is directionally interesting but not a confident verdict. */
export const LOW_SAMPLE_THRESHOLD = 5;

/** A display-safe value for the four headline comparison metrics.
 *
 *  The API legitimately uses 0.0 for an own location with no ratings/reviews.
 *  That is missing evidence, not a terrible score, so charts must not plot it.
 *  Zero total reviews remains a real volume value.
 */
export function headlineMetricValue(
  subject: ComparisonSubject,
  key: HeadlineMetricKey,
): number | null {
  const { metrics, facts } = subject;
  switch (key) {
    case "avg_rating":
      return (metrics.total_ratings ?? 0) > 0 &&
        metrics.avg_rating != null &&
        metrics.avg_rating >= 1
        ? metrics.avg_rating
        : null;
    case "reviews_per_month":
      return (
        metrics.reviews_last_month ??
        (metrics.reviews_last_year != null
          ? metrics.reviews_last_year / 12
          : null)
      );
    case "total_reviews":
      return metrics.total_reviews;
    case "positive_pct":
      return (metrics.total_reviews ?? 0) > 0 ? facts.positive_pct : null;
  }
}

export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

export function formatHeadlineValue(key: HeadlineMetricKey, value: number): string {
  if (key === "avg_rating") return value.toFixed(1);
  if (key === "positive_pct") return `${Math.round(value)}%`;
  return String(Math.round(value));
}

export function formatHeadlineGap(key: HeadlineMetricKey, value: number): string {
  if (key === "avg_rating") return `${Math.abs(value).toFixed(1)}★`;
  if (key === "positive_pct") return `${Math.abs(Math.round(value))} pts`;
  return String(Math.round(Math.abs(value)));
}
