"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import HeatmapGrid from "@/components/benchmark/HeatmapGrid";
import OwnLocations from "@/components/benchmark/OwnLocations";
import {
  deleteBenchmarkPlace,
  fetchSavedPlaces,
  saveBenchmarkPlace,
  searchPlaces,
  setBenchmarkHeatmap,
  type PlaceResult,
  type SavedPlace,
} from "@/lib/api-benchmark";
const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

export default function BenchmarkPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlaceResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);

  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const saved = savedQuery.data ?? [];

  const search = useCallback(async () => {
    const q = query.trim();
    if (q.length < 2) return;
    setSearching(true);
    setSearched(true);
    try {
      setResults(await searchPlaces(q));
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, [query]);

  useEffect(() => {
    const timer = setTimeout(() => { void search(); }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  async function save(place: PlaceResult) {
    setBusyId(place.place_id);
    try {
      await saveBenchmarkPlace({
        place_id: place.place_id,
        label: place.name,
        latitude: place.latitude,
        longitude: place.longitude,
      });
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
      setResults((prev) => prev.filter((p) => p.place_id !== place.place_id));
    } catch {
      // Keep the result visible so the tenant can retry.
    } finally {
      setBusyId(null);
    }
  }

  async function toggleHeatmap(place: SavedPlace) {
    setBusyId(place.place_id);
    try {
      await setBenchmarkHeatmap(place.place_id, !place.in_heatmap);
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
    } finally {
      setBusyId(null);
    }
  }

  async function remove(placeId: string) {
    setBusyId(placeId);
    try {
      await deleteBenchmarkPlace(placeId);
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      {/* 1 — Hero: centred title, subtitle and a single search box */}
      <section className="relative mb-6 flex min-h-[42vh] flex-col items-center justify-center overflow-hidden rounded-[32px] border border-[var(--ui-line)] bg-[#F1F2F5] px-5 py-12 text-center">
        {/* Solid decorative marks only — no gradients, no blur, no glass. */}
        <span aria-hidden className="pointer-events-none absolute left-[8%] top-[14%] h-2.5 w-2.5 rounded-full bg-[#FF4F6E]" />
        <span aria-hidden className="pointer-events-none absolute right-[12%] top-[22%] h-3 w-3 rounded-full bg-[#3D1D6E]" />
        <span aria-hidden className="pointer-events-none absolute bottom-[16%] left-[16%] h-2 w-2 rounded-full bg-[#B0338A]" />
        <span aria-hidden className="pointer-events-none absolute bottom-[18%] right-[8%] h-2.5 w-2.5 rounded-full bg-[#FF6E85]" />
        <span aria-hidden className="pointer-events-none absolute right-[24%] top-[12%] h-1.5 w-1.5 rotate-45 bg-[#FF4F6E]" />

        <h1 className="relative flex items-center justify-center gap-3 text-[26px] font-bold text-[#14101F] sm:text-[32px]">
          Welcome to Benchmark
          <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-[#FF4F6E]" />
        </h1>
        <p className="relative mt-2 max-w-lg text-[12px] leading-relaxed text-[#3B2D5E] sm:text-[13px]">
          Search any business, save the ones that matter, and watch how the market moves.
        </p>

        <div className="relative mt-7 w-full max-w-xl">
          <div className="flex items-center gap-3 rounded-[16px] border border-[var(--ui-line)] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(20,16,31,0.06)]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 shrink-0 text-[#3B2D5E]" aria-hidden>
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search businesses, categories or cities"
              aria-label="Search businesses"
              className={`min-w-0 flex-1 bg-transparent text-[13px] text-[#14101F] outline-none placeholder:text-[#3B2D5E]/70 ${FOCUS}`}
            />
          </div>
          {searching ? (
            <p className="mt-2 text-[11px] text-[#3B2D5E]">Searching…</p>
          ) : searched && results.length === 0 && query.length >= 2 ? (
            <p className="mt-2 text-[11px] text-[#3B2D5E]">No businesses found.</p>
          ) : null}
          {results.length > 0 ? (
            <ul className="mt-3 max-h-64 overflow-y-auto rounded-[16px] border border-[var(--ui-line)] bg-white text-left">
              {results.map((place) => (
                <li key={place.place_id} className="flex items-center gap-3 border-b border-[var(--ui-line)] px-4 py-2.5 last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-semibold text-[#14101F]">{place.name || "Unnamed place"}</p>
                    <p className="truncate text-[11px] text-[#3B2D5E]">{place.address}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void save(place)}
                    disabled={busyId === place.place_id}
                    className={`shrink-0 rounded-[16px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
                  >
                    Save
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-[10px] text-[#3B2D5E]">Business data from Google Maps</p>
        </div>
      </section>

      {/* 2 — Heatmap: a grid of colour-coded cards; click for a snapshot modal */}
      <section className="mb-6">
        <HeatmapGrid places={saved.filter((place) => place.in_heatmap)} />
      </section>

      {/* 3 — Saved business cards */}
      <section aria-label="Saved businesses">
        <h2 className="mb-3 text-[14px] font-bold text-[var(--ui-ink)]">
          Saved businesses ({saved.length})
        </h2>
        {savedQuery.isPending ? (
          <p className="text-[12px] text-[var(--ui-ink-2)]">Loading…</p>
        ) : saved.length === 0 ? (
          <p className="rounded-[12px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-8 text-center text-[12px] text-[var(--ui-ink-2)]">
            Nothing saved yet. Search above and add the businesses relevant to your market.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {saved.map((place) => (
              <article key={place.id} className="relative rounded-[12px] border border-[var(--ui-line)] bg-white p-4">
                <div className="flex items-start gap-2">
                  <Link
                    href={`/dashboard/benchmark/${encodeURIComponent(place.place_id)}`}
                    className="min-w-0 flex-1 truncate text-[13px] font-bold text-[#14101F] hover:underline"
                  >
                    {place.label || place.name || place.place_id}
                  </Link>
                  <div className="relative shrink-0">
                    <button
                      type="button"
                      aria-label={`Actions for ${place.label || place.name || place.place_id}`}
                      aria-expanded={menuId === place.id}
                      onClick={() => setMenuId((v) => v === place.id ? null : place.id)}
                      className={`rounded-[8px] px-2 py-1 text-[15px] leading-none text-[#3B2D5E] hover:bg-[#F4F2F7] ${FOCUS}`}
                    >
                      ⋯
                    </button>
                    {menuId === place.id ? (
                      <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-[12px] border border-[var(--ui-line)] bg-white p-1 shadow-[0_2px_8px_rgba(20,16,31,0.10)]">
                        <button
                          type="button"
                          onClick={() => { setMenuId(null); void toggleHeatmap(place); }}
                          disabled={busyId === place.place_id}
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                        >
                          {place.in_heatmap ? "Remove from heatmap" : "Add to heatmap"}
                        </button>
                        <button
                          type="button"
                          onClick={() => { setMenuId(null); void remove(place.place_id); }}
                          disabled={busyId === place.place_id}
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-red-600 hover:bg-[#F4F2F7] ${FOCUS}`}
                        >
                          Remove from bench
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                <p className="mt-0.5 truncate text-[10px] text-[#3B2D5E]">{place.place_id}</p>
                <p className="mt-3 font-mono text-[17px] font-bold text-[#14101F]">
                  {place.rating != null ? place.rating.toFixed(1) : "—"}<span className="text-[11px]">★</span>
                </p>
                <p className="font-mono text-[10px] text-[#3B2D5E]">{place.review_count ?? "—"} reviews</p>
                <div className="mt-3 flex gap-2">
                  <Link
                    href={`/dashboard/benchmark/${encodeURIComponent(place.place_id)}`}
                    className={`rounded-[12px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white ${FOCUS}`}
                  >
                    Open
                  </Link>
                  {!place.in_heatmap ? (
                    <button
                      type="button"
                      onClick={() => void toggleHeatmap(place)}
                      disabled={busyId === place.place_id}
                      className={`rounded-[12px] border border-[#3D1D6E]/25 px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
                    >
                      Add to heatmap
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* 4 — Your own locations, for self-benchmarking */}
      <section className="mt-8" aria-label="Your own locations">
        <OwnLocations />
      </section>
    </div>
  );
}
