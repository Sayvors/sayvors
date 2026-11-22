"use client";

import { useCallback, useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import HeatmapGrid from "@/components/benchmark/HeatmapGrid";
import OwnLocations from "@/components/benchmark/OwnLocations";
import {
  deleteBenchmarkPlace,
  fetchSavedPlaces,
  refreshBenchmarkPlace,
  saveBenchmarkPlace,
  searchPlaces,
  setBenchmarkHeatmap,
  type BenchmarkSearchResponse,
  type PlaceResult,
  type SavedPlace,
} from "@/lib/api-benchmark";
const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

export default function BenchmarkPage() {
  const { t } = useI18n();
  const b = t.benchmark;
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [searchRes, setSearchRes] = useState<BenchmarkSearchResponse | null>(null);
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
      setSearchRes(await searchPlaces(q));
    } catch {
      setSearchRes({ query: q, location: {}, nearby: [], other: [] });
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
      setSearchRes((prev) => prev ? {
        ...prev,
        nearby: prev.nearby.filter((p) => p.place_id !== place.place_id),
        other: prev.other.filter((p) => p.place_id !== place.place_id),
      } : prev);
      // Fetch last-week details (cost-capped) so the card becomes ready to compare.
      await refreshBenchmarkPlace(place.place_id);
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
    } catch {
      // Keep the result visible so the tenant can retry; saved card may be not ready.
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
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
      <section className="relative mb-6 flex min-h-[42vh] flex-col items-center justify-center overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-[#F1F2F5] px-5 py-12 text-center">
        {/* Solid decorative marks only — no gradients, no blur, no glass. */}
        <span aria-hidden className="pointer-events-none absolute left-[8%] top-[14%] h-2.5 w-2.5 rounded-full bg-[#FF4F6E]" />
        <span aria-hidden className="pointer-events-none absolute right-[12%] top-[22%] h-3 w-3 rounded-full bg-[#3D1D6E]" />
        <span aria-hidden className="pointer-events-none absolute bottom-[16%] left-[16%] h-2 w-2 rounded-full bg-[#B0338A]" />
        <span aria-hidden className="pointer-events-none absolute bottom-[18%] right-[8%] h-2.5 w-2.5 rounded-full bg-[#FF6E85]" />
        <span aria-hidden className="pointer-events-none absolute right-[24%] top-[12%] h-1.5 w-1.5 rotate-45 bg-[#FF4F6E]" />

        <h1 className="relative flex items-center justify-center gap-3 text-[26px] font-bold text-[#14101F] sm:text-[32px]">
          {b.title}
          <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-[#FF4F6E]" />
        </h1>
        <p className="relative mt-2 max-w-lg text-[12px] leading-relaxed text-[#3B2D5E] sm:text-[13px]">
          {b.subtitle}
        </p>

        <div className="relative mt-7 w-full max-w-xl">
          <div className="flex items-center gap-3 rounded-[8px] border border-[var(--ui-line)] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(20,16,31,0.06)]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 shrink-0 text-[#3B2D5E]" aria-hidden>
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={b.searchPlaceholder}
              aria-label={b.searchAria}
              className={`min-w-0 flex-1 bg-transparent text-[13px] text-[#14101F] outline-none placeholder:text-[#3B2D5E]/70 ${FOCUS}`}
            />
          </div>
          {searching ? (
            <p className="mt-2 text-[11px] text-[#3B2D5E]">{b.searching}</p>
          ) : searched && (searchRes?.nearby.length ?? 0) === 0 && (searchRes?.other.length ?? 0) === 0 && query.length >= 2 ? (
            <p className="mt-2 text-[11px] text-[#3B2D5E]">{b.noBusinessesFound}</p>
          ) : null}
          {(searchRes?.nearby.length || searchRes?.other.length) ? (
            <div className="mt-3 max-h-80 overflow-y-auto rounded-[8px] border border-[var(--ui-line)] bg-white text-left">
              {searchRes?.nearby.length ? (
                <div>
                  <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wide text-[#3D1D6E]">
                    {b.nearby}{searchRes.location?.city ? ` · ${searchRes.location.city}` : searchRes.location?.country ? ` · ${searchRes.location.country}` : ""}
                  </p>
                  <ul>
                    {searchRes.nearby.map((place) => (
                      <li key={place.place_id} className="flex items-center gap-3 border-b border-[var(--ui-line)] px-4 py-2.5 last:border-b-0">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[12px] font-semibold text-[#14101F]">{place.name || b.unnamedPlace}</p>
                          <p className="truncate text-[11px] text-[#3B2D5E]">{place.address}</p>
                          <p className="mt-0.5 text-[10px] text-[#3B2D5E]/80">{place.rating != null ? `${place.rating.toFixed(1)}★` : "—"} · {place.review_count ?? "—"} {b.reviews}</p>
                        </div>
                        {busyId === place.place_id ? (
                          <div className="w-32 shrink-0">
                            <p className="text-[10px] font-semibold text-[#3D1D6E]">{b.fetchingDetails}</p>
                            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#E9E3F3]"><div className="h-full w-2/3 animate-pulse rounded-full bg-[#3D1D6E]" /></div>
                          </div>
                        ) : (
                          <button type="button" onClick={() => void save(place)} disabled={!!busyId} className={`shrink-0 rounded-[8px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-50 ${FOCUS}`}>{b.save}</button>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {searchRes?.nearby.length && searchRes?.other.length ? (
                <div className="flex items-center gap-3 px-4 py-2">
                  <div className="h-px flex-1 bg-[var(--ui-line)]" />
                  <span className="text-[10px] font-bold uppercase tracking-wide text-[#7C7392]">
                    {b.otherLocations}{searchRes.location?.country ? ` · ${searchRes.location.country}` : ""}
                  </span>
                  <div className="h-px flex-1 bg-[var(--ui-line)]" />
                </div>
              ) : null}
              {searchRes?.other.length ? (
                <ul>
                  {searchRes.other.map((place) => (
                    <li key={place.place_id} className="flex items-center gap-3 border-b border-[var(--ui-line)] px-4 py-2.5 last:border-b-0">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[12px] font-semibold text-[#14101F]">{place.name || b.unnamedPlace}</p>
                        <p className="truncate text-[11px] text-[#3B2D5E]">{place.address}</p>
                        <p className="mt-0.5 text-[10px] text-[#3B2D5E]/80">{place.rating != null ? `${place.rating.toFixed(1)}★` : "—"} · {place.review_count ?? "—"} {b.reviews}</p>
                      </div>
                      {busyId === place.place_id ? (
                        <div className="w-32 shrink-0">
                          <p className="text-[10px] font-semibold text-[#3D1D6E]">{b.fetchingDetails}</p>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#E9E3F3]"><div className="h-full w-2/3 animate-pulse rounded-full bg-[#3D1D6E]" /></div>
                        </div>
                      ) : (
                        <button type="button" onClick={() => void save(place)} disabled={!!busyId} className={`shrink-0 rounded-[8px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-50 ${FOCUS}`}>{b.save}</button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <p className="mt-2 text-[10px] text-[#3B2D5E]">{b.dataFromGoogleMaps}</p>
        </div>
      </section>

      {/* 2 — Heatmap: a grid of colour-coded cards; click for a snapshot modal */}
      <section className="mb-6">
        <HeatmapGrid />
      </section>

      {/* 3 — Saved business cards */}
      <section aria-label={b.savedBusinesses.replace("{n}", String(saved.length))}>
        <h2 className="mb-3 text-[14px] font-bold text-[var(--ui-ink)]">
          {b.savedBusinesses.replace("{n}", String(saved.length))}
        </h2>
        {savedQuery.isPending ? (
          <p className="text-[12px] text-[var(--ui-ink-2)]">{b.loading}</p>
        ) : saved.length === 0 ? (
          <p className="rounded-[8px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-8 text-center text-[12px] text-[var(--ui-ink-2)]">
            {b.nothingSaved}
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {saved.map((place) => {
              const ready = Boolean(place.fetched_at) && !place.last_scrape_error;
              const fetching = busyId === place.place_id;
              const name = place.label || place.name || b.savedBusiness;
              return (
              <article key={place.id} className="relative rounded-[8px] border border-[var(--ui-line)] bg-white p-4">
                <div className="flex items-start gap-2">
                  {ready ? (
                    <Link
                      href={`/dashboard/benchmark/compare?vs=${encodeURIComponent(`saved:${place.place_id}`)}`}
                      className="min-w-0 flex-1 truncate text-[13px] font-bold text-[#14101F] hover:underline"
                    >
                      {name}
                    </Link>
                  ) : (
                    <p className="min-w-0 flex-1 truncate text-[13px] font-bold text-[#14101F]">{name}</p>
                  )}
                  <div className="relative shrink-0">
                    <button
                      type="button"
                      aria-label={b.actionsFor.replace("{name}", name)}
                      aria-expanded={menuId === place.id}
                      onClick={() => setMenuId((v) => v === place.id ? null : place.id)}
                      className={`rounded-[8px] px-2 py-1 text-[15px] leading-none text-[#3B2D5E] hover:bg-[#F4F2F7] ${FOCUS}`}
                    >
                      ⋯
                    </button>
                    {menuId === place.id ? (
                      <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-[8px] border border-[var(--ui-line)] bg-white p-1 shadow-[0_2px_8px_rgba(20,16,31,0.10)]">
                        {ready ? (
                          <Link
                            href={`/dashboard/benchmark/compare?vs=${encodeURIComponent(`saved:${place.place_id}`)}`}
                            onClick={() => setMenuId(null)}
                            className={`block w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                          >
                            {b.compareAction}
                          </Link>
                        ) : (
                          <button type="button" disabled className="w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#7C7392]">{b.compareNotReady}</button>
                        )}
                        <button
                          type="button"
                          onClick={() => { setMenuId(null); void toggleHeatmap(place); }}
                          disabled={fetching}
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                        >
                          {place.in_heatmap ? b.removeFromHeatmap : b.addToHeatmap}
                        </button>
                        {!ready && !fetching ? (
                          <button
                            type="button"
                            onClick={() => { setMenuId(null); setBusyId(place.place_id); void refreshBenchmarkPlace(place.place_id).finally(() => { void queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] }); setBusyId(null); }); }}
                            className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                          >
                            {b.fetchDetails}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => { setMenuId(null); void remove(place.place_id); }}
                          disabled={fetching}
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-red-600 hover:bg-[#F4F2F7] ${FOCUS}`}
                        >
                          {b.removeFromBench}
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                <p className="mt-0.5 truncate text-[10px] text-[#3B2D5E]">{ready ? b.readyToCompare : fetching ? b.fetchingDetails : b.detailsNotReady}</p>
                <p className="mt-3 font-mono text-[17px] font-bold text-[#14101F]">
                  {place.rating != null ? place.rating.toFixed(1) : "—"}<span className="text-[11px]">★</span>
                </p>
                <p className="font-mono text-[10px] text-[#3B2D5E]">{place.review_count ?? "—"} {b.reviews}</p>
                {fetching ? (
                  <div className="mt-3">
                    <p className="text-[10px] font-semibold text-[#3D1D6E]">{b.fetchingLastWeek}</p>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#E9E3F3]"><div className="h-full w-2/3 animate-pulse rounded-full bg-[#3D1D6E]" /></div>
                  </div>
                ) : (
                  <div className="mt-3 flex gap-2">
                    {ready ? (
                      <Link
                        href={`/dashboard/benchmark/${encodeURIComponent(place.place_id)}`}
                        className={`rounded-[8px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white ${FOCUS}`}
                      >
                        {b.open}
                      </Link>
                    ) : (
                      <button type="button" disabled className="rounded-[8px] bg-[#3D1D6E]/40 px-3 py-1.5 text-[11px] font-bold text-white">{b.open}</button>
                    )}
                    {!place.in_heatmap ? (
                      <button
                        type="button"
                        onClick={() => void toggleHeatmap(place)}
                        disabled={fetching}
                        className={`rounded-[8px] border border-[#3D1D6E]/25 px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
                      >
                        {b.addToHeatmap}
                      </button>
                    ) : null}
                  </div>
                )}
              </article>
              );
            })}
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
