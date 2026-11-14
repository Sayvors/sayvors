"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import {
  fetchAcquisition,
  fetchKeywords,
  fetchMessagingGrowth,
  fetchOpportunities,
  fetchOverview,
  fetchTimeseries,
  fetchVisibility,
  fetchGrowthCards,
  type TimeseriesPoint,
} from "@/lib/api-analytics";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";
import { StatCard } from "@/components/analytics/StatCard";
import { FactSource } from "@/components/analytics/FactSource";
import { GBP_DASHBOARD_URL } from "@/lib/google-links";
import GrowthCardsSection from "@/components/analytics/GrowthCards";
import FeatureLock from "@/components/billing/FeatureLock";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type GrowthDict = Dict["growth"];
type PageDict = Dict["growth"]["page"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

const TYPE_STYLES: Record<string, { bg: string; labelKey: "typeOperations" | "typeReputation" | "typeMarketing" | "typeProfile" }> = {
  operations: { bg: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]", labelKey: "typeOperations" },
  reputation: { bg: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]", labelKey: "typeReputation" },
  marketing: { bg: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]", labelKey: "typeMarketing" },
  profile: { bg: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]", labelKey: "typeProfile" },
};

const ACTION_ICONS: Record<string, React.ReactNode> = {
  impressions: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  website: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  calls: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.13.96.36 1.9.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0122 16.92z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  directions: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M12 2l10 10-10 10L2 12 12 2z" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9 12h6M13 9l3 3-3 3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

function TrendArrow({ value }: { value: number | null }) {
  const { locale } = useI18n();
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  if (value === null || value === undefined) return <span className="text-[11px] text-[var(--ui-ink-2)]">—</span>;
  const up = value > 0;
  const flat = value === 0;
  return (
    <span className={`inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-px text-[10px] font-bold tabular-nums ${up ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]" : flat ? "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]" : "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"}`}>
      {!flat && (
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2 w-2 ${up ? "" : "rotate-180"}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {up ? "+" : ""}{fmt(Math.abs(Math.round(value * 10) / 10))}%
    </span>
  );
}

type TrendMetricKey = "impressions" | "website" | "calls" | "directions";

function trendValue(p: TimeseriesPoint, metric: TrendMetricKey): number {
  if (metric === "website") return p.website_clicks;
  if (metric === "calls") return p.call_clicks;
  if (metric === "directions") return p.direction_requests;
  return p.impressions_maps;
}

function rollupMonthly(points: TimeseriesPoint[], metric: TrendMetricKey, dateLocale: string): { label: string; value: number }[] {
  const byMonth = new Map<string, number>();
  for (const p of points) {
    const key = p.date.slice(0, 7);
    byMonth.set(key, (byMonth.get(key) ?? 0) + trendValue(p, metric));
  }
  return [...byMonth.entries()]
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([key, value]) => {
      const [y, m] = key.split("-").map(Number);
      const label = new Date(y, m - 1, 1).toLocaleDateString(dateLocale, { month: "short" });
      return { label, value };
    });
}

function TrendChart({ points, metric, granularity }: {
  points: TimeseriesPoint[];
  metric: TrendMetricKey;
  granularity: "day" | "month";
}) {
  const { t, locale } = useI18n();
  const pg = t.growth.page;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const metricLabel = metric === "impressions" ? pg.mViews : metric === "website" ? pg.mClicks : metric === "calls" ? pg.mCalls : pg.mVisits;
  const buckets = granularity === "month"
    ? rollupMonthly(points, metric, dateLocale)
    : points.map((p) => ({
        label: new Date(`${p.date}T00:00:00`).toLocaleDateString(dateLocale, { day: "numeric", month: "short" }),
        value: trendValue(p, metric),
      }));
  const max = Math.max(1, ...buckets.map((b) => b.value));
  const W = 600;
  const H = 150;
  const PAD = 12;
  if (buckets.length === 0) {
    return <div className="flex h-36 items-center justify-center text-[12px] text-[var(--ui-ink-2)]">{pg.noActivity}</div>;
  }
  const step = buckets.length > 1 ? (W - PAD * 2) / (buckets.length - 1) : 0;
  const path = buckets
    .map((b, i) => `${i === 0 ? "M" : "L"}${(PAD + i * step).toFixed(1)},${(H - PAD - (b.value / max) * (H - PAD * 2)).toFixed(1)}`)
    .join(" ");
  const ticks = buckets.filter((_, i) => i % Math.max(1, Math.ceil(buckets.length / 6)) === 0);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-36 w-full" role="img" aria-label={fill(pg.trendAria, { metric: metricLabel })}>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={PAD} x2={W - PAD} y1={H * f} y2={H * f} className="stroke-[var(--ui-line)]" />
        ))}
        <path d={path} fill="none" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" className="stroke-[var(--ui-ink)]" />
        {buckets.map((b, i) => (
          <circle
            key={i}
            cx={PAD + i * step}
            cy={H - PAD - (b.value / max) * (H - PAD * 2)}
            r="3"
            className="fill-[var(--ui-ink)]"
          >
            <title>{`${b.label}: ${fmt(b.value)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-[var(--ui-ink-2)]">
        {ticks.map((t, i) => (
          <span key={i}>{t.label}</span>
        ))}
      </div>
    </div>
  );
}

function GrowthPageContent() {
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const channels = useGoogleChannels();
  const [granularity, setGranularity] = useState<"day" | "month">("day");
  const [trendMetric, setTrendMetric] = useState<"impressions" | "website" | "calls" | "directions">("impressions");
  const queryClient = useQueryClient();

  const growthQuery = useQuery({
    queryKey: queryKeys.growth.all(days, channelId),
    queryFn: async () => {
      const [v, a, o, t, k, ov, mg, gc] = await Promise.all([
        fetchVisibility(days, channelId),
        fetchAcquisition(days, channelId),
        fetchOpportunities(days, channelId),
        fetchTimeseries(days, channelId),
        fetchKeywords(days, channelId).catch(() => null),
        fetchOverview(days, channelId).catch(() => null),
        fetchMessagingGrowth(days, channelId).catch(() => null),
        fetchGrowthCards(days, channelId).catch(() => null),
      ]);
      return {
        visibility: v,
        acquisition: a,
        opportunities: o,
        points: t,
        keywords: k,
        overview: ov,
        messagingGrowth: mg,
        growthCards: gc,
      };
    },
    staleTime: 30 * 1000,
  });
  const visibility = growthQuery.data?.visibility ?? null;
  const acquisition = growthQuery.data?.acquisition ?? null;
  const opportunities = growthQuery.data?.opportunities ?? null;
  const points = growthQuery.data?.points ?? [];
  const keywords = growthQuery.data?.keywords ?? null;
  const overview = growthQuery.data?.overview ?? null;
  const messagingGrowth = growthQuery.data?.messagingGrowth ?? null;
  const growthCards = growthQuery.data?.growthCards ?? null;
  const loading = growthQuery.isPending;
  const error = growthQuery.isError && !growthQuery.data;
  const { t, locale } = useI18n();
  const pg: PageDict = t.growth.page;
  const gc = t.growth.cards;
  const gbp = t.bench.fact.gbp;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";

  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const nativePerf = !!visibility && visibility.impressions_maps > 0;
  const impressions = visibility?.impressions_maps ?? 0;
  const website = acquisition?.website_clicks.total ?? 0;
  const calls = acquisition?.call_clicks.total ?? 0;
  const directions = acquisition?.direction_requests.total ?? 0;
  const actions = website + calls + directions;
  const ctr = visibility?.click_through_pct ?? null;
  const hasOpps = (opportunities?.opportunities.length ?? 0) > 0;
  const showMain = nativePerf;
  const showEmpty = !showMain && !hasOpps && !loading;

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">{pg.title}</h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">
            {pg.sub}
          </p>
        </div>
        <RangeChannelControls
          days={days}
          setDays={(d) => {
            setDays(d);
          }}
          channelId={channelId}
          setChannelId={(c) => {
            setChannelId(c);
          }}
          channels={channels}
        />
      </div>

      <div className="mb-5">
        <GrowthCardsSection
          cards={growthCards}
          loading={loading}
          googleConnected={channels.length > 0}
        />
      </div>

      {error && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[13px] font-semibold text-[var(--ui-ink-2)]">{pg.loadFail}</p>
          <button
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ["growth"] });
            }}
            className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            {pg.retry}
          </button>
        </div>
      ) : showEmpty ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[14px] font-bold text-[var(--ui-ink)]">{pg.emptyTitle}</p>
          <p className="max-w-sm text-[12px] text-[var(--ui-ink-2)]">
            {pg.emptyBody}
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-5 sm:gap-6 lg:grid-cols-4">
            <StatCard
              loading={loading}
              label={pg.kpiMaps}
              value={fmt(impressions)}
              sub={pg.kpiMapsSub}
              delta={visibility?.impressions_trend_pct}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={ACTION_ICONS.impressions}
              source="Google Business Profile"
              sourceDetail={fill(pg.lastDays, { n: fmt(days) })}
              sourceHref={channels.length > 0 ? GBP_DASHBOARD_URL : undefined}
              sourceLinkLabel={gbp}
            />
            <StatCard
              loading={loading}
              label={pg.kpiWeb}
              value={fmt(website)}
              sub={fill(pg.lastDays, { n: fmt(days) })}
              delta={acquisition?.website_clicks.trend_pct}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={ACTION_ICONS.website}
              source="Google Business Profile"
              sourceDetail={fill(pg.lastDays, { n: fmt(days) })}
              sourceHref={channels.length > 0 ? GBP_DASHBOARD_URL : undefined}
              sourceLinkLabel={gbp}
            />
            <StatCard
              loading={loading}
              label={pg.kpiCalls}
              value={fmt(calls)}
              sub={fill(pg.lastDays, { n: fmt(days) })}
              delta={acquisition?.call_clicks.trend_pct}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={ACTION_ICONS.calls}
              source="Google Business Profile"
              sourceDetail={fill(pg.lastDays, { n: fmt(days) })}
              sourceHref={channels.length > 0 ? GBP_DASHBOARD_URL : undefined}
              sourceLinkLabel={gbp}
            />
            <StatCard
              loading={loading}
              label={pg.kpiDirections}
              value={fmt(directions)}
              sub={fill(pg.lastDays, { n: fmt(days) })}
              delta={acquisition?.direction_requests.trend_pct}
              accent="bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
              icon={ACTION_ICONS.directions}
              source="Google Business Profile"
              sourceDetail={fill(pg.lastDays, { n: fmt(days) })}
              sourceHref={channels.length > 0 ? GBP_DASHBOARD_URL : undefined}
              sourceLinkLabel={gbp}
            />
          </div>

          {/* CTR panel */}
          {showMain && (
          <div className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{pg.convTitle}</h3>
              <p className="mt-3 text-[32px] font-bold text-[var(--ui-ink)]">
                {ctr !== null ? `${fmt(Math.round(ctr * 10) / 10)}%` : "—"}
              </p>
              <p className="text-[11px] text-[var(--ui-ink-2)]">{pg.convSub}</p>
              <div className="mt-4 space-y-2 border-t border-[var(--ui-line)] pt-4 text-[12px] text-[var(--ui-ink-2)]">
                <p className="flex justify-between">
                  <span>{pg.custActions}</span>
                  <span className="font-semibold text-[var(--ui-ink)]">{fmt(actions)}</span>
                </p>
                <p className="flex justify-between">
                  <span>{pg.totalReviews}</span>
                  <span className="font-semibold text-[var(--ui-ink)]">{fmt(overview?.total_reviews ?? 0)}</span>
                </p>
                <p className="flex justify-between">
                  <span>{pg.respRate}</span>
                  <span className="font-semibold text-[var(--ui-ink)]">{overview ? `${fmt(Math.round(overview.response_rate))}%` : "—"}</span>
                </p>
              </div>
              <FactSource
                source="Google Business Profile"
                detail={fill(pg.lastDays, { n: fmt(days) })}
                href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
                linkLabel={gbp}
              />
          </div>
          )}

          {/* Trends — daily / monthly, fed by location_daily_metrics
              (native Google Performance API) */}
          {showMain && (
          <section aria-label={pg.trendsAria} className="ui-card p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{pg.trendsTitle}</h3>
                <p className="text-[11px] text-[var(--ui-ink-2)]">{pg.trendsSub}</p>
              </div>
              <div className="flex gap-2">
                <div className="flex rounded-[2px] bg-[var(--ui-sunken)] p-0.5" role="group" aria-label={pg.metricAria}>
                  {([
                    { key: "impressions", label: pg.mViews },
                    { key: "website", label: pg.mClicks },
                    { key: "calls", label: pg.mCalls },
                    { key: "directions", label: pg.mVisits },
                  ] as const).map((m) => (
                    <button
                      key={m.key}
                      onClick={() => setTrendMetric(m.key)}
                      aria-pressed={trendMetric === m.key}
                      className={`rounded-[2px] px-2.5 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                        trendMetric === m.key ? "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
                      }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                <div className="flex rounded-[2px] bg-[var(--ui-sunken)] p-0.5" role="group" aria-label={pg.granAria}>
                  {(["day", "month"] as const).map((g) => (
                    <button
                      key={g}
                      onClick={() => setGranularity(g)}
                      aria-pressed={granularity === g}
                      className={`rounded-[2px] px-2.5 py-1 text-[11px] font-semibold capitalize transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                        granularity === g ? "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
                      }`}
                    >
                      {g === "day" ? pg.daily : pg.monthly}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            {loading ? (
              <div className="h-40 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" aria-hidden />
            ) : (
              <TrendChart points={points} metric={trendMetric} granularity={granularity} />
            )}
            <FactSource
              source="Google Business Profile"
              detail={`${granularity === "day" ? pg.granDay : pg.granMonth} · ${fill(pg.lastDays, { n: fmt(days) })}`}
              href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
              linkLabel={gbp}
            />
          </section>
          )}

          {/* Search keywords — native Google only; honest empty state otherwise */}
          <section aria-label={pg.kwAria} className="ui-card p-5">
            <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{pg.kwTitle}</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">{pg.kwSub}</p>
            {loading || !keywords ? (
              <div className="mt-3 space-y-2" aria-hidden>
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-9 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" />
                ))}
              </div>
            ) : !keywords.available ? (
              <p className="mt-3 rounded-[2px] bg-[var(--ui-sunken)] px-3 py-3 text-[12px] text-[var(--ui-ink-2)]">
                {pg.kwNeedNative}
              </p>
            ) : keywords.keywords.length === 0 ? (
              <p className="mt-3 rounded-[2px] bg-[var(--ui-sunken)] px-3 py-3 text-[12px] text-[var(--ui-ink-2)]">
                {pg.kwEmpty}
              </p>
            ) : (
              <ol className="mt-3 divide-y divide-[var(--ui-line)]">
                {keywords.keywords.slice(0, 10).map((k) => (
                  <li key={k.keyword} className="flex items-center gap-3 py-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--ui-ink)]">{k.keyword}</span>
                    <span className="shrink-0 text-[12px] tabular-nums text-[var(--ui-ink-2)]">{fmt(k.impressions)} {pg.viewsWord}</span>
                    <TrendArrow value={k.trend_pct} />
                  </li>
                ))}
              </ol>
            )}
            <p className="mt-2 text-[10px] text-[var(--ui-ink-2)]">
              {pg.kwNote}
            </p>
            <FactSource
              source={pg.kwSource}
              detail={fill(pg.kwDetail, { n: fmt(days) })}
              href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
              linkLabel={gbp}
            />
          </section>

          {/* Opportunities — independent of performance data */}
          <section aria-label={pg.oppAria} className="ui-card p-5">
            <h3 className="mb-4 text-[14px] font-bold text-[var(--ui-ink)]">{pg.oppTitle}</h3>
            {loading || !opportunities ? (
              <div className="space-y-2" aria-hidden>
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-10 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" />
                ))}
              </div>
            ) : opportunities.opportunities.length === 0 ? (
              <p className="py-4 text-center text-[12px] text-[var(--ui-ink-2)]">{pg.oppEmpty}</p>
            ) : (
              <ol className="space-y-2.5">
                {opportunities.opportunities.map((o) => {
                  const style = TYPE_STYLES[o.type] ?? TYPE_STYLES.reputation;
                  return (
                    <li key={o.priority} className="flex items-start gap-3 rounded-xl p-3 transition hover:bg-[var(--ui-sunken)]">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--ui-ink)] text-[11px] font-bold text-[var(--ui-on-ink)]">
                        {fmt(o.priority)}
                      </span>
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-[var(--ui-ink)]">
                          {o.title}
                          <span className={`rounded px-1.5 py-px text-[9px] font-bold uppercase ${style.bg}`}>{gc[style.labelKey]}</span>
                        </p>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ui-ink-2)]">{o.detail}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
            <FactSource
              source={pg.oppSource}
              detail={pg.oppDetail}
              href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
              linkLabel={gbp}
            />
          </section>

          {/* Messaging growth — customer growth from stored daily rollups */}
          {messagingGrowth && (
            <section aria-label={pg.msgAria} className="ui-card p-5">
              <h3 className="mb-4 text-[14px] font-bold text-[var(--ui-ink)]">{pg.msgTitle}</h3>
              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{pg.newContacts}</p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{fmt(messagingGrowth.total_new_contacts)}</p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{pg.newContactsSub}</p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{pg.msgIn}</p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{fmt(messagingGrowth.total_messages_in)}</p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{pg.msgInSub}</p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{pg.msgOut}</p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{fmt(messagingGrowth.total_messages_out)}</p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{pg.msgOutSub}</p>
                </div>
              </div>
              {messagingGrowth.customer_growth.length > 0 && (
                <div className="mt-5">
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{pg.perWeek}</p>
                  <div className="flex items-end gap-2" style={{ height: 80 }}>
                    {messagingGrowth.customer_growth.map((w) => {
                      const max = Math.max(...messagingGrowth.customer_growth.map((x) => x.new_contacts), 1);
                      const pct = (w.new_contacts / max) * 100;
                      return (
                        <div key={w.week} className="flex flex-1 flex-col items-center justify-end gap-1" title={fill(pg.weekTitle, { week: w.week, n: fmt(w.new_contacts) })}>
                          <div className="w-full rounded-t-[2px] bg-[var(--ui-ink)] transition-all" style={{ height: `${Math.max(2, pct)}%` }} />
                          <span className="text-[9px] tabular-nums text-[var(--ui-ink-2)]">{w.week.split("-W")[1]}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {messagingGrowth.follower_growth && (
                <div className="mt-5 border-t border-[var(--ui-line)] pt-4">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{pg.followers}</p>
                  {messagingGrowth.follower_growth.collecting ? (
                    <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">{pg.collectingFollowers}</p>
                  ) : (
                    <div className="mt-2 flex items-baseline gap-4">
                      <span className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                        {messagingGrowth.follower_growth.net >= 0 ? "+" : ""}{fmt(messagingGrowth.follower_growth.net)}
                      </span>
                      <span className="text-[12px] text-[var(--ui-ink-2)]">
                        {messagingGrowth.follower_growth.rate_pct !== null ? `${fmt(Math.round(messagingGrowth.follower_growth.rate_pct * 10) / 10)}%` : "—"} {pg.changeWord}
                      </span>
                    </div>
                  )}
                </div>
              )}
              <FactSource
                source={pg.rollupSource}
                detail={fill(pg.lastDays, { n: fmt(days) })}
              />
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export default function GrowthPage() {
  return (
    <FeatureLock feature="growth">
      <GrowthPageContent />
    </FeatureLock>
  );
}
