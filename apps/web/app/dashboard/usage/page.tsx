"use client";

import { useCallback, useEffect, useState } from "react";
import { formatMs, formatTokens, getUsageSummary, type UsageSummary } from "@/lib/api-usage";

const DAY_OPTIONS = [7, 30, 90];

function AreaChart({ points }: { points: { x: string; y: number }[] }) {
  const W = 560;
  const H = 140;
  const PAD = 28;
  const max = Math.max(1, ...points.map((p) => p.y));
  const n = Math.max(1, points.length - 1);
  const px = (i: number) => PAD + (i / n) * (W - PAD * 2);
  const py = (v: number) => H - PAD - (v / max) * (H - PAD * 2);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
  const area = `${line} L${px(points.length - 1).toFixed(1)},${(H - PAD).toFixed(1)} L${PAD},${(H - PAD).toFixed(1)} Z`;
  const ticks = [0, 0.5, 1].map((f) => Math.round(max * f));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD} x2={W - PAD} y1={py(t)} y2={py(t)} stroke="currentColor" strokeOpacity={0.08} />
          <text x={PAD - 5} y={py(t) + 3.5} textAnchor="end" fontSize={9} fill="currentColor" opacity={0.45}>
            {t >= 1000 ? `${(t / 1000).toFixed(1)}K` : t}
          </text>
        </g>
      ))}
      <path d={area} fill="#5b2d8e" opacity={0.12} />
      <path d={line} fill="none" stroke="#5b2d8e" strokeWidth={2} strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={px(i)} cy={py(p.y)} r={i === points.length - 1 ? 3 : 1.6} fill="#5b2d8e">
          <title>{`${p.x}: ${p.y.toLocaleString()} tokens`}</title>
        </circle>
      ))}
      <text x={PAD} y={H - 8} fontSize={9} fill="currentColor" opacity={0.45}>
        {points[0]?.x ?? ""}
      </text>
      <text x={W - PAD} y={H - 8} textAnchor="end" fontSize={9} fill="currentColor" opacity={0.45}>
        {points[points.length - 1]?.x ?? ""}
      </text>
    </svg>
  );
}

function SplitDonut({ a, b, labelA, labelB }: { a: number; b: number; labelA: string; labelB: string }) {
  const total = Math.max(1, a + b);
  const R = 44;
  const C = 2 * Math.PI * R;
  const fracA = a / total;
  return (
    <div className="flex items-center gap-4">
      <svg width={110} height={110} viewBox="0 0 110 110">
        <circle cx={55} cy={55} r={R} fill="none" strokeWidth={14} stroke="rgba(0,0,0,0.06)" />
        <circle
          cx={55} cy={55} r={R} fill="none" stroke="#5b2d8e" strokeWidth={14}
          strokeDasharray={`${(fracA * C).toFixed(1)} ${C.toFixed(1)}`}
          transform="rotate(-90 55 55)" strokeLinecap="round"
        />
        <text x={55} y={52} textAnchor="middle" fontSize={14} fontWeight={800} fill="currentColor">
          {total >= 1000 ? `${(total / 1000).toFixed(1)}K` : total}
        </text>
        <text x={55} y={66} textAnchor="middle" fontSize={9} fill="currentColor" opacity={0.5}>
          tokens
        </text>
      </svg>
      <div className="space-y-1.5 text-[12px]">
        {[
          { label: labelA, value: a, color: "bg-deep-violet" },
          { label: labelB, value: b, color: "bg-magenta" },
        ].map((r) => (
          <div key={r.label} className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${r.color}`} />
            <span className="text-ink/60">{r.label}</span>
            <span className="font-bold tabular-nums text-ink">{((r.value / total) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function UsagePage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getUsageSummary(d));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load usage");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const maxPurpose = Math.max(1, ...((data?.by_purpose ?? []).map((p) => p.total_tokens)));
  // Defensive defaults: older backends may omit keys.
  const totals = data?.totals ?? { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, avg_latency_ms: 0 };
  const byPurpose = data?.by_purpose ?? [];
  const daily = data?.daily ?? [];

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="space-y-5 p-4 sm:p-6">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Token Usage</h1>
            <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
              Every AI call metered by task — tokens in/out, latency, and daily trend.
            </p>
          </div>
          <div className="flex gap-1.5">
            {DAY_OPTIONS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={[
                  "rounded-lg px-3 py-1.5 text-[12px] font-semibold transition",
                  days === d ? "bg-deep-violet text-white" : "bg-white text-ink/60 hover:bg-ink/[0.04]",
                ].join(" ")}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-2xl border-2 border-white bg-white/60" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
            <p className="text-[13px] font-medium text-ink/60">{error}</p>
            <button
              type="button"
              onClick={() => void load(days)}
              className="mt-3 rounded-xl bg-deep-violet px-5 py-2 text-[12px] font-bold text-white"
            >
              Retry
            </button>
          </div>
        ) : data ? (
          <>
            {/* Totals */}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "Total tokens", value: formatTokens(totals.total_tokens) },
                { label: "LLM calls", value: String(totals.calls) },
                { label: "Prompt / completion", value: `${formatTokens(totals.prompt_tokens)} / ${formatTokens(totals.completion_tokens)}` },
                { label: "Avg latency", value: formatMs(totals.avg_latency_ms) },
              ].map((c) => (
                <div key={c.label} className="rounded-2xl border-2 border-white bg-white/80 p-4">
                  <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">{c.label}</div>
                  <div className="mt-2 text-[22px] font-bold tabular-nums text-ink">{c.value}</div>
                </div>
              ))}
            </div>

            {/* Daily + purpose breakdown */}
            <div className="grid gap-3 lg:grid-cols-2">
              {/* Daily trend */}
              <div className="rounded-2xl border-2 border-white bg-white/80 p-4 text-ink">
                <h2 className="text-[16px] font-bold text-ink">Daily trend</h2>
                <p className="text-[12px] text-ink/50">Tokens per day.</p>
                {daily.length === 0 ? (
                  <p className="mt-3 text-[12px] text-ink/40">No data.</p>
                ) : (
                  <AreaChart points={daily.map((d) => ({ x: d.day.slice(5), y: d.total_tokens }))} />
                )}
              </div>

              {/* Prompt vs completion */}
              <div className="rounded-2xl border-2 border-white bg-white/80 p-4 text-ink">
                <h2 className="text-[16px] font-bold text-ink">Prompt vs completion</h2>
                <p className="text-[12px] text-ink/50">Where your tokens go.</p>
                <div className="mt-3">
                  <SplitDonut
                    a={totals.prompt_tokens}
                    b={totals.completion_tokens}
                    labelA="Prompt"
                    labelB="Completion"
                  />
                </div>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              {/* By purpose */}
              <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
                <h2 className="text-[16px] font-bold text-ink">By feature</h2>
                <p className="text-[12px] text-ink/50">Which engine parts consume tokens.</p>
                {byPurpose.length === 0 ? (
                  <p className="mt-3 text-[12px] text-ink/40">No data.</p>
                ) : (
                  <div className="mt-3 space-y-2">
                    {byPurpose.map((p, i) => (
                      <div key={p.purpose} className="flex items-center gap-2 text-[12px]">
                        <span className="w-40 truncate font-medium text-ink/70">{p.purpose}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink/[0.06]">
                          <div
                            className={["h-full rounded-full", i % 3 === 0 ? "bg-deep-violet" : i % 3 === 1 ? "bg-magenta" : "bg-sky-500"].join(" ")}
                            style={{ width: `${Math.max(2, (p.total_tokens / maxPurpose) * 100)}%` }}
                          />
                        </div>
                        <span className="w-16 text-right tabular-nums text-ink/55">{formatTokens(p.total_tokens)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
