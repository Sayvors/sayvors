"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteBenchmarkPlace,
  fetchSavedPlaces,
  saveBenchmarkPlace,
  searchPlaces,
  type PlaceResult,
  type SavedPlace,
} from "@/lib/api-benchmark";
import { loadGoogleMaps } from "@/lib/google-maps";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
const FALLBACK = { lat: 24.7136, lng: 46.6753 };
const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Google Maps heatmap of the tenant's saved competitors. */
function BenchmarkHeatmap({ places }: { places: SavedPlace[] }) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const heatRef = useRef<any>(null);
  const [state, setState] = useState<"loading" | "ready" | "nokey" | "error">(
    MAPS_KEY ? "loading" : "nokey"
  );

  useEffect(() => {
    if (!MAPS_KEY) return;
    let cancelled = false;
    (async () => {
      try {
        await loadGoogleMaps(MAPS_KEY);
        if (cancelled || !mountRef.current) return;
        const g = (window as unknown as { google?: any }).google;
        if (!g?.maps?.Map || !g?.maps?.visualization?.HeatmapLayer) {
          setState("error");
          return;
        }
        mapRef.current = new g.maps.Map(mountRef.current, {
          center: FALLBACK,
          zoom: 10,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
        });
        heatRef.current = new g.maps.visualization.HeatmapLayer({ map: mapRef.current });
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (state !== "ready" || !heatRef.current || !mapRef.current) return;
    const g = (window as unknown as { google?: any }).google;
    const points = places
      .filter((p) => p.latitude != null && p.longitude != null)
      .map((p) => ({
        location: new g.maps.LatLng(p.latitude as number, p.longitude as number),
        weight: Math.min(1, Math.max(0.1, (p.review_count ?? 0) / 1000)),
      }));
    heatRef.current.setData(points);
    if (points.length > 0) {
      const bounds = new g.maps.LatLngBounds();
      points.forEach((p: any) => bounds.extend(p.location));
      mapRef.current.fitBounds(bounds, 64);
    }
  }, [places, state]);

  return (
    <div className="relative h-[420px] w-full overflow-hidden rounded-[32px] border border-[var(--ui-line)] bg-white sm:h-[520px]">
      <div ref={mountRef} className="h-full w-full" aria-label="Heatmap of saved businesses" />
      {state !== "ready" ? (
        <div className="absolute inset-0 flex items-center justify-center bg-white/90 px-6 text-center text-[12px] text-[var(--ui-ink-2)]">
          {state === "nokey"
            ? "Add a Google Maps key to show the heatmap."
            : state === "error"
            ? "The map could not load. Your saved places are still below."
            : "Loading map…"}
        </div>
      ) : places.every((p) => p.latitude == null) ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] text-[var(--ui-ink-2)]">
          Save a business to see it on the map.
        </div>
      ) : null}
    </div>
  );
}

export default function BenchmarkPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlaceResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

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
          <div className="flex items-center gap-3 rounded-[24px] border border-[var(--ui-line)] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(20,16,31,0.06)]">
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
            <ul className="mt-3 max-h-64 overflow-y-auto rounded-[24px] border border-[var(--ui-line)] bg-white text-left">
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
                    className={`shrink-0 rounded-[24px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
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

      {/* 2 — Full-width heatmap */}
      <section className="mb-6" aria-label="Market heatmap">
        <BenchmarkHeatmap places={saved} />
      </section>

      {/* 3 — Saved business cards */}
      <section aria-label="Saved businesses">
        <h2 className="mb-3 text-[14px] font-bold text-[var(--ui-ink)]">
          Saved businesses ({saved.length})
        </h2>
        {savedQuery.isPending ? (
          <p className="text-[12px] text-[var(--ui-ink-2)]">Loading…</p>
        ) : saved.length === 0 ? (
          <p className="rounded-[32px] border border-dashed border-[var(--ui-line)] bg-white px-5 py-8 text-center text-[12px] text-[var(--ui-ink-2)]">
            Nothing saved yet. Search above and add the businesses relevant to your market.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {saved.map((place) => (
              <article key={place.id} className="rounded-[32px] border border-[var(--ui-line)] bg-white p-5">
                <h3 className="truncate text-[14px] font-bold text-[var(--ui-ink)]">
                  {place.label || place.name || place.place_id}
                </h3>
                <p className="mt-0.5 truncate text-[11px] text-[var(--ui-ink-2)]">{place.place_id}</p>
                <p className="mt-4 font-mono text-[18px] font-bold text-[var(--ui-ink)]">
                  {place.rating != null ? place.rating.toFixed(1) : "—"}<span className="text-[12px]">★</span>
                </p>
                <p className="mt-1 font-mono text-[11px] text-[var(--ui-ink-2)]">
                  {place.review_count ?? "—"} reviews
                </p>
                <button
                  type="button"
                  onClick={() => void remove(place.place_id)}
                  disabled={busyId === place.place_id}
                  className={`mt-4 rounded-[24px] border border-red-400 px-3 py-1.5 text-[11px] font-bold text-red-600 disabled:opacity-50 ${FOCUS}`}
                >
                  Remove
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
