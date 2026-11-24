import type { SubjectHistory } from "./api-benchmark";

export type TrendMetric = "rating" | "reviews";

export interface TrendPoint {
  at: number;
  value: number;
}

export interface TrendSeries {
  key: string;
  name: string;
  kind: SubjectHistory["kind"];
  points: TrendPoint[];
}

/** Build comparable series on a real date axis.
 *
 *  Review history already stores cumulative totals. Plotting those totals is
 *  stable and understandable; deriving a per-interval velocity made a single
 *  missing snapshot look like a collapse in momentum.
 */
export function buildTrendSeries(
  history: readonly SubjectHistory[],
  metric: TrendMetric,
): TrendSeries[] {
  const out: TrendSeries[] = [];
  for (const subject of history) {
    const points: TrendPoint[] = [];
    for (const point of subject.points) {
      if (!point.at) continue;
      const at = new Date(point.at).getTime();
      const raw = metric === "rating" ? point.rating : point.reviews;
      if (!Number.isFinite(at) || raw == null || !Number.isFinite(raw)) continue;
      const value = Number(raw);
      if (metric === "rating" && (value < 1 || value > 5)) continue;
      if (metric === "reviews" && value < 0) continue;
      points.push({ at, value });
    }
    points.sort((a, b) => a.at - b.at);
    if (points.length >= 1) {
      out.push({
        key: subject.key,
        name: subject.name ?? subject.key,
        kind: subject.kind,
        points,
      });
    }
  }
  return out;
}

export function sharedTimeDomain(series: readonly TrendSeries[]): {
  start: number;
  end: number;
} {
  const dates = series.flatMap((row) => row.points.map((point) => point.at));
  if (dates.length === 0) return { start: 0, end: 0 };
  return {
    start: Math.min(...dates),
    end: Math.max(...dates),
  };
}

export function seriesDelta(series: TrendSeries): number {
  return series.points[series.points.length - 1].value - series.points[0].value;
}
