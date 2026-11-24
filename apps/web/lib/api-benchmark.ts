/** Benchmark API client — free Google Maps search and the tenant's saved bench. */
import { apiFetch } from "@/lib/api-rag";

export interface PlaceResult {
  place_id: string;
  name: string | null;
  address: string | null;
  rating: number | null;
  review_count: number | null;
  latitude: number | null;
  longitude: number | null;
  types: string[];
  // Canonical Maps URL from search. Carries the feature id used by the free
  // place-detail and review endpoints.
  maps_url?: string | null;
  /** Google place photo URL, used as the saved card's logo/avatar. */
  thumbnail?: string | null;
}

export interface BenchmarkSearchResponse {
  query: string;
  location: { city?: string | null; country?: string | null };
  nearby: PlaceResult[];
  other: PlaceResult[];
}

export interface PlaceDetails extends PlaceResult {
  reviews: {
    rating: number | null;
    text: string | null;
    publish_time: string | null;
    author: string | null;
    author_photo?: string | null;
    owner_answer?: string | null;
    owner_answer_time?: string | null;
    review_id?: string | null;
  }[];
  photos: { name: string; width: number | null; height: number | null }[];
  saved_id: string;
  label: string | null;
}

export interface SavedPlace {
  id: string;
  place_id: string;
  label: string | null;
  notes: string | null;
  name: string | null;
  rating: number | null;
  review_count: number | null;
  latitude: number | null;
  longitude: number | null;
  in_heatmap: boolean;
  in_bench_set: boolean;
  fetched_at: string | null;
  /** Search metadata is enough to open a card before reviews finish loading. */
  details_ready?: boolean;
  last_scrape_error: string | null;
  created_at: string | null;
  maps_url?: string | null;
  /** Google place photo URL, used as the card avatar; falls back to initials. */
  thumbnail?: string | null;
  /** Google Maps address returned by the search/scrape; shown on the card. */
  address?: string | null;
}

/** A card is usable when search metadata or a completed refresh exists, unless
 *  the last refresh failed. Older API responses fall back to `fetched_at`.
 */
export function isSavedPlaceReady(
  place: Pick<SavedPlace, "details_ready" | "fetched_at" | "last_scrape_error">,
): boolean {
  if (place.last_scrape_error) return false;
  if (typeof place.details_ready === "boolean") return place.details_ready;
  return Boolean(place.fetched_at);
}

export async function searchPlaces(query: string): Promise<BenchmarkSearchResponse> {
  // The free map RPC answers in ~2s. 30s is headroom for a slow route/proxy,
  // not the old browser-scraper's two-minute wait.
  const res = await apiFetch(
    `/api/v1/benchmark/search?q=${encodeURIComponent(query)}`,
    {},
    30000,
  ) as any;
  if (Array.isArray(res)) {
    return { query, location: {}, nearby: res, other: [] };
  }
  return {
    query: res?.query ?? query,
    location: res?.location ?? {},
    nearby: Array.isArray(res?.nearby) ? res.nearby : [],
    other: Array.isArray(res?.other) ? res.other : [],
  };
}

export function fetchSavedPlaces(): Promise<SavedPlace[]> {
  return apiFetch("/api/v1/benchmark/places");
}

export function saveBenchmarkPlace(input: {
  place_id: string;
  label?: string | null;
  notes?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  rating?: number | null;
  review_count?: number | null;
  maps_url?: string | null;
  thumbnail?: string | null;
}): Promise<SavedPlace> {
  return apiFetch("/api/v1/benchmark/places", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function setBenchmarkHeatmap(placeId: string, enabled?: boolean): Promise<SavedPlace> {
  const query = enabled === undefined ? "" : `?enabled=${enabled}`;
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}/heatmap${query}`, {
    method: "POST",
  });
}

export function setBenchmarkSet(placeId: string, enabled: boolean): Promise<SavedPlace> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}/bench-set?enabled=${enabled}`, {
    method: "POST",
  });
}

export function getBenchmarkPlaceDetails(placeId: string): Promise<PlaceDetails> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}/details`);
}

export function refreshBenchmarkPlace(placeId: string): Promise<SavedPlace> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}/refresh`, {
    method: "POST",
  });
}

export function deleteBenchmarkPlace(placeId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}`, {
    method: "DELETE",
  });
}

/* ── Two-sided comparison ─────────────────────────────────────────────── */

export type CompareKind = "saved" | "own";

/** URL-safe subject id: `saved:<place_id>` or `own:<channel_id>`. */
export function subjectKey(kind: CompareKind, id: string): string {
  return `${kind}:${id}`;
}

export interface ComparisonSubject {
  key: string;
  kind: CompareKind | "unknown";
  id: string;
  available: boolean;
  reason: string | null;
  name: string | null;
  address: string | null;
  verified: boolean;
  data_source: "google_places" | "sayvors_analytics";
  metrics: {
    total_reviews: number | null;
    reviews_last_day: number | null;
    reviews_last_week: number | null;
    reviews_last_month: number | null;
    reviews_last_year: number | null;
    avg_rating: number | null;
    total_ratings: number | null;
    five_star: number | null;
    four_star: number | null;
    one_star: number | null;
    impressions: number | null;
    calls: number | null;
    /* Period-only facts; null when the range is "live". */
    period_reviews: number | null;
    period_avg_rating: number | null;
    rating_change: number | null;
    period_impressions: number | null;
    period_calls: number | null;
  };
  facts: {
    positive_pct: number | null;
    negative_pct: number | null;
    branch: string | null;
    employee_mentions: number | null;
    working_hard_mentions: number | null;
    menu_price_mentions: number | null;
    parking_praised: number | null;
    parking_criticised: number | null;
    services: string[];
    top_problems: string[];
    named_team: { name: string; mentions: number; positive: number }[];
  };
  notes: string[];
  /** Cohort tags from the channel's metadata; own subjects only, [] otherwise. */
  tags: string[];
}

/** Period filter: live reads now; the others compute a window from history. */
export type CompareRange = "live" | "30d" | "90d" | "365d";

export const RANGE_DAYS: Record<CompareRange, number | null> = {
  live: null,
  "30d": 30,
  "90d": 90,
  "365d": 365,
};

export function fetchComparison(
  subjects: string[],
  range: CompareRange = "live"
): Promise<{ range: CompareRange; days: number | null; subjects: ComparisonSubject[]; summary: CompareSummary | null; distribution: CompareDistribution }> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  return apiFetch(`/api/v1/benchmark/compare?${q}&range=${range}`);
}

/* ── North-star summary + distribution (computed server-side) ────────── */

export type Health = "good" | "warn" | "bad";

export interface CompareSummary {
  rank: number;
  of: number;
  own: { key: string; name: string | null };
  leader: { key: string; name: string | null };
  gaps: Partial<Record<"avg_rating" | "reviews_per_month" | "total_reviews" | "positive_pct", number | null>>;
  health: Health;
}

export interface DistributionRow {
  best: { name: string; value: number };
  median: number;
  worst: { name: string; value: number };
  gap: number;
  values: number[];
  max_scale: number | null;
}

export type CompareDistribution = Record<string, DistributionRow>;

/* ── Stored history ───────────────────────────────────────────────────── */

export interface HistoryPoint {
  at: string | null;
  rating: number | null;
  reviews: number | null;
}

export interface SubjectHistory {
  key: string;
  kind: CompareKind | "unknown";
  name: string | null;
  points: HistoryPoint[];
}

export function fetchHistory(
  subjects: string[],
  days: number,
  points = 12
): Promise<{ days: number; points: number; subjects: SubjectHistory[] }> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  return apiFetch(`/api/v1/benchmark/history?${q}&days=${days}&points=${points}`);
}

/* ── Reviews table ─────────────────────────────────────────────────────── */

export interface SubjectReviews {
  key: string;
  name: string | null;
  summary: {
    total: number | null;
    sampled: number;
    answered: number;
    unanswered: number;
    response_rate: number | null;
  };
  reviews: {
    rating: number | null;
    time: string | null;
    sentiment: string;
    text: string;
    author?: string | null;
    author_photo?: string | null;
    answered: boolean;
    owner_answer?: string | null;
    owner_answer_time?: string | null;
    problems?: string[];
  }[];
}

export function fetchReviews(subjects: string[]): Promise<{ subjects: SubjectReviews[] }> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  return apiFetch(`/api/v1/benchmark/reviews?${q}`);
}

/* ── Dynamic review themes ─────────────────────────────────────────────── */

export type ReviewThemeStatus = "ready" | "pending" | "unavailable" | "error";
export type ReviewThemeSentiment = "positive" | "negative" | "mixed";

export interface ReviewThemeSubject {
  key: string;
  name: string | null;
  kind: CompareKind;
  status: ReviewThemeStatus;
  sample_size: number;
  sample_hash: string | null;
  analyzed_at: string | null;
  source?: "llm" | "local";
  error_code?: string | null;
  error_message?: string | null;
}

export interface ReviewThemeQuote {
  review_id: string;
  quote: string;
  review_text: string;
  rating: number | null;
  author: string | null;
  author_photo: string | null;
  reviewed_at: string | null;
  review_url: string | null;
}

export interface ReviewThemeCell {
  mentions: number;
  sample_size: number;
  percentage: number;
  positive: number;
  negative: number;
  quotes: ReviewThemeQuote[];
}

export interface ReviewThemeRow {
  key: string;
  label: string;
  sentiment: ReviewThemeSentiment;
  cells: Record<string, ReviewThemeCell>;
  /** Server-computed comparison values; the UI falls back to ready cells. */
  own_pct?: number | null;
  peer_median_pct?: number | null;
  gap_pct?: number | null;
}

export interface ReviewThemesResponse {
  subjects: ReviewThemeSubject[];
  rows: ReviewThemeRow[];
}

export function fetchReviewThemes(
  subjects: string[],
  mainKey: string | null,
  signal?: AbortSignal,
): Promise<ReviewThemesResponse> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  const main = mainKey ? `&main=${encodeURIComponent(mainKey)}` : "";
  return apiFetch(`/api/v1/benchmark/themes?${q}${main}`, {
    signal,
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
}

export function retryReviewThemes(
  subjects: string[],
  mainKey: string | null,
): Promise<ReviewThemesResponse> {
  return apiFetch("/api/v1/benchmark/themes/retry", {
    method: "POST",
    body: JSON.stringify({ subjects, main: mainKey }),
  });
}

/* ── AI summary (fail-open: the endpoint answers with a template fallback) ─ */

export interface AiSummaryResponse {
  summary: string;
  source: "ai" | "template";
}

/** The endpoint accepts at most 6 subjects — the picker's cap; slice anyway. */
const AI_SUMMARY_MAX_SUBJECTS = 6;

export function fetchAiSummary(subjects: string[]): Promise<AiSummaryResponse> {
  const body = JSON.stringify({ subjects: subjects.slice(0, AI_SUMMARY_MAX_SUBJECTS) });
  return apiFetch("/api/v1/benchmark/ai-summary", {
    method: "POST",
    body,
  });
}
