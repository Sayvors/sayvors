// Distinct-business helpers: the backend guarantees one channel row per
// location (unique index on user/platform/listing_key), but counts must
// stay right even if a twin row ever slips through. Identity is ALWAYS the
// stable listing/location ID from the API — never the display name (two
// branches can share a name).

export interface BusinessChannel {
  id: string;
  display_name: string | null;
  // Localith listing_id, or Google location_id for native OAuth rows.
  // Absent on old backends — callers then fall back to the row id.
  listing_id?: string | null;
  source?: string | null;
}

export function businessKey(channel: BusinessChannel): string {
  return channel.listing_id || channel.id;
}

/** Collapse twin rows: first row wins per listing identity. */
export function dedupeBusinesses<T extends BusinessChannel>(channels: T[]): T[] {
  const seen = new Map<string, T>();
  for (const channel of channels) {
    const key = businessKey(channel);
    if (!seen.has(key)) seen.set(key, channel);
  }
  return [...seen.values()];
}
