/** Client-side helpers for the benchmark heatmap (P: fixed 20-slot sheet).

 * - `toneForRating`: rating → solid fill/text (no gradients, per UI rules).
 * - `layoutPlaces`: turns a tenant's saved places into 20 ordered slots for one
 *   of the 5 layout modes (rating-desc/asc, reviews-desc, random, map).
 * - `mapBounds`: lat/lng bounds used by map mode's graticule labels.
 *
 * Pure functions so they are unit-testable and reusable by a future
 * Google-Maps `HeatmapLayer` implementation behind the same surface.
 */
import type { SavedPlace } from "@/lib/api-benchmark";

export type HeatMode = "rating-desc" | "rating-asc" | "reviews-desc" | "random" | "map";

export interface Tone {
  bg: string;
  fg: string;
}

export interface HeatSlot {
  kind: "place" | "dummy";
  place?: SavedPlace;
}

export interface MapBounds {
  minLat: number;
  maxLat: number;
  minLng: number;
  maxLng: number;
}

/** Solid, rating-driven fill. No gradients. */
export function toneForRating(rating: number | null): Tone {
  if (rating === null) return { bg: "#F1F2F5", fg: "#3B2D5E" };
  if (rating >= 5) return { bg: "#176A45", fg: "#FFFFFF" };
  if (rating >= 4.5) return { bg: "#10A96B", fg: "#FFFFFF" };
  if (rating >= 4.0) return { bg: "#F7DFA5", fg: "#14101F" };
  if (rating >= 3.0) return { bg: "#F2B95E", fg: "#14101F" };
  return { bg: "#C0392B", fg: "#FFFFFF" };
}

function cmpNum(a: number | null, b: number | null, desc: boolean): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1; // nulls always last
  if (b === null) return -1;
  return desc ? b - a : a - b;
}

function byRatingDesc(a: SavedPlace, b: SavedPlace): number {
  return cmpNum(a.rating, b.rating, true) || cmpNum(a.review_count, b.review_count, true);
}
function byRatingAsc(a: SavedPlace, b: SavedPlace): number {
  return cmpNum(a.rating, b.rating, false) || cmpNum(a.review_count, b.review_count, true);
}
function byReviewsDesc(a: SavedPlace, b: SavedPlace): number {
  return cmpNum(a.review_count, b.review_count, true) || cmpNum(a.rating, b.rating, true);
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seededShuffle<T>(arr: T[], seed: number): T[] {
  const out = [...arr];
  const rng = mulberry32(seed);
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function mapBounds(places: SavedPlace[]): MapBounds | null {
  const pts = places.filter((p) => p.latitude != null && p.longitude != null);
  if (pts.length === 0) return null;
  return {
    minLat: Math.min(...pts.map((p) => p.latitude as number)),
    maxLat: Math.max(...pts.map((p) => p.latitude as number)),
    minLng: Math.min(...pts.map((p) => p.longitude as number)),
    maxLng: Math.max(...pts.map((p) => p.longitude as number)),
  };
}

function nearestFree(cells: (SavedPlace | null)[], row: number, col: number): number {
  let best = -1;
  let bestDist = Infinity;
  for (let i = 0; i < cells.length; i++) {
    if (cells[i] !== null) continue;
    const r = Math.floor(i / 5);
    const c = i % 5;
    const d = Math.abs(r - row) + Math.abs(c - col);
    if (d < bestDist || (d === bestDist && (best === -1 || i < best))) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}

export function mapLayout(pinned: SavedPlace[]): SavedPlace[] {
  const cells: (SavedPlace | null)[] = Array(20).fill(null);
  const withCoords = pinned.filter((p) => p.latitude != null && p.longitude != null);
  const noCoords = pinned.filter((p) => p.latitude == null || p.longitude == null);

  if (withCoords.length === 0) {
    return [...pinned].sort(byRatingDesc);
  }

  const bounds = mapBounds(withCoords)!;
  const latSpan = bounds.maxLat - bounds.minLat;
  const lngSpan = bounds.maxLng - bounds.minLng;
  const sorted = [...withCoords].sort(byRatingDesc);

  if (withCoords.length === 1) {
    cells[7] = sorted[0]; // centre-ish (row 1, col 2)
  } else {
    for (const p of sorted) {
      const col =
        lngSpan === 0 ? 2 : Math.max(0, Math.min(4, Math.floor(((p.longitude as number) - bounds.minLng) / lngSpan * 5)));
      const row =
        latSpan === 0 ? 1 : Math.max(0, Math.min(3, Math.floor(((bounds.maxLat - (p.latitude as number)) / latSpan) * 4)));
      let idx = row * 5 + col;
      if (cells[idx] !== null) idx = nearestFree(cells, row, col);
      if (idx >= 0) cells[idx] = p;
    }
  }

  for (const p of [...noCoords].sort(byRatingDesc)) {
    const free = cells.findIndex((c) => c === null);
    if (free >= 0) cells[free] = p;
  }

  return cells.filter((c): c is SavedPlace => c !== null);
}

export function layoutPlaces(places: SavedPlace[], mode: HeatMode, seed: number): HeatSlot[] {
  const pinned = places.filter((p) => p.in_heatmap);
  let ordered: SavedPlace[];
  switch (mode) {
    case "rating-asc":
      ordered = [...pinned].sort(byRatingAsc);
      break;
    case "reviews-desc":
      ordered = [...pinned].sort(byReviewsDesc);
      break;
    case "random":
      ordered = seededShuffle(pinned, seed);
      break;
    case "map":
      ordered = mapLayout(pinned);
      break;
    default:
      ordered = [...pinned].sort(byRatingDesc);
      break;
  }
  const real = ordered.slice(0, 20);
  const slots: HeatSlot[] = real.map((place) => ({ kind: "place", place }));
  while (slots.length < 20) slots.push({ kind: "dummy" });
  return slots;
}