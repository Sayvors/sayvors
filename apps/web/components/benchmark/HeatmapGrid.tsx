"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchSavedPlaces, type SavedPlace } from "@/lib/api-benchmark";
import VerificationBadge from "@/components/shared/VerificationBadge";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

/**
 * Mosaic geometry, not data: a stable mix of wide, tall and square tiles so
 * the board reads like a heat map rather than a spreadsheet. `dense` packing
 * closes the gaps left by the larger tiles.
 */
const SPANS = [
  "col-span-2 row-span-2",
  "col-span-1 row-span-2",
  "col-span-1 row-span-1",
  "col-span-2 row-span-1",
  "col-span-1 row-span-1",
  "col-span-1 row-span-2",
  "col-span-2 row-span-1",
  "col-span-1 row-span-1",
];

type Tone = { bg: string; fg: string; sub: string };

/**
 * Solid intensity steps from review volume — no gradients (UI rules). The
 * brightest step is reserved for genuine high-volume listings, so an empty
 * bench stays grey and a single added business lights up one tile.
 */
function toneFor(place: SavedPlace): Tone {
  const n = place.review_count ?? 0;
  if (n >= 500) {
    return { bg: "#B0338A", fg: "#FFFFFF", sub: "#FCE4F2" };
  }
  if (n >= 100) {
    return { bg: "#D8459F", fg: "#FFFFFF", sub: "#FCE4F2" };
  }
  if (n >= 20) {
    return { bg: "#F6DCEB", fg: "#14101F", sub: "#6B3F60" };
  }
  return { bg: "#F1F2F5", fg: "#14101F", sub: "#3B2D5E" };
}

function compareHref(place: SavedPlace): string {
  return `/dashboard/benchmark/compare?vs=${encodeURIComponent(`saved:${place.place_id}`)}`;
}

export default function HeatmapGrid() {
  const query = useQuery({
    queryKey: ["benchmark", "saved"],
    queryFn: fetchSavedPlaces,
  });
  const places = (query.data ?? []).filter((place) => place.in_heatmap);

  return (
    <section aria-label="Market heatmap">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">Market heatmap</h2>
        <p className="hidden text-[10px] text-[#3B2D5E] sm:block">
          Tile size is fixed · colour intensity is review volume · click a business to compare
        </p>
      </div>

      {query.isPending ? (
        <p className="text-[12px] text-[#3B2D5E]">Loading heatmap…</p>
      ) : places.length === 0 ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <div
              key={i}
              className={`min-h-[120px] rounded-[16px] border border-dashed border-[#3D1D6E]/15 bg-[#F1F2F5] ${SPANS[i]}`}
            />
          ))}
        </div>
      ) : (
        <div className="grid auto-rows-[minmax(130px,auto)] grid-flow-row-dense grid-cols-2 gap-2 sm:grid-cols-4">
          {places.slice(0, 24).map((place, index) => {
            const tone = toneFor(place);
            return (
              <Link
                key={place.id}
                href={compareHref(place)}
                style={{ backgroundColor: tone.bg, color: tone.fg }}
                className={`flex min-h-[130px] flex-col justify-between overflow-hidden rounded-[16px] border border-black/5 p-4 transition-transform active:translate-y-[2px] active:scale-[0.98] ${SPANS[index % SPANS.length]} ${FOCUS}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="max-w-[92%] text-[17px] font-bold leading-tight sm:text-[19px]">
                    {place.label || place.name || place.place_id}
                  </h3>
                  <VerificationBadge status="unstarted" compact />
                </div>

                <div className="mt-3">
                  <p className="font-mono text-[26px] font-bold leading-none sm:text-[30px]">
                    {place.rating != null ? place.rating.toFixed(1) : "—"}
                    <span aria-hidden className="ml-0.5 text-[15px]">★</span>
                  </p>
                  <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color: tone.sub }}>
                    Avg rating
                  </p>
                  <p className="mt-2 font-mono text-[13px] font-bold" style={{ color: tone.sub }}>
                    {place.review_count ?? 0} <span className="text-[10px] font-semibold">total reviews</span>
                  </p>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2" aria-label="Intensity scale">
        {["#F1F2F5", "#F6DCEB", "#D8459F", "#B0338A"].map((color) => (
          <span
            key={color}
            aria-hidden
            className="h-4 w-8 rounded-[6px] border border-[#3D1D6E]/10"
            style={{ backgroundColor: color }}
          />
        ))}
      </div>
    </section>
  );
}
