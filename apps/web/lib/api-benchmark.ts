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

export function deleteBenchmarkPlace(placeId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}`, {
    method: "DELETE",
  });
}
