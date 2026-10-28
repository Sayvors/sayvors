"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import Link from "next/link";
import { apiFetch } from "@/lib/api-rag";
import { dedupeBusinesses } from "@/lib/channel-identity";
import {
  fetchOverview,
  fetchTimeseries,
} from "@/lib/api-analytics";
import { StatCard } from "@/components/analytics/StatCard";
import MessagingSection from "@/components/analytics/MessagingSection";
import { MetricChart, RatingDistribution, SentimentSplitBar } from "@/components/analytics/Charts";
import PulseCards from "@/components/analytics/PulseCards";
import { ReviewInbox } from "@/components/analytics/ReviewInbox";
import PresenceSection, {
  presenceFromProfile,
  type PresenceData,
} from "@/components/analytics/PresenceSection";
import { useI18n } from "@/lib/i18n/I18nProvider";

/* The Overview tab: controls + messaging rollup cards + Google reviews KPIs,
 * charts and the review inbox. Lives in components/ because the page file
 * was getting too big — the shell in app/dashboard/analytics/page.tsx just
 * picks tabs now.
 *
 * Theme: the Team page's flat system. The .team-ui ancestor (which defines
 * the --ui-* vars and paints the #F5F5F5 page) lives on the analytics shell;
 * this panel and everything it renders consume the vars. Three colours only:
 * ink, surface, sunken — status by weight and inversion, never by hue. */

const RANGES = [7, 30, 90] as const;

function fmtDuration(seconds: number | null, locale: string, labels: { minutes: string; hours: string; days: string }) {
  if (seconds === null) return "—";
  const number = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
  if (seconds < 3600) return labels.minutes.replace("{value}", number(Math.round(seconds / 60)));
  if (seconds < 86_400) return labels.hours.replace("{value}", number(Number((seconds / 3600).toFixed(1))));
  return labels.days.replace("{value}", number(Number((seconds / 86_400).toFixed(1))));
}

export default function OverviewPanel() {
  const { t, locale } = useI18n();
  const copy = t.analytics.kpis;
  const queryClient = useQueryClient();
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  // Messaging section reports back once its fetch settles, so the empty
  // state below waits for it — a WhatsApp-only tenant has no reviews but
  // plenty to show. null = still unknown.
  const [messagingHasData, setMessagingHasData] = useState<boolean | null>(null);

  // Channels (Google) + derived label/listing maps.
  const channelsQuery = useQuery({
    queryKey: queryKeys.analytics.channels(),
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels");
      const google = dedupeBusinesses(
        (data.channels ?? []).filter(
          (c: { platform: string }) => c.platform === "google_reviews"
        )
      );
      const channels = google.map((c: { id: string; display_name: string | null }) => ({
        id: c.id,
        label: c.display_name ?? "Google Business",
      }));
      const labelMap: Record<string, string> = {};
      for (const c of google as { id: string; display_name: string | null }[]) {
        if (c.id) labelMap[c.id] = c.display_name ?? "Google Business";
      }
      const idMap: Record<string, string> = {};
      for (const c of google as { id: string; listing_id?: string | null }[]) {
        if (c.id && c.listing_id) idMap[c.id] = c.listing_id;
      }
      return { channels, labelMap, idMap };
    },
    staleTime: 5 * 60 * 1000,
  });
  const channels = channelsQuery.data?.channels ?? [];
  const channelLabels = channelsQuery.data?.labelMap ?? {};
  const channelListingIds = channelsQuery.data?.idMap ?? {};

  // Overview + timeseries (refetch on days/channel/refresh).
  const overviewQuery = useQuery({
    queryKey: queryKeys.analytics.overview(days, channelId ?? "all"),
    queryFn: async () => {
      const [o, pts] = await Promise.all([
        fetchOverview(days, channelId),
        fetchTimeseries(days, channelId),
      ]);
      return { overview: o, points: pts };
    },
    staleTime: 30 * 1000,
  });
  const overview = overviewQuery.data?.overview ?? null;
  const points = overviewQuery.data?.points ?? [];
  const loading = channelsQuery.isPending || overviewQuery.isPending;
  const error = overviewQuery.isError && !overviewQuery.data;

  // Google presence snapshot (per branch or aggregate).
  const presenceQuery = useQuery({
    queryKey: queryKeys.analytics.presence(channelId),
    queryFn: async () => {
      if (channelId) {
        const listingId = channelListingIds[channelId] ?? null;
        if (!listingId) return null;
        const prof = await apiFetch(
          `/api/v1/integrations/localith/profile?listing_id=${encodeURIComponent(listingId)}`
        ).catch(() => null);
        return presenceFromProfile(prof);
      }
      const agg = await apiFetch("/api/v1/integrations/localith/profiles/aggregate").catch(() => null);
      if (!agg) return null;
      const n = (k: string) => {
        const v = agg[k];
        const f = typeof v === "number" ? v : parseFloat(String(v ?? ""));
        return Number.isFinite(f) ? f : 0;
      };
      return {
        listingName: typeof agg.listing_name === "string" ? agg.listing_name : "",
        windowLabel: typeof agg.window_label === "string" ? agg.window_label : null,
        searchViews: n("search_views"),
        mapViews: n("map_views"),
        websiteClicks: n("website_clicks"),
        directionRequests: n("direction_requests"),
        phoneCalls: n("phone_calls"),
        totalReviews: n("total_reviews"),
        averageRating: n("average_rating"),
      } as PresenceData;
    },
    enabled: !channelsQuery.isPending,
    staleTime: 60 * 1000,
  });
  const presence = presenceQuery.data ?? null;

  const hasData = !!overview && overview.total_reviews > 0;
  const hasPresence = !!presence;
  const rangeBtn = (active: boolean) =>
    `rounded-[2px] px-2.5 py-1 text-[11px] font-semibold outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
      active
        ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
        : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
    }`;

  return (
    <div className="h-full overflow-y-auto px-4 pb-4 sm:px-6 sm:pb-6">
      {/* Controls */}
      <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
        {channels.length > 1 && (
            <select
              value={channelId ?? ""}
              onChange={(e) => {
                setChannelId(e.target.value || null);
              }}
              aria-label="Filter by location"
              className="h-8 w-full rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 text-[12px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] sm:w-auto"
            >
              <option value="">All locations</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
          )}
          <div className="flex rounded-[2px] bg-[var(--ui-sunken)] p-0.5" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => {
                  setDays(r);
                }}
                aria-pressed={days === r}
                className={rangeBtn(days === r)}
              >
                {r}d
              </button>
            ))}
          </div>
      </div>

      {/* Messages & response speed — WhatsApp / IG / FB, from the rollup table.
          Independent of the Google data below; hides itself when empty. */}
      {!error && (
        <MessagingSection days={days} refreshToken={refreshToken} onHasData={setMessagingHasData} />
      )}

      {error && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[13px] font-semibold text-[var(--ui-ink-2)]">Couldn&apos;t load your analytics.</p>
          <p className="text-[11px] text-[var(--ui-ink-2)]">Check that the API is running, then try again.</p>
          <button
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ["analytics"] });
              setRefreshToken((t) => t + 1);
            }}
            className="ui-btn bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            Retry
          </button>
        </div>
      ) : !hasData && !hasPresence && messagingHasData === false && !loading ? (
        /* Empty state — no reviews and no connected listing */
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-[2px] bg-[var(--ui-ink)] text-[var(--ui-on-ink)]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6" aria-hidden>
              <path d="M21 21H5a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v16z" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M7 14l3-3 2 2 4-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="text-[14px] font-bold text-[var(--ui-ink)]">No review data yet</p>
          <p className="max-w-sm text-[12px] text-[var(--ui-ink-2)]">
            Connect your Google Business Profile and enable auto-reply — insights will appear here as reviews come in.
          </p>
          <Link
            href="/dashboard/channels"
            className="ui-btn mt-1 bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            Connect a channel
          </Link>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Reputation pulse + who is waiting: the two decision cards. */}
          <PulseCards days={days} channelId={channelId} />

          {/* Google presence — daily trends charted, window totals as tiles */}
          {presence && (
            <PresenceSection
              presence={presence}
              points={points}
              channelLabels={channelLabels}
              scopeLabel={t.dashboard.pulse.allBusinesses}
              locale={locale}
              loading={loading}
            />
          )}
          {hasData && (
          <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 gap-4 sm:gap-5 lg:grid-cols-4">
            <StatCard
              loading={loading}
              label={copy.avgRating}
              value={overview ? new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(overview.avg_rating) : "0"}
              sub={copy.outOfFiveStars}
              noPriorData={copy.noPriorData}
              delta={overview?.period.rating_delta}
              deltaSuffix=""
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
                </svg>
              }
            />
            <StatCard
              loading={loading}
              label={copy.reviews}
              value={overview ? new Intl.NumberFormat(locale).format(overview.period.reviews) : "0"}
              sub={copy.lastDays.replace("{days}", new Intl.NumberFormat(locale).format(days))}
              noPriorData={copy.noPriorData}
              delta={overview?.period.reviews_delta_pct}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />
            <StatCard
              loading={loading}
              label={copy.responseRate}
              value={overview ? `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(overview.response_rate)}%` : "0%"}
              sub={overview && overview.avg_response_seconds !== null ? copy.avgDuration.replace("{duration}", fmtDuration(overview.avg_response_seconds, locale, copy)) : copy.noRepliesYet}
              noPriorData={copy.noPriorData}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
                  <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />
            <StatCard
              loading={loading}
              label={copy.customerActions}
              value={overview ? new Intl.NumberFormat(locale).format(overview.google_performance.customer_actions) : "0"}
              sub={copy.actionBreakdown}
              noPriorData={copy.noPriorData}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
                  <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />
          </div>

          {/* Charts row */}
          <div className="grid grid-cols-1 gap-5 sm:gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {loading ? (
                <div className="h-48 animate-pulse rounded-[2px] bg-[var(--ui-sunken)] sm:h-72" aria-hidden />
              ) : (
                <MetricChart points={points} />
              )}
            </div>
            <div className="space-y-5 sm:space-y-6">
              <div className="ui-card p-4 sm:p-5">
                <h3 className="mb-3 text-[13px] font-bold text-[var(--ui-ink)]">Rating distribution</h3>
                {loading ? (
                  <div className="space-y-2" aria-hidden>
                    {[0, 1, 2, 3, 4].map((i) => (
                      <div key={i} className="h-2.5 animate-pulse rounded-full bg-[var(--ui-sunken)]" style={{ width: `${90 - i * 12}%` }} />
                    ))}
                  </div>
                ) : (
                  overview && <RatingDistribution distribution={overview.rating_distribution} total={overview.total_reviews} />
                )}
              </div>
              <div className="ui-card p-4 sm:p-5">
                <h3 className="mb-3 text-[13px] font-bold text-[var(--ui-ink)]">Sentiment</h3>
                {loading ? (
                  <div className="h-3 animate-pulse rounded-full bg-[var(--ui-sunken)]" aria-hidden />
                ) : (
                  overview && (
                    <SentimentSplitBar
                      positive={overview.sentiment.positive}
                      neutral={overview.sentiment.neutral}
                      negative={overview.sentiment.negative}
                    />
                  )
                )}
              </div>
            </div>
          </div>

          {/* Review inbox */}
          <ReviewInbox channelId={channelId} refreshToken={refreshToken} />
          </>
          )}
        </div>
      )}
    </div>
  );
}
