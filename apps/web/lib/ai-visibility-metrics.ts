const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "searching",
  "fetching",
  "reading",
  "validating",
  "writing",
]);

/** Keep missing evidence distinct from a measured zero. */
export function formatRate(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

export function isActiveStatus(status: string): boolean {
  return ACTIVE_RUN_STATUSES.has(status);
}
