import { describe, it, expect } from "vitest";
import type { SavedPlace } from "@/lib/api-benchmark";
import {
  toneForRating,
  layoutPlaces,
  mapBounds,
} from "./heatmap-tone";

function mkPlace(over: Partial<SavedPlace> = {}): SavedPlace {
  return {
    id: over.id ?? "p",
    place_id: over.place_id ?? "pid",
    label: over.label ?? null,
    notes: over.notes ?? null,
    name: over.name ?? "Place",
    rating: over.rating ?? null,
    review_count: over.review_count ?? 0,
    latitude: over.latitude ?? null,
    longitude: over.longitude ?? null,
    in_heatmap: over.in_heatmap ?? true,
    in_bench_set: over.in_bench_set ?? false,
    fetched_at: over.fetched_at ?? null,
    last_scrape_error: over.last_scrape_error ?? null,
    created_at: over.created_at ?? null,
  };
}

describe("toneForRating", () => {
  it("5.0 is deep green", () => {
    expect(toneForRating(5).bg).toBe("#176A45");
    expect(toneForRating(5).fg).toBe("#FFFFFF");
  });
  it("4.5–4.9 is green", () => {
    expect(toneForRating(4.5).bg).toBe("#10A96B");
    expect(toneForRating(4.9).bg).toBe("#10A96B");
  });
  it("4.0–4.4 is light amber", () => {
    expect(toneForRating(4.0).bg).toBe("#F7DFA5");
    expect(toneForRating(4.4).bg).toBe("#F7DFA5");
  });
  it("3.0–3.9 is amber", () => {
    expect(toneForRating(3.0).bg).toBe("#F2B95E");
    expect(toneForRating(3.9).bg).toBe("#F2B95E");
  });
  it("below 3.0 is red", () => {
    expect(toneForRating(2.9).bg).toBe("#C0392B");
    expect(toneForRating(1.0).bg).toBe("#C0392B");
  });
  it("null is grey", () => {
    expect(toneForRating(null).bg).toBe("#F1F2F5");
  });
});

describe("layoutPlaces", () => {
  it("always returns exactly 20 slots", () => {
    expect(layoutPlaces([], "rating-desc", 1)).toHaveLength(20);
    const places = Array.from({ length: 3 }, (_, i) =>
      mkPlace({ id: `p${i}`, rating: 4 + i * 0.1, in_heatmap: true })
    );
    expect(layoutPlaces(places, "rating-desc", 1)).toHaveLength(20);
  });
  it("excludes places not pinned to the heatmap", () => {
    const places = [mkPlace({ id: "a", in_heatmap: false }), mkPlace({ id: "b", in_heatmap: true })];
    const slots = layoutPlaces(places, "rating-desc", 1);
    const real = slots.filter((s) => s.kind === "place");
    expect(real).toHaveLength(1);
    expect(real[0].place?.id).toBe("b");
  });
  it("rating-desc puts highest rating first", () => {
    const places = [
      mkPlace({ id: "low", rating: 3.0 }),
      mkPlace({ id: "high", rating: 4.9 }),
    ];
    const slots = layoutPlaces(places, "rating-desc", 1);
    expect(slots[0].place?.id).toBe("high");
    expect(slots[1].place?.id).toBe("low");
  });
  it("rating-asc puts lowest rating first", () => {
    const places = [
      mkPlace({ id: "low", rating: 3.0 }),
      mkPlace({ id: "high", rating: 4.9 }),
    ];
    const slots = layoutPlaces(places, "rating-asc", 1);
    expect(slots[0].place?.id).toBe("low");
  });
  it("caps at 20 real places", () => {
    const places = Array.from({ length: 25 }, (_, i) =>
      mkPlace({ id: `p${i}`, rating: 4.0, in_heatmap: true })
    );
    const slots = layoutPlaces(places, "rating-desc", 1);
    expect(slots.filter((s) => s.kind === "place")).toHaveLength(20);
    expect(slots.filter((s) => s.kind === "dummy")).toHaveLength(0);
  });
  it("random is stable for the same seed", () => {
    const places = Array.from({ length: 5 }, (_, i) => mkPlace({ id: `p${i}`, rating: 4.0 }));
    const a = layoutPlaces(places, "random", 42).map((s) => s.place?.id);
    const b = layoutPlaces(places, "random", 42).map((s) => s.place?.id);
    expect(a).toEqual(b);
  });
  it("map mode returns at most 20 and uses coordinates", () => {
    const places = [
      mkPlace({ id: "a", rating: 4.5, latitude: 24.7, longitude: 46.6 }),
      mkPlace({ id: "b", rating: 3.2, latitude: 24.8, longitude: 46.7 }),
    ];
    const slots = layoutPlaces(places, "map", 1);
    expect(slots.filter((s) => s.kind === "place")).toHaveLength(2);
    const bounds = mapBounds(places);
    expect(bounds).not.toBeNull();
  });
});