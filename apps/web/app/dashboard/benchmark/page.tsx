"use client";

import { useCallback, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import HeatmapGrid from "@/components/benchmark/HeatmapGrid";
import OwnLocations from "@/components/benchmark/OwnLocations";
import {
  deleteBenchmarkPlace,
  fetchSavedPlaces,
  isSavedPlaceReady,
  refreshBenchmarkPlace,
  saveBenchmarkPlace,
  searchPlaces,
  setBenchmarkHeatmap,
  setBenchmarkSet,
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
  // Distinguish "the search failed / timed out" from "genuinely no matches".
  // Showing "No businesses found" for a timeout hides the real problem.
  const [searchError, setSearchError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);

  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const saved = savedQuery.data ?? [];
  const benchSetCount = saved.filter((p) => p.in_bench_set).length;

  // Search is explicit (button/Enter), never search-as-you-type. The ref guards
  // against a second submit while one is in flight — the disabled button covers
  // the UI, this covers programmatic/rapid Enter presses and stale closures.
  const searchingRef = useRef(false);

  const search = useCallback(async () => {
    const q = query.trim();
    if (q.length < 2 || searchingRef.current) return;
    searchingRef.current = true;
    setSearching(true);
    setSearched(true);
    setSearchError(null);
    try {
      setSearchRes(await searchPlaces(q));
    } catch (e) {
      // A failed/timed-out search is NOT "no matches" — say so, and keep any
      // previous results visible so the tenant isn't left with a blank page.
      setSearchError(e instanceof Error ? e.message : b.searchFailed);
    } finally {
      searchingRef.current = false;
      setSearching(false);
    }
  }, [query, b.searchFailed]);

  async function save(place: PlaceResult) {
    setBusyId(place.place_id);
    try {
      await saveBenchmarkPlace({
        place_id: place.place_id,
        label: place.name,
        latitude: place.latitude,
        longitude: place.longitude,
        rating: place.rating,
        review_count: place.review_count,
        // The Maps URL carries the feature id the free detail/review endpoints
        // use; the photo makes the saved card recognizable immediately.
        maps_url: place.maps_url,
        thumbnail: place.thumbnail,
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

  async function toggleBenchSet(place: SavedPlace) {
    setBusyId(place.place_id);
    try {
      await setBenchmarkSet(place.place_id, !place.in_bench_set);
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
    } catch {
      // A rejected toggle (e.g. losing a cap race) re-syncs the counter from
      // the server instead of failing silently.
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
              id="benchmark-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void search();
                }
              }}
              placeholder={b.searchPlaceholder}
              aria-label={b.searchAria}
              className={`min-w-0 flex-1 bg-transparent text-[13px] text-[#14101F] outline-none placeholder:text-[#3B2D5E]/70 ${FOCUS}`}
            />
            {/* Explicit submit: never search-as-you-type. The button stays
                disabled for the whole request. */}
            <button
              type="button"
              onClick={() => void search()}
              disabled={searching || query.trim().length < 2}
              aria-label={b.searchAria}
              className={`flex shrink-0 items-center justify-center gap-1.5 rounded-[8px] bg-[#3D1D6E] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
            >
              {searching ? (
                <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5 animate-spin" aria-hidden>
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
                  <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                </svg>
              ) : null}
              <span className="min-w-[52px] text-center">{searching ? b.searching : b.searchButton}</span>
            </button>
          </div>
          {searching ? (
            <p className="mt-2 text-[11px] text-[#3B2D5E]">{b.searchSlowHint}</p>
          ) : searchError ? (
            <p role="alert" className="mt-2 text-[11px] text-red-600">{searchError}</p>
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
        <h2 className="mb-1 text-[14px] font-bold text-[var(--ui-ink)]">
          {b.savedBusinesses.replace("{n}", String(saved.length))}
        </h2>
        <p className="mb-3 text-[11px] text-[#3B2D5E]">
          {b.benchSetCount.replace("{n}", String(benchSetCount)).replace("{max}", "5")}
        </p>
        {savedQuery.isPending ? (
          <p className="text-[12px] text-[var(--ui-ink-2)]">{b.loading}</p>
        ) : savedQuery.isError ? (
          <div className="rounded-[8px] border border-[#FF4F6E]/25 bg-white px-5 py-6">
            <p role="alert" className="text-[12px] font-semibold text-[#B32442]">{b.loadFailed}</p>
            <button
              type="button"
              onClick={() => void savedQuery.refetch()}
              className={`mt-3 rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
            >
              {t.common.retry}
            </button>
          </div>
        ) : saved.length === 0 ? (
          <p className="rounded-[8px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-8 text-center text-[12px] text-[var(--ui-ink-2)]">
            {b.nothingSaved}
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {saved.map((place) => {
              const ready = isSavedPlaceReady(place);
              const fetching = busyId === place.place_id;
              const name = place.label || place.name || b.savedBusiness;
              // Two-letter monogram keeps the avatar legible even for long business names.
              const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join("").toUpperCase() || "?";
              const reviewCount = place.review_count != null ? place.review_count.toLocaleString("en-US") : "—";
              const statusClass = ready
                ? "bg-[#E6F4EA] text-[#1B7A43]"
                : fetching
                  ? "bg-[#EDE6F7] text-[#3D1D6E]"
                  : "bg-[#F4F2F7] text-[#7C7392]";
              const statusDot = ready ? "bg-[#2E9E5B]" : fetching ? "bg-[#3D1D6E]" : "bg-[#9C94AE]";
              return (
              <article key={place.id} className="relative flex h-full flex-col rounded-[8px] border border-[var(--ui-line)] bg-white p-4 shadow-[0_2px_6px_rgba(20,16,31,0.05)]">
                <div className="flex items-start gap-3">
                  {/* Google-sourced logo: photo when available, monogram otherwise. */}
                  <div className="relative shrink-0">
                    <div className="flex h-[52px] w-[52px] items-center justify-center overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-[#F4F2F7]">
                      {place.thumbnail ? (
                        <img
                          src={place.thumbnail}
                          alt=""
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <span aria-hidden className="text-[16px] font-bold text-[#3D1D6E]">{initials}</span>
                      )}
                    </div>
                    {/* Official Google G — four solid colours, no gradient. */}
                    <span aria-hidden className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full border border-[var(--ui-line)] bg-white shadow-[0_1px_3px_rgba(20,16,31,0.15)]">
                      <svg viewBox="0 0 48 48" className="h-3 w-3">
                        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
                        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
                        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
                        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
                      </svg>
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    {ready ? (
                      <Link
                        href={`/dashboard/benchmark/compare?vs=${encodeURIComponent(`saved:${place.place_id}`)}`}
                        className={`block truncate text-[13px] font-bold text-[#14101F] transition hover:text-[#3D1D6E] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                      >
                        {name}
                      </Link>
                    ) : (
                      <p className="truncate text-[13px] font-bold text-[#14101F]">{name}</p>
                    )}
                    {place.address ? (
                      <p className="mt-0.5 truncate text-[11px] text-[#3B2D5E]" title={place.address}>{place.address}</p>
                    ) : null}
                    <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className="font-mono text-[17px] font-bold leading-none text-[#3D1D6E]">
                        {place.rating != null ? place.rating.toFixed(1) : "—"}<span className="text-[11px]">★</span>
                      </span>
                      <span className="text-[10px] text-[#3B2D5E]">{reviewCount} {b.reviews}</span>
                    </div>
                    <div className="mt-2">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${statusClass}`}>
                        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${statusDot}`} />
                        {ready ? b.readyToCompare : fetching ? b.fetchingDetails : b.detailsNotReady}
                      </span>
                    </div>
                  </div>
                  <div className="relative shrink-0">
                    <button
                      type="button"
                      aria-label={b.actionsFor.replace("{name}", name)}
                      aria-expanded={menuId === place.id}
                      onClick={() => setMenuId((v) => v === place.id ? null : place.id)}
                      className={`rounded-[8px] px-2 py-1 text-[15px] leading-none text-[#3B2D5E] transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                    >
                      ⋯
                    </button>
                    {menuId === place.id ? (
                      <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-[8px] border border-[var(--ui-line)] bg-white p-1 shadow-[0_2px_8px_rgba(20,16,31,0.10)]">
                        {ready ? (
                          <Link
                            href={`/dashboard/benchmark/compare?vs=${encodeURIComponent(`saved:${place.place_id}`)}`}
                            onClick={() => setMenuId(null)}
                            className={`block w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
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
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                        >
                          {place.in_heatmap ? b.removeFromHeatmap : b.addToHeatmap}
                        </button>
                        {!ready && !fetching ? (
                          <button
                            type="button"
                            onClick={() => { setMenuId(null); setBusyId(place.place_id); void refreshBenchmarkPlace(place.place_id).finally(() => { void queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] }); setBusyId(null); }); }}
                            className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                          >
                            {b.fetchDetails}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => { setMenuId(null); void remove(place.place_id); }}
                          disabled={fetching}
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-red-600 transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                        >
                          {b.removeFromBench}
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                {fetching ? (
                  <div className="mt-auto rounded-[8px] border border-[#E9E3F3] bg-[#F4F2F7] px-3 py-2">
                    <p className="text-[10px] font-semibold text-[#3D1D6E]">{b.fetchingLastWeek}</p>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#E9E3F3]"><div className="h-full w-2/3 animate-pulse rounded-full bg-[#3D1D6E]" /></div>
                  </div>
                ) : (
                  <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-[var(--ui-line)] pt-3">
                    {ready ? (
                      <Link
                        href={`/dashboard/benchmark/${encodeURIComponent(place.place_id)}`}
                        className={`rounded-[8px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white shadow-[0_1px_2px_rgba(61,29,110,0.25)] transition hover:bg-[#4A2A80] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
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
                        className={`rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                      >
                        {b.addToHeatmap}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void toggleBenchSet(place)}
                      disabled={fetching || (!place.in_bench_set && benchSetCount >= 5)}
                      title={!place.in_bench_set && benchSetCount >= 5 ? b.benchSetFull : undefined}
                      className={`rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] transition hover:bg-[#F4F2F7] active:translate-y-[2px] active:scale-[0.98] disabled:opacity-50 ${FOCUS}`}
                    >
                      {place.in_bench_set ? b.benchSetIn : b.benchSetOut}
                    </button>
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
