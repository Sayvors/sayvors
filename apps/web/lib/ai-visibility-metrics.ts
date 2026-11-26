const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "searching",
  "fetching",
  "reading",
  "validating",
  "writing",
]);

/** Keep missing or invalid evidence distinct from a measured zero. */
export function formatRate(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "—" : `${value.toFixed(1)}%`;
}

export function isActiveStatus(status: string): boolean {
  return ACTIVE_RUN_STATUSES.has(status);
}
