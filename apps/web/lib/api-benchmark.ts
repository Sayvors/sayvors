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
}): Promise<SavedPlace> {
  return apiFetch("/api/v1/benchmark/places", {
    method: "POST",
    body: JSON.stringify(input),
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
