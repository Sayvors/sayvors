"use client";

import { useMemo, useState } from "react";
import type { TimeseriesPoint } from "@/lib/api-analytics";

/* ── Metric switcher + area chart ─────────────────────────────────── */

type MetricKey = "reviews" | "sentiment" | "google";

const METRICS: { key: MetricKey; label: string }[] = [
  { key: "reviews", label: "Reviews" },
  { key: "sentiment", label: "Sentiment" },
  { key: "google", label: "Google" },
];

function fmtDay(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en", { month: "short", day: "numeric" });
}

function fmtNum(n: number) {
  return new Intl.NumberFormat("en", { notation: n >= 10000 ? "compact" : "standard" }).format(n);
}

function buildPath(values: number[], max: number, w: number, h: number, pad: number) {
  const n = values.length;
  if (n === 0 || max <= 0) return { line: "", area: "" };
  const pts = values.map((v, i) => {
    const x = n === 1 ? w / 2 : (i / (n - 1)) * w;
    const y = h - pad - (Math.max(0, v) / max) * (h - pad * 2);
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${w} ${h} L0 ${h} Z`;
  return { line, area };
}

export function MetricChart({ points }: { points: TimeseriesPoint[] }) {
  const [metric, setMetric] = useState<MetricKey>("reviews");
  const [hover, setHover] = useState<number | null>(null);

  const series = useMemo(() => {
    if (metric === "reviews") {
      return [{ key: "reviews_count", label: "Reviews", color: "#5b2d8e", values: points.map((p) => p.reviews_count) }];
    }
    if (metric === "google") {
      return [{ key: "impressions", label: "Maps impressions", color: "#0ea5e9", values: points.map((p) => p.impressions_maps) }];
    }
    return [
      { key: "pos", label: "Positive", color: "#10b981", values: points.map((p) => p.positive_count) },
      { key: "neu", label: "Neutral", color: "#8b7fb8", values: points.map((p) => p.neutral_count) },
      { key: "neg", label: "Negative", color: "#ff4f6e", values: points.map((p) => p.negative_count) },
    ];
  }, [metric, points]);

  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const W = 600;
  const H = 170;
  const PAD = 10;
  const hasData = points.length > 0;

  const hoverInfo =
    hover !== null && points[hover]
      ? {
          date: fmtDay(points[hover].date),
          rows: series.map((s) => ({ label: s.label, color: s.color, value: s.values[hover] ?? 0 })),
        }
      : null;

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-ink">Activity over time</h3>
        <div className="flex rounded-lg bg-deep-violet/[0.06] p-0.5" role="group" aria-label="Chart metric">
          {METRICS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetric(m.key)}
              aria-pressed={metric === m.key}
              className={`rounded-md px-2.5 py-1 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                metric === m.key ? "bg-white text-deep-violet shadow-sm" : "text-ink/45 hover:text-ink/70"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {!hasData ? (
        <div className="flex h-40 items-center justify-center text-[12px] text-ink/35">
          No activity in this period yet
        </div>
      ) : (
        <div className="relative">
          {/* legend */}
          <div className="mb-2 flex flex-wrap gap-3">
            {series.map((s) => (
              <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-ink/50">
                <span className="h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden />
                {s.label}
              </span>
            ))}
          </div>

          <div className="relative" onMouseLeave={() => setHover(null)}>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              className="h-40 w-full"
              role="img"
              aria-label={`${METRICS.find((m) => m.key === metric)?.label} chart`}
              onMouseMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const frac = (e.clientX - rect.left) / rect.width;
                setHover(Math.min(points.length - 1, Math.max(0, Math.round(frac * (points.length - 1)))));
              }}
            >
              <defs>
                {series.map((s) => (
                  <linearGradient key={s.key} id={`grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={s.color} stopOpacity="0.28" />
                    <stop offset="100%" stopColor={s.color} stopOpacity="0.02" />
                  </linearGradient>
                ))}
              </defs>
              {[0.25, 0.5, 0.75].map((f) => (
                <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} stroke="#1a1230" strokeOpacity="0.05" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              ))}
              {[...series].reverse().map((s) => {
                const { line, area } = buildPath(s.values, max, W, H, PAD);
                return (
                  <g key={s.key}>
                    <path d={area} fill={`url(#grad-${s.key})`} />
                    <path d={line} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  </g>
                );
              })}
              {hover !== null && points.length > 1 && (
                <line
                  x1={(hover / (points.length - 1)) * W}
                  x2={(hover / (points.length - 1)) * W}
                  y1="0"
                  y2={H}
                  stroke="#5b2d8e"
                  strokeOpacity="0.35"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>

            {/* max label */}
            <span className="pointer-events-none absolute right-1 top-0 text-[9px] font-medium text-ink/30">{fmtNum(max)}</span>

            {/* tooltip */}
            {hoverInfo && (
              <div
                className="pointer-events-none absolute top-1 z-10 rounded-lg border border-deep-violet/[0.1] bg-white/95 px-2.5 py-1.5 shadow-lg backdrop-blur-sm"
                style={{
                  left: `min(max(${(hover! / Math.max(1, points.length - 1)) * 100}%, 60px), calc(100% - 60px))`,
                  transform: "translateX(-50%)",
                }}
              >
                <p className="text-[10px] font-semibold text-ink/70">{hoverInfo.date}</p>
                {hoverInfo.rows.map((r) => (
                  <p key={r.label} className="flex items-center gap-1.5 text-[10px] text-ink/55">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: r.color }} aria-hidden />
                    {r.label}: <span className="font-semibold text-ink">{fmtNum(r.value)}</span>
                  </p>
                ))}
              </div>
            )}
          </div>

          {/* x labels */}
          <div className="mt-1 flex justify-between text-[9px] text-ink/30">
            <span>{fmtDay(points[0].date)}</span>
            {points.length > 2 && <span>{fmtDay(points[Math.floor(points.length / 2)].date)}</span>}
            <span>{fmtDay(points[points.length - 1].date)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sparkline (dashboard cards) ──────────────────────────────────── */

export function Sparkline({
  values,
  color = "#5b2d8e",
  width = 96,
  height = 28,
}: {
  values: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return null;
  const max = Math.max(1, ...values);
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - 2 - (Math.max(0, v) / max) * (height - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="shrink-0" width={width} height={height} aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={width} cy={height - 2 - (Math.max(0, values[values.length - 1]) / max) * (height - 4)} r="2.5" fill={color} />
    </svg>
  );
}

/* ── Rating distribution ──────────────────────────────────────────── */

const STAR_COLORS: Record<number, string> = {
  5: "#10b981",
  4: "#0ea5e9",
  3: "#f59e0b",
  2: "#ff8fa0",
  1: "#ff4f6e",
};

export function RatingDistribution({ distribution, total }: { distribution: Record<string, number>; total: number }) {
  const max = Math.max(1, ...Object.values(distribution));
  return (
    <div className="space-y-2" aria-label="Rating distribution">
      {[5, 4, 3, 2, 1].map((star) => {
        const count = distribution[String(star)] ?? 0;
        const pct = total ? Math.round((count / total) * 100) : 0;
        return (
          <div key={star} className="flex items-center gap-2">
            <span className="flex w-8 items-center gap-0.5 text-[11px] font-semibold text-ink/55">
              {star}
              <svg viewBox="0 0 24 24" fill="currentColor" className="h-2.5 w-2.5 text-amber" aria-hidden>
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
              </svg>
            </span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-ink/[0.05]">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${(count / max) * 100}%`, background: STAR_COLORS[star] }}
              />
            </div>
            <span className="w-14 text-right text-[11px] tabular-nums text-ink/40" title={`${count} reviews (${pct}%)`}>
              {count} · {pct}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ── Sentiment split bar ──────────────────────────────────────────── */

export function SentimentSplitBar({
  positive,
  neutral,
  negative,
}: {
  positive: number;
  neutral: number;
  negative: number;
}) {
  const total = positive + neutral + negative;
  const seg = (n: number) => (total ? (n / total) * 100 : 0);
  const rows = [
    { label: "Positive", value: positive, color: "#10b981", pct: seg(positive) },
    { label: "Neutral", value: neutral, color: "#8b7fb8", pct: seg(neutral) },
    { label: "Negative", value: negative, color: "#ff4f6e", pct: seg(negative) },
  ];
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-ink/[0.05]" role="img" aria-label="Sentiment split">
        {rows.map((r) => (
          <div
            key={r.label}
            className="h-full transition-all duration-500"
            style={{ width: `${r.pct}%`, background: r.color }}
          />
        ))}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {rows.map((r) => (
          <div key={r.label} className="text-center">
            <p className="flex items-center justify-center gap-1.5 text-[11px] font-semibold text-ink/70">
              <span className="h-2 w-2 rounded-full" style={{ background: r.color }} aria-hidden />
              {r.label}
            </p>
            <p className="text-[16px] font-bold text-ink">{total ? Math.round(r.pct) : 0}%</p>
            <p className="text-[10px] text-ink/40">{r.value} reviews</p>
          </div>
        ))}
      </div>
    </div>
  );
}
