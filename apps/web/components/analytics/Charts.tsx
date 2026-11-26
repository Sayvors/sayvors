"use client";

import { useMemo, useState } from "react";
import type { TimeseriesPoint } from "@/lib/api-analytics";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { FactSource } from "@/components/analytics/FactSource";
import { CHART_COLORS, DonutChart } from "@/components/analytics/ReputationCharts";

/* ── Metric switcher + area chart ─────────────────────────────────── */

type MetricKey = "reviews" | "sentiment";

type MetricChartLabels = {
  activityOverTime: string;
  metric: string;
  reviews: string;
  sentiment: string;
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
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
  noActivity: "No activity in this period yet",
  chartLabel: "{metric} chart",
};

const METRICS: { key: MetricKey }[] = [
  { key: "reviews" },
  { key: "sentiment" },
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

export function MetricChart({
  points,
  labels,
  locale = "en",
  source,
  sourceDetail,
  sourceHref,
  sourceLinkLabel,
}: {
  points: TimeseriesPoint[];
  labels?: MetricChartLabels;
  locale?: string;
  source?: string;
  sourceDetail?: string;
  sourceHref?: string;
  sourceLinkLabel?: string;
}) {
  const { t } = useI18n();
  const c = t.analytics.charts;
  const [metric, setMetric] = useState<MetricKey>("reviews");
  const [hover, setHover] = useState<number | null>(null);
  const chartLabels = labels ?? {
    activityOverTime: c.activityOverTime,
    metric: c.metric,
    reviews: c.reviews,
    sentiment: c.sentiment,
    positive: c.positive,
    neutral: c.neutral,
    negative: c.negative,
    noActivity: c.noActivity,
    chartLabel: c.chartLabel,
  };
  const metricLabels: Record<MetricKey, string> = {
    reviews: chartLabels.reviews,
    sentiment: chartLabels.sentiment,
  };

  const seriesPoints = useMemo(() => {
    const byDate = new Map<string, TimeseriesPoint>();
    for (const point of points) {
      const existing = byDate.get(point.date);
      if (!existing) {
        byDate.set(point.date, { ...point });
        continue;
      }
      existing.reviews_count += point.reviews_count;
      existing.positive_count += point.positive_count;
      existing.neutral_count += point.neutral_count;
      existing.negative_count += point.negative_count;
      existing.impressions_maps += point.impressions_maps;
      existing.replies_count += point.replies_count;
      existing.website_clicks += point.website_clicks;
      existing.call_clicks += point.call_clicks;
      existing.direction_requests += point.direction_requests;
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [points]);

  // Chart-series palette: color is data ink, never a surface treatment.
  const series = useMemo(() => {
    if (metric === "reviews") {
      return [{ key: "reviews_count", label: chartLabels.reviews, color: CHART_COLORS.violet, values: seriesPoints.map((p) => p.reviews_count) }];
    }
    return [
      { key: "pos", label: chartLabels.positive, color: CHART_COLORS.green, values: seriesPoints.map((p) => p.positive_count) },
      { key: "neu", label: chartLabels.neutral, color: CHART_COLORS.amber, values: seriesPoints.map((p) => p.neutral_count) },
      { key: "neg", label: chartLabels.negative, color: CHART_COLORS.red, values: seriesPoints.map((p) => p.negative_count) },
    ];
  }, [chartLabels, metric, seriesPoints]);

  const max = metric === "sentiment"
    ? Math.max(1, ...seriesPoints.map((p) => p.positive_count + p.neutral_count + p.negative_count))
    : Math.max(1, ...series.flatMap((s) => s.values));
  const W = 600;
  const H = 170;
  const PAD = 10;
  const hasData = seriesPoints.length > 0;

  const hoverInfo =
    hover !== null && seriesPoints[hover]
      ? {
          date: fmtDay(seriesPoints[hover].date, locale),
          rows: series.map((s) => ({ label: s.label, color: s.color, value: s.values[hover] ?? 0 })),
        }
      : null;

  return (
    <div className="ui-card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{chartLabels.activityOverTime}</h3>
        <div className="flex rounded-[8px] bg-[var(--ui-sunken)] p-0.5" role="group" aria-label={chartLabels.metric}>
          {METRICS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetric(m.key)}
              aria-pressed={metric === m.key}
              className={`rounded-[8px] px-2.5 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
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
                setHover(Math.min(seriesPoints.length - 1, Math.max(0, Math.round(frac * (seriesPoints.length - 1)))));
              }}
            >
              {[0.25, 0.5, 0.75].map((f) => (
                <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} className="stroke-[var(--ui-line)]" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              ))}
              {metric === "reviews" ? (
                seriesPoints.map((point, index) => {
                  const slot = W / Math.max(1, seriesPoints.length);
                  const barWidth = Math.min(30, slot * 0.62);
                  const x = index * slot + (slot - barWidth) / 2;
                  const height = (Math.max(0, point.reviews_count) / max) * (H - PAD * 2);
                  const latest = index === seriesPoints.length - 1;
                  return (
                    <rect
                      key={`${point.date}-${index}`}
                      data-metric-bar
                      x={x}
                      y={H - PAD - height}
                      width={barWidth}
                      height={Math.max(2, height)}
                      rx="3"
                      fill={latest ? CHART_COLORS.coral : CHART_COLORS.violet}
                      opacity={latest ? 1 : 0.78}
                    >
                      <title>{`${fmtDay(point.date, locale)}: ${point.reviews_count}`}</title>
                    </rect>
                  );
                })
              ) : (
                seriesPoints.map((point, index) => {
                  const slot = W / Math.max(1, seriesPoints.length);
                  const barWidth = Math.min(30, slot * 0.62);
                  const x = index * slot + (slot - barWidth) / 2;
                  let yBase = H - PAD;
                  const stack = [
                    { key: "negative", value: point.negative_count, color: CHART_COLORS.red },
                    { key: "neutral", value: point.neutral_count, color: CHART_COLORS.amber },
                    { key: "positive", value: point.positive_count, color: CHART_COLORS.green },
                  ];
                  return (
                    <g key={`${point.date}-${index}`}>
                      {stack.map((segment) => {
                        const height = (Math.max(0, segment.value) / max) * (H - PAD * 2);
                        yBase -= height;
                        return (
                          <rect
                            key={segment.key}
                            data-stack={segment.key}
                            x={x}
                            y={yBase}
                            width={barWidth}
                            height={Math.max(0, height)}
                            fill={segment.color}
                          >
                            <title>{`${fmtDay(point.date, locale)} Â· ${segment.key}: ${segment.value}`}</title>
                          </rect>
                        );
                      })}
                    </g>
                  );
                })
              )}
              {hover !== null && seriesPoints.length > 1 && (
                <line
                  x1={(hover / (seriesPoints.length - 1)) * W}
                  x2={(hover / (seriesPoints.length - 1)) * W}
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
                className="pointer-events-none absolute top-1 z-10 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1.5"
                style={{
                  left: `min(max(${(hover! / Math.max(1, seriesPoints.length - 1)) * 100}%, 60px), calc(100% - 60px))`,
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
            <span>{fmtDay(seriesPoints[0].date, locale)}</span>
            {seriesPoints.length > 2 && <span>{fmtDay(seriesPoints[Math.floor(seriesPoints.length / 2)].date, locale)}</span>}
            <span>{fmtDay(seriesPoints[seriesPoints.length - 1].date, locale)}</span>
          </div>
        </div>
      )}
      {source && (
        <FactSource
          source={source}
          detail={sourceDetail}
          href={sourceHref}
          linkLabel={sourceLinkLabel}
        />
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

// Star colors are ordered from healthy to critical, not decorative hues.
const STAR_COLORS: Record<number, string> = {
  5: CHART_COLORS.green,
  4: CHART_COLORS.teal,
  3: CHART_COLORS.amber,
  2: CHART_COLORS.orange,
  1: CHART_COLORS.red,
};

export function RatingDistribution({
  distribution,
  total,
  averageRating = null,
  labels,
  source,
  sourceDetail,
  sourceHref,
  sourceLinkLabel,
}: {
  distribution: Record<string, number>;
  total: number;
  averageRating?: number | null;
  labels?: { ariaLabel: string; reviewsTooltip: string };
  source?: string;
  sourceDetail?: string;
  sourceHref?: string;
  sourceLinkLabel?: string;
}) {
  const { t } = useI18n();
  const l = labels ?? { ariaLabel: t.analytics.charts.ratingDistribution, reviewsTooltip: t.analytics.charts.reviewsTooltip };
  const c = t.analytics.charts;
  const segments = [5, 4, 3, 2, 1].map((star) => ({
    label: `${star}★`,
    value: Math.max(0, distribution[String(star)] ?? 0),
    color: STAR_COLORS[star],
  }));
  if (total <= 0 || segments.every((segment) => segment.value === 0)) {
    return <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2,#3B2D5E)]">{c.noRatings}</p>;
  }
  return (
    <div className="space-y-3">
      <DonutChart
        ariaLabel={l.ariaLabel}
        centerValue={averageRating != null ? averageRating.toFixed(1) : "—"}
        centerLabel={c.average}
        emptyLabel={c.noRatings}
        segmentAttribute="star-segment"
        segments={segments}
        size={156}
        thickness={16}
      />
      <p className="text-center font-mono text-[10px] text-[var(--ui-ink-2,#3B2D5E)]">
        {c.reviewsTotal.replace("{count}", String(total))}
      </p>
      {source && (
        <FactSource
          source={source}
          detail={sourceDetail}
          href={sourceHref}
          linkLabel={sourceLinkLabel}
        />
      )}
    </div>
  );
}

/* ── Sentiment split bar ──────────────────────────────────────────── */

export function SentimentSplitBar({
  positive,
  neutral,
  negative,
  source,
  sourceDetail,
  sourceHref,
  sourceLinkLabel,
}: {
  positive: number;
  neutral: number;
  negative: number;
  source?: string;
  sourceDetail?: string;
  sourceHref?: string;
  sourceLinkLabel?: string;
}) {
  const { t } = useI18n();
  const c = t.analytics.charts;
  const total = Math.max(0, positive) + Math.max(0, neutral) + Math.max(0, negative);
  const positivePct = total ? Math.round((Math.max(0, positive) / total) * 100) : 0;
  const segments = [
    { label: c.positive, value: Math.max(0, positive), color: CHART_COLORS.green },
    { label: c.neutral, value: Math.max(0, neutral), color: CHART_COLORS.amber },
    { label: c.negative, value: Math.max(0, negative), color: CHART_COLORS.red },
  ];
  return (
    <div className="space-y-3">
      <DonutChart
        ariaLabel="Sentiment mix"
        centerValue={`${positivePct}%`}
        centerLabel={c.positive}
        emptyLabel={c.noActivity}
        segments={segments}
        size={156}
        thickness={16}
      />
      <p className="text-center font-mono text-[10px] text-[var(--ui-ink-2,#3B2D5E)]">
        {c.reviewsTotal.replace("{count}", String(total))}
      </p>
      {source && (
        <FactSource
          source={source}
          detail={sourceDetail}
          href={sourceHref}
          linkLabel={sourceLinkLabel}
        />
      )}
    </div>
  );
}
