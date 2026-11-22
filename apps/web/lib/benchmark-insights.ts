/**
 * Client-side insight math for the benchmark compare page (P1/P2).
 *
 * The formulas and thresholds here are a binding contract
 * (docs/plans/2026-11-22-benchmark-p1p2.md) consumed by the CompletenessCard,
 * FixFirstTickets and BaselineAlert components — treat changes as breaking.
 */
import type {
  CompareSummary,
  ComparisonSubject,
  HistoryPoint,
} from "@/lib/api-benchmark";

/* ── Completeness score ────────────────────────────────────────────────── */

export interface CompletenessPart {
  /** One of `rating | recency | sentiment | depth`. */
  key: string;
  score: number;
  max: number;
}

// Weights sum to 100 so the total reads directly as a percentage:
// rating 40 / recency 20 / sentiment 20 / depth 20.
const RATING_MAX = 40;
const RECENCY_MAX = 20;
const SENTIMENT_MAX = 20;
const DEPTH_MAX = 20;

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * How complete (and healthy) a subject's benchmark data is, 0–100.
 *
 * Returns `null` only when the subject has no data at all (every source
 * metric null) so the card renders nothing instead of a meaningless 0.
 * Individual missing metrics just score 0 in their part.
 */
export function completenessScore(
  subject: ComparisonSubject
): { score: number; parts: CompletenessPart[] } | null {
  const m = subject.metrics;
  const positive = subject.facts.positive_pct;

  const hasRating = m.avg_rating !== null;
  const hasRecency = m.reviews_last_month !== null || m.reviews_last_year !== null;
  const hasSentiment = positive !== null;
  const hasDepth = m.total_reviews !== null;
  if (!hasRating && !hasRecency && !hasSentiment && !hasDepth) {
    return null;
  }

  let rating = 0;
  if (m.avg_rating !== null) {
    rating = (m.avg_rating / 5) * RATING_MAX;
  }

  let recency = 0;
  if (m.reviews_last_month !== null) {
    recency = Math.min(RECENCY_MAX, m.reviews_last_month * 2);
  } else if (m.reviews_last_year !== null) {
    // Monthly velocity unknown — approximate from the yearly count.
    recency = Math.min(RECENCY_MAX, (m.reviews_last_year / 12) * 2);
  }

  let sentiment = 0;
  if (positive !== null) {
    sentiment = (positive / 100) * SENTIMENT_MAX;
  }

  let depth = 0;
  if (m.total_reviews !== null) {
    depth = Math.min(DEPTH_MAX, (m.total_reviews / 100) * DEPTH_MAX);
  }

  const parts: CompletenessPart[] = [
    { key: "rating", score: round1(rating), max: RATING_MAX },
    { key: "recency", score: round1(recency), max: RECENCY_MAX },
    { key: "sentiment", score: round1(sentiment), max: SENTIMENT_MAX },
    { key: "depth", score: round1(depth), max: DEPTH_MAX },
  ];
  // Sum the already-rounded parts, then round once more so float artifacts
  // (e.g. 63.60000000000001) never leak into the UI.
  const score = round1(parts.reduce((sum, p) => sum + p.score, 0));
  return { score, parts };
}

/* ── Fix-first ranking ─────────────────────────────────────────────────── */

export type FixMetric = "avg_rating" | "reviews_per_month" | "positive_pct";

// The gap record also carries total_reviews, but raw review count is not
// something a tenant can act on directly, so it never becomes a ticket.
const ACTIONABLE_METRICS: FixMetric[] = [
  "avg_rating",
  "reviews_per_month",
  "positive_pct",
];

/**
 * Top actionable gaps between the tenant and the leader, worst first, max 3.
 * Only gaps the tenant can actually close (positive, non-null, actionable
 * metric) make the list.
 */
export function rankFixFirst(
  summary: CompareSummary,
  // In the signature per contract so call sites can pass what they already
  // hold; the gaps already compare leader vs own, so no subject data is
  // needed for the math.
  subjects: ComparisonSubject[]
): { metric: FixMetric; gap: number }[] {
  const gaps = summary.gaps ?? {};
  return ACTIONABLE_METRICS.map((metric) => ({ metric, gap: gaps[metric] }))
    .filter((row): row is { metric: FixMetric; gap: number } => row.gap != null && row.gap > 0)
    .sort((a, b) => b.gap - a.gap) // Worst gap first — biggest lever at the top.
    .slice(0, 3);
}

/* ── Baseline deviation ────────────────────────────────────────────────── */

export interface BaselineDeviation {
  hasEnough: boolean;
  direction: "up" | "down" | null;
  delta: number;
  streak: number;
}

/** Smallest |delta| in rating stars that counts as a real deviation. */
const DEVIATION_THRESHOLD = 0.15;
/** The baseline mean uses at most this many oldest points. */
const BASELINE_MAX_POINTS = 8;
/** Fewer rating points than this cannot separate a baseline from "now". */
const MIN_RATING_POINTS = 2;

/**
 * Compare the newest rating against the mean of the oldest rating points.
 * `delta` is rounded to 2dp before the threshold check so float noise
 * (3.15 − 3 = 0.14999…) cannot silently swallow an exact-threshold move.
 */
export function baselineDeviation(points: HistoryPoint[]): BaselineDeviation {
  const notEnough: BaselineDeviation = { hasEnough: false, direction: null, delta: 0, streak: 0 };
  // Only points that actually carry a rating participate (at+rating pairs).
  const ratings: number[] = [];
  for (const p of points) {
    if (p.rating !== null) ratings.push(p.rating);
  }
  if (ratings.length < MIN_RATING_POINTS) return notEnough;

  const baselineCount = Math.min(Math.floor(ratings.length / 2), BASELINE_MAX_POINTS);
  const baselineSum = ratings.slice(0, baselineCount).reduce((sum, r) => sum + r, 0);
  const baseline = baselineSum / baselineCount;
  const latest = ratings[ratings.length - 1];
  const delta = round2(latest - baseline);
  const direction = Math.abs(delta) >= DEVIATION_THRESHOLD ? (delta > 0 ? "up" : "down") : null;
  if (!direction) {
    return { hasEnough: true, direction: null, delta, streak: 0 };
  }

  // Streak: consecutive trailing points sitting on the deviation's side of
  // the same baseline; a point back on the baseline breaks it.
  let streak = 0;
  for (let i = ratings.length - 1; i >= 0; i--) {
    const onSide = direction === "up" ? ratings[i] > baseline : ratings[i] < baseline;
    if (!onSide) break;
    streak++;
  }
  return { hasEnough: true, direction, delta, streak };
}
