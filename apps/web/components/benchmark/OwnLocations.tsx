"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import { fetchSavedPlaces, saveBenchmarkPlace, type SavedPlace } from "@/lib/api-benchmark";
import VerificationBadge from "@/components/shared/VerificationBadge";

interface LocationWithVerification {
  id: string;
  display_name: string | null;
  platform: string;
  place_id: string | null;
  verification: string | null;
}

interface Overview {
  avg_rating: number;
  total_reviews: number;
  response_rate: number;
  reputation_score: number;
}

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

export default function OwnLocations() {
  const queryClient = useQueryClient();
  const [menuId, setMenuId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const savedQuery = useQuery({ queryKey: ["benchmark", "saved"], queryFn: fetchSavedPlaces });
  const savedPlaces: SavedPlace[] = savedQuery.data ?? [];

  const isOnHeatmap = (placeId: string | null) =>
    Boolean(placeId && savedPlaces.some((p) => p.place_id === placeId && p.in_heatmap));

  async function addToHeatmap(location: {
    id: string; display_name: string | null; place_id: string | null;
    overview: { avg_rating: number; total_reviews: number } | null;
  }) {
    if (!location.place_id) return;
    setBusyId(location.id);
    try {
      await saveBenchmarkPlace({
        place_id: location.place_id,
        label: location.display_name || "My location",
        rating: location.overview?.avg_rating ?? null,
        review_count: location.overview?.total_reviews ?? null,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["benchmark", "saved"] }),
        queryClient.invalidateQueries({ queryKey: ["benchmark", "own-locations"] }),
      ]);
    } finally {
      setBusyId(null);
    }
  }

  const query = useQuery({
    queryKey: ["benchmark", "own-locations"],
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100");
      const google = ((data.channels ?? []) as LocationWithVerification[]).filter(
        (c) => c.platform === "google_reviews"
      );
      const withMetrics = await Promise.all(
        google.map(async (channel) => {
          const [overviewResult, verificationResult] = await Promise.all([
            apiFetch(`/api/v1/analytics/overview?days=30&channel_id=${encodeURIComponent(channel.id)}`)
              .catch(() => null),
            apiFetch(`/api/v1/channels/${encodeURIComponent(channel.id)}/verification`)
              .then((v: { status?: string }) => v?.status ?? null)
              .catch(() => null),
          ]);
          return {
            ...channel,
            overview: overviewResult as Overview | null,
            verification: verificationResult,
          };
        })
      );
      return withMetrics;
    },
  });

  const locations = query.data ?? [];

  return (
    <section aria-label="Your own locations">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[14px] font-bold text-[#14101F]">Your own locations</h2>
        <p className="text-[10px] text-[#3B2D5E]">Benchmark your branches against each other</p>
      </div>

      {query.isPending ? (
        <p className="text-[12px] text-[#3B2D5E]">Loading…</p>
      ) : locations.length === 0 ? (
        <p className="rounded-[8px] border border-dashed border-[#3D1D6E]/20 bg-white px-5 py-8 text-center text-[12px] text-[#3B2D5E]">
          Connect a Google Business Profile to see your locations here.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {locations.map((location) => (
            <article
              key={location.id}
              className="relative rounded-[8px] border border-[#3D1D6E]/10 bg-white p-4"
            >
              <div className="flex items-start gap-2">
                <Link
                  href={`/dashboard/benchmark/compare?main=${encodeURIComponent(`own:${location.id}`)}`}
                  className="min-w-0 flex-1 truncate text-[14px] font-bold text-[#14101F] hover:underline"
                >
                  {location.display_name || "Unnamed location"}
                </Link>
                <VerificationBadge status={location.verification} compact />
                <div className="relative shrink-0">
                  <button
                    type="button"
                    aria-label={`Actions for ${location.display_name || "location"}`}
                    aria-expanded={menuId === location.id}
                    onClick={() => setMenuId((v) => v === location.id ? null : location.id)}
                    className={`rounded-[8px] px-2 py-1 text-[15px] leading-none text-[#3B2D5E] hover:bg-[#F4F2F7] ${FOCUS}`}
                  >
                    ⋯
                  </button>
                  {menuId === location.id ? (
                    <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-[8px] border border-[var(--ui-line)] bg-white p-1 shadow-[0_2px_8px_rgba(20,16,31,0.10)]">
                      <Link
                        href={`/dashboard/benchmark/compare?main=${encodeURIComponent(`own:${location.id}`)}`}
                        onClick={() => setMenuId(null)}
                        className={`block w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                      >
                        Compare
                      </Link>
                      <Link
                        href={`/dashboard/locations?channel=${encodeURIComponent(location.id)}`}
                        onClick={() => setMenuId(null)}
                        className={`block w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                      >
                        Open in Locations
                      </Link>
                      {location.place_id ? (
                        <a
                          href={`https://www.google.com/maps/place/?q=place_id:${encodeURIComponent(location.place_id)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={() => setMenuId(null)}
                          className={`block w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                        >
                          Open in Google Maps
                        </a>
                      ) : null}
                      {location.place_id && !isOnHeatmap(location.place_id) ? (
                        <button
                          type="button"
                          onClick={() => { setMenuId(null); void addToHeatmap(location); }}
                          disabled={busyId === location.id}
                          className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                        >
                          Add to heatmap
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => {
                          setMenuId(null);
                          setBusyId(location.id);
                          void queryClient.invalidateQueries({ queryKey: ["benchmark", "own-locations"] })
                            .finally(() => setBusyId(null));
                        }}
                        className={`w-full rounded-[8px] px-2.5 py-2 text-left text-[11px] font-semibold text-[#14101F] hover:bg-[#F4F2F7] ${FOCUS}`}
                      >
                        Refresh
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
              <p className="mt-0.5 truncate text-[10px] text-[#3B2D5E]">{location.place_id || "No place id"}</p>

              <div className="mt-4 grid grid-cols-3 gap-2">
                <div className="rounded-[8px] bg-[#F4F2F7] px-2 py-2">
                  <p className="text-[9px] uppercase tracking-wide text-[#3B2D5E]">Rating</p>
                  <p className="font-mono text-[22px] font-bold leading-tight text-[#14101F]">
                    {location.overview ? location.overview.avg_rating.toFixed(1) : "—"}<span className="text-[12px]">★</span>
                  </p>
                </div>
                <div className="rounded-[8px] bg-[#F4F2F7] px-2 py-2">
                  <p className="text-[9px] uppercase tracking-wide text-[#3B2D5E]">Reviews</p>
                  <p className="font-mono text-[22px] font-bold leading-tight text-[#14101F]">
                    {location.overview?.total_reviews ?? "—"}
                  </p>
                </div>
                <div className="rounded-[8px] bg-[#F4F2F7] px-2 py-2">
                  <p className="text-[9px] uppercase tracking-wide text-[#3B2D5E]">Replies</p>
                  <p className="font-mono text-[22px] font-bold leading-tight text-[#14101F]">
                    {location.overview ? `${Math.round(location.overview.response_rate)}%` : "—"}
                  </p>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Link
                  href={`/dashboard/locations?channel=${encodeURIComponent(location.id)}`}
                  className={`rounded-[8px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white ${FOCUS}`}
                >
                  Open
                </Link>
                <Link
                  href={`/dashboard/benchmark/compare?main=${encodeURIComponent(`own:${location.id}`)}`}
                  className={`rounded-[8px] border border-[#3D1D6E]/25 px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
                >
                  Compare
                </Link>
                {location.place_id ? (
                  !isOnHeatmap(location.place_id) ? (
                    <button
                      type="button"
                      onClick={() => void addToHeatmap(location)}
                      disabled={busyId === location.id}
                      className={`rounded-[8px] border border-[#3D1D6E]/25 px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
                    >
                      Add to heatmap
                    </button>
                  ) : (
                    <span className="text-[10px] font-semibold text-[#0E5C36]">On heatmap</span>
                  )
                ) : (
                  <span className="text-[10px] text-[#3B2D5E]" title="Google has not supplied a place id for this location">
                    No place id — cannot add
                  </span>
                )}
              </div>
              {busyId === location.id ? (
                <span className="ml-2 text-[10px] text-[#3B2D5E]">Refreshing…</span>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
