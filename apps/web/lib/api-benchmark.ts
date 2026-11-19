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

export function fetchComparison(subjects: string[]): Promise<{ subjects: ComparisonSubject[] }> {
  const q = subjects.map((s) => `subjects=${encodeURIComponent(s)}`).join("&");
  return apiFetch(`/api/v1/benchmark/compare?${q}`);
}
