import { describe, it, expect } from "vitest";
import {
  completenessScore,
  rankFixFirst,
  baselineDeviation,
} from "./benchmark-insights";
import type {
  CompareSummary,
  ComparisonSubject,
  HistoryPoint,
} from "@/lib/api-benchmark";

/* Fixtures: ComparisonSubject is a wide payload, so each test overrides only
   the fields it cares about and everything else starts as "no data". */
const BASE_METRICS: ComparisonSubject["metrics"] = {
  total_reviews: null,
  reviews_last_day: null,
  reviews_last_week: null,
  reviews_last_month: null,
  reviews_last_year: null,
  avg_rating: null,
  total_ratings: null,
  five_star: null,
  four_star: null,
  one_star: null,
  star_share_base: null,
  impressions: null,
  calls: null,
  period_reviews: null,
  period_avg_rating: null,
  rating_change: null,
  period_impressions: null,
  period_calls: null,
};

const BASE_FACTS: ComparisonSubject["facts"] = {
  positive_pct: null,
  negative_pct: null,
  branch: null,
  employee_mentions: null,
  working_hard_mentions: null,
  menu_price_mentions: null,
  parking_praised: null,
  parking_criticised: null,
  services: [],
  top_problems: [],
  named_team: [],
};

function mkSubject(over: Partial<ComparisonSubject> = {}): ComparisonSubject {
  const subject: ComparisonSubject = {
    key: "own:x",
    kind: "own",
    id: "x",
    available: true,
    reason: null,
    name: "Cafe Alpha",
    address: null,
    verified: false,
    data_source: "google_places",
    metrics: { ...BASE_METRICS },
    facts: { ...BASE_FACTS },
    notes: [],
    tags: [],
  };
  // Object.assign keeps the declared ComparisonSubject type; spreading `over`
  // into the literal would widen required props (e.g. tags) to optional.
  return Object.assign(subject, over);
}

function mkSummary(gaps: CompareSummary["gaps"]): CompareSummary {
  return {
    rank: 2,
    of: 4,
    own: { key: "own:x", name: "Cafe Alpha" },
    leader: { key: "saved:y", name: "Rival Cafe" },
    gaps,
    health: "warn",
  };
}

function pt(rating: number | null, at = "2026-01-01"): HistoryPoint {
  return { at, rating, reviews: 10 };
}

describe("completenessScore", () => {
  it("scores a perfect subject 100 across all four parts", () => {
    const subject = mkSubject({
      metrics: {
        ...BASE_METRICS,
        avg_rating: 5,
        reviews_last_month: 10,
        reviews_last_year: 500,
        total_reviews: 150,
      },
      facts: { ...BASE_FACTS, positive_pct: 100 },
    });
    const result = completenessScore(subject);
    expect(result).not.toBeNull();
    expect(result!.score).toBe(100);
    expect(result!.parts).toEqual([
      { key: "rating", score: 40, max: 40 },
      { key: "recency", score: 20, max: 20 },
      { key: "sentiment", score: 20, max: 20 },
      { key: "depth", score: 20, max: 20 },
    ]);
  });

  it("rounds parts to one decimal", () => {
    const subject = mkSubject({
      metrics: {
        ...BASE_METRICS,
        avg_rating: 4.2,
        reviews_last_month: 3,
        total_reviews: 45,
      },
      facts: { ...BASE_FACTS, positive_pct: 75 },
    });
    // rating 4.2/5*40 = 33.6; recency 3*2 = 6; sentiment 75/100*20 = 15; depth 45/100*20 = 9
    expect(completenessScore(subject)).toEqual({
      score: 63.6,
      parts: [
        { key: "rating", score: 33.6, max: 40 },
        { key: "recency", score: 6, max: 20 },
        { key: "sentiment", score: 15, max: 20 },
        { key: "depth", score: 9, max: 20 },
      ],
    });
  });

  it("caps recency and depth at their maxima", () => {
    const subject = mkSubject({
      metrics: {
        ...BASE_METRICS,
        avg_rating: 5,
        reviews_last_month: 25,
        total_reviews: 300,
      },
      facts: { ...BASE_FACTS, positive_pct: 100 },
    });
    const result = completenessScore(subject)!;
    expect(result.parts.find((p) => p.key === "recency")!.score).toBe(20);
    expect(result.parts.find((p) => p.key === "depth")!.score).toBe(20);
    expect(result.score).toBe(100);
  });

  it("falls back to reviews_last_year for recency when the month value is missing", () => {
    const subject = mkSubject({
      metrics: { ...BASE_METRICS, reviews_last_year: 60 },
      facts: { ...BASE_FACTS, positive_pct: 100 },
    });
    // 60/12*2 = 10
    expect(completenessScore(subject)!.parts.find((p) => p.key === "recency")!.score).toBe(10);
  });

  it("prefers reviews_last_month over the yearly fallback", () => {
    const subject = mkSubject({
      metrics: { ...BASE_METRICS, reviews_last_month: 2, reviews_last_year: 600 },
      facts: { ...BASE_FACTS, positive_pct: 100 },
    });
    // month wins: 2*2 = 4, not the yearly 600/12*2 = 100
    expect(completenessScore(subject)!.parts.find((p) => p.key === "recency")!.score).toBe(4);
  });

  it("scores null metrics as 0 parts without nulling the result", () => {
    const subject = mkSubject({
      metrics: { ...BASE_METRICS, reviews_last_month: 5, total_reviews: 50 },
      facts: { ...BASE_FACTS, positive_pct: 80 },
    });
    // rating 0, recency 10, sentiment 16, depth 10 → 36
    const result = completenessScore(subject)!;
    expect(result.parts.find((p) => p.key === "rating")!.score).toBe(0);
    expect(result.score).toBe(36);
  });

  it("returns null when the subject has no data at all", () => {
    expect(completenessScore(mkSubject())).toBeNull();
  });
});

describe("rankFixFirst", () => {
  it("returns only actionable gaps over zero, worst first", () => {
    const summary = mkSummary({
      avg_rating: 0.5,
      reviews_per_month: 2,
      positive_pct: 12,
      total_reviews: 40,
    });
    expect(rankFixFirst(summary, [mkSubject()])).toEqual([
      { metric: "positive_pct", gap: 12 },
      { metric: "reviews_per_month", gap: 2 },
      { metric: "avg_rating", gap: 0.5 },
    ]);
  });

  it("excludes non-actionable total_reviews even when it is the biggest gap", () => {
    const summary = mkSummary({ total_reviews: 99 });
    expect(rankFixFirst(summary, [mkSubject()])).toEqual([]);
  });

  it("drops gaps that are zero, negative or null", () => {
    const summary = mkSummary({
      avg_rating: 0,
      reviews_per_month: -1.5,
      positive_pct: null,
    });
    expect(rankFixFirst(summary, [mkSubject()])).toEqual([]);
  });

  it("caps the list at 3 items", () => {
    const summary = mkSummary({
      avg_rating: 0.1,
      reviews_per_month: 0.2,
      positive_pct: 0.3,
      total_reviews: 50,
    });
    const result = rankFixFirst(summary, [mkSubject()]);
    expect(result).toHaveLength(3);
    expect(result[0]).toEqual({ metric: "positive_pct", gap: 0.3 });
  });

  it("returns an empty list when no gaps exist", () => {
    expect(rankFixFirst(mkSummary({}), [mkSubject()])).toEqual([]);
  });
});

describe("baselineDeviation", () => {
  it("reports not-enough for empty or single rating points", () => {
    expect(baselineDeviation([])).toEqual({
      hasEnough: false,
      direction: null,
      delta: 0,
      streak: 0,
    });
    expect(baselineDeviation([pt(4)])).toEqual({
      hasEnough: false,
      direction: null,
      delta: 0,
      streak: 0,
    });
  });

  it("reports not-enough when no point carries a rating", () => {
    expect(baselineDeviation([pt(null), pt(null)])).toEqual({
      hasEnough: false,
      direction: null,
      delta: 0,
      streak: 0,
    });
  });

  it("ignores points without a rating", () => {
    const points = [pt(null), pt(3), pt(3), pt(3.2)];
    // Rating points [3, 3, 3.2]: baseline 3, latest 3.2 → delta 0.2, streak 1
    expect(baselineDeviation(points)).toEqual({
      hasEnough: true,
      direction: "up",
      delta: 0.2,
      streak: 1,
    });
  });

  it("flags an upward deviation with its trailing streak", () => {
    const points = [pt(3), pt(3), pt(3), pt(4.2), pt(4.4)];
    // Baseline = mean(3, 3) = 3; latest 4.4 → delta 1.4; trailing above: 4.4, 4.2
    expect(baselineDeviation(points)).toEqual({
      hasEnough: true,
      direction: "up",
      delta: 1.4,
      streak: 2,
    });
  });

  it("flags a downward deviation with its trailing streak", () => {
    const points = [pt(4), pt(4), pt(3.8), pt(3.7)];
    // Baseline = 4; latest 3.7 → delta -0.3; trailing below: 3.7, 3.8
    expect(baselineDeviation(points)).toEqual({
      hasEnough: true,
      direction: "down",
      delta: -0.3,
      streak: 2,
    });
  });

  it("fires exactly at the 0.15 threshold and not below it", () => {
    const at = baselineDeviation([pt(3), pt(3), pt(3.15)]);
    expect(at.hasEnough).toBe(true);
    expect(at.direction).toBe("up");

    const below = baselineDeviation([pt(3), pt(3), pt(3.1)]);
    expect(below).toEqual({ hasEnough: true, direction: null, delta: 0.1, streak: 0 });
  });

  it("reports no direction when the latest point sits on the baseline", () => {
    expect(baselineDeviation([pt(3), pt(3)])).toEqual({
      hasEnough: true,
      direction: null,
      delta: 0,
      streak: 0,
    });
  });

  it("bases the mean on at most the oldest 8 points", () => {
    const points: HistoryPoint[] = [
      ...Array.from({ length: 8 }, () => pt(2)),
      ...Array.from({ length: 12 }, () => pt(5)),
    ];
    // 20 rating points: oldest half (10) capped to 8 → baseline 2.0, delta 3;
    // without the cap the baseline would be 2.6 and the delta 2.4.
    expect(baselineDeviation(points)).toEqual({
      hasEnough: true,
      direction: "up",
      delta: 3,
      streak: 12,
    });
  });
});
