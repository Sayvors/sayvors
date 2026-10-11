"use client";

import { useMemo, useState } from "react";
import type { TimeseriesPoint } from "@/lib/api-analytics";

/* ── Metric switcher + area chart ─────────────────────────────────── */

type MetricKey = "reviews" | "sentiment" | "google";

type MetricChartLabels = {
  activityOverTime: string;
  metric: string;
  reviews: string;
  sentiment: string;
  google: string;
  mapsImpressions: string;
  positive: string;
  neutral: string;
  negative: string;
  noActivity: string;
  chartLabel: string;
};

const DEFAULT_METRIC_CHART_LABELS: MetricChartLabels = {
  activityOverTime: "Activity over time",
  metric: "Chart metric",
  reviews: "Reviews",
  sentiment: "Sentiment",
  google: "Google",
  mapsImpressions: "Maps impressions",
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
  noActivity: "No activity in this period yet",
  chartLabel: "{metric} chart",
};

const METRICS: { key: MetricKey }[] = [
  { key: "reviews" },
  { key: "sentiment" },
  { key: "google" },
];

function fmtDay(iso: string, locale: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(locale, { month: "short", day: "numeric" });
}

function fmtNum(n: number, locale: string) {
  return new Intl.NumberFormat(locale, { notation: n >= 10000 ? "compact" : "standard" }).format(n);
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

export function MetricChart({ points, labels, locale = "en" }: { points: TimeseriesPoint[]; labels?: MetricChartLabels; locale?: string }) {
  const [metric, setMetric] = useState<MetricKey>("reviews");
  const [hover, setHover] = useState<number | null>(null);
  const chartLabels = labels ?? DEFAULT_METRIC_CHART_LABELS;
  const metricLabels: Record<MetricKey, string> = {
    reviews: chartLabels.reviews,
    sentiment: chartLabels.sentiment,
    google: chartLabels.google,
  };

  // Monochrome ink ramp (needs the .team-ui ancestor for the --ui-* vars):
  // primary series = ink, secondary = ink-2, tertiary = line-strong. The
  // colour strings live in style props, never SVG presentation attributes,
  // because var() does not resolve there.
  const series = useMemo(() => {
    if (metric === "reviews") {
      return [{ key: "reviews_count", label: chartLabels.reviews, color: "var(--ui-ink)", values: points.map((p) => p.reviews_count) }];
    }
    if (metric === "google") {
      return [{ key: "impressions", label: chartLabels.mapsImpressions, color: "var(--ui-ink)", values: points.map((p) => p.impressions_maps) }];
    }
    return [
      { key: "pos", label: chartLabels.positive, color: "var(--ui-ink)", values: points.map((p) => p.positive_count) },
      { key: "neu", label: chartLabels.neutral, color: "var(--ui-ink-2)", values: points.map((p) => p.neutral_count) },
      { key: "neg", label: chartLabels.negative, color: "var(--ui-line-strong)", values: points.map((p) => p.negative_count) },
    ];
  }, [chartLabels, metric, points]);

  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const W = 600;
  const H = 170;
  const PAD = 10;
  const hasData = points.length > 0;

  const hoverInfo =
    hover !== null && points[hover]
      ? {
          date: fmtDay(points[hover].date, locale),
          rows: series.map((s) => ({ label: s.label, color: s.color, value: s.values[hover] ?? 0 })),
        }
      : null;

  return (
    <div className="ui-card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{chartLabels.activityOverTime}</h3>
        <div className="flex rounded-[2px] bg-[var(--ui-sunken)] p-0.5" role="group" aria-label={chartLabels.metric}>
          {METRICS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetric(m.key)}
              aria-pressed={metric === m.key}
              className={`rounded-[2px] px-2.5 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                metric === m.key ? "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
              }`}
            >
              {metricLabels[m.key]}
            </button>
          ))}
        </div>
      </div>

      {!hasData ? (
        <div className="flex h-40 items-center justify-center text-[12px] text-[var(--ui-ink-2)]">
          {chartLabels.noActivity}
        </div>
      ) : (
        <div className="relative">
          {/* legend */}
          <div className="mb-2 flex flex-wrap gap-3">
            {series.map((s) => (
              <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-[var(--ui-ink-2)]">
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
              aria-label={chartLabels.chartLabel.replace("{metric}", metricLabels[metric])}
              onMouseMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const frac = (e.clientX - rect.left) / rect.width;
                setHover(Math.min(points.length - 1, Math.max(0, Math.round(frac * (points.length - 1)))));
              }}
            >
              {[0.25, 0.5, 0.75].map((f) => (
                <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} className="stroke-[var(--ui-line)]" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              ))}
              {[...series].reverse().map((s) => {
                const { line, area } = buildPath(s.values, max, W, H, PAD);
                return (
                  <g key={s.key}>
                    <path d={area} style={{ fill: s.color }} fillOpacity="0.06" />
                    <path d={line} fill="none" style={{ stroke: s.color }} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  </g>
                );
              })}
              {hover !== null && points.length > 1 && (
                <line
                  x1={(hover / (points.length - 1)) * W}
                  x2={(hover / (points.length - 1)) * W}
                  y1="0"
                  y2={H}
                  className="stroke-[var(--ui-line-strong)]"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>

            {/* max label */}
            <span className="pointer-events-none absolute right-1 top-0 text-[9px] font-medium text-[var(--ui-ink-2)]">{fmtNum(max, locale)}</span>

            {/* tooltip */}
            {hoverInfo && (
              <div
                className="pointer-events-none absolute top-1 z-10 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1.5"
                style={{
                  left: `min(max(${(hover! / Math.max(1, points.length - 1)) * 100}%, 60px), calc(100% - 60px))`,
                  transform: "translateX(-50%)",
                }}
              >
                <p className="text-[10px] font-semibold text-[var(--ui-ink)]">{hoverInfo.date}</p>
                {hoverInfo.rows.map((r) => (
                  <p key={r.label} className="flex items-center gap-1.5 text-[10px] text-[var(--ui-ink-2)]">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: r.color }} aria-hidden />
                    {r.label}: <span className="font-semibold text-[var(--ui-ink)]">{fmtNum(r.value, locale)}</span>
                  </p>
                ))}
              </div>
            )}
          </div>

          {/* x labels */}
          <div className="mt-1 flex justify-between text-[9px] text-[var(--ui-ink-2)]">
            <span>{fmtDay(points[0].date, locale)}</span>
            {points.length > 2 && <span>{fmtDay(points[Math.floor(points.length / 2)].date, locale)}</span>}
            <span>{fmtDay(points[points.length - 1].date, locale)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sparkline (dashboard cards) ──────────────────────────────────── */

export function Sparkline({
  values,
  color = "var(--ui-ink)",
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
      <polyline points={pts} fill="none" style={{ stroke: color }} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={width} cy={height - 2 - (Math.max(0, values[values.length - 1]) / max) * (height - 4)} r="2.5" style={{ fill: color }} />
    </svg>
  );
}

/* ── Rating distribution ──────────────────────────────────────────── */

// No hue: more stars = heavier ink, so the ramp reads by weight alone.
const STAR_COLORS: Record<number, string> = {
  5: "var(--ui-ink)",
  4: "var(--ui-ink)",
  3: "var(--ui-ink-2)",
  2: "var(--ui-line-strong)",
  1: "var(--ui-line-strong)",
};

export function RatingDistribution({ distribution, total, labels = { ariaLabel: "Rating distribution", reviewsTooltip: "{count} reviews ({percent}%)" } }: { distribution: Record<string, number>; total: number; labels?: { ariaLabel: string; reviewsTooltip: string } }) {
  const max = Math.max(1, ...Object.values(distribution));
  return (
    <div className="space-y-3" aria-label={labels.ariaLabel}>
      {[5, 4, 3, 2, 1].map((star) => {
        const count = distribution[String(star)] ?? 0;
        const pct = total ? Math.round((count / total) * 100) : 0;
        return (
          <div key={star} className="flex items-center gap-3">
            <span className="flex w-8 shrink-0 items-center justify-end gap-1 text-[12px] font-bold tabular-nums text-[var(--ui-ink)]">
              {star}
              <svg viewBox="0 0 24 24" fill="currentColor" className="h-3 w-3 text-[var(--ui-ink-2)]" aria-hidden>
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
              </svg>
            </span>
            {/* Bar length scales to the biggest star so the graph fills the card */}
            <div className="h-4 flex-1 overflow-hidden rounded-[2px] bg-[var(--ui-sunken)]">
              <div
                className="h-full rounded-[2px] transition-all duration-500"
                style={{ width: `${(count / max) * 100}%`, background: STAR_COLORS[star] }}
              />
            </div>
            <span className="w-14 shrink-0 text-right text-[11px] font-semibold tabular-nums text-[var(--ui-ink)]" title={labels.reviewsTooltip.replace("{count}", String(count)).replace("{percent}", String(pct))}>
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
    { label: "Positive", value: positive, color: "var(--ui-ink)", pct: seg(positive) },
    { label: "Neutral", value: neutral, color: "var(--ui-ink-2)", pct: seg(neutral) },
    { label: "Negative", value: negative, color: "var(--ui-line-strong)", pct: seg(negative) },
  ];
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-[var(--ui-sunken)]" role="img" aria-label="Sentiment split">
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
            <p className="flex items-center justify-center gap-1.5 text-[11px] font-semibold text-[var(--ui-ink)]">
              <span className="h-2 w-2 rounded-full" style={{ background: r.color }} aria-hidden />
              {r.label}
            </p>
            <p className="text-[16px] font-bold text-[var(--ui-ink)]">{total ? Math.round(r.pct) : 0}%</p>
            <p className="text-[10px] text-[var(--ui-ink-2)]">{r.value} reviews</p>
          </div>
        ))}
      </div>
    </div>
  );
}
