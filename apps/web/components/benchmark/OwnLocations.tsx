"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";

interface Channel {
  id: string;
  display_name: string | null;
  platform: string;
  place_id: string | null;
}

interface Overview {
  avg_rating: number;
  total_reviews: number;
  response_rate: number;
  reputation_score: number;
}

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

export default function OwnLocations() {
  const query = useQuery({
    queryKey: ["benchmark", "own-locations"],
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100");
      const google = ((data.channels ?? []) as Channel[]).filter(
        (c) => c.platform === "google_reviews"
      );
      const withMetrics = await Promise.all(
        google.map(async (channel) => {
          try {
            const overview = await apiFetch(
              `/api/v1/analytics/overview?days=30&channel_id=${encodeURIComponent(channel.id)}`
            ) as Overview;
            return { ...channel, overview };
          } catch {
            return { ...channel, overview: null };
          }
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
        <p className="rounded-[12px] border border-dashed border-[#3D1D6E]/20 bg-white px-5 py-8 text-center text-[12px] text-[#3B2D5E]">
          Connect a Google Business Profile to see your locations here.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {locations.map((location) => (
            <article
              key={location.id}
              className={`rounded-[12px] border border-[#3D1D6E]/10 bg-white p-4 ${FOCUS}`}
            >
              <h3 className="truncate text-[13px] font-bold text-[#14101F]">
                {location.display_name || "Unnamed location"}
              </h3>
              <p className="mt-0.5 truncate text-[10px] text-[#3B2D5E]">{location.place_id || "No place id"}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 font-mono text-[11px]">
                <div>
                  <p className="text-[9px] uppercase tracking-wide text-[#3B2D5E]">Rating</p>
                  <p className="font-bold text-[#14101F]">
                    {location.overview ? location.overview.avg_rating.toFixed(1) : "—"}★
                  </p>
                </div>
                <div>
                  <p className="text-[9px] uppercase tracking-wide text-[#3B2D5E]">Reviews</p>
                  <p className="font-bold text-[#14101F]">{location.overview?.total_reviews ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[9px] uppercase tracking-wide text-[#3B2D5E]">Replies</p>
                  <p className="font-bold text-[#14101F]">
                    {location.overview ? `${Math.round(location.overview.response_rate)}%` : "—"}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
