/* Location groups — shared selector helpers.
 *
 * Groups are stored server-side against Localith `listing_id`s. Pages differ
 * in what they key locations by: Locations uses listing IDs directly, while
 * Posts / Services / Reviews work in channel IDs. So a group is resolved
 * through a caller-supplied `listingId -> local id` map, and members with no
 * local counterpart are skipped rather than sent as bogus IDs.
 */
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

export const ALL_BRANCHES = "__all__";
export const GROUP_PREFIX = "__group__:";

export interface LocationGroup {
  id: string;
  name: string;
  listing_ids: string[];
  position: number;
}

export const groupValue = (id: string) => `${GROUP_PREFIX}${id}`;

export const parseGroupValue = (value: string | null | undefined): string | null =>
  value && value.startsWith(GROUP_PREFIX) ? value.slice(GROUP_PREFIX.length) : null;

/** Groups for the signed-in user. Never throws — a group-less page still works. */
export function useLocationGroups(): {
  groups: LocationGroup[];
  reload: () => Promise<void>;
} {
  const [groups, setGroups] = useState<LocationGroup[]>([]);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/locations/groups");
        if (!cancelled && Array.isArray(data)) setGroups(data as LocationGroup[]);
      } catch {
        /* groups unavailable — selectors simply list no groups */
      }
    })();
    return () => { cancelled = true; };
  }, [nonce]);

  return { groups, reload: async () => setNonce((n) => n + 1) };
}

/** Local IDs a group resolves to, in the order of `localIds`. */
export function groupTargets(
  group: LocationGroup | null,
  listingIdToLocalId: Record<string, string>,
  localIds: string[],
): string[] {
  if (!group) return [];
  const wanted = new Set(group.listing_ids);
  return localIds.filter((localId) =>
    Object.entries(listingIdToLocalId).some(
      ([listingId, mapped]) => wanted.has(listingId) && mapped === localId,
    ),
  );
}

/** How many of a group's members are currently reachable on this page. */
export function groupLiveCount(
  group: LocationGroup,
  listingIdToLocalId: Record<string, string>,
): number {
  return Object.keys(listingIdToLocalId).filter((listingId) =>
    group.listing_ids.includes(listingId),
  ).length;
}
