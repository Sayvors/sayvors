const KEY = "sayvors-admin-recent-searches";
const LIMIT = 5;

export function loadRecentSearches(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((value): value is string => typeof value === "string").slice(0, LIMIT)
      : [];
  } catch {
    return [];
  }
}

export function rememberSearch(query: string): string[] {
  const value = query.trim();
  if (!value) return loadRecentSearches();
  const next = [value, ...loadRecentSearches().filter((item) => item !== value)].slice(0, LIMIT);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* private mode — recent searches are a convenience, not a requirement */
  }
  return next;
}
