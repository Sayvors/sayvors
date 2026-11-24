"use client";

import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteBenchmarkPlace,
  fetchSavedPlaces,
  refreshBenchmarkPlace,
  saveBenchmarkPlace,
  searchPlaces,
  type BenchmarkSearchResponse,
  type PlaceResult,
} from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ink)]";

export default function CompetitorBench() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [searchRes, setSearchRes] = useState<BenchmarkSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const saved = savedQuery.data ?? [];

  const search = useCallback(async () => {
    const q = query.trim();
    if (q.length < 2) return;
    setSearching(true);
    setSearchError(null);
    setSearched(true);
    try {
      setSearchRes(await searchPlaces(q));
    } catch (e) {
      setSearchRes({ query: q, location: {}, nearby: [], other: [] });
      setSearchError(e instanceof Error ? e.message : "Search failed");
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
        maps_url: place.maps_url,
        thumbnail: place.thumbnail,
        rating: place.rating,
        review_count: place.review_count,
        latitude: place.latitude,
        longitude: place.longitude,
      });
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
      setSearchRes((prev) => prev ? { ...prev, nearby: prev.nearby.filter((p) => p.place_id !== place.place_id), other: prev.other.filter((p) => p.place_id !== place.place_id) } : prev);
      await refreshBenchmarkPlace(place.place_id);
      await queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] });
    } catch {
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
    <section className="ui-card mb-5 p-4 sm:p-5" aria-label="Competitor bench">
      <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">Find and save competitors</h2>
      <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
        Search any business by name, category or city. Save the relevant ones to benchmark them against your own.
      </p>

      <label className="mt-4 block text-[11px] font-semibold text-[var(--ui-ink-2)]">
        Search
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="restaurant near me, hospitals in Riyadh, banks in Malaz"
          className={`mt-2 w-full rounded-[8px] border border-[var(--ui-line)] bg-white px-4 py-3 text-[13px] text-[var(--ink)] ${FOCUS}`}
        />
      </label>

      {searchError ? <p role="alert" className="mt-3 text-[12px] text-red-600">{searchError}</p> : null}
      {searching ? <p className="mt-3 text-[12px] text-[var(--ui-ink-2)]">Searching…</p> : null}
      {searched && !searching && (searchRes?.nearby.length ?? 0) === 0 && (searchRes?.other.length ?? 0) === 0 && !searchError ? (
        <p className="mt-3 text-[12px] text-[var(--ui-ink-2)]">No businesses found. Try a different phrase or city.</p>
      ) : null}

      {(searchRes?.nearby.length || searchRes?.other.length) ? (
        <div className="mt-3 rounded-[8px] border border-[var(--ui-line)] bg-white">
          {searchRes?.nearby.length ? (
            <div>
              <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wide text-[#3D1D6E]">
                Nearby{searchRes.location?.city ? ` · ${searchRes.location.city}` : searchRes.location?.country ? ` · ${searchRes.location.country}` : ""}
              </p>
              <ul className="divide-y divide-[var(--ui-line)]">
                {searchRes.nearby.map((place) => (
                  <li key={place.place_id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-semibold text-[var(--ui-ink)]">{place.name || "Unnamed place"}</p>
                      <p className="truncate text-[11px] text-[var(--ui-ink-2)]">{place.address}</p>
                      <p className="mt-0.5 text-[10px] text-[var(--ui-ink-2)]">{place.rating != null ? `${place.rating.toFixed(1)}★` : "—"} · {place.review_count ?? "—"} reviews</p>
                    </div>
                    {busyId === place.place_id ? (
                      <div className="w-32 shrink-0">
                        <p className="text-[10px] font-semibold text-[#3D1D6E]">Fetching details…</p>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#E9E3F3]"><div className="h-full w-2/3 animate-pulse rounded-full bg-[#3D1D6E]" /></div>
                      </div>
                    ) : (
                      <button type="button" onClick={() => void save(place)} disabled={!!busyId} className={`rounded-[8px] bg-[var(--ink)] px-4 py-2 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}>Save</button>
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
                Other locations{searchRes.location?.country ? ` · ${searchRes.location.country}` : ""}
              </span>
              <div className="h-px flex-1 bg-[var(--ui-line)]" />
            </div>
          ) : null}
          {searchRes?.other.length ? (
            <ul className="divide-y divide-[var(--ui-line)]">
              {searchRes.other.map((place) => (
                <li key={place.place_id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold text-[var(--ui-ink)]">{place.name || "Unnamed place"}</p>
                    <p className="truncate text-[11px] text-[var(--ui-ink-2)]">{place.address}</p>
                    <p className="mt-0.5 text-[10px] text-[var(--ui-ink-2)]">{place.rating != null ? `${place.rating.toFixed(1)}★` : "—"} · {place.review_count ?? "—"} reviews</p>
                  </div>
                  {busyId === place.place_id ? (
                    <div className="w-32 shrink-0">
                      <p className="text-[10px] font-semibold text-[#3D1D6E]">Fetching details…</p>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#E9E3F3]"><div className="h-full w-2/3 animate-pulse rounded-full bg-[#3D1D6E]" /></div>
                    </div>
                  ) : (
                    <button type="button" onClick={() => void save(place)} disabled={!!busyId} className={`rounded-[8px] bg-[var(--ink)] px-4 py-2 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}>Save</button>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="mt-5 border-t border-[var(--ui-line)] pt-4">
        <h3 className="text-[12px] font-bold text-[var(--ui-ink)]">Your bench ({saved.length})</h3>
        {savedQuery.isPending ? (
          <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">Loading…</p>
        ) : saved.length === 0 ? (
          <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">
            Nothing saved yet. Only save businesses relevant to your own category and location.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-[var(--ui-line)]">
            {saved.map((place) => {
              const ready = Boolean(place.fetched_at) && !place.last_scrape_error;
              const fetching = busyId === place.place_id;
              return (
              <li key={place.id} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-semibold text-[var(--ui-ink)]">{place.label || place.name || "Saved business"}</p>
                  <p className="text-[10px] text-[var(--ui-ink-2)]">{ready ? "Ready to compare" : fetching ? "Fetching details…" : "Details not ready"}</p>
                  <p className="font-mono text-[11px] text-[var(--ui-ink)]">
                    {place.rating != null ? place.rating.toFixed(1) : "—"}★ · {place.review_count ?? "—"} reviews
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void remove(place.place_id)}
                  disabled={fetching}
                  className={`rounded-[8px] border border-red-400 px-3 py-1.5 text-[11px] font-bold text-red-600 disabled:opacity-50 ${FOCUS}`}
                >
                  Remove
                </button>
              </li>
              );
            })}
          </ul>
        )}
      </div>
      <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">Business data from Google Maps</p>
    </section>
  );
}
