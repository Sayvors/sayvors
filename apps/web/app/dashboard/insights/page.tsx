"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  fetchProblems,
  fetchProducts,
  fetchTopics,
  type ProblemsResponse,
  type ProductsResponse,
  type TopicsResponse,
} from "@/lib/api-analytics";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";

function TrendChip({ trend }: { trend: number | null }) {
  if (trend === null) return <span className="text-[10px] font-medium text-ink/30">new</span>;
  const up = trend > 0;
  const flat = trend === 0;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${
        flat ? "text-ink/40" : up ? "text-coral" : "text-emerald"
      }`}
    >
      {!flat && (
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2.5 w-2.5 ${up ? "" : "rotate-180"}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {Math.abs(trend)}%
    </span>
  );
}

const SEVERITY_BADGE: Record<string, string> = {
  high: "bg-coral/10 text-coral",
  medium: "bg-amber/10 text-amber-600",
  low: "bg-ink/[0.05] text-ink/50",
};

const STATUS_LABEL: Record<string, string> = {
  emerging: "Emerging",
  increasing: "Increasing",
  decreasing: "Decreasing",
  recurring: "Recurring",
};

function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded-lg bg-ink/[0.06]" style={{ width: `${95 - i * 8}%` }} />
      ))}
    </div>
  );
}

function HeroStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="min-w-0 flex-1 rounded-xl bg-white/70 px-3.5 py-2.5 backdrop-blur-sm">
      <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">{label}</p>
      <p className="mt-0.5 truncate text-[15px] font-bold capitalize text-ink" title={value}>{value}</p>
      <p className="truncate text-[10px] text-ink/40">{sub}</p>
    </div>
  );
}

function MomentumBars({ items, days }: { items: { name: string; trend: number | null }[]; days: number }) {
  const movers = items
    .filter((t) => t.trend !== null && t.trend !== 0)
    .sort((a, b) => Math.abs(b.trend as number) - Math.abs(a.trend as number))
    .slice(0, 6);
  if (movers.length === 0) return null;
  const max = Math.max(...movers.map((m) => Math.abs(m.trend as number)), 1);
  return (
    <section aria-label="Momentum" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
      <h3 className="text-[14px] font-bold text-ink">Momentum</h3>
      <p className="text-[11px] text-ink/45">Biggest movers vs the previous {days} days — right is growing, left is fading.</p>
      <ul className="mt-3 space-y-2">
        {movers.map((m) => {
          const v = m.trend as number;
          const up = v > 0;
          return (
            <li key={m.name} className="flex items-center gap-2">
              <span className="w-28 shrink-0 truncate text-right text-[11px] font-semibold capitalize text-ink/70">{m.name}</span>
              <span className="relative h-4 flex-1 overflow-hidden rounded-full bg-ink/[0.05]">
                <span className="absolute left-1/2 top-0 h-full w-px bg-ink/20" aria-hidden />
                <span
                  className={`absolute top-1 h-2 rounded-full ${up ? "bg-emerald" : "bg-coral"}`}
                  style={up
                    ? { left: "50%", width: `${Math.max(2, (v / max) * 48)}%` }
                    : { right: "50%", width: `${Math.max(2, (Math.abs(v) / max) * 48)}%` }}
                />
              </span>
              <span className={`w-12 shrink-0 text-[11px] font-bold tabular-nums ${up ? "text-emerald" : "text-coral"}`}>
                {up ? "+" : ""}{v}%
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default function InsightsPage() {
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const channels = useGoogleChannels();
  const [topics, setTopics] = useState<TopicsResponse | null>(null);
  const [problems, setProblems] = useState<ProblemsResponse | null>(null);
  const [products, setProducts] = useState<ProductsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const hasLoaded = useRef(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchTopics(days, channelId), fetchProblems(days, channelId), fetchProducts(days, channelId)])
      .then(([t, p, pr]) => {
        if (cancelled) return;
        setTopics(t);
        setProblems(p);
        setProducts(pr);
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
  }, [days, channelId, refreshToken]);

  const hasData = !!topics && topics.topics.length > 0;

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff] p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Insights</h1>
          <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
            What customers talk about — topics, problems and products, ranked by AI.
          </p>
        </div>
        <RangeChannelControls
          days={days}
          setDays={(d) => {
            setDays(d);
            setLoading(true);
          }}
          channelId={channelId}
          setChannelId={(c) => {
            setChannelId(c);
            setLoading(true);
          }}
          channels={channels}
        />
      </div>

      {error && !loading ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[13px] font-semibold text-ink/60">Couldn&apos;t load insights.</p>
          <button
            onClick={() => {
              setError(false);
              setLoading(true);
              setRefreshToken((t) => t + 1);
            }}
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            Retry
          </button>
        </div>
      ) : !hasData && !loading ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[14px] font-bold text-ink">No topic data yet</p>
          <p className="max-w-sm text-[12px] text-ink/50">
            Once reviews flow through the AI pipeline, topics, problems and products appear here automatically.
          </p>
        </div>
      ) : (
        <>
          {/* At-a-glance: best, worst, fastest-moving */}
          {(() => {
            const emergingTopics = (topics?.topics ?? []).filter((t) => t.emerging).length;
            const topProblem = [...(problems?.problems ?? [])].sort((a, b) => b.impact_score - a.impact_score)[0];
            return (
              <div className="mb-3 flex flex-col gap-2 rounded-2xl border-2 border-white bg-white/80 p-3 backdrop-blur-sm sm:flex-row">
                <HeroStat
                  label="Most loved"
                  value={products?.most_loved ?? "—"}
                  sub="highest praise among products"
                />
                <HeroStat
                  label="Fix first"
                  value={topProblem?.name ?? (problems && problems.problems.length === 0 ? "Nothing — all clear" : "—")}
                  sub={topProblem ? `impact ${topProblem.impact_score} · ${topProblem.mentions} mentions` : "no problems detected"}
                />
                <HeroStat
                  label="Fastest growing"
                  value={products?.fastest_growing ?? "—"}
                  sub="rising mention volume"
                />
                <HeroStat
                  label="Emerging topics"
                  value={loading ? "…" : String(emergingTopics)}
                  sub="new this period"
                />
              </div>
            );
          })()}
          {(() => {
            const topProblem = [...(problems?.problems ?? [])].sort((a, b) => b.impact_score - a.impact_score)[0];
            if (loading || !topProblem) return null;
            return (
              <div className="mb-3 flex flex-wrap items-center gap-3 rounded-2xl border-2 border-coral/20 bg-coral/[0.04] p-4 backdrop-blur-sm">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${SEVERITY_BADGE[topProblem.severity]}`}>
                  {topProblem.severity}
                </span>
                <p className="min-w-0 flex-1 text-[12.5px] text-ink">
                  <strong className="capitalize">{topProblem.name}</strong>
                  <span className="text-ink/55"> — {topProblem.mentions} mentions · {STATUS_LABEL[topProblem.status] ?? topProblem.status} · </span>
                  <TrendChip trend={topProblem.trend_pct} />
                </p>
                <Link href="/dashboard/reviews" className="shrink-0 rounded-lg bg-coral px-3 py-1.5 text-[11px] font-bold text-white transition hover:bg-coral/90">
                  Read the reviews →
                </Link>
              </div>
            );
          })()}
          <div className="grid gap-3 lg:grid-cols-3">
          {/* Topics */}
          <section aria-label="Topics" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
            <h3 className="mb-4 text-[14px] font-bold text-ink">Topics</h3>
            {loading || !topics ? (
              <SkeletonList />
            ) : topics.topics.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-ink/35">No topics detected yet</p>
            ) : (
              <ul className="space-y-3">
                {topics.topics.slice(0, 8).map((t) => {
                  const total = Math.max(1, t.positive + t.neutral + t.negative);
                  return (
                    <li key={t.name} className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-1.5 truncate text-[12px] font-semibold capitalize text-ink/80">
                          {t.name}
                          {t.emerging && (
                            <span className="rounded bg-sky/10 px-1 py-px text-[9px] font-bold uppercase text-sky">new</span>
                          )}
                        </p>
                        <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-ink/[0.05]" role="img" aria-label={`${t.positive} positive, ${t.neutral} neutral, ${t.negative} negative`}>
                          <div className="h-full bg-emerald" style={{ width: `${(t.positive / total) * 100}%` }} />
                          <div className="h-full bg-amber-400" style={{ width: `${(t.neutral / total) * 100}%` }} />
                          <div className="h-full bg-coral" style={{ width: `${(t.negative / total) * 100}%` }} />
                        </div>
                      </div>
                      <span className="text-[11px] tabular-nums text-ink/40">{t.mentions}</span>
                      <TrendChip trend={t.trend_pct} />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Problems */}
          <section aria-label="Problems" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
            <h3 className="mb-4 text-[14px] font-bold text-ink">Problems</h3>
            {loading || !problems ? (
              <SkeletonList />
            ) : problems.problems.length === 0 ? (
              <div className="py-6 text-center">
                <p className="text-[12px] font-semibold text-emerald">No problems detected</p>
                <p className="mt-1 text-[11px] text-ink/35">That&apos;s a good sign — keep it up.</p>
              </div>
            ) : (
              <ul className="space-y-3">
                {problems.problems.slice(0, 8).map((p) => (
                  <li key={p.name} className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-1.5 truncate text-[12px] font-semibold capitalize text-ink/80">
                        {p.name}
                        <span className={`rounded px-1 py-px text-[9px] font-bold uppercase ${SEVERITY_BADGE[p.severity]}`}>
                          {p.severity}
                        </span>
                      </p>
                      <p className="text-[10px] text-ink/35">
                        {STATUS_LABEL[p.status] ?? p.status} · impact {p.impact_score}
                      </p>
                    </div>
                    <span className="text-[11px] tabular-nums text-ink/40">{p.mentions}</span>
                    <TrendChip trend={p.trend_pct} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Products */}
          <section aria-label="Products" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
            <h3 className="mb-4 text-[14px] font-bold text-ink">Products &amp; services</h3>
            {loading || !products ? (
              <SkeletonList />
            ) : products.products.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-ink/35">No products detected yet</p>
            ) : (
              <ul className="space-y-3">
                {products.products.slice(0, 8).map((p) => {
                  const loved = p.name === products.most_loved;
                  const criticized = p.name === products.most_criticized;
                  const growing = p.name === products.fastest_growing;
                  return (
                    <li key={p.name} className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-center gap-1.5 text-[12px] font-semibold capitalize text-ink/80">
                          {p.name}
                          {loved && <span className="rounded bg-emerald/10 px-1 py-px text-[9px] font-bold uppercase text-emerald">loved</span>}
                          {criticized && <span className="rounded bg-coral/10 px-1 py-px text-[9px] font-bold uppercase text-coral">criticized</span>}
                          {growing && <span className="rounded bg-sky/10 px-1 py-px text-[9px] font-bold uppercase text-sky">rising</span>}
                          {p.emerging && <span className="rounded bg-sky/10 px-1 py-px text-[9px] font-bold uppercase text-sky">new</span>}
                        </p>
                        <p className="text-[10px] text-ink/35">
                          {p.positive_pct}% positive · {p.mentions} mentions
                          {p.avg_rating !== null && ` · ${p.avg_rating} avg`}
                        </p>
                      </div>
                      <TrendChip trend={p.trend_pct} />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
        {!loading && (topics || products) && (
          <div className="mt-3">
            <MomentumBars
              days={days}
              items={[
                ...(topics?.topics ?? []).map((t) => ({ name: t.name, trend: t.trend_pct })),
                ...(products?.products ?? []).map((p) => ({ name: p.name, trend: p.trend_pct })),
              ]}
            />
          </div>
        )}
        </>
      )}
    </div>
  );
}
