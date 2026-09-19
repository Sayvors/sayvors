"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import {
  fetchOverview,
  fetchTimeseries,
  type Overview,
  type TimeseriesPoint,
  type ChannelOption,
} from "@/lib/api-analytics";
import { StatCard } from "@/components/analytics/StatCard";
import { MetricChart, RatingDistribution, SentimentSplitBar } from "@/components/analytics/Charts";
import { ReviewInbox } from "@/components/analytics/ReviewInbox";
import InsightsPage from "../insights/page";
import GrowthPage from "../growth/page";
import BenchmarkPage from "../benchmark/page";

const RANGES = [7, 30, 90] as const;

function fmtDuration(seconds: number | null) {
  if (seconds === null) return "—";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86_400).toFixed(1)}d`;
}

/* ── AI summary strip (rule-based composition from live KPIs) ────── */

function SummaryStrip({ overview }: { overview: Overview }) {
  const p = overview.period;
  const g = overview.google_performance;
  const items: { tone: "good" | "bad" | "info"; text: string }[] = [];

  if (p.rating_delta !== null && p.rating_delta !== 0) {
    items.push({
      tone: p.rating_delta > 0 ? "good" : "bad",
      text: `Average rating ${p.rating_delta > 0 ? "improved" : "dropped"} ${Math.abs(p.rating_delta)} stars vs previous ${p.days} days`,
    });
  }
  if (p.reviews_delta_pct !== null && p.reviews_delta_pct !== 0) {
    items.push({
      tone: p.reviews_delta_pct > 0 ? "info" : "bad",
      text: `Review volume ${p.reviews_delta_pct > 0 ? "up" : "down"} ${Math.abs(p.reviews_delta_pct)}%`,
    });
  }
  items.push({
    tone: overview.sentiment.positive_pct >= 70 ? "good" : overview.sentiment.negative_pct > 30 ? "bad" : "info",
    text: `${overview.sentiment.positive_pct}% positive sentiment across all reviews`,
  });
  if (overview.unanswered > 0) {
    items.push({
      tone: "bad",
      text: overview.unanswered === 1
        ? "1 review still needs a reply"
        : `${overview.unanswered} reviews still need a reply`,
    });
  }
  if (g.customer_actions > 0) {
    items.push({ tone: "good", text: `${g.customer_actions} customer actions from Google this period` });
  }

  const toneDot = { good: "bg-emerald", bad: "bg-coral", info: "bg-sky" };

  return (
    <section
      aria-label="Business summary"
      className="relative overflow-hidden rounded-2xl border-2 border-white bg-gradient-to-r from-deep-violet to-magenta p-5 text-white shadow-md shadow-deep-violet/20"
    >
      <div className="mb-2.5 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-white/15">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5" aria-hidden>
            <path d="M12 2a7 7 0 014 12.7V17a1 1 0 01-1 1H9a1 1 0 01-1-1v-2.3A7 7 0 0112 2z" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M9 21h6" strokeLinecap="round" />
          </svg>
        </span>
        <h2 className="text-[13px] font-bold tracking-wide">Sayvors AI — Business Intelligence</h2>
        <span className="ml-auto flex items-center gap-3 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold">
          <span title="Reputation score">Reputation {overview.reputation_score}</span>
          <span className="h-3 w-px bg-white/25" aria-hidden />
          <span title="Business health score">Health {overview.health_score}</span>
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
  windowLabel: string;
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
    windowLabel: conn.metrics_start && conn.metrics_end ? `${conn.metrics_start} → ${conn.metrics_end}` : "last 30 days",
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

function PresenceSection({ presence }: { presence: PresenceData }) {
  const p = presence;
  const cells: { label: string; value: string; sub?: string }[] = [
    { label: "Search views", value: String(p.searchViews) },
    { label: "Map views", value: String(p.mapViews) },
    { label: "Impressions", value: String(p.searchViews + p.mapViews), sub: "search + maps" },
    { label: "Website clicks", value: String(p.websiteClicks) },
    { label: "Direction requests", value: String(p.directionRequests) },
    { label: "Phone calls", value: String(p.phoneCalls) },
    { label: "Published posts", value: String(p.publishedPosts) },
    { label: "Avg posting time", value: String(p.avgPostingTime) },
    { label: "Avg response time", value: `${p.avgResponseTimeH}h` },
    { label: "Response percentage", value: `${p.responsePct}%` },
  ];
  return (
    <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-bold text-ink">Google presence{p.listingName ? ` — ${p.listingName}` : ""}</h3>
        <p className="text-[11px] text-ink/40">{p.windowLabel} · via Localith</p>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {cells.map((c) => (
          <div key={c.label} className="rounded-xl bg-ink/[0.03] px-3 py-2.5 text-center">
            <p className="text-[18px] font-bold text-ink">{c.value}</p>
            <p className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-ink/45">{c.label}</p>
            {c.sub && <p className="text-[9px] text-ink/30">{c.sub}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Overview tab ─────────────────────────────────────────────────── */

function OverviewPanel() {
  const [days, setDays] = useState<number>(30);
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [channelId, setChannelId] = useState<string | null>(null);
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
      apiFetch("/api/v1/integrations/localith/profile").catch(() => null),
    ])
      .then(([o, t, prof]) => {
        if (cancelled) return;
        setOverview(o);
        setPoints(t);
        setPresence(presenceFromProfile(prof));
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

  useEffect(() => {
    apiFetch("/api/v1/channels/")
      .then((data) => {
        const google = (data.channels ?? [])
          .filter((c: { platform: string }) => c.platform === "google_reviews")
          .map((c: { id: string; display_name: string | null }) => ({
            id: c.id,
            label: c.display_name ?? "Google Business",
          }));
        setChannels(google);
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
      <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
        {channels.length > 1 && (
            <select
              value={channelId ?? ""}
              onChange={(e) => {
                setChannelId(e.target.value || null);
                setLoading(true);
              }}
              aria-label="Filter by location"
              className="h-8 rounded-lg border border-deep-violet/[0.1] bg-white px-2 text-[12px] text-ink outline-none transition focus:ring-2 focus:ring-deep-violet/30"
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
          {/* Google presence — live from Localith even before the first review */}
          {presence && <PresenceSection presence={presence} />}
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
              label="Avg rating"
              value={overview ? `${overview.avg_rating}` : "0"}
              sub="out of 5 stars"
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
              label="Reviews"
              value={overview ? String(overview.period.reviews) : "0"}
              sub={`last ${days} days`}
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
              label="Response rate"
              value={overview ? `${overview.response_rate}%` : "0%"}
              sub={overview && overview.avg_response_seconds !== null ? `avg ${fmtDuration(overview.avg_response_seconds)}` : "no replies yet"}
              accent="bg-emerald/10 text-emerald"
              icon={
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
                  <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />
            <StatCard
              loading={loading}
              label="Customer actions"
              value={overview ? new Intl.NumberFormat("en").format(overview.google_performance.customer_actions) : "0"}
              sub="clicks · calls · directions"
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
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {loading ? (
                <div className="h-72 animate-pulse rounded-2xl border-2 border-white bg-white/60" aria-hidden />
              ) : (
                <MetricChart points={points} />
              )}
            </div>
            <div className="space-y-3">
              <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
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
              <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
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

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "insights", label: "Insights" },
  { id: "growth", label: "Growth" },
  { id: "benchmark", label: "Benchmark" },
] as const;

type AnalyticsTab = (typeof TABS)[number]["id"];

function AnalyticsShell() {
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: AnalyticsTab =
    raw === "insights" || raw === "growth" || raw === "benchmark" ? raw : "overview";

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      <div className="shrink-0 px-4 pt-4 sm:px-6 sm:pt-6">
        <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Analytics</h1>
        <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
          Reputation, sentiment and Google performance — all in one place.
        </p>
        <div
          role="tablist"
          aria-label="Analytics sections"
          className="mt-3 flex gap-1 overflow-x-auto rounded-xl bg-deep-violet/[0.06] p-1"
        >
          {TABS.map((t) => {
            const active = tab === t.id;
            return (
              <Link
                key={t.id}
                role="tab"
                aria-selected={active}
                href={t.id === "overview" ? "/dashboard/analytics" : `/dashboard/analytics?tab=${t.id}`}
                scroll={false}
                className={`whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  active
                    ? "bg-white text-deep-violet shadow-sm"
                    : "text-ink/45 hover:text-ink/70"
                }`}
              >
                {t.label}
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
