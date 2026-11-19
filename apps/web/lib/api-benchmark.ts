/** Benchmark API client — live Places search and the tenant's saved bench. */
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
}

export interface PlaceDetails extends PlaceResult {
  reviews: { rating: number | null; text: string | null; publish_time: string | null; author: string | null }[];
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
  created_at: string | null;
}

export function searchPlaces(query: string): Promise<PlaceResult[]> {
  return apiFetch(`/api/v1/benchmark/search?q=${encodeURIComponent(query)}`);
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

export function getBenchmarkPlaceDetails(placeId: string): Promise<PlaceDetails> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}/details`);
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
): Promise<{ range: CompareRange; days: number | null; subjects: ComparisonSubject[] }> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  return apiFetch(`/api/v1/benchmark/compare?${q}&range=${range}`);
}

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
  reviews: {
    rating: number | null;
    time: string | null;
    sentiment: string;
    text: string;
    problems?: string[];
  }[];
}

export function fetchReviews(subjects: string[]): Promise<{ subjects: SubjectReviews[] }> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  return apiFetch(`/api/v1/benchmark/reviews?${q}`);
}
