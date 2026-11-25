export type GapUnit = "count" | "percent" | "rating";

function rounded(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

/** Percentages are evidence shares, not raw floating-point strings. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${rounded(value, 1)}%`;
}

/** Google ratings always read as two-decimal star scores in comparison tables. */
export function formatRating(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)} ★`;
}

/** Format a signed row difference using the row's own unit. */
export function formatGap(value: number, unit: GapUnit): string | null {
  if (!Number.isFinite(value)) return null;
  const decimals = unit === "count" ? 0 : unit === "percent" ? 1 : 2;
  const magnitude = rounded(Math.abs(value), decimals);
  if (magnitude === 0) return null;
  const sign = value < 0 ? "−" : "+";
  const suffix = unit === "percent" ? "%" : unit === "rating" ? " ★" : "";
  return `${sign}${magnitude}${suffix}`;
}
