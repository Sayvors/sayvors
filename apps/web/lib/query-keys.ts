/**
 * Centralised query keys.
 *
 * One factory per domain. Keys are arrays so TanStack can prefix-match for
 * invalidation (e.g. invalidateKeys(["channels"]) drops every channel query).
 *
 * Rule of thumb: a key is derived only from its inputs — never from component
 * state — so two components asking for the same thing share one cache entry.
 */
export const queryKeys = {
  channels: {
    all: () => ["channels"] as const,
    list: (limit = 100) => ["channels", "list", limit] as const,
    autoreply: (channelId: string) => ["channels", "autoreply", channelId] as const,
    services: (channelId: string) => ["channels", "services", channelId] as const,
    reviews: (channelId: string, status: string, limit: number) =>
      ["channels", "reviews", channelId, status, limit] as const,
  },
  meta: {
    connections: () => ["meta", "connections"] as const,
    assets: (provider: string) => ["meta", "assets", provider] as const,
  },
  localith: {
    connections: () => ["localith", "connections"] as const,
    listings: () => ["localith", "listings"] as const,
    profile: (listingId: string) => ["localith", "profile", listingId] as const,
  },
  reviewIssues: {
    all: () => ["review-issues"] as const,
    list: (status: string, ticketed: boolean, limit: number) =>
      ["review-issues", "list", status, ticketed, limit] as const,
  },
  databank: {
    all: () => ["databank"] as const,
  },
  onboarding: {
    state: () => ["onboarding", "state"] as const,
  },
  insights: {
    overview: (days: number) => ["insights", "overview", days] as const,
  },
};
