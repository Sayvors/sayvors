"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchBenchmark,
  fetchMarketBenchmarks,
  type BenchmarkResponse,
  type BranchBenchmark,
} from "@/lib/api-analytics";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";
import BenchmarkCards from "@/components/analytics/BenchmarkCards";
import { FactSource } from "@/components/analytics/FactSource";
import { GBP_DASHBOARD_URL } from "@/lib/google-links";
import { refreshExternalBenchmark } from "@/lib/api-analytics";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type BenchDict = Dict["bench"];
type PageDict = Dict["bench"]["page"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

type MetricFocus = "reputation" | "rating" | "sentiment" | "response" | "volume";

const FOCUS_META: Record<MetricFocus, { max: number; unit: string }> = {
  reputation: { max: 100, unit: "" },
  rating: { max: 5, unit: "★" },
  sentiment: { max: 100, unit: "%" },
  response: { max: 100, unit: "%" },
  volume: { max: 0, unit: "" },
};

function focusLabel(f: MetricFocus, fx: BenchDict["focus"]): string {
  switch (f) {
    case "reputation": return fx.reputationLabel;
    case "rating": return fx.ratingLabel;
    case "sentiment": return fx.sentimentLabel;
    case "response": return fx.responseLabel;
    case "volume": return fx.volumeLabel;
  }
}

function focusHint(f: MetricFocus, fx: BenchDict["focus"]): string {
  switch (f) {
    case "reputation": return fx.reputationHint;
    case "rating": return fx.ratingHint;
    case "sentiment": return fx.sentimentHint;
    case "response": return fx.responseHint;
    case "volume": return fx.volumeHint;
  }
}

function focusValue(b: BranchBenchmark, f: MetricFocus): number {
  switch (f) {
    case "reputation": return b.reputation_score;
    case "rating": return b.avg_rating;
    case "sentiment": return b.positive_pct;
    case "response": return b.response_rate;
    case "volume": return b.reviews_total;
  }
}

function fmtValue(b: BranchBenchmark, f: MetricFocus, fmt: (n: number) => string): string {
  const v = focusValue(b, f);
  if (f === "rating") return `${fmt(Math.round(v * 10) / 10)}★`;
  if (f === "sentiment" || f === "response") return `${fmt(Math.round(v))}%`;
  return `${fmt(Math.round(v))}`;
}

const MEDALS = ["🥇", "🥈", "🥉"];

export default function BenchmarkPage() {
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [focus, setFocus] = useState<MetricFocus>("reputation");
  const [branchSearch, setBranchSearch] = useState("");
  const [branchFilter, setBranchFilter] = useState<"all" | "with_reviews" | "no_reviews" | "top3" | "needs_attention">("all");
  const channels = useGoogleChannels();
  const [benchmark, setBenchmark] = useState<BenchmarkResponse | null>(null);
  const [marketBenchmarks, setMarketBenchmarks] = useState<{ metric: string; median: number | null; p25: number | null; p75: number | null; business_count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const hasLoaded = useRef(false);
  const [retryCount, setRetryCount] = useState(0);
  const [refreshingExternal, setRefreshingExternal] = useState(false);
  const { t, locale } = useI18n();
  const bp: PageDict = t.bench.page;
  const fx = t.bench.focus;
  const gbp = t.bench.fact.gbp;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);

  const handleRefreshExternal = async () => {
    setRefreshingExternal(true);
    try {
      await refreshExternalBenchmark();
      setLoading(true);
      setRetryCount((c) => c + 1);
    } catch {
      // Entitlement/key errors are surfaced by the API; the card keeps its
      // previous state rather than pretending a refresh happened.
    } finally {
      setRefreshingExternal(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchBenchmark(days, channelId),
      fetchMarketBenchmarks().catch(() => []),
    ])
      .then(([b, mb]) => {
        if (cancelled) return;
        setBenchmark(b);
        // The endpoint returns up to 50 stored rows (one per scope/date). The
        // card is a current snapshot, so keep the latest row per metric
        // instead of rendering the same metric five times.
        const latest = new Map<string, (typeof mb)[number]>();
        for (const row of mb ?? []) {
          const prev = latest.get(row.metric);
          if (!prev || row.date > prev.date) latest.set(row.metric, row);
        }
        setMarketBenchmarks([...latest.values()]);
        setError(false);
        hasLoaded.current = true;
      })
      .catch(() => {
        if (!cancelled && !hasLoaded.current) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, channelId, retryCount]);

  const branches = useMemo(() => {
    let list = [...(benchmark?.branches ?? [])];
    // Text search
    if (branchSearch.trim()) {
      const q = branchSearch.toLowerCase();
      list = list.filter((b) => b.name.toLowerCase().includes(q));
    }
    // Status filter
    if (branchFilter === "with_reviews") list = list.filter((b) => b.reviews_total > 0);
    if (branchFilter === "no_reviews") list = list.filter((b) => b.reviews_total === 0);
    if (branchFilter === "top3") list = [...list].sort((a, b) => b.reputation_score - a.reputation_score).slice(0, 3);
    if (branchFilter === "needs_attention" && benchmark?.needs_attention) {
      list = list.filter((b) => b.channel_id === benchmark.needs_attention!.channel_id);
    }
    list.sort((a, b) => focusValue(b, focus) - focusValue(a, focus) || b.reviews_total - a.reviews_total);
    return list;
  }, [benchmark, focus, branchSearch, branchFilter]);

  const focusMax = useMemo(() => {
    if (focus === "volume") return Math.max(1, ...branches.map((b) => b.reviews_total));
    return FOCUS_META[focus].max;
  }, [branches, focus]);

  const accountAvg = useMemo(() => {
    if (branches.length === 0) return 0;
    return branches.reduce((s, b) => s + focusValue(b, focus), 0) / branches.length;
  }, [branches, focus]);

  const portfolio = benchmark ? {
    health: benchmark.portfolio_health_score,
    actionRate: benchmark.portfolio_action_rate,
    velocity: benchmark.portfolio_velocity_per_month,
    impressions: benchmark.portfolio_impressions,
    actions: benchmark.portfolio_actions,
    plain: benchmark.plain_summary,
    dist: benchmark.distribution,
  } : null;

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">{bp.title}</h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">{bp.sub}</p>
        </div>
        <RangeChannelControls
          days={days}
          setDays={(d) => { setDays(d); setLoading(true); }}
          channelId={channelId}
          setChannelId={(c) => { setChannelId(c); setLoading(true); }}
          channels={channels}
        />
      </div>

      <div className="mb-5">
        <BenchmarkCards
          benchmark={benchmark}
          loading={loading}
          onRefreshExternal={() => void handleRefreshExternal()}
          refreshingExternal={refreshingExternal}
          googleConnected={channels.length > 0}
        />
      </div>

      {error && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[13px] font-semibold text-[var(--ui-ink-2)]">{bp.loadFail}</p>
          <button
            onClick={() => { setError(false); setLoading(true); setRetryCount((c) => c + 1); }}
            className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            {bp.retry}
          </button>
        </div>
      ) : !benchmark && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[14px] font-bold text-[var(--ui-ink)]">{bp.emptyTitle}</p>
          <p className="max-w-sm text-[12px] text-[var(--ui-ink-2)]">
            {bp.emptyBody}
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Portfolio health strip — the 4 numbers owners check first */}
          {portfolio && benchmark && (
            <>
            <section aria-label={bp.healthAria} className="grid gap-5 sm:gap-6 sm:grid-cols-4">
              <div className="rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-ink)] p-4 text-[var(--ui-on-ink)]">
                <p className="text-[10px] font-bold uppercase tracking-widest opacity-70">{bp.health}</p>
                <p className="mt-1 text-[28px] font-black leading-none">{portfolio.health ?? "—"}<span className="text-[14px] font-bold opacity-70">/100</span></p>
                <p className="mt-1 text-[11px] leading-tight opacity-75">
                  {portfolio.health != null ? (portfolio.health >= 80 ? bp.strong : portfolio.health >= 60 ? bp.solid : bp.needsWork) : "—"}
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">{bp.actionRate}</p>
                <p className="mt-1 text-[22px] font-black leading-none text-[var(--ui-ink)]">
                  {portfolio.actionRate != null ? `${fmt(Math.round(portfolio.actionRate * 10) / 10)}%` : "—"}
                </p>
                <p className="mt-1 text-[11px] leading-tight text-[var(--ui-ink-2)]">
                  {portfolio.impressions != null && portfolio.impressions > 0
                    ? `${fill(bp.actionsLine, { actions: fmt(portfolio.actions ?? 0), views: fmt(portfolio.impressions), verdict: portfolio.actionRate != null && portfolio.actionRate < 5 ? bp.lowConv : portfolio.actionRate != null && portfolio.actionRate >= 8 ? bp.converting : bp.average })}`
                    : bp.needViews}
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">{bp.velocity}</p>
                <p className="mt-1 text-[22px] font-black leading-none text-[var(--ui-ink)]">
                  {portfolio.velocity != null ? `${fmt(Math.round(portfolio.velocity * 10) / 10)}` : "—"}<span className="text-[13px] font-bold text-[var(--ui-ink-2)]">{bp.perMo}</span>
                </p>
                <p className="mt-1 text-[11px] leading-tight text-[var(--ui-ink-2)]">{fill(bp.velocityLine, { n: fmt(benchmark.days) })}</p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">{bp.respRate}</p>
                <p className="mt-1 text-[22px] font-black leading-none text-[var(--ui-ink)]">{fmt(Math.round(benchmark.current_response_rate ?? 0))}%</p>
                <p className="mt-1 text-[11px] leading-tight text-[var(--ui-ink-2)]">{benchmark.current_response_rate < 70 ? bp.liftIt : benchmark.current_response_rate >= 90 ? bp.excellent : bp.good90}</p>
              </div>
            </section>
            <FactSource
              source="Google Business Profile"
              detail={fill(bp.lastDaysDetail, { n: fmt(benchmark.days) })}
              href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
              linkLabel={gbp}
            />
            </>
          )}

          {/* Plain-English AI summary — replaces industry estimate as primary insight */}
          {portfolio?.plain && (
            <section aria-label={bp.summaryAria} className="ui-card p-4">
              <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--ui-ink)]">{bp.plain}</p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--ui-ink-2)]">{portfolio.plain}</p>
              <FactSource
                source={bp.sayvorsSummary}
                detail={bp.generatedFrom}
              />
            </section>
          )}

          {/* Industry benchmark bands */}
          {benchmark && (
            <section aria-label={bp.marketAria} className="ui-card p-5">
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bp.marketTitle}</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{bp.marketSub}</p>
              <ul className="mt-4 divide-y divide-[var(--ui-line)]">
                {[
                  { label: bp.mRespRate, you: benchmark.current_response_rate, unit: "%", median: 75.5, good: 90 },
                  { label: bp.mAvgRating, you: benchmark.current_avg_rating, unit: "", median: 4.3, good: 4.7 },
                  { label: bp.mSentiment, you: benchmark.current_sentiment_positive_pct, unit: "%", median: 70, good: 85 },
                ].map((b) => {
                  const you = b.you ?? 0;
                  const status = you >= b.good ? bp.excellent2 : you >= b.median ? bp.onPar : bp.below;
                  const statusCls = you >= b.good ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : you >= b.median ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]";
                  return (
                    <li key={b.label} className="flex items-center gap-3 py-3 first:pt-1 last:pb-1">
                      <div className="min-w-0 flex-1">
                        <p className="text-[12.5px] font-semibold text-[var(--ui-ink)]">{b.label}</p>
                        <p className="mt-0.5 text-[10.5px] text-[var(--ui-ink-2)]">{fill(bp.medianGood, { m: fmt(b.median), u: b.unit, g: fmt(b.good) })}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[13px] font-bold tabular-nums text-[var(--ui-ink)]">{typeof you === "number" ? fmt(Math.round(you * 10) / 10) : "—"}{b.unit}</p>
                        <span className={`mt-1 inline-block rounded-[2px] px-2 py-0.5 text-[10px] font-bold ${statusCls}`}>{status}</span>
                      </div>
                    </li>
                  );
                })}
              </ul>
              {benchmark.current_response_rate < 90 && (
                <div className="mt-4 rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-3">
                  <p className="text-[12px] font-semibold text-[var(--ui-ink)]">{bp.nudgeTitle}</p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{fill(bp.nudgeBody, { n: fmt(Math.round(benchmark.current_response_rate)) })}</p>
                </div>
              )}
              <FactSource
                source={bp.studiesSource}
                detail={bp.studiesDetail}
              />
            </section>
          )}

 
           {/* Market response ranking — your median vs. other Sayvors businesses */}
           {marketBenchmarks.length > 0 ? (
             <section aria-label={bp.speedAria} className="ui-card p-5">
               <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bp.speedTitle}</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                {fill(bp.speedSub, { n: fmt(Math.max(...marketBenchmarks.map((m) => m.business_count || 0))) })}
              </p>
              {Math.max(...marketBenchmarks.map((m) => m.business_count || 0)) < 3 && (
                <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink)]">
                  {bp.peersFew}
                </p>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {marketBenchmarks.map((mb, idx) => {
                  const enough = (mb.business_count ?? 0) >= 3 && mb.median !== null;
                  return (
                    <div key={`${mb.metric}:${idx}`} className="rounded-[2px] bg-[var(--ui-sunken)] p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{mb.metric.replace(/_/g, " ")}</p>
                      <p className="mt-1 text-[18px] font-black tabular-nums text-[var(--ui-ink)]">
                        {enough ? (mb.metric.includes("seconds") ? fmt(Math.round(mb.median as number)) + "s" : fmt(Math.round((mb.median as number) * 10) / 10)) : "-"}
                      </p>
                      {enough && mb.p25 !== null && mb.p75 !== null && (
                        <p className="mt-1 text-[10.5px] text-[var(--ui-ink-2)]">
                          p25: {mb.metric.includes("seconds") ? fmt(Math.round(mb.p25)) + "s" : fmt(Math.round(mb.p25 * 10) / 10)} - p75: {mb.metric.includes("seconds") ? fmt(Math.round(mb.p75)) + "s" : fmt(Math.round(mb.p75 * 10) / 10)}
                        </p>
                      )}
                      <p className="mt-1 text-[10px] text-[var(--ui-ink-2)]">{fill(bp.businessesN, { n: fmt(mb.business_count) })}</p>
                    </div>
                  );
                })}
              </div>
               {benchmark && marketBenchmarks.some((mb) => mb.metric === "median_first_response_seconds" && mb.median !== null) && (() => {
                 const mb = marketBenchmarks.find((m) => m.metric === "median_first_response_seconds");
                 if (!mb?.median || (mb.business_count ?? 0) < 3) return null;
                 return (
                   <div className="mt-4 rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-3">
                     <p className="text-[12px] font-semibold text-[var(--ui-ink)]">
                       {fill(bp.marketMedianLine, { n: fmt(Math.round(mb.median)), m: fmt(mb.business_count) })}
                     </p>
                     <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                       {fill(bp.yourRateLine, { n: fmt(Math.round(benchmark.current_response_rate)), m: marketBenchmarks.find((m) => m.metric === "response_rate")?.median != null ? fmt(Math.round(marketBenchmarks.find((m) => m.metric === "response_rate")!.median!)) : "—" })}
                     </p>
                   </div>
                 );
               })()}
               <FactSource
                 source={bp.marketSource}
                 detail={fill(bp.marketDetail, { n: fmt(Math.max(...marketBenchmarks.map((m) => m.business_count || 0))) })}
                 note={bp.marketNote}
                 href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
                 linkLabel="Open GBP dashboard"
               />
             </section>
           ) : (
             <section aria-label={bp.speedAria} className="ui-card p-5">
               <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bp.speedTitle}</h3>
               <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">
                 {bp.collecting}
               </p>
             </section>
           )}

                      {/* Metric focus filter */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={fx.groupAria}>
            {(Object.keys(FOCUS_META) as MetricFocus[]).map((f) => (
              <button
                key={f}
                onClick={() => setFocus(f)}
                aria-pressed={focus === f}
                title={focusHint(f, fx)}
                className={`rounded-[2px] px-3.5 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                  focus === f
                    ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                    : "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
                }`}
              >
                {focusLabel(f, fx)}
              </button>
            ))}
          </div>

          {/* Filter options */}
          <div className="ui-card flex flex-wrap items-center gap-2 p-3">
            <div className="relative flex-1 min-w-[180px]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--ui-ink-2)]" aria-hidden>
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
              </svg>
              <input
                value={branchSearch}
                onChange={(e) => setBranchSearch(e.target.value)}
                placeholder={bp.filterPh}
                className="ui-input w-full bg-[var(--ui-surface)] py-2 pl-8 pr-3 text-[12px] font-medium text-[var(--ui-ink)] placeholder:text-[var(--ui-ink-2)]"
              />
            </div>
            <select
              value={branchFilter}
              onChange={(e) => setBranchFilter(e.target.value as typeof branchFilter)}
              className="ui-input bg-[var(--ui-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)]"
            >
              <option value="all">{fill(bp.filterAll, { n: fmt(benchmark?.branches.length ?? 0) })}</option>
              <option value="with_reviews">{bp.filterWith}</option>
              <option value="no_reviews">{bp.filterNone}</option>
              <option value="top3">{bp.filterTop}</option>
              <option value="needs_attention">{bp.filterNeeds}</option>
            </select>
            {(branchSearch || branchFilter !== "all") && (
              <button
                onClick={() => { setBranchSearch(""); setBranchFilter("all"); }}
                className="ui-btn bg-[var(--ui-sunken)] px-3 py-2 text-[11px] font-semibold text-[var(--ui-ink)]"
              >
                {bp.clearFilters}
              </button>
            )}
            <span className="ml-auto text-[11px] font-medium text-[var(--ui-ink-2)]">
              {fill(bp.shownLine, { shown: fmt(branches.length), total: fmt(benchmark?.branches.length ?? 0) })}
            </span>
          </div>

          {/* Distribution strip — variance at a glance */}
          {portfolio?.dist && benchmark!.branches.length > 1 && (
            <section aria-label={bp.distAria} className="ui-card flex flex-wrap gap-2 p-3 text-[11px]">
              {(() => {
                const d = portfolio.dist as Record<string, { best: number; median: number; worst: number; gap: number }>;
                const rep = d["reputation_score"];
                const vel = d["velocity_per_month"];
                return (
                  <>
                    {rep && (
                      <span className="ui-chip gap-1.5 px-3 py-1.5 font-medium text-[var(--ui-ink-2)]">
                        <span className="h-1.5 w-1.5 rounded-full bg-[var(--ui-ink)]" aria-hidden />
                        {bp.distRep}: <strong className="text-[var(--ui-ink)]">{fmt(rep.best)}</strong> {bp.distBest} · {fmt(rep.median)} {bp.distMedian} · {fmt(rep.worst)} {bp.distWorst} · <span className={rep.gap > 30 ? "font-bold text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}>{bp.distGap} {fmt(rep.gap)}</span>{rep.gap > 30 ? ` — ${bp.fixVar}` : ""}
                      </span>
                    )}
                    {vel && (
                      <span className="ui-chip gap-1.5 px-3 py-1.5 font-medium text-[var(--ui-ink-2)]">
                        {bp.distVel}: <strong className="text-[var(--ui-ink)]">{fmt(vel.best)}/mo</strong> {bp.distBest} · {fmt(vel.median)}/mo {bp.distMedian} · {bp.distGap} {fmt(vel.gap)}/mo
                      </span>
                    )}
                  </>
                );
              })()}
            </section>
          )}

          {/* Leader spotlight */}
          {benchmark?.leader && (
            <section aria-label={bp.leaderAria} className="rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-ink)] p-5 text-[var(--ui-on-ink)]">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-70">{fill(bp.leaderTitle, { name: benchmark.leader.name })}</p>
              <ul className="mt-2 space-y-1">
                {benchmark.leader.reasons.map((r) => (
                  <li key={r} className="flex items-start gap-1.5 text-[13px] font-medium opacity-80">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--ui-on-ink)]" aria-hidden />
                    {r}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Branch leaderboard */}
          <section aria-label={bp.rankAria} className="ui-card p-5">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <h3 className="inline-flex items-center gap-1.5 text-[14px] font-bold text-[var(--ui-ink)]">
                {fill(bp.rankTitle, { focus: focusLabel(focus, fx) })}
                <span className="group relative inline-flex">
                  <span
                    tabIndex={0}
                    role="button"
                    aria-label={bp.howCalc}
                    className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-[var(--ui-line-strong)] bg-[var(--ui-sunken)] text-[10px] font-bold leading-none text-[var(--ui-ink-2)] transition hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                  >
                    i
                  </span>
                  <span className="pointer-events-none absolute left-1/2 top-full z-50 mt-2 hidden w-[420px] max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-3 text-left text-[11px] font-normal leading-relaxed text-[var(--ui-ink)] group-hover:block group-focus-within:block">
                    <span className="block text-[11px] font-bold text-[var(--ui-ink)]">{bp.howTitle}</span>
                    <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[var(--ui-ink-2)]">
                      <span>{bp.howBody}</span>
                      <span className="font-mono text-[10px] text-[var(--ui-ink)]">
                        {bp.repFormula}
                      </span>
                    </span>
                    <span className="mt-2 flex items-center justify-between gap-3 border-t border-[var(--ui-line)] pt-2 text-[var(--ui-ink-2)]">
                      <span>Al&nbsp;Malqa: 4.86★ →48.6 + 86% →21.5 + 29% →7.1 = <span className="font-bold text-[var(--ui-ink)]">~{fmt(77)}</span></span>
                      <span className="shrink-0 text-[var(--ui-ink-2)]">{bp.avgIs}</span>
                    </span>
                  </span>
                </span>
              </h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">{fill(bp.acctAvg, { v: focus === "rating" ? fmt(Math.round(accountAvg * 10) / 10) + "★" : focus === "volume" ? fmt(Math.round(accountAvg)) : `${fmt(Math.round(accountAvg))}${FOCUS_META[focus].unit}` })}</p>
            </div>
            <p className="mb-4 text-[11px] text-[var(--ui-ink-2)]">{focusHint(focus, fx)}</p>
            {branches.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{bp.noBranches}</p>
            ) : (
              <div className="space-y-3">
                {branches.map((b, i) => {
                  const v = focusValue(b, focus);
                  const pct = Math.max(2, Math.min(100, (v / focusMax) * 100));
                  const empty = b.reviews_total === 0;
                  return (
                    <div key={b.channel_id}>
                      <div className="flex items-center gap-2.5">
                        <span className="w-6 shrink-0 text-center text-[15px]" aria-hidden>
                          {empty ? "💤" : (MEDALS[i] ?? `#${i + 1}`)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline justify-between gap-2">
                            <p className="truncate text-[13px] font-bold text-[var(--ui-ink)]">
                              {b.name}
                              {b.top_problem ? (
                                <span className="ml-2 truncate text-[10.5px] font-medium text-[var(--ui-ink)]">
                                  {fill(bp.mentionLine, { p: b.top_problem, n: fmt(b.top_problem_mentions) })}
                                </span>
                              ) : null}
                            </p>
                            <p className="shrink-0 text-[15px] font-bold tabular-nums text-[var(--ui-ink)]">
                              {empty ? "—" : fmtValue(b, focus, fmt)}
                            </p>
                          </div>
                          <div className="mt-1 h-2 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                            <div
                              className={`h-full rounded-full transition-all ${empty ? "bg-[var(--ui-line)]" : i === 0 ? "bg-[var(--ui-ink)]" : "bg-[var(--ui-ink-2)]"}`}
                              style={{ width: `${empty ? 100 : pct}%` }}
                            />
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-[var(--ui-ink-2)]">
                            <span>⭐ {fmt(Math.round(b.avg_rating * 10) / 10)} · {fill(bp.reviewsLine, { n: fmt(b.reviews_total) })}</span>
                            <span>😊 {fill(bp.positiveLine, { n: fmt(Math.round(b.positive_pct)) })}</span>
                            <span>↩️ {fill(bp.repliedLine, { n: fmt(Math.round(b.response_rate)) })}</span>
                            {b.health_score != null && <span className="font-semibold text-[var(--ui-ink)]">{fill(bp.healthLine, { n: fmt(b.health_score) })}</span>}
                            {b.velocity_per_month != null && <span>{fill(bp.veloLine, { n: fmt(Math.round(b.velocity_per_month * 10) / 10) })}</span>}
                            {b.action_rate != null && <span>{fill(bp.actionLine, { n: fmt(Math.round(b.action_rate * 10) / 10) })}</span>}
                            {b.impressions_maps != null && b.impressions_maps > 0 && <span>{fill(bp.viewsLine, { n: fmt(b.impressions_maps) })}</span>}
                            {typeof b.rating_delta === "number" && b.rating_delta !== 0 && (
                              <span className={b.rating_delta > 0 ? "font-semibold text-[var(--ui-ink)]" : "font-bold text-[var(--ui-ink)]"}>
                                {fill(bp.deltaLine, { dir: b.rating_delta > 0 ? "▲" : "▼", n: fmt(Math.abs(Math.round(b.rating_delta * 10) / 10)) })}
                              </span>
                            )}
                            {b.gap_vs_leader_per_year != null && b.gap_vs_leader_per_year > 0 && (
                              <span className="font-semibold text-[var(--ui-ink)]">{fill(bp.gapLine, { n: fmt(Math.round(b.gap_vs_leader_per_year * 10) / 10) })}</span>
                            )}
                          </div>
                          {b.top_problem_mentions > 0 && b.action_rate != null && b.action_rate < 5 && (
                            <p className="mt-1 text-[10.5px] font-semibold text-[var(--ui-ink)]">{bp.notConverting}</p>
                          )}
                          {empty && (
                            <p className="mt-1 text-[10.5px] italic text-[var(--ui-ink-2)]">
                              {bp.noSync}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <FactSource
              source="Google Business Profile"
              detail={fill(bp.branchDetail, { n: fmt(benchmark?.days ?? days) })}
              href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
              linkLabel={gbp}
            />
          </section>

          {/* Needs attention */}
          {benchmark?.needs_attention && (
            <section aria-label={bp.attentionAria} className="rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-ink)] p-5 text-[var(--ui-on-ink)]">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-70">{fill(bp.attentionTitle, { name: benchmark.needs_attention.name })}</p>
              <ul className="mt-2 space-y-1">
                {benchmark.needs_attention.reasons.map((r) => (
                  <li key={r} className="flex items-start gap-1.5 text-[13px] font-medium opacity-80">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--ui-on-ink)]" aria-hidden />
                    {r}
                  </li>
                ))}
              </ul>
              <Link
                href="/dashboard/reviews"
                className="mt-3 inline-block rounded-[2px] bg-[var(--ui-on-ink)] px-3.5 py-1.5 text-[12px] font-bold text-[var(--ui-ink)] transition hover:opacity-90"
              >
                {bp.fixInReviews}
              </Link>
            </section>
          )}

          {/* Per-branch recommendations */}
          {(benchmark?.recommendations?.length ?? 0) > 0 && (
            <section aria-label={bp.recAria} className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{bp.recTitle}</h3>
              <div className="mt-3 grid gap-5 sm:gap-6 md:grid-cols-2">
                {benchmark!.recommendations.map((rec, i) => (
                  <div
                    key={`${rec.channel_id}-${i}`}
                    className={`rounded-xl border p-3.5 ${
                      rec.priority === "high"
                        ? "border-[var(--ui-line-strong)] bg-[var(--ui-surface)]"
                        : rec.priority === "win"
                          ? "border-[var(--ui-line)] bg-[var(--ui-surface)]"
                          : "border-[var(--ui-line)] bg-[var(--ui-sunken)]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
                        rec.priority === "high"
                          ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                          : rec.priority === "win"
                            ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
                            : "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]"
                      }`}>
                        {rec.priority === "win" ? bp.playbook : rec.priority}
                      </span>
                      <p className="truncate text-[12px] font-bold text-[var(--ui-ink)]">{rec.name}</p>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ui-ink-2)]">{rec.text}</p>
                  </div>
                ))}
              </div>
              <FactSource
                source={bp.recSource}
                detail={bp.recDetail}
                href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
                linkLabel={gbp}
              />
            </section>
          )}

          {/* Recommended locations */}
          {benchmark?.branches && benchmark.branches.length > 0 && (
            <section aria-label={bp.recLocAria} className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{bp.recLocTitle}</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{bp.recLocSub}</p>
              <div className="mt-3 grid gap-5 sm:gap-6 sm:grid-cols-2">
                {benchmark.branches.slice(0, 2).map((b) => (
                  <div key={b.channel_id} className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-[13px] font-bold text-[var(--ui-ink)]">{b.name}</p>
                      <span className="shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2 py-0.5 text-[10px] font-bold text-[var(--ui-on-ink)]">#{fmt(b.rank)} · {fmt(b.reputation_score)}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">⭐ {fmt(Math.round(b.avg_rating * 10) / 10)} · {fill(bp.reviewsLine, { n: fmt(b.reviews_total) })} · {fill(bp.positiveLine, { n: fmt(Math.round(b.positive_pct)) })} · {fill(bp.repliedLine, { n: fmt(Math.round(b.response_rate)) })}</p>
                    <p className="mt-2 text-[11px] font-medium text-[var(--ui-ink-2)]">
                      {b.rank === 1 ? bp.topChoice : b.avg_rating < 4 ? bp.priorityImp : bp.solidPerf}
                    </p>
                    <Link href="/dashboard/locations" className="mt-2 inline-block text-[11px] font-semibold text-[var(--ui-ink)] hover:underline">{bp.viewLoc}</Link>
                  </div>
                ))}
              </div>
              <FactSource
                source="Google Business Profile"
                detail={fill(bp.branchDetail, { n: fmt(benchmark.days) })}
                href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
                linkLabel={gbp}
              />
            </section>
          )}

          {/* Recommended services */}
          {(benchmark && (benchmark.top_services?.length > 0 || benchmark.needs_fix_services?.length > 0)) && (
            <section aria-label={bp.recSvcAria} className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{bp.recSvcTitle}</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{bp.recSvcSub}</p>
              <div className="mt-3 grid gap-5 sm:gap-6 sm:grid-cols-2">
                <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">{bp.promote}</p>
                  {(benchmark.top_services ?? []).length === 0 ? (
                    <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">{bp.noStandout}</p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {(benchmark.top_services ?? []).map((s) => (
                        <li key={s.name} className="flex items-start justify-between gap-2 text-[12px]">
                          <span className="font-semibold text-[var(--ui-ink)]">{s.name}</span>
                          <span className="shrink-0 text-[11px] text-[var(--ui-ink-2)]">{fill(bp.svcStats, { pct: fmt(Math.round(s.positive_pct)), m: fmt(s.mentions), r: s.avg_rating ? ` · ${fmt(Math.round(s.avg_rating * 10) / 10)}★` : "" })}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">{bp.fixThese}</p>
                  {(benchmark.needs_fix_services ?? []).length === 0 ? (
                    <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">{bp.noComplaints}</p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {(benchmark.needs_fix_services ?? []).map((s) => (
                        <li key={s.name} className="flex items-start justify-between gap-2 text-[12px]">
                          <span className="font-semibold text-[var(--ui-ink)]">{s.name}</span>
                          <span className="shrink-0 text-[11px] font-semibold text-[var(--ui-ink)]">{fill(bp.svcNeg, { n: fmt(s.negative), m: fmt(s.mentions) })}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              {(benchmark.top_topics ?? []).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(benchmark.top_topics ?? []).slice(0, 6).map((topic: { name: string; mentions: number }) => (
                    <span key={topic.name} className="ui-chip px-2.5 py-1 text-[11px] font-medium text-[var(--ui-ink-2)]">
                      #{topic.name} · {fmt(topic.mentions)}
                    </span>
                  ))}
                </div>
              )}
              <Link href="/dashboard/locations?tab=services" className="mt-3 inline-block text-[11px] font-semibold text-[var(--ui-ink)] hover:underline">{bp.manageSvc}</Link>
              <FactSource
                source={bp.svcSource}
                detail={fill(bp.svcDetail, { n: fmt(benchmark.days) })}
                href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
                linkLabel={gbp}
              />
            </section>
          )}

          {/* Market view — you vs real Sayvors tenants, no synthetic averages */}
          {benchmark?.cohort && benchmark.cohort.count > 0 && (benchmark.market ?? []).length > 0 ? (
            <section aria-label={bp.marketRankAria} className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">
                {fill(bp.marketYouTitle, { n: fmt(benchmark.cohort.count), label: benchmark.cohort.label })}
              </h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                {benchmark.my_rank
                  ? <>{fill(bp.rankLinePre, { r: fmt(benchmark.my_rank), t: fmt((benchmark.market ?? []).length) })}<strong className="font-semibold text-[var(--ui-ink)]"> — {fill(bp.rankLineScope, { scope: benchmark.cohort.scope === "network" ? bp.scopeNetwork : bp.scopeMarket })}</strong></>
                  : <>{bp.rankEmpty}</>}
              </p>
              <ol className="mt-3 space-y-1.5">
                {(benchmark.market ?? []).map((e) => (
                  <li
                    key={`${e.is_you ? "you" : "them"}-${e.channel_id ?? e.listing_id ?? e.name}`}
                    className={`flex items-center gap-2.5 rounded-xl border px-3 py-2 ${e.is_you ? "border-[var(--ui-ink)] bg-[var(--ui-surface)]" : "border-[var(--ui-line)] bg-[var(--ui-surface)]"}`}
                  >
                    <span className="w-6 shrink-0 text-center text-[13px] font-bold text-[var(--ui-ink-2)]">
                      {e.rank === 1 ? "🥇" : e.rank === 2 ? "🥈" : e.rank === 3 ? "🥉" : e.rank}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-[var(--ui-ink)]">
                        {e.name}
                        {e.is_you && (
                          <span className="ml-1.5 rounded-full bg-[var(--ui-ink)] px-1.5 py-px align-middle text-[9px] font-bold uppercase tracking-wide text-[var(--ui-on-ink)]">{bp.youBadge}</span>
                        )}
                      </span>
                      <span className="block text-[11px] text-[var(--ui-ink-2)]">
                        {fmt(Math.round(e.avg_rating * 10) / 10)}★ · {fill(bp.reviewsLine, { n: fmt(e.reviews_total) })}
                        {typeof e.response_rate === "number" ? ` · ${fill(bp.repliedLine, { n: fmt(Math.round(e.response_rate)) })}` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 text-[13px] font-bold text-[var(--ui-ink)]">{fmt(e.reputation_score)}</span>
                  </li>
                ))}
              </ol>
              {typeof benchmark.cohort.median_rating === "number" && (
                <p className="mt-3 text-[11px] text-[var(--ui-ink-2)]">
                  {fill(bp.medLine, { r: fmt(Math.round(benchmark.cohort.median_rating * 10) / 10), n: fmt(benchmark.cohort.median_reviews ?? 0) })}
                  {typeof benchmark.cohort.top3_median_rating === "number" && <> {fill(bp.top3, { r: fmt(Math.round(benchmark.cohort.top3_median_rating * 10) / 10) })}</>}
                </p>
              )}
              <FactSource
                source={bp.listingsSource}
                detail={bp.mktDetail}
                note={bp.mktNote}
                href={channels.length > 0 ? GBP_DASHBOARD_URL : null}
                linkLabel={gbp}
              />
            </section>
          ) : (
            <p className="px-1 text-center text-[10.5px] leading-relaxed text-[var(--ui-ink-2)]">
              {benchmark?.benchmark_text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
