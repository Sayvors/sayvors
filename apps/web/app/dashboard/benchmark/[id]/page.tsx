"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useI18n } from "@/lib/i18n/I18nProvider";
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

function reviewDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function Stars({ rating }: { rating: number | null }) {
  if (rating == null || rating < 1) {
    return <span className="text-[11px] text-[#7C7392]">No rating</span>;
  }
  const clamped = Math.min(5, Math.max(1, Math.round(rating)));
  return (
    <span
      aria-label={`${clamped} out of 5 stars`}
      className="text-[13px] leading-none tracking-[0.08em] text-[#F4B400]"
    >
      {"★".repeat(clamped)}
      <span className="text-[#E9E3F3]">{"★".repeat(5 - clamped)}</span>
    </span>
  );
}

function ReviewerAvatar({ name, photo }: { name: string | null; photo?: string | null }) {
  if (photo) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={photo}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        className="h-9 w-9 shrink-0 rounded-full border border-[#3D1D6E]/10 object-cover"
      />
    );
  }
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      aria-hidden
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#E9E3F3] text-[13px] font-bold text-[#3D1D6E]"
    >
      {initial}
    </span>
  );
}

function OwnerReply({ text, at }: { text: string; at?: string | null }) {
  return (
    <div className="rounded-[8px] border-l-[3px] border-[#3D1D6E]/25 bg-[#F4F2F7] px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[#3D1D6E]">
        Response from the owner
        {at ? <span className="ml-1 font-medium normal-case tracking-normal text-[#7C7392]">· {reviewDate(at)}</span> : null}
      </p>
      <p className="mt-1 text-[12px] leading-relaxed text-[#3B2D5E]">{text}</p>
    </div>
  );
}

/** Skeleton that mirrors the loaded layout so the wait reads as structure,
 *  not a blank page. Solid white cards + pulse bars (no gradients/glass). */
function DetailSkeleton() {
  return (
    <div aria-busy="true" className="mt-5">
      <p className="flex items-center gap-2 text-[12px] font-semibold text-[#3D1D6E]">
        <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5 animate-spin" aria-hidden>
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        Loading details…
      </p>

      {/* header */}
      <div className="mt-4 space-y-2">
        <div className="h-6 w-64 max-w-full animate-pulse rounded-full bg-[#E9E3F3]" />
        <div className="h-3 w-40 max-w-full animate-pulse rounded-full bg-[#E9E3F3]" />
      </div>

      {/* compare table card */}
      <div className="mt-6 overflow-hidden rounded-[8px] border border-[#3D1D6E]/12 bg-white">
        <div className="space-y-2 border-b border-[#3D1D6E]/10 px-5 py-4">
          <div className="h-4 w-52 max-w-full animate-pulse rounded-full bg-[#E9E3F3]" />
          <div className="h-3 w-72 max-w-full animate-pulse rounded-full bg-[#E9E3F3]" />
        </div>
        <div className="space-y-3 px-5 py-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-6">
              <div className="h-3 w-28 animate-pulse rounded-full bg-[#E9E3F3]" />
              <div className="h-3 w-16 animate-pulse rounded-full bg-[#E9E3F3]" />
              <div className="h-3 w-16 animate-pulse rounded-full bg-[#E9E3F3]" />
              <div className="h-3 w-16 animate-pulse rounded-full bg-[#E9E3F3]" />
            </div>
          ))}
        </div>
      </div>

      {/* sentiment cards */}
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-3 rounded-[8px] border border-[#3D1D6E]/12 bg-white p-4">
            <div className="h-3 w-32 max-w-full animate-pulse rounded-full bg-[#E9E3F3]" />
            <div className="h-5 w-16 animate-pulse rounded-full bg-[#E9E3F3]" />
            <div className="h-2 w-full animate-pulse rounded-full bg-[#E9E3F3]" />
          </div>
        ))}
      </div>

      {/* reviews */}
      <div className="mt-6 overflow-hidden rounded-[8px] border border-[#3D1D6E]/12 bg-white">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-2 border-b border-[#3D1D6E]/8 px-5 py-4 last:border-b-0">
            <div className="h-3 w-24 animate-pulse rounded-full bg-[#E9E3F3]" />
            <div className="h-3 w-full animate-pulse rounded-full bg-[#E9E3F3]" />
            <div className="h-3 w-3/4 animate-pulse rounded-full bg-[#E9E3F3]" />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function BenchmarkDetailPage() {
  const { t } = useI18n();
  const d = t.benchmark.detail;
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
        { label: d.rating, theirs: fmt(details.rating, "★"), ours: comparisons.map((c) => fmt(c.overview?.avg_rating, "★")), betterWhenHigher: true },
        { label: d.totalReviews, theirs: fmt(details.review_count), ours: comparisons.map((c) => fmt(c.overview?.total_reviews)), betterWhenHigher: true },
        { label: d.responseRate, theirs: "—", ours: comparisons.map((c) => c.overview ? `${Math.round(c.overview.response_rate)}%` : "—"), betterWhenHigher: true },
        { label: d.positiveSentiment, theirs: "—", ours: comparisons.map((c) => c.overview ? `${Math.round(c.overview.sentiment.positive_pct)}%` : "—"), betterWhenHigher: true },
        { label: d.sentimentSplit, theirs: "—", ours: comparisons.map((c) => c.overview
          ? `${Math.round(c.overview.sentiment.positive_pct)}% / ${Math.round(c.overview.sentiment.neutral_pct)}% / ${Math.round(c.overview.sentiment.negative_pct)}%`
          : "—"), betterWhenHigher: true },
        { label: d.reputationScore, theirs: "—", ours: comparisons.map((c) => fmt(c.overview?.reputation_score)), betterWhenHigher: true },
      ]
    : [];

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <Link href="/dashboard/benchmark" className={`text-[12px] font-semibold text-[#3D1D6E] ${FOCUS}`}>
        ← Back to benchmark
      </Link>

      {detailsQuery.isPending ? (
        <DetailSkeleton />
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
                        {c.channel.display_name || d.unnamedLocation}
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

          <section className="mt-6" aria-label={d.sentimentByLocation}>
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
                      {channel.display_name || d.unnamedLocation}
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

          <section className="mt-6" aria-label={d.currentReviews}>
            <h2 className="mb-3 text-[14px] font-bold text-[#14101F]">Current reviews</h2>
            {details.reviews.length === 0 ? (
              <p className="text-[12px] text-[#3B2D5E]">No reviews returned by Google.</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {details.reviews.slice(0, 20).map((review, i) => (
                  <article
                    key={review.review_id ?? i}
                    className="flex flex-col gap-3 rounded-[8px] border border-[#3D1D6E]/12 bg-white p-4"
                  >
                    <div className="flex items-start gap-3">
                      <ReviewerAvatar name={review.author} photo={review.author_photo} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[12px] font-bold text-[#14101F]">
                          {review.author || "Google user"}
                        </p>
                        <div className="mt-1 flex items-center gap-2">
                          <Stars rating={review.rating} />
                          <span className="text-[10px] text-[#7C7392]">
                            {reviewDate(review.publish_time)}
                          </span>
                        </div>
                      </div>
                    </div>
                    {review.text ? (
                      <p className="text-[12px] leading-relaxed text-[#3B2D5E]">{review.text}</p>
                    ) : null}
                    {review.owner_answer ? (
                      <OwnerReply text={review.owner_answer} at={review.owner_answer_time} />
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>
          <p className="mt-5 text-[10px] text-[#3B2D5E]">Business data from Google Maps</p>
        </>
      )}
    </div>
  );
}
