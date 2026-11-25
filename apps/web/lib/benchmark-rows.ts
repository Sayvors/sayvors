import type { ComparisonSubject } from "@/lib/api-benchmark";
import {
  formatPercent,
  formatRating,
  type GapUnit,
} from "@/lib/benchmark-format";

export interface BenchmarkMetricCopy {
  reviewsTotal: string;
  averageRating: string;
  reviewsLastMonth: string;
  reviewsLastYear: string;
  fiveStarRatings: string;
  oneStarRatings: string;
}

export interface BenchmarkMetricRow {
  key:
    | "total_reviews"
    | "avg_rating"
    | "reviews_last_month"
    | "reviews_last_year"
    | "five_star_pct"
    | "one_star_pct";
  label: string;
  value: (subject: ComparisonSubject) => number | null;
  tierValue?: (subject: ComparisonSubject) => number | null;
  higherIsBetter?: boolean;
  gapUnit: GapUnit;
  render: (subject: ComparisonSubject) => string;
}

function count(value: number | null | undefined): string {
  return value == null ? "—" : String(value);
}

function subjectRating(subject: ComparisonSubject): string {
  const { avg_rating, total_ratings } = subject.metrics;
  if (avg_rating == null || total_ratings === 0) return "—";
  return formatRating(avg_rating);
}

function starShare(subject: ComparisonSubject, star: 1 | 5): number | null {
  const total = subject.metrics.star_share_base;
  const count = star === 5 ? subject.metrics.five_star : subject.metrics.one_star;
  return total != null && total > 0 && count != null ? (count / total) * 100 : null;
}

/** The primary comparison is deliberately capped at six reputation metrics. */
export function getMetricRows(c: BenchmarkMetricCopy): BenchmarkMetricRow[] {
  return [
    {
      key: "total_reviews",
      label: c.reviewsTotal,
      value: (subject) => subject.metrics.total_reviews,
      higherIsBetter: true,
      gapUnit: "count",
      render: (subject) => count(subject.metrics.total_reviews),
    },
    {
      key: "avg_rating",
      label: c.averageRating,
      value: (subject) => subject.metrics.avg_rating,
      tierValue: (subject) => subject.metrics.total_ratings !== 0 ? subject.metrics.avg_rating : null,
      higherIsBetter: true,
      gapUnit: "rating",
      render: subjectRating,
    },
    {
      key: "reviews_last_month",
      label: c.reviewsLastMonth,
      value: (subject) => subject.metrics.reviews_last_month,
      higherIsBetter: true,
      gapUnit: "count",
      render: (subject) => count(subject.metrics.reviews_last_month),
    },
    {
      key: "reviews_last_year",
      label: c.reviewsLastYear,
      value: (subject) => subject.metrics.reviews_last_year,
      gapUnit: "count",
      render: (subject) => count(subject.metrics.reviews_last_year),
    },
    {
      key: "five_star_pct",
      label: c.fiveStarRatings,
      value: (subject) => starShare(subject, 5),
      higherIsBetter: true,
      gapUnit: "percent",
      render: (subject) => formatPercent(starShare(subject, 5)),
    },
    {
      key: "one_star_pct",
      label: c.oneStarRatings,
      value: (subject) => starShare(subject, 1),
      higherIsBetter: false,
      gapUnit: "percent",
      render: (subject) => formatPercent(starShare(subject, 1)),
    },
  ];
}
