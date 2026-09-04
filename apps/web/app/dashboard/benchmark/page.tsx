"use client";

import { useEffect, useRef, useState } from "react";
import { fetchBenchmark, type BenchmarkResponse } from "@/lib/api-analytics";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";

export default function BenchmarkPage() {
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
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

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff] p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Benchmark</h1>
          <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">Compare your business against comparable businesses.</p>
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
            Once enough comparable businesses are aggregated (Premium feature), competitive intelligence appears here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Comparison cards */}
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="rounded-2xl border-2 border-white bg-gradient-to-r from-deep-violet to-magenta p-5 text-white shadow-md shadow-deep-violet/20 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold tracking-wide">Your business</h3>
              <p className="mt-1 text-[22px] font-bold">⭐ {benchmark?.current_avg_rating ?? "--"}</p>
              <p className="mt-1 text-[11px] text-white/70">Avg rating · {benchmark?.current_reviews_total ?? 0} reviews</p>
            </div>
            <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold tracking-wide text-ink">Similar businesses</h3>
              <p className="mt-1 text-[22px] font-bold text-ink">⭐ {benchmark?.similar_avg_rating ?? "--"}</p>
              <p className="mt-1 text-[11px] text-ink/45">Avg · {benchmark?.similar_reviews_total ?? 0} reviews</p>
            </div>
            <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold tracking-wide text-ink">Performance</h3>
              <p className="mt-1 text-[22px] font-bold text-ink">Top {benchmark?.percentile_text ? benchmark.percentile_text.replace("You're in the top ", "").replace("% of comparable businesses", "%") : "--"}</p>
              <p className="mt-1 text-[11px] text-ink/45">Reputation benchmark</p>
            </div>
          </div>

          {/* Benchmark text */}
          {benchmark && (
            <section aria-label="Benchmark analysis" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm space-y-3">
              <h3 className="text-[14px] font-bold text-ink">Benchmark &amp; competitive outlook</h3>
              <p className="text-[12px] leading-relaxed text-ink/70">{benchmark.benchmark_text}</p>
              {benchmark.outperforms.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald">Where you lead</p>
                  <ul className="mt-1.5 space-y-0.5 text-[12px] text-ink/70">
                    {benchmark.outperforms.map((o) => (
                      <li key={o} className="flex items-start gap-1.5">
                        <span className="mt-0.5 h-1 w-1 shrink-0 rounded-full bg-emerald" aria-hidden />
                        {o}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {benchmark.underperforms.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-coral">Where to improve</p>
                  <ul className="mt-1.5 space-y-0.5 text-[12px] text-ink/70">
                    {benchmark.underperforms.map((o) => (
                      <li key={o} className="flex items-start gap-1.5">
                        <span className="mt-0.5 h-1 w-1 shrink-0 rounded-full bg-coral" aria-hidden />
                        {o}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="mt-2 border-t border-deep-violet/[0.06] pt-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-deep-violet">Opportunities</p>
                <ul className="mt-1.5 space-y-1 text-[12px] text-ink/60">
                  {benchmark.competitive_opportunities.map((o, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="mt-0.5 h-1 w-1 shrink-0 rounded-full bg-amber" aria-hidden />
                      {o}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-2 border-t border-deep-violet/[0.06] pt-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-deep-violet">Industry trends</p>
                <ul className="mt-1.5 space-y-1 text-[12px] text-ink/60">
                  {benchmark.industry_trends.map((t) => (
                    <li key={t} className="flex items-start gap-1.5">
                      <span className="mt-0.5 h-1 w-1 shrink-0 rounded-full bg-deep-violet/40" aria-hidden />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
