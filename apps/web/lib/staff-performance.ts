/**
 * Per-staff review performance, derived from the staff summary endpoint.
 *
 * The numbers come from the review AI's sentiment on reviews that *name* the
 * employee (`positive`/`neutral`/`negative` + `avg_rating`). No new API is
 * needed. These helpers are pure so the ranking/verdict logic is unit-tested
 * and the UI cannot quietly disagree between the card and the team chart.
 */
export interface StaffSummaryLike {
  staff_member_id: string;
  name: string;
  mentions: number;
  positive: number;
  neutral: number;
  negative: number;
  avg_rating: number | null;
  prior_mentions: number;
  trend: "up" | "down" | "flat";
}

export interface SentimentShares {
  positive: number; // 0..100, rounded
  neutral: number;
  negative: number;
}

export type StaffVerdict = "great" | "good" | "mixed" | "watch" | "new";

export function sentimentShares(row: StaffSummaryLike): SentimentShares {
  const total = row.positive + row.neutral + row.negative;
  if (total <= 0) return { positive: 0, neutral: 0, negative: 0 };
  const pct = (n: number) => Math.round((n / total) * 100);
  return { positive: pct(row.positive), neutral: pct(row.neutral), negative: pct(row.negative) };
}

/**
 * -100 (all negative) .. +100 (all positive). `mentions: 0` is 0 — neutral,
 * never a false "great" that would outrank a real performer.
 */
export function staffScore(row: StaffSummaryLike): number {
  const total = row.positive + row.neutral + row.negative;
  if (total <= 0) return 0;
  return Math.round(((row.positive - row.negative) / total) * 100);
}

/**
 * Owner-facing verdict, based only on the sentiment split the AI reported.
 * Kept explainable: no hidden weighting, so a merchant can always see why a
 * person was labelled a certain way from the bar next to it.
 */
export function staffVerdict(row: StaffSummaryLike): StaffVerdict {
  if (row.mentions <= 0) return "new";
  const s = sentimentShares(row);
  if (s.negative >= 40) return "watch";
  if (s.positive >= 70) return "great";
  if (s.positive >= 50) return "good";
  return "mixed";
}

/** Best performers first; ties broken by volume then name for a stable order. */
export function rankStaff(rows: readonly StaffSummaryLike[]): StaffSummaryLike[] {
  return [...rows].sort(
    (a, b) => staffScore(b) - staffScore(a) || b.mentions - a.mentions || a.name.localeCompare(b.name),
  );
}
