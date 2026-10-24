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

type MetricFocus = "reputation" | "rating" | "sentiment" | "response" | "volume";

const FOCUS_META: Record<MetricFocus, { label: string; hint: string; max: number; unit: string }> = {
  reputation: { label: "Reputation", hint: "0–100 composite of rating, replies & sentiment", max: 100, unit: "" },
  rating: { label: "Rating", hint: "Average Google stars", max: 5, unit: "★" },
  sentiment: { label: "Sentiment", hint: "% of reviews classified positive", max: 100, unit: "%" },
  response: { label: "Response rate", hint: "% of reviews your business replied to", max: 100, unit: "%" },
  volume: { label: "Volume", hint: "Total reviews indexed", max: 0, unit: "" },
};

function focusValue(b: BranchBenchmark, f: MetricFocus): number {
  switch (f) {
    case "reputation": return b.reputation_score;
    case "rating": return b.avg_rating;
    case "sentiment": return b.positive_pct;
    case "response": return b.response_rate;
    case "volume": return b.reviews_total;
  }
}

function fmtValue(b: BranchBenchmark, f: MetricFocus): string {
  const v = focusValue(b, f);
  if (f === "rating") return `${v.toFixed(1)}★`;
  if (f === "sentiment" || f === "response") return `${v.toFixed(0)}%`;
  return `${Math.round(v)}`;
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

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchBenchmark(days, channelId),
      fetchMarketBenchmarks("median_first_response_seconds").catch(() => []),
    ])
      .then(([b, mb]) => {
        if (cancelled) return;
        setBenchmark(b);
        setMarketBenchmarks(mb ?? []);
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
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">Benchmark</h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">Your branches, ranked against each other — real data, no estimates.</p>
        </div>
        <RangeChannelControls
          days={days}
          setDays={(d) => { setDays(d); setLoading(true); }}
          channelId={channelId}
          setChannelId={(c) => { setChannelId(c); setLoading(true); }}
          channels={channels}
        />
      </div>

      {error && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[13px] font-semibold text-[var(--ui-ink-2)]">Couldn&apos;t load benchmark data.</p>
          <button
            onClick={() => { setError(false); setLoading(true); setRetryCount((c) => c + 1); }}
            className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            Retry
          </button>
        </div>
      ) : !benchmark && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[14px] font-bold text-[var(--ui-ink)]">No comparison data yet</p>
          <p className="max-w-sm text-[12px] text-[var(--ui-ink-2)]">
            Connect at least one location and sync its reviews — branch comparison appears here.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Portfolio health strip — the 4 numbers owners check first */}
          {portfolio && benchmark && (
            <section aria-label="Portfolio health" className="grid gap-5 sm:gap-6 sm:grid-cols-4">
              <div className="rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-ink)] p-4 text-[var(--ui-on-ink)]">
                <p className="text-[10px] font-bold uppercase tracking-widest opacity-70">Health score</p>
                <p className="mt-1 text-[28px] font-black leading-none">{portfolio.health ?? "—"}<span className="text-[14px] font-bold opacity-70">/100</span></p>
                <p className="mt-1 text-[11px] leading-tight opacity-75">
                  {portfolio.health != null ? (portfolio.health >= 80 ? "Strong — keep the lead" : portfolio.health >= 60 ? "Solid — close the gaps" : "Needs work — see below") : "—"}
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">Action rate</p>
                <p className="mt-1 text-[22px] font-black leading-none text-[var(--ui-ink)]">
                  {portfolio.actionRate != null ? `${portfolio.actionRate.toFixed(1)}%` : "—"}
                </p>
                <p className="mt-1 text-[11px] leading-tight text-[var(--ui-ink-2)]">
                  {portfolio.impressions != null && portfolio.impressions > 0
                    ? `${portfolio.actions} actions from ${portfolio.impressions.toLocaleString()} views · ${portfolio.actionRate != null && portfolio.actionRate < 5 ? "views not turning into calls" : portfolio.actionRate != null && portfolio.actionRate >= 8 ? "converting well" : "average" }`
                    : "Need location views data"}
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">Velocity</p>
                <p className="mt-1 text-[22px] font-black leading-none text-[var(--ui-ink)]">
                  {portfolio.velocity != null ? `${portfolio.velocity}` : "—"}<span className="text-[13px] font-bold text-[var(--ui-ink-2)]">/mo</span>
                </p>
                <p className="mt-1 text-[11px] leading-tight text-[var(--ui-ink-2)]">Reviews per month · last {benchmark.days}d pace</p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">Response rate</p>
                <p className="mt-1 text-[22px] font-black leading-none text-[var(--ui-ink)]">{(benchmark.current_response_rate ?? 0).toFixed(0)}%</p>
                <p className="mt-1 text-[11px] leading-tight text-[var(--ui-ink-2)]">{benchmark.current_response_rate < 70 ? "Lift this to protect reputation" : benchmark.current_response_rate >= 90 ? "Excellent — answering everyone" : "Good — aim for 90%+"}</p>
              </div>
            </section>
          )}

          {/* Plain-English AI summary — replaces industry estimate as primary insight */}
          {portfolio?.plain && (
            <section aria-label="Summary" className="ui-card p-4">
              <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--ui-ink)]">In plain English</p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--ui-ink-2)]">{portfolio.plain}</p>
            </section>
          )}

          {/* Industry benchmark bands */}
          {benchmark && (
            <section aria-label="Industry benchmarks" className="ui-card p-5">
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">You vs. the market</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">Industry medians from published studies.</p>
              <ul className="mt-4 divide-y divide-[var(--ui-line)]">
                {[
                  { label: "Review response rate", you: benchmark.current_response_rate, unit: "%", median: 75.5, good: 90 },
                  { label: "Average rating", you: benchmark.current_avg_rating, unit: "", median: 4.3, good: 4.7 },
                  { label: "Sentiment (positive %)", you: benchmark.current_sentiment_positive_pct, unit: "%", median: 70, good: 85 },
                ].map((b) => {
                  const you = b.you ?? 0;
                  const status = you >= b.good ? "Excellent" : you >= b.median ? "On par" : "Below median";
                  const statusCls = you >= b.good ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : you >= b.median ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]";
                  return (
                    <li key={b.label} className="flex items-center gap-3 py-3 first:pt-1 last:pb-1">
                      <div className="min-w-0 flex-1">
                        <p className="text-[12.5px] font-semibold text-[var(--ui-ink)]">{b.label}</p>
                        <p className="mt-0.5 text-[10.5px] text-[var(--ui-ink-2)]">Median {b.median}{b.unit} / Good {b.good}{b.unit}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[13px] font-bold tabular-nums text-[var(--ui-ink)]">{typeof you === "number" ? you.toFixed(1) : "—"}{b.unit}</p>
                        <span className={`mt-1 inline-block rounded-[2px] px-2 py-0.5 text-[10px] font-bold ${statusCls}`}>{status}</span>
                      </div>
                    </li>
                  );
                })}
              </ul>
              {benchmark.current_response_rate < 90 && (
                <div className="mt-4 rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-3">
                  <p className="text-[12px] font-semibold text-[var(--ui-ink)]">Nudge: every +25% response rate = +4.1% GBP conversions (SOCi 2024)</p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">You are at {benchmark.current_response_rate.toFixed(0)}%. Reaching 90% could lift conversions.</p>
                </div>
              )}
            </section>
          )}

 
           {/* Market response ranking — your median vs. other Sayvors businesses */}
           {marketBenchmarks.length > 0 && (
             <section aria-label="Market response ranking" className="ui-card p-5">
               <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Your response speed vs. the market</h3>
               <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                 Median first reply across {marketBenchmarks[0]?.business_count ?? 0} businesses on Sayvors.
               </p>
               <div className="mt-4 grid gap-3 sm:grid-cols-3">
                 {marketBenchmarks.map((mb) => (
                   <div key={mb.metric} className="rounded-[2px] bg-[var(--ui-sunken)] p-3">
                     <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{mb.metric.replace(/_/g, " ")}</p>
                     <p className="mt-1 text-[18px] font-black tabular-nums text-[var(--ui-ink)]">
                       {mb.median !== null ? Math.round(mb.median) : "—"}{mb.metric.includes("response") ? "s" : ""}
                     </p>
                     {mb.p25 !== null && mb.p75 !== null && (
                       <p className="mt-1 text-[10.5px] text-[var(--ui-ink-2)]">
                         p25: {Math.round(mb.p25)} · p75: {Math.round(mb.p75)}
                       </p>
                     )}
                   </div>
                 ))}
               </div>
               {benchmark && marketBenchmarks.some((mb) => mb.metric === "median_first_response_seconds" && mb.median !== null) && (
                 <p className="mt-3 text-[11.5px] text-[var(--ui-ink-2)]">
                   {(() => {
                     const mb = marketBenchmarks.find((m) => m.metric === "median_first_response_seconds");
                     const yours = benchmark.current_response_rate; // placeholder for median FRT
                     if (!mb?.median) return null;
                     return `Market median first reply: ${Math.round(mb.median)}s. ${mb.business_count} businesses compared.`;
                   })()}
                 </p>
               )}
             </section>
           )}

           {/* Metric focus filter */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Comparison metric">
            {(Object.keys(FOCUS_META) as MetricFocus[]).map((f) => (
              <button
                key={f}
                onClick={() => setFocus(f)}
                aria-pressed={focus === f}
                title={FOCUS_META[f].hint}
                className={`rounded-[2px] px-3.5 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                  focus === f
                    ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                    : "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
                }`}
              >
                {FOCUS_META[f].label}
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
                placeholder="Filter branches by name…"
                className="ui-input w-full bg-[var(--ui-surface)] py-2 pl-8 pr-3 text-[12px] font-medium text-[var(--ui-ink)] placeholder:text-[var(--ui-ink-2)]"
              />
            </div>
            <select
              value={branchFilter}
              onChange={(e) => setBranchFilter(e.target.value as typeof branchFilter)}
              className="ui-input bg-[var(--ui-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)]"
            >
              <option value="all">All branches ({benchmark?.branches.length ?? 0})</option>
              <option value="with_reviews">With reviews</option>
              <option value="no_reviews">No reviews yet</option>
              <option value="top3">Top 3 performers</option>
              <option value="needs_attention">Needs attention</option>
            </select>
            {(branchSearch || branchFilter !== "all") && (
              <button
                onClick={() => { setBranchSearch(""); setBranchFilter("all"); }}
                className="ui-btn bg-[var(--ui-sunken)] px-3 py-2 text-[11px] font-semibold text-[var(--ui-ink)]"
              >
                Clear filters
              </button>
            )}
            <span className="ml-auto text-[11px] font-medium text-[var(--ui-ink-2)]">
              {branches.length} of {benchmark?.branches.length ?? 0} shown
            </span>
          </div>

          {/* Distribution strip — variance at a glance */}
          {portfolio?.dist && benchmark!.branches.length > 1 && (
            <section aria-label="Distribution" className="ui-card flex flex-wrap gap-2 p-3 text-[11px]">
              {(() => {
                const d = portfolio.dist as Record<string, { best: number; median: number; worst: number; gap: number }>;
                const rep = d["reputation_score"];
                const vel = d["velocity_per_month"];
                return (
                  <>
                    {rep && (
                      <span className="ui-chip gap-1.5 px-3 py-1.5 font-medium text-[var(--ui-ink-2)]">
                        <span className="h-1.5 w-1.5 rounded-full bg-[var(--ui-ink)]" aria-hidden />
                        Reputation: <strong className="text-[var(--ui-ink)]">{rep.best}</strong> best · {rep.median} median · {rep.worst} worst · <span className={rep.gap > 30 ? "font-bold text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}>gap {rep.gap}</span>{rep.gap > 30 ? " — fix variance" : ""}
                      </span>
                    )}
                    {vel && (
                      <span className="ui-chip gap-1.5 px-3 py-1.5 font-medium text-[var(--ui-ink-2)]">
                        Velocity: <strong className="text-[var(--ui-ink)]">{vel.best}/mo</strong> best · {vel.median}/mo median · gap {vel.gap}/mo
                      </span>
                    )}
                  </>
                );
              })()}
            </section>
          )}

          {/* Leader spotlight */}
          {benchmark?.leader && (
            <section aria-label="Leading branch" className="rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-ink)] p-5 text-[var(--ui-on-ink)]">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-70">🏆 Leading branch — why {benchmark.leader.name} is great</p>
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
          <section aria-label="Branch ranking" className="ui-card p-5">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <h3 className="inline-flex items-center gap-1.5 text-[14px] font-bold text-[var(--ui-ink)]">
                Branch ranking · {FOCUS_META[focus].label}
                <span className="group relative inline-flex">
                  <span
                    tabIndex={0}
                    role="button"
                    aria-label="How is this calculated?"
                    className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-[var(--ui-line-strong)] bg-[var(--ui-sunken)] text-[10px] font-bold leading-none text-[var(--ui-ink-2)] transition hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                  >
                    i
                  </span>
                  <span className="pointer-events-none absolute left-1/2 top-full z-50 mt-2 hidden w-[420px] max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-3 text-left text-[11px] font-normal leading-relaxed text-[var(--ui-ink)] group-hover:block group-focus-within:block">
                    <span className="block text-[11px] font-bold text-[var(--ui-ink)]">How scores are calculated</span>
                    <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[var(--ui-ink-2)]">
                      <span>avg rating, response rate & positive % are live SQL aggregates per branch.</span>
                      <span className="font-mono text-[10px] text-[var(--ui-ink)]">
                        reputation = (avg&nbsp;rating&nbsp;/&nbsp;5&nbsp;×&nbsp;50) + (response&nbsp;rate&nbsp;×&nbsp;25) + (positive&nbsp;%&nbsp;×&nbsp;25)
                      </span>
                    </span>
                    <span className="mt-2 flex items-center justify-between gap-3 border-t border-[var(--ui-line)] pt-2 text-[var(--ui-ink-2)]">
                      <span>Al&nbsp;Malqa: 4.86★ →48.6 + 86% →21.5 + 29% →7.1 = <span className="font-bold text-[var(--ui-ink)]">~77</span></span>
                      <span className="shrink-0 text-[var(--ui-ink-2)]">Avg = mean of branches</span>
                    </span>
                  </span>
                </span>
              </h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">Account average: {focus === "rating" ? accountAvg.toFixed(1) + "★" : focus === "volume" ? Math.round(accountAvg) : `${accountAvg.toFixed(0)}${FOCUS_META[focus].unit}`}</p>
            </div>
            <p className="mb-4 text-[11px] text-[var(--ui-ink-2)]">{FOCUS_META[focus].hint}</p>
            {branches.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">No branches with data in this period.</p>
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
                                  ⚠ guests mention “{b.top_problem}” ×{b.top_problem_mentions}
                                </span>
                              ) : null}
                            </p>
                            <p className="shrink-0 text-[15px] font-bold tabular-nums text-[var(--ui-ink)]">
                              {empty ? "—" : fmtValue(b, focus)}
                            </p>
                          </div>
                          <div className="mt-1 h-2 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                            <div
                              className={`h-full rounded-full transition-all ${empty ? "bg-[var(--ui-line)]" : i === 0 ? "bg-[var(--ui-ink)]" : "bg-[var(--ui-ink-2)]"}`}
                              style={{ width: `${empty ? 100 : pct}%` }}
                            />
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-[var(--ui-ink-2)]">
                            <span>⭐ {b.avg_rating.toFixed(1)} · {b.reviews_total} reviews</span>
                            <span>😊 {b.positive_pct.toFixed(0)}% positive</span>
                            <span>↩️ {b.response_rate.toFixed(0)}% replied</span>
                            {b.health_score != null && <span className="font-semibold text-[var(--ui-ink)]">♥ {b.health_score} health</span>}
                            {b.velocity_per_month != null && <span>⚡ {b.velocity_per_month}/mo</span>}
                            {b.action_rate != null && <span>🎯 {b.action_rate.toFixed(1)}% action rate</span>}
                            {b.impressions_maps != null && b.impressions_maps > 0 && <span>👁 {b.impressions_maps.toLocaleString()} views</span>}
                            {typeof b.rating_delta === "number" && b.rating_delta !== 0 && (
                              <span className={b.rating_delta > 0 ? "font-semibold text-[var(--ui-ink)]" : "font-bold text-[var(--ui-ink)]"}>
                                {b.rating_delta > 0 ? "▲" : "▼"} {Math.abs(b.rating_delta).toFixed(1)}★ this period
                              </span>
                            )}
                            {b.gap_vs_leader_per_year != null && b.gap_vs_leader_per_year > 0 && (
                              <span className="font-semibold text-[var(--ui-ink)]">gap +{b.gap_vs_leader_per_year}/yr vs leader</span>
                            )}
                          </div>
                          {b.top_problem_mentions > 0 && b.action_rate != null && b.action_rate < 5 && (
                            <p className="mt-1 text-[10.5px] font-semibold text-[var(--ui-ink)]">Views not converting — check listing completeness & CTA.</p>
                          )}
                          {empty && (
                            <p className="mt-1 text-[10.5px] italic text-[var(--ui-ink-2)]">
                              No reviews synced yet — still waiting on Google. Excluded from ranking.
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Needs attention */}
          {benchmark?.needs_attention && (
            <section aria-label="Branch needing attention" className="rounded-[2px] border border-[var(--ui-ink)] bg-[var(--ui-ink)] p-5 text-[var(--ui-on-ink)]">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-70">🎯 Needs attention — {benchmark.needs_attention.name}</p>
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
                Fix it in Reviews →
              </Link>
            </section>
          )}

          {/* Per-branch recommendations */}
          {(benchmark?.recommendations?.length ?? 0) > 0 && (
            <section aria-label="Branch recommendations" className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">What to do next, per branch</h3>
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
                        {rec.priority === "win" ? "Playbook" : rec.priority}
                      </span>
                      <p className="truncate text-[12px] font-bold text-[var(--ui-ink)]">{rec.name}</p>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ui-ink-2)]">{rec.text}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Recommended locations */}
          {benchmark?.branches && benchmark.branches.length > 0 && (
            <section aria-label="Recommended locations" className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">📍 Recommended locations</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">Where to send customers & where to focus improvement — based on your real branch scores.</p>
              <div className="mt-3 grid gap-5 sm:gap-6 sm:grid-cols-2">
                {benchmark.branches.slice(0, 2).map((b) => (
                  <div key={b.channel_id} className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-[13px] font-bold text-[var(--ui-ink)]">{b.name}</p>
                      <span className="shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2 py-0.5 text-[10px] font-bold text-[var(--ui-on-ink)]">#{b.rank} · {b.reputation_score}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">⭐ {b.avg_rating.toFixed(1)} · {b.reviews_total} reviews · {b.positive_pct.toFixed(0)}% positive · {b.response_rate.toFixed(0)}% replied</p>
                    <p className="mt-2 text-[11px] font-medium text-[var(--ui-ink-2)]">
                      {b.rank === 1 ? "🏆 Top choice to recommend — show this location first." : b.avg_rating < 4 ? "🔧 Priority for improvement — lift rating above 4.0★." : "✨ Solid performer — keep the momentum."}
                    </p>
                    <Link href="/dashboard/locations" className="mt-2 inline-block text-[11px] font-semibold text-[var(--ui-ink)] hover:underline">View location →</Link>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Recommended services */}
          {(benchmark && (benchmark.top_services?.length > 0 || benchmark.needs_fix_services?.length > 0)) && (
            <section aria-label="Service recommendations" className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">🛎️ Recommended services</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">What to promote vs fix — derived from review mentions & sentiment.</p>
              <div className="mt-3 grid gap-5 sm:gap-6 sm:grid-cols-2">
                <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">Promote these</p>
                  {(benchmark.top_services ?? []).length === 0 ? (
                    <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">No standout services yet — need more reviews mentioning specific services.</p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {(benchmark.top_services ?? []).map((s) => (
                        <li key={s.name} className="flex items-start justify-between gap-2 text-[12px]">
                          <span className="font-semibold text-[var(--ui-ink)]">{s.name}</span>
                          <span className="shrink-0 text-[11px] text-[var(--ui-ink-2)]">{s.positive_pct.toFixed(0)}% positive · {s.mentions}×{s.avg_rating ? ` · ${s.avg_rating.toFixed(1)}★` : ""}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">Fix these</p>
                  {(benchmark.needs_fix_services ?? []).length === 0 ? (
                    <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">No recurring service complaints detected. Keep monitoring.</p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {(benchmark.needs_fix_services ?? []).map((s) => (
                        <li key={s.name} className="flex items-start justify-between gap-2 text-[12px]">
                          <span className="font-semibold text-[var(--ui-ink)]">{s.name}</span>
                          <span className="shrink-0 text-[11px] font-semibold text-[var(--ui-ink)]">{s.negative} negative · {s.mentions}×</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              {(benchmark.top_topics ?? []).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(benchmark.top_topics ?? []).slice(0, 6).map((t: { name: string; mentions: number }) => (
                    <span key={t.name} className="ui-chip px-2.5 py-1 text-[11px] font-medium text-[var(--ui-ink-2)]">
                      #{t.name} · {t.mentions}
                    </span>
                  ))}
                </div>
              )}
              <Link href="/dashboard/services" className="mt-3 inline-block text-[11px] font-semibold text-[var(--ui-ink)] hover:underline">Manage services →</Link>
            </section>
          )}

          {/* Market view — you vs real Sayvors tenants, no synthetic averages */}
          {benchmark?.cohort && benchmark.cohort.count > 0 && (benchmark.market ?? []).length > 0 ? (
            <section aria-label="Market ranking" className="ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">
                🏆 You vs {benchmark.cohort.count} {benchmark.cohort.label} on Sayvors
              </h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                {benchmark.my_rank
                  ? <>You rank <strong className="font-semibold text-[var(--ui-ink)]">#{benchmark.my_rank} of {(benchmark.market ?? []).length}</strong> — real connected businesses, same {benchmark.cohort.scope === "network" ? "network" : "market"}.</>
                  : <>Real connected businesses in your market — connect a branch to enter the ranking.</>}
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
                          <span className="ml-1.5 rounded-full bg-[var(--ui-ink)] px-1.5 py-px align-middle text-[9px] font-bold uppercase tracking-wide text-[var(--ui-on-ink)]">You</span>
                        )}
                      </span>
                      <span className="block text-[11px] text-[var(--ui-ink-2)]">
                        {e.avg_rating.toFixed(1)}★ · {e.reviews_total} reviews
                        {typeof e.response_rate === "number" ? ` · ${e.response_rate.toFixed(0)}% replies` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 text-[13px] font-bold text-[var(--ui-ink)]">{e.reputation_score}</span>
                  </li>
                ))}
              </ol>
              {typeof benchmark.cohort.median_rating === "number" && (
                <p className="mt-3 text-[11px] text-[var(--ui-ink-2)]">
                  Market median: <strong className="font-semibold text-[var(--ui-ink-2)]">{benchmark.cohort.median_rating.toFixed(1)}★</strong>
                  {" · "}{benchmark.cohort.median_reviews ?? 0} reviews
                  {typeof benchmark.cohort.top3_median_rating === "number" && <> · top-3 median {benchmark.cohort.top3_median_rating.toFixed(1)}★</>}
                </p>
              )}
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
