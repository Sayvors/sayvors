"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import { dedupeBusinesses } from "@/lib/channel-identity";
import {
  fetchOverview,
  fetchTimeseries,
  type Overview,
  type TimeseriesPoint,
  type ChannelOption,
} from "@/lib/api-analytics";
import { StatCard } from "@/components/analytics/StatCard";
import { MetricChart, RatingDistribution, SentimentSplitBar } from "@/components/analytics/Charts";
import PresenceChart from "@/components/analytics/PresenceChart";
import { ReviewInbox } from "@/components/analytics/ReviewInbox";
import { useI18n } from "@/lib/i18n/I18nProvider";
import InsightsPage from "../insights/page";
import GrowthPage from "../growth/page";
import BenchmarkPage from "../benchmark/page";

const RANGES = [7, 30, 90] as const;

function fmtDuration(seconds: number | null, locale: string, labels: { minutes: string; hours: string; days: string }) {
  if (seconds === null) return "—";
  const number = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
  if (seconds < 3600) return labels.minutes.replace("{value}", number(Math.round(seconds / 60)));
  if (seconds < 86_400) return labels.hours.replace("{value}", number(Number((seconds / 3600).toFixed(1))));
  return labels.days.replace("{value}", number(Number((seconds / 86_400).toFixed(1))));
}

/* ── AI summary strip (rule-based composition from live KPIs) ────── */

function SummaryStrip({ overview }: { overview: Overview }) {
  const { t, locale } = useI18n();
  const copy = t.analytics.kpis;
  const p = overview.period;
  const g = overview.google_performance;
  const items: { tone: "good" | "bad" | "info"; text: string }[] = [];

  if (p.rating_delta !== null && p.rating_delta !== 0) {
    items.push({
      tone: p.rating_delta > 0 ? "good" : "bad",
      text: (p.rating_delta > 0 ? copy.ratingImproved : copy.ratingDropped)
        .replace("{value}", new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(Math.abs(p.rating_delta)))
        .replace("{days}", new Intl.NumberFormat(locale).format(p.days)),
    });
  }
  if (p.reviews_delta_pct !== null && p.reviews_delta_pct !== 0) {
    items.push({
      tone: p.reviews_delta_pct > 0 ? "info" : "bad",
      text: (p.reviews_delta_pct > 0 ? copy.reviewVolumeUp : copy.reviewVolumeDown)
        .replace("{value}", new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(Math.abs(p.reviews_delta_pct))),
    });
  }
  items.push({
    tone: overview.sentiment.positive_pct >= 70 ? "good" : overview.sentiment.negative_pct > 30 ? "bad" : "info",
    text: copy.positiveSentiment.replace("{value}", new Intl.NumberFormat(locale).format(overview.sentiment.positive_pct)),
  });
  if (overview.unanswered > 0) {
    items.push({
      tone: "bad",
      text: overview.unanswered === 1
        ? copy.oneReviewNeedsReply
        : copy.reviewsNeedReply.replace("{count}", new Intl.NumberFormat(locale).format(overview.unanswered)),
    });
  }
  if (g.customer_actions > 0) {
    items.push({ tone: "good", text: copy.googleCustomerActions.replace("{count}", new Intl.NumberFormat(locale).format(g.customer_actions)) });
  }

  const toneDot = { good: "bg-emerald", bad: "bg-coral", info: "bg-sky" };

  return (
    <section
      aria-label={copy.businessSummary}
      className="relative overflow-hidden rounded-2xl border-2 border-white bg-gradient-to-r from-deep-violet to-magenta p-5 text-white shadow-md shadow-deep-violet/20"
    >
      <div className="mb-2.5 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-white/15">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5" aria-hidden>
            <path d="M12 2a7 7 0 014 12.7V17a1 1 0 01-1 1H9a1 1 0 01-1-1v-2.3A7 7 0 0112 2z" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M9 21h6" strokeLinecap="round" />
          </svg>
        </span>
        <h2 className="text-[13px] font-bold tracking-wide">{t.dashboard.briefing.title}</h2>
        <span className="ml-auto flex items-center gap-3 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold">
          <span title={copy.reputationScore}>{t.dashboard.briefing.reputation} {new Intl.NumberFormat(locale).format(overview.reputation_score)}</span>
          <span className="h-3 w-px bg-white/25" aria-hidden />
          <span title={copy.healthScore}>{t.dashboard.briefing.health} {new Intl.NumberFormat(locale).format(overview.health_score)}</span>
        </span>
      </div>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {items.slice(0, 4).map((item, i) => (
          <li key={i} className="flex items-center gap-2 text-[12px] text-white/90">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${toneDot[item.tone]}`} aria-hidden />
            {item.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ── Google presence (Localith snapshot — live even with 0 reviews) ── */

interface PresenceData {
  listingName: string;
  windowLabel: string | null;
  searchViews: number;
  mapViews: number;
  websiteClicks: number;
  directionRequests: number;
  phoneCalls: number;
  publishedPosts: number;
  avgPostingTime: number;
  avgResponseTimeH: number;
  responsePct: number;
  totalReviews: number;
  averageRating: number;
}

function num(v: unknown): number {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
}

function presenceFromProfile(prof: {
  connection?: { listing_name?: string; metrics_start?: string | null; metrics_end?: string | null; total_reviews?: number; average_rating?: number };
  metrics?: { listings?: Record<string, number | string | null>[] };
  item_metrics?: { listings?: Record<string, number | string | null>[] };
} | null): PresenceData | null {
  const perf = prof?.metrics?.listings?.[0];
  const rev = prof?.item_metrics?.listings?.[0];
  if (!perf && !rev) return null;
  const conn = prof?.connection ?? {};
  return {
    listingName: conn.listing_name ?? "",
    windowLabel: conn.metrics_start && conn.metrics_end ? `${conn.metrics_start} → ${conn.metrics_end}` : null,
    searchViews: num(perf?.googleSearchDesktop) + num(perf?.googleSearchMobile),
    mapViews: num(perf?.googleMapsDesktop) + num(perf?.googleMapsMobile),
    websiteClicks: num(perf?.websiteClicks),
    directionRequests: num(perf?.directions),
    phoneCalls: num(perf?.callClicks),
    publishedPosts: num(perf?.numPublishedPosts),
    avgPostingTime: num(perf?.avgPostingTime),
    avgResponseTimeH: num(perf?.avgReviewResponseTime),
    responsePct: num(perf?.reviewResponsePercentage),
    totalReviews: num(rev?.numberOfReviews ?? conn.total_reviews),
    averageRating: num(rev?.averageRating ?? conn.average_rating),
  };
}

function PresenceSection({
  presence,
  points,
  channelLabels,
  scopeLabel,
  locale,
  loading,
}: {
  presence: PresenceData;
  points: TimeseriesPoint[];
  channelLabels: Record<string, string>;
  scopeLabel: string;
  locale: string;
  loading: boolean;
}) {
  const { t } = useI18n();
  const copy = t.analytics.presence;
  const p = presence;

  const labels = {
    discovery: copy.presenceDiscovery,
    actions: copy.presenceActions,
    impressions: copy.impressions,
    searchViews: copy.searchViews,
    mapViews: copy.mapViews,
    websiteClicks: copy.websiteClicks,
    directionRequests: copy.directionRequests,
    phoneCalls: copy.phoneCalls,
    messages: copy.messages,
    bookings: copy.bookings,
    reviewsMetric: copy.reviewsMetric,
    repliesMetric: copy.repliesMetric,
    totalLabel: copy.totalLabel,
    perBranchDay: copy.perBranchDay,
    dailyAvg: copy.dailyAvg,
    peak: copy.peak,
    on: copy.on,
    scopeTotal: copy.scopeTotal,
    scopeByBranch: copy.scopeByBranch,
    noMetricYet: copy.noMetricYet,
    noMetricHint: copy.noMetricHint,
  };

  // The daily series carries the countable metrics. These four are window
  // aggregates from Localith with no per-day breakdown, so they stay as
  // tiles under the chart rather than pretending to be a trend.
  const windowCells: { label: string; value: string }[] = [
    { label: copy.publishedPosts, value: String(p.publishedPosts) },
    { label: copy.avgPostingTime, value: String(p.avgPostingTime) },
    { label: copy.avgResponseTime, value: `${p.avgResponseTimeH}h` },
    { label: copy.responseRate, value: `${p.responsePct}%` },
  ];

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
        <PresenceChart
          points={points}
          channelLabels={channelLabels}
          labels={labels}
          group="discovery"
          locale={locale}
          loading={loading}
          scopeLabel={scopeLabel}
        />
        <PresenceChart
          points={points}
          channelLabels={channelLabels}
          labels={labels}
          group="actions"
          locale={locale}
          loading={loading}
          scopeLabel={scopeLabel}
        />
      </div>
      <div className="rounded-2xl border-2 border-white bg-white/80 p-3.5 backdrop-blur-sm sm:p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[13px] font-bold text-ink">
            {copy.title}
            {p.listingName ? ` — ${p.listingName}` : ""}
          </h3>
          <p className="text-[10px] text-ink/40">
            {p.windowLabel ?? copy.last30Days} · {copy.viaLocalith}
          </p>
        </div>
        <p className="mt-0.5 text-[9px] text-ink/35">{copy.periodTotals}</p>
        <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {windowCells.map((c) => (
            <div key={c.label} className="rounded-lg bg-ink/[0.03] px-2 py-2 text-center">
              <p className="text-[14px] font-bold text-ink sm:text-[15px]">{c.value}</p>
              <p className="mt-0.5 text-[9px] font-medium uppercase tracking-wide text-ink/45">{c.label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Overview tab ─────────────────────────────────────────────────── */

function OverviewPanel() {
  const { t, locale } = useI18n();
  const copy = t.analytics.kpis;
  const [days, setDays] = useState<number>(30);
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [channelListingIds, setChannelListingIds] = useState<Record<string, string>>({});
  const [channelLabels, setChannelLabels] = useState<Record<string, string>>({});
  const [overview, setOverview] = useState<Overview | null>(null);
  const [points, setPoints] = useState<TimeseriesPoint[]>([]);
  const [presence, setPresence] = useState<PresenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const hasLoadedOnce = useRef(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchOverview(days, channelId),
      fetchTimeseries(days, channelId),
    ])
      .then(([o, t]) => {
        if (cancelled) return;
        setOverview(o);
        setPoints(t);
        setError(false);
        hasLoadedOnce.current = true;
      })
      .catch(() => {
        if (!cancelled && !hasLoadedOnce.current) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, channelId, refreshToken]);

  // Google presence follows the business selector — each channel maps to its
  // Localith listing_id, so the snapshot refetches per branch. "All locations"
  // shows cumulative totals across every branch (additive metrics summed,
  // rates review-weighted by the backend).
  useEffect(() => {
    let cancelled = false;
    if (channelId) {
      const listingId = channelListingIds[channelId] ?? null;
      if (!listingId) {
        // Native Google channel with no Localith listing — no snapshot to show.
        setPresence(null);
        return;
      }
      apiFetch(`/api/v1/integrations/localith/profile?listing_id=${encodeURIComponent(listingId)}`)
        .catch(() => null)
        .then((prof) => {
          if (!cancelled) setPresence(presenceFromProfile(prof));
        });
    } else {
      apiFetch("/api/v1/integrations/localith/profiles/aggregate")
        .catch(() => null)
        .then((agg: Record<string, unknown> | null) => {
          if (cancelled) return;
          if (!agg) {
            setPresence(null);
            return;
          }
          const n = (k: string) => {
            const v = agg[k];
            const f = typeof v === "number" ? v : parseFloat(String(v ?? ""));
            return Number.isFinite(f) ? f : 0;
          };
          setPresence({
            listingName: typeof agg.listing_name === "string" ? agg.listing_name : "",
            windowLabel: typeof agg.window_label === "string" ? agg.window_label : null,
            searchViews: n("search_views"),
            mapViews: n("map_views"),
            websiteClicks: n("website_clicks"),
            directionRequests: n("direction_requests"),
            phoneCalls: n("phone_calls"),
            publishedPosts: n("published_posts"),
            avgPostingTime: n("avg_posting_time"),
            avgResponseTimeH: n("avg_response_time_h"),
            responsePct: n("response_pct"),
            totalReviews: n("total_reviews"),
            averageRating: n("average_rating"),
          });
        });
    }
    return () => {
      cancelled = true;
    };
  }, [channelId, channelListingIds]);

  useEffect(() => {
    apiFetch("/api/v1/channels")
      .then((data) => {
        const google = dedupeBusinesses(
          (data.channels ?? []).filter(
            (c: { platform: string }) => c.platform === "google_reviews"
          )
        );
        setChannels(google.map((c: { id: string; display_name: string | null }) => ({
          id: c.id,
          label: c.display_name ?? "Google Business",
        })));
        // Branch names for the chart's "By branch" comparison lines.
        const labelMap: Record<string, string> = {};
        for (const c of google as { id: string; display_name: string | null }[]) {
          if (c.id) labelMap[c.id] = c.display_name ?? "Google Business";
        }
        setChannelLabels(labelMap);
        const idMap: Record<string, string> = {};
        for (const c of google as { id: string; listing_id?: string | null }[]) {
          if (c.id && c.listing_id) idMap[c.id] = c.listing_id;
        }
        setChannelListingIds(idMap);
      })
      .catch(() => setChannels([]));
  }, []);

  const hasData = !!overview && overview.total_reviews > 0;
  const hasPresence = !!presence;
  const rangeBtn = (active: boolean) =>
    `rounded-md px-2.5 py-1 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
      active ? "bg-white text-deep-violet shadow-sm" : "text-ink/45 hover:text-ink/70"
    }`;

  return (
    <div className="h-full overflow-y-auto px-4 pb-4 sm:px-6 sm:pb-6">
      {/* Controls */}
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
        {channels.length > 1 && (
            <select
              value={channelId ?? ""}
              onChange={(e) => {
                setChannelId(e.target.value || null);
                setLoading(true);
              }}
              aria-label="Filter by location"
              className="h-8 w-full rounded-lg border border-deep-violet/[0.1] bg-white px-2 text-[12px] text-ink outline-none transition focus:ring-2 focus:ring-deep-violet/30 sm:w-auto"
            >
              <option value="">All locations</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
          )}
          <div className="flex rounded-lg bg-deep-violet/[0.06] p-0.5" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => {
                  setDays(r);
                  setLoading(true);
                }}
                aria-pressed={days === r}
                className={rangeBtn(days === r)}
              >
                {r}d
              </button>
            ))}
          </div>
      </div>

      {error && !loading ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[13px] font-semibold text-ink/60">Couldn&apos;t load your analytics.</p>
          <p className="text-[11px] text-ink/40">Check that the API is running, then try again.</p>
          <button
            onClick={() => {
              setError(false);
              setLoading(true);
              setRefreshToken((t) => t + 1);
            }}
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
          >
            Retry
          </button>
        </div>
      ) : !hasData && !hasPresence && !loading ? (
        /* Empty state — no reviews and no connected listing */
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6" aria-hidden>
              <path d="M21 21H5a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v16z" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M7 14l3-3 2 2 4-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="text-[14px] font-bold text-ink">No review data yet</p>
          <p className="max-w-sm text-[12px] text-ink/50">
            Connect your Google Business Profile and enable auto-reply — insights will appear here as reviews come in.
          </p>
          <Link
            href="/dashboard/channels"
            className="mt-1 rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
          >
            Connect a channel
          </Link>
        </div>
      ) : (
        <div className="space-y-5">
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
          {!hasData && !loading && (
            <div className="flex flex-col items-center gap-2 rounded-2xl border-2 border-white bg-white/80 py-10 text-center backdrop-blur-sm">
              <p className="text-[14px] font-bold text-ink">No review data yet</p>
              <p className="max-w-sm text-[12px] text-ink/50">
                Review insights, sentiment and charts will appear here as reviews come in.
              </p>
              <Link
                href="/dashboard/channels"
                className="mt-1 rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
              >
                Check connection
              </Link>
            </div>
          )}
          {hasData && (
          <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              loading={loading}
              label={copy.avgRating}
              value={overview ? new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(overview.avg_rating) : "0"}
              sub={copy.outOfFiveStars}
              noPriorData={copy.noPriorData}
              delta={overview?.period.rating_delta}
              deltaSuffix=""
              accent="bg-amber/10 text-amber-600"
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
              accent="bg-deep-violet/10 text-deep-violet"
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
              accent="bg-emerald/10 text-emerald"
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
              accent="bg-sky/10 text-sky"
              icon={
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
                  <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />
          </div>

          {/* AI summary */}
          {overview && !loading && <SummaryStrip overview={overview} />}

          {/* Charts row */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {loading ? (
                <div className="h-48 animate-pulse rounded-2xl border-2 border-white bg-white/60 sm:h-72" aria-hidden />
              ) : (
                <MetricChart points={points} />
              )}
            </div>
            <div className="space-y-3">
              <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm sm:p-5">
                <h3 className="mb-3 text-[14px] font-bold text-ink">Rating distribution</h3>
                {loading ? (
                  <div className="space-y-2" aria-hidden>
                    {[0, 1, 2, 3, 4].map((i) => (
                      <div key={i} className="h-2.5 animate-pulse rounded-full bg-ink/[0.06]" style={{ width: `${90 - i * 12}%` }} />
                    ))}
                  </div>
                ) : (
                  overview && <RatingDistribution distribution={overview.rating_distribution} total={overview.total_reviews} />
                )}
              </div>
              <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm sm:p-5">
                <h3 className="mb-3 text-[14px] font-bold text-ink">Sentiment</h3>
                {loading ? (
                  <div className="h-3 animate-pulse rounded-full bg-ink/[0.06]" aria-hidden />
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

/* ── Tab shell (Overview / Insights / Growth / Benchmark) ───────────── */

const TABS = ["overview", "insights", "growth", "benchmark"] as const;

type AnalyticsTab = (typeof TABS)[number];

function AnalyticsShell() {
  const { t } = useI18n();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: AnalyticsTab =
    raw === "insights" || raw === "growth" || raw === "benchmark" ? raw : "overview";

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      <div className="shrink-0 px-4 pt-4 sm:px-6 sm:pt-6">
        <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">{t.nav.analytics}</h1>
        <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
          {t.analytics.subtitle}
        </p>
        <div
          role="tablist"
          aria-label={t.analytics.sections}
          className="mt-3 flex gap-1 overflow-x-auto rounded-xl bg-deep-violet/[0.06] p-1"
        >
          {TABS.map((tabId) => {
            const active = tab === tabId;
            const label = tabId === "overview"
              ? t.analytics.overview
              : tabId === "benchmark"
                ? t.analytics.benchmark
                : t.nav[tabId];
            return (
              <Link
                key={tabId}
                role="tab"
                aria-selected={active}
                href={tabId === "overview" ? "/dashboard/analytics" : `/dashboard/analytics?tab=${tabId}`}
                scroll={false}
                className={`whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  active
                    ? "bg-white text-deep-violet shadow-sm"
                    : "text-ink/45 hover:text-ink/70"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </div>
      </div>
      <div className="mt-3 min-h-0 flex-1">
        {tab === "overview" && <OverviewPanel />}
        {tab === "insights" && <InsightsPage />}
        {tab === "growth" && <GrowthPage />}
        {tab === "benchmark" && <BenchmarkPage />}
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense>
      <AnalyticsShell />
    </Suspense>
  );
}
