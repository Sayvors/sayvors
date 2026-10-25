"use client";

import { QueryClient } from "@tanstack/react-query";

/**
 * Shared QueryClient defaults for the whole dashboard.
 *
 * - `staleTime` of 30s means a navigation back to a page that was visited
 *   in the last half-minute reuses the cache instead of re-fetching; this is
 *   the direct fix for the "refetch storm" the readiness report calls out.
 * - `gcTime` of 5 min keeps inactive data warm long enough to feel instant
 *   when the user bounces between views, but bounded so memory stays flat.
 * - `refetchOnWindowFocus` off: a returning tab should not hammer the API
 *   with a full re-fetch of every mounted query.
 * - `retry` 1: fail fast on a dead endpoint instead of hammering it 3x.
 * - `refetchOnMount` 'always' would defeat the cache; default ('stale') is
 *   fine and lets a fresh mount skip the fetch when data is still fresh.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30 * 1000,
        gcTime: 5 * 60 * 1000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        retry: 1,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 5000),
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
