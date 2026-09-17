"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchBenchmark,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const hasLoaded = useRef(false);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchBenchmark(days, channelId)
      .then((b) => {
        if (cancelled) return;
        setBenchmark(b);
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

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff] p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Benchmark</h1>
          <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">Your branches, ranked against each other — real data, no estimates.</p>
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
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[13px] font-semibold text-ink/60">Couldn&apos;t load benchmark data.</p>
          <button
            onClick={() => { setError(false); setLoading(true); setRetryCount((c) => c + 1); }}
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            Retry
          </button>
        </div>
      ) : !benchmark && !loading ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[14px] font-bold text-ink">No comparison data yet</p>
          <p className="max-w-sm text-[12px] text-ink/50">
            Connect at least one location and sync its reviews — branch comparison appears here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Metric focus filter */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Comparison metric">
            {(Object.keys(FOCUS_META) as MetricFocus[]).map((f) => (
              <button
                key={f}
                onClick={() => setFocus(f)}
                aria-pressed={focus === f}
                title={FOCUS_META[f].hint}
                className={`rounded-full px-3.5 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  focus === f
                    ? "bg-deep-violet text-white shadow-sm shadow-deep-violet/25"
                    : "border border-ink/[0.08] bg-white/70 text-ink/55 hover:text-ink"
                }`}
              >
                {FOCUS_META[f].label}
              </button>
            ))}
          </div>

          {/* Filter options */}
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-white bg-white/60 p-3 backdrop-blur-sm">
            <div className="relative flex-1 min-w-[180px]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/30" aria-hidden>
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
              </svg>
              <input
                value={branchSearch}
                onChange={(e) => setBranchSearch(e.target.value)}
                placeholder="Filter branches by name…"
                className="w-full rounded-xl border border-ink/10 bg-white py-2 pl-8 pr-3 text-[12px] font-medium text-ink placeholder:text-ink/30 outline-none transition focus:border-deep-violet/30 focus:bg-white"
              />
            </div>
            <select
              value={branchFilter}
              onChange={(e) => setBranchFilter(e.target.value as typeof branchFilter)}
              className="rounded-xl border border-ink/10 bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 outline-none focus:border-deep-violet/30"
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
                className="rounded-xl bg-ink/[0.06] px-3 py-2 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.08]"
              >
                Clear filters
              </button>
            )}
            <span className="ml-auto text-[11px] font-medium text-ink/40">
              {branches.length} of {benchmark?.branches.length ?? 0} shown
            </span>
          </div>

          {/* Leader spotlight */}
          {benchmark?.leader && (
            <section aria-label="Leading branch" className="rounded-2xl border-2 border-amber-300/70 bg-gradient-to-r from-amber-50 to-white p-5 shadow-sm backdrop-blur-sm">
              <p className="text-[10px] font-bold uppercase tracking-widest text-amber-600">🏆 Leading branch — why {benchmark.leader.name} is great</p>
              <ul className="mt-2 space-y-1">
                {benchmark.leader.reasons.map((r) => (
                  <li key={r} className="flex items-start gap-1.5 text-[13px] font-medium text-ink/80">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                    {r}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Branch leaderboard */}
          <section aria-label="Branch ranking" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <h3 className="inline-flex items-center gap-1.5 text-[14px] font-bold text-ink">
                Branch ranking · {FOCUS_META[focus].label}
                <span className="group relative inline-flex">
                  <span
                    tabIndex={0}
                    role="button"
                    aria-label="How is this calculated?"
                    className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-ink/15 bg-ink/[0.04] text-[10px] font-bold leading-none text-ink/60 outline-none transition hover:border-deep-violet/30 hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30"
                  >
                    i
                  </span>
                  <span className="pointer-events-none absolute left-1/2 top-full z-50 mt-2 hidden w-[420px] max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-xl border border-ink/10 bg-ink px-4 py-3 text-left text-[11px] font-normal leading-relaxed text-white shadow-2xl group-hover:block group-focus-within:block">
                    <span className="block text-[11px] font-bold text-white">How scores are calculated</span>
                    <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-white/70">
                      <span>avg rating, response rate & positive % are live SQL aggregates per branch.</span>
                      <span className="font-mono text-[10px] text-white/90">
                        reputation = (avg&nbsp;rating&nbsp;/&nbsp;5&nbsp;×&nbsp;50) + (response&nbsp;rate&nbsp;×&nbsp;25) + (positive&nbsp;%&nbsp;×&nbsp;25)
                      </span>
                    </span>
                    <span className="mt-2 flex items-center justify-between gap-3 border-t border-white/10 pt-2 text-white/60">
                      <span>Al&nbsp;Malqa: 4.86★ →48.6 + 86% →21.5 + 29% →7.1 = <span className="font-bold text-white">~77</span></span>
                      <span className="shrink-0 text-white/40">Avg = mean of branches</span>
                    </span>
                  </span>
                </span>
              </h3>
              <p className="text-[11px] text-ink/45">Account average: {focus === "rating" ? accountAvg.toFixed(1) + "★" : focus === "volume" ? Math.round(accountAvg) : `${accountAvg.toFixed(0)}${FOCUS_META[focus].unit}`}</p>
            </div>
            <p className="mb-4 text-[11px] text-ink/45">{FOCUS_META[focus].hint}</p>
            {branches.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-ink/45">No branches with data in this period.</p>
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
                            <p className="truncate text-[13px] font-bold text-ink">
                              {b.name}
                              {b.top_problem ? (
                                <span className="ml-2 truncate text-[10.5px] font-medium text-coral">
                                  ⚠ guests mention “{b.top_problem}” ×{b.top_problem_mentions}
                                </span>
                              ) : null}
                            </p>
                            <p className="shrink-0 text-[15px] font-bold tabular-nums text-deep-violet">
                              {empty ? "—" : fmtValue(b, focus)}
                            </p>
                          </div>
                          <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink/[0.06]">
                            <div
                              className={`h-full rounded-full transition-all ${empty ? "bg-ink/10" : i === 0 ? "bg-gradient-to-r from-deep-violet to-magenta" : "bg-deep-violet/40"}`}
                              style={{ width: `${empty ? 100 : pct}%` }}
                            />
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-ink/45">
                            <span>⭐ {b.avg_rating.toFixed(1)} · {b.reviews_total} reviews</span>
                            <span>😊 {b.positive_pct.toFixed(0)}% positive</span>
                            <span>↩️ {b.response_rate.toFixed(0)}% replied</span>
                            {typeof b.rating_delta === "number" && b.rating_delta !== 0 && (
                              <span className={b.rating_delta > 0 ? "font-semibold text-emerald" : "font-semibold text-coral"}>
                                {b.rating_delta > 0 ? "▲" : "▼"} {Math.abs(b.rating_delta).toFixed(1)}★ this period
                              </span>
                            )}
                          </div>
                          {empty && (
                            <p className="mt-1 text-[10.5px] italic text-ink/40">
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
            <section aria-label="Branch needing attention" className="rounded-2xl border-2 border-coral/30 bg-coral/[0.04] p-5 backdrop-blur-sm">
              <p className="text-[10px] font-bold uppercase tracking-widest text-coral">🎯 Needs attention — {benchmark.needs_attention.name}</p>
              <ul className="mt-2 space-y-1">
                {benchmark.needs_attention.reasons.map((r) => (
                  <li key={r} className="flex items-start gap-1.5 text-[13px] font-medium text-ink/80">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                    {r}
                  </li>
                ))}
              </ul>
              <Link
                href="/dashboard/reviews"
                className="mt-3 inline-block rounded-lg bg-coral px-3.5 py-1.5 text-[12px] font-bold text-white transition hover:opacity-90"
              >
                Fix it in Reviews →
              </Link>
            </section>
          )}

          {/* Per-branch recommendations */}
          {(benchmark?.recommendations?.length ?? 0) > 0 && (
            <section aria-label="Branch recommendations" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold text-ink">What to do next, per branch</h3>
              <div className="mt-3 grid gap-2.5 md:grid-cols-2">
                {benchmark!.recommendations.map((rec, i) => (
                  <div
                    key={`${rec.channel_id}-${i}`}
                    className={`rounded-xl border p-3.5 ${
                      rec.priority === "high"
                        ? "border-coral/25 bg-coral/[0.05]"
                        : rec.priority === "win"
                          ? "border-emerald/25 bg-emerald/[0.05]"
                          : "border-ink/[0.06] bg-ink/[0.02]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
                        rec.priority === "high"
                          ? "bg-coral/15 text-coral"
                          : rec.priority === "win"
                            ? "bg-emerald/15 text-emerald"
                            : "bg-ink/[0.06] text-ink/50"
                      }`}>
                        {rec.priority === "win" ? "Playbook" : rec.priority}
                      </span>
                      <p className="truncate text-[12px] font-bold text-ink">{rec.name}</p>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-ink/65">{rec.text}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Recommended locations */}
          {benchmark?.branches && benchmark.branches.length > 0 && (
            <section aria-label="Recommended locations" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold text-ink">📍 Recommended locations</h3>
              <p className="mt-1 text-[11px] text-ink/45">Where to send customers & where to focus improvement — based on your real branch scores.</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {benchmark.branches.slice(0, 2).map((b) => (
                  <div key={b.channel_id} className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-[13px] font-bold text-ink">{b.name}</p>
                      <span className="shrink-0 rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-bold text-deep-violet">#{b.rank} · {b.reputation_score}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-ink/50">⭐ {b.avg_rating.toFixed(1)} · {b.reviews_total} reviews · {b.positive_pct.toFixed(0)}% positive · {b.response_rate.toFixed(0)}% replied</p>
                    <p className="mt-2 text-[11px] font-medium text-ink/60">
                      {b.rank === 1 ? "🏆 Top choice to recommend — show this location first." : b.avg_rating < 4 ? "🔧 Priority for improvement — lift rating above 4.0★." : "✨ Solid performer — keep the momentum."}
                    </p>
                    <Link href="/dashboard/locations" className="mt-2 inline-block text-[11px] font-semibold text-deep-violet hover:underline">View location →</Link>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Recommended services */}
          {(benchmark && (benchmark.top_services?.length > 0 || benchmark.needs_fix_services?.length > 0)) && (
            <section aria-label="Service recommendations" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold text-ink">🛎️ Recommended services</h3>
              <p className="mt-1 text-[11px] text-ink/45">What to promote vs fix — derived from review mentions & sentiment.</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-emerald/20 bg-emerald/[0.04] p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-emerald">Promote these</p>
                  {(benchmark.top_services ?? []).length === 0 ? (
                    <p className="mt-2 text-[12px] text-ink/45">No standout services yet — need more reviews mentioning specific services.</p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {(benchmark.top_services ?? []).map((s) => (
                        <li key={s.name} className="flex items-start justify-between gap-2 text-[12px]">
                          <span className="font-semibold text-ink">{s.name}</span>
                          <span className="shrink-0 text-[11px] text-ink/50">{s.positive_pct.toFixed(0)}% positive · {s.mentions}×{s.avg_rating ? ` · ${s.avg_rating.toFixed(1)}★` : ""}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="rounded-xl border border-coral/20 bg-coral/[0.04] p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-coral">Fix these</p>
                  {(benchmark.needs_fix_services ?? []).length === 0 ? (
                    <p className="mt-2 text-[12px] text-ink/45">No recurring service complaints detected. Keep monitoring.</p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {(benchmark.needs_fix_services ?? []).map((s) => (
                        <li key={s.name} className="flex items-start justify-between gap-2 text-[12px]">
                          <span className="font-semibold text-ink">{s.name}</span>
                          <span className="shrink-0 text-[11px] text-coral">{s.negative} negative · {s.mentions}×</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              {(benchmark.top_topics ?? []).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(benchmark.top_topics ?? []).slice(0, 6).map((t: { name: string; mentions: number }) => (
                    <span key={t.name} className="rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-medium text-ink/60">
                      #{t.name} · {t.mentions}
                    </span>
                  ))}
                </div>
              )}
              <Link href="/dashboard/services" className="mt-3 inline-block text-[11px] font-semibold text-deep-violet hover:underline">Manage services →</Link>
            </section>
          )}

          {/* External estimate — honestly labeled secondary reference */}
          <section aria-label="Industry estimate" className="rounded-2xl border border-dashed border-ink/15 bg-white/40 p-4 backdrop-blur-sm">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink/40">
              Industry estimate · approximated from similar profiles, not live competitor data
            </p>
            <p className="mt-1 text-[12px] text-ink/60">
              Similar businesses average <strong>{benchmark?.similar_avg_rating?.toFixed(1) ?? "—"}★</strong>
              {" "}across <strong>{benchmark?.similar_reviews_total ?? 0}</strong> reviews
              {typeof benchmark?.similar_response_rate === "number" && (
                <> · <strong>{benchmark.similar_response_rate.toFixed(0)}%</strong> reply rate</>
              )}
              . {benchmark?.benchmark_text}
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
