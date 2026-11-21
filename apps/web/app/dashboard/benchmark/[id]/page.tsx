"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { apiFetch } from "@/lib/api-rag";
import {
  getBenchmarkPlaceDetails,
  fetchSavedPlaces,
  type PlaceDetails,
} from "@/lib/api-benchmark";
import { fetchOverview, type Overview } from "@/lib/api-analytics";

interface Channel {
  id: string;
  display_name: string | null;
  platform: string;
}

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

interface Row {
  label: string;
  theirs: string;
  ours: string[];
  betterWhenHigher: boolean;
}

function fmt(value: number | null | undefined, suffix = ""): string {
  return value == null ? "—" : `${typeof value === "number" && !Number.isInteger(value) ? value.toFixed(1) : value}${suffix}`;
}

export default function BenchmarkDetailPage() {
  const params = useParams<{ id: string }>();
  const placeId = params.id;

  const detailsQuery = useQuery({
    queryKey: ["benchmark", "details", placeId],
    queryFn: () => getBenchmarkPlaceDetails(placeId),
  });

  const channelsQuery = useQuery({
    queryKey: ["benchmark", "own-locations-list"],
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100");
      return ((data.channels ?? []) as Channel[]).filter(
        (c) => c.platform === "google_reviews"
      );
    },
  });

  const selectedQuery = useQuery({
    queryKey: ["benchmark", "compare", placeId],
    queryFn: async () => {
      const channels = channelsQuery.data ?? [];
      return Promise.all(
        channels.map(async (channel) => {
          try {
            const overview = await apiFetch(
              `/api/v1/analytics/overview?days=30&channel_id=${encodeURIComponent(channel.id)}`
            ) as Overview;
            return { channel, overview };
          } catch {
            return { channel, overview: null };
          }
        })
      );
    },
    enabled: channelsQuery.isSuccess,
  });

  const details: PlaceDetails | undefined = detailsQuery.data;
  const comparisons = selectedQuery.data ?? [];

  const rows: Row[] = details
    ? [
        { label: "Rating", theirs: fmt(details.rating, "★"), ours: comparisons.map((c) => fmt(c.overview?.avg_rating, "★")), betterWhenHigher: true },
        { label: "Total reviews", theirs: fmt(details.review_count), ours: comparisons.map((c) => fmt(c.overview?.total_reviews)), betterWhenHigher: true },
        { label: "Response rate", theirs: "—", ours: comparisons.map((c) => c.overview ? `${Math.round(c.overview.response_rate)}%` : "—"), betterWhenHigher: true },
        { label: "Positive sentiment", theirs: "—", ours: comparisons.map((c) => c.overview ? `${Math.round(c.overview.sentiment.positive_pct)}%` : "—"), betterWhenHigher: true },
        { label: "Sentiment split", theirs: "—", ours: comparisons.map((c) => c.overview
          ? `${Math.round(c.overview.sentiment.positive_pct)}% / ${Math.round(c.overview.sentiment.neutral_pct)}% / ${Math.round(c.overview.sentiment.negative_pct)}%`
          : "—"), betterWhenHigher: true },
        { label: "Reputation score", theirs: "—", ours: comparisons.map((c) => fmt(c.overview?.reputation_score)), betterWhenHigher: true },
      ]
    : [];

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <Link href="/dashboard/benchmark" className={`text-[12px] font-semibold text-[#3D1D6E] ${FOCUS}`}>
        ← Back to benchmark
      </Link>

      {detailsQuery.isPending ? (
        <p className="mt-6 text-[12px] text-[#3B2D5E]">Loading details…</p>
      ) : detailsQuery.isError || !details ? (
        <p className="mt-6 text-[12px] text-red-700">Could not load this business.</p>
      ) : (
        <>
          <header className="mt-5">
            <h1 className="text-[22px] font-bold text-[#14101F] sm:text-[26px]">
              {details.name || details.label || placeId}
            </h1>
            <p className="mt-1 text-[12px] text-[#3B2D5E]">{details.address}</p>
          </header>

          <section className="mt-6 overflow-hidden rounded-[8px] border border-[#3D1D6E]/12 bg-white">
            <div className="border-b border-[#3D1D6E]/10 px-5 py-4">
              <h2 className="text-[14px] font-bold text-[#14101F]">
                Compare with your locations
              </h2>
              <p className="mt-0.5 text-[11px] text-[#3B2D5E]">
                Select which of your locations to include in the comparison.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]">
                <thead>
                  <tr className="border-b border-[#3D1D6E]/10 text-[10px] uppercase tracking-wide text-[#3B2D5E]">
                    <th className="px-5 py-3 font-semibold">Metric</th>
                    <th className="px-5 py-3 font-semibold">This business</th>
                    {comparisons.map((c) => (
                      <th key={c.channel.id} className="px-5 py-3 font-semibold">
                        {c.channel.display_name || "Unnamed location"}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.label} className="border-b border-[#3D1D6E]/8 last:border-b-0">
                      <td className="px-5 py-3 font-semibold text-[#14101F]">{row.label}</td>
                      <td className="px-5 py-3 font-mono font-bold text-[#3D1D6E]">{row.theirs}</td>
                      {row.ours.map((value, i) => (
                        <td key={i} className="px-5 py-3 font-mono text-[#3B2D5E]">{value}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="mt-6" aria-label="Sentiment by location">
            <h2 className="mb-3 text-[14px] font-bold text-[#14101F]">
              Sentiment &amp; positive feedback
            </h2>
            {comparisons.length === 0 ? (
              <p className="text-[12px] text-[#3B2D5E]">
                Connect a Google location to see its sentiment here.
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {comparisons.map(({ channel, overview }) => (
                  <article key={channel.id} className="rounded-[8px] border border-[#3D1D6E]/12 bg-white p-4">
                    <h3 className="truncate text-[12px] font-bold text-[#14101F]">
                      {channel.display_name || "Unnamed location"}
                    </h3>
                    {overview ? (
                      <>
                        <p className="mt-2 font-mono text-[18px] font-bold text-[#0E5C36]">
                          {Math.round(overview.sentiment.positive_pct)}%
                          <span className="ml-1 text-[10px] font-semibold text-[#3B2D5E]">positive</span>
                        </p>
                        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-[#F4F2F7]">
                          <span style={{ width: `${overview.sentiment.positive_pct}%` }} className="bg-[#0E5C36]" />
                          <span style={{ width: `${overview.sentiment.neutral_pct}%` }} className="bg-[#B0338A]" />
                          <span style={{ width: `${overview.sentiment.negative_pct}%` }} className="bg-[#FF4F6E]" />
                        </div>
                        <p className="mt-2 font-mono text-[10px] text-[#3B2D5E]">
                          {Math.round(overview.sentiment.positive_pct)}% pos · {Math.round(overview.sentiment.neutral_pct)}% neu · {Math.round(overview.sentiment.negative_pct)}% neg
                        </p>
                      </>
                    ) : (
                      <p className="mt-2 text-[11px] text-[#3B2D5E]">No sentiment data yet.</p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="mt-6" aria-label="Current reviews">
            <h2 className="mb-3 text-[14px] font-bold text-[#14101F]">Current reviews</h2>
            {details.reviews.length === 0 ? (
              <p className="text-[12px] text-[#3B2D5E]">No reviews returned by Google.</p>
            ) : (
              <ul className="divide-y divide-[#3D1D6E]/10 rounded-[8px] border border-[#3D1D6E]/12 bg-white">
                {details.reviews.slice(0, 20).map((review, i) => (
                  <li key={i} className="px-5 py-3">
                    <p className="font-mono text-[11px] font-bold text-[#3D1D6E]">
                      {review.rating != null ? `${review.rating}★` : "—"}
                      {review.publish_time ? ` · ${review.publish_time.slice(0, 10)}` : ""}
                    </p>
                    <p className="mt-1 text-[12px] leading-relaxed text-[#3B2D5E]">{review.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <p className="mt-5 text-[10px] text-[#3B2D5E]">Business data from Google Maps</p>
        </>
      )}
    </div>
  );
}
