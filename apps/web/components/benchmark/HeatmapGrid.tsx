"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchSavedPlaces, type SavedPlace } from "@/lib/api-benchmark";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";
import {
  HeatMode,
  layoutPlaces,
  toneForRating,
} from "@/lib/heatmap-tone";
import BenchmarkMap from "@/components/benchmark/BenchmarkMap";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";
const MODES: HeatMode[] = ["rating-desc", "rating-asc", "reviews-desc", "random", "map"];
const SLOT_COUNT = 20;

function modeLabel(b: Dict["benchmark"], m: HeatMode): string {
  switch (m) {
    case "rating-asc":
      return b.heatmapModeRatingAsc ?? "Lowest first";
    case "reviews-desc":
      return b.heatmapModeReviewsDesc ?? "Most reviewed";
    case "random":
      return b.heatmapModeRandom ?? "Random";
    case "map":
      return b.heatmapModeMap ?? "Map";
    default:
      return b.heatmapModeRatingDesc ?? "Best rated first";
  }
}

function compareHref(place: SavedPlace): string {
  return `/dashboard/benchmark/compare?vs=${encodeURIComponent(`saved:${place.place_id}`)}`;
}

function AddLocationTile({ label }: { label: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        const el = document.getElementById("benchmark-search") as HTMLInputElement | null;
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          window.setTimeout(() => el.focus(), 250);
        }
      }}
      className={`flex min-h-[120px] flex-col items-center justify-center gap-2 rounded-[8px] border border-dashed border-[#3D1D6E]/30 bg-[#F1F2F5] text-[#3B2D5E] transition-transform active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
      aria-label={label}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-6 w-6" aria-hidden>
        <path d="M12 5v14M5 12h14" strokeLinecap="round" />
      </svg>
      <span className="text-[11px] font-semibold">{label}</span>
    </button>
  );
}

export default function HeatmapGrid() {
  const { t } = useI18n();
  const b = t.benchmark;
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawMode = searchParams.get("heat") as HeatMode | null;
  const mode: HeatMode = rawMode && MODES.includes(rawMode) ? rawMode : "rating-desc";
  const [seed, setSeed] = useState(() => Date.now());

  const query = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const places = query.data ?? [];
  const pinned = places.filter((p) => p.in_heatmap);
  const slots = useMemo(() => layoutPlaces(places, mode, seed), [places, mode, seed]);

  const setMode = (m: HeatMode) => {
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("heat", m);
    router.replace(`?${sp.toString()}`, { scroll: false });
  };

  if (query.isPending) {
    return (
      <section aria-label={b.marketHeatmap} className="mb-6">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">{b.marketHeatmap}</h2>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-5">
          {Array.from({ length: SLOT_COUNT }, (_, i) => (
            <div key={i} className="min-h-[120px] animate-pulse rounded-[8px] bg-[#F1F2F5]" />
          ))}
        </div>
      </section>
    );
  }

  if (query.isError) {
    return (
      <section aria-label={b.marketHeatmap} className="mb-6">
        <h2 className="mb-3 text-[14px] font-bold text-[var(--ui-ink)]">{b.marketHeatmap}</h2>
        <div className="rounded-[8px] border border-[#FF4F6E]/25 bg-white px-5 py-6">
          <p role="alert" className="text-[12px] font-semibold text-[#B32442]">{b.loadFailed}</p>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className={`mt-3 rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
          >
            {t.common.retry}
          </button>
        </div>
      </section>
    );
  }

  const showing = Math.min(pinned.length, SLOT_COUNT);

  return (
    <section aria-label={b.marketHeatmap} className="mb-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">{b.marketHeatmap}</h2>
          <p className="text-[10px] text-[#3B2D5E]">{b.heatmapHint}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 overflow-x-auto rounded-[8px] border border-[var(--ui-line)] bg-white p-1">
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={`whitespace-nowrap rounded-[6px] px-2.5 py-1 text-[11px] font-semibold transition-colors ${FOCUS} ${
                  mode === m ? "bg-[#3D1D6E] text-white" : "text-[#3B2D5E] hover:bg-[#F4F2F7]"
                }`}
              >
                {modeLabel(b, m)}
              </button>
            ))}
          </div>
          {mode === "random" && (
            <button
              type="button"
              onClick={() => setSeed(Date.now())}
              className={`rounded-[8px] border border-[#3D1D6E]/25 px-2.5 py-1 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
            >
              {b.heatmapShuffle ?? "Shuffle"}
            </button>
          )}
        </div>
      </div>

      {pinned.length > SLOT_COUNT && (
        <p className="mb-2 text-[10px] text-[#3B2D5E]">
          {(b.heatmapShowing ?? "Showing {n} of {total}")
            .replace("{n}", String(showing))
            .replace("{total}", String(pinned.length))}
        </p>
      )}

      {mode === "map" ? (
        <BenchmarkMap
          places={pinned}
          apiKey={process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? ""}
        />
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-5">
          {slots.map((slot, i) => {
            if (slot.kind === "dummy") {
              return <AddLocationTile key={`dummy-${i}`} label={b.heatmapAddLocation ?? "Add location"} />;
            }
            const p = slot.place as SavedPlace;
            const tone = toneForRating(p.rating);
            return (
              <Link
                key={p.id}
                href={compareHref(p)}
                aria-label={`${p.label || p.name || p.place_id}: ${p.rating != null ? p.rating.toFixed(1) : "—"} stars, ${p.review_count ?? 0} reviews`}
                style={{ backgroundColor: tone.bg, color: tone.fg }}
                className={`flex min-h-[120px] flex-col justify-between overflow-hidden rounded-[8px] border border-black/5 p-3 transition-transform active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
              >
                <h3 className="truncate text-[12px] font-bold leading-tight">
                  {p.label || p.name || p.place_id}
                </h3>
                <div>
                  <p className="font-mono text-[24px] font-bold leading-none">
                    {p.rating != null ? p.rating.toFixed(1) : "—"}
                    <span aria-hidden className="ms-0.5 text-[13px]">★</span>
                  </p>
                  <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color: tone.fg, opacity: 0.85 }}>
                    {p.rating != null ? (b.avgRating ?? "Avg rating") : (b.heatmapNoRating ?? "No rating")}
                  </p>
                  <p className="mt-2 font-mono text-[12px] font-bold" style={{ color: tone.fg, opacity: 0.9 }}>
                    {p.review_count ?? 0} <span className="text-[9px] font-semibold">{b.reviews ?? "reviews"}</span>
                  </p>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {mode !== "map" ? (
        <div className="mt-4 flex flex-wrap items-center gap-2" aria-label={b.marketHeatmap}>
          {[
            { color: "#C0392B", label: "< 3.0" },
            { color: "#F2B95E", label: "3.0–3.9" },
            { color: "#F7DFA5", label: "4.0–4.4" },
            { color: "#10A96B", label: "4.5–4.9" },
            { color: "#176A45", label: "5.0" },
            { color: "#F1F2F5", label: b.heatmapNoRating ?? "No rating" },
          ].map(({ color, label }) => (
            <span key={label} className="flex items-center gap-1.5">
              <span aria-hidden className="h-4 w-6 rounded-[4px] border border-[#3D1D6E]/10" style={{ backgroundColor: color }} />
              <span className="text-[10px] text-[#3B2D5E]">{label}</span>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}