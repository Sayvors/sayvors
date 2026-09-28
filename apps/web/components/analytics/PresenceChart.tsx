"use client";

import { useMemo, useState } from "react";
import type { TimeseriesPoint } from "@/lib/api-analytics";

/**
 * Google-presence chart, Analytics-style: pick a metric, read the trend.
 *
 * Two scopes over the same daily points:
 *   - total: one area for everything in the current selection
 *   - byBranch: one line per location, so branches can be compared
 *
 * Only daily metrics appear here. Window-level numbers (posts published,
 * avg posting/response time) have no per-day series and stay as tiles below.
 */

type MetricKey =
  | "impressions"
  | "impressions_search"
  | "impressions_maps"
  | "website_clicks"
  | "direction_requests"
  | "call_clicks"
  | "messages"
  | "bookings"
  | "reviews_count"
  | "replies_count";

interface MetricDef {
  key: MetricKey;
  label: string;
  color: string;
  group: "discovery" | "actions";
  /** Sum is meaningful for counts; averages are computed from the same series. */
  value: (p: TimeseriesPoint) => number;
}

export interface PresenceChartLabels {
  discovery: string;
  actions: string;
  impressions: string;
  searchViews: string;
  mapViews: string;
  websiteClicks: string;
  directionRequests: string;
  phoneCalls: string;
  messages: string;
  bookings: string;
  reviewsMetric: string;
  repliesMetric: string;
  totalLabel: string;
  perBranchDay: string;
  dailyAvg: string;
  peak: string;
  on: string;
  scopeTotal: string;
  scopeByBranch: string;
  noMetricYet: string;
  noMetricHint: string;
}

const METRICS: MetricDef[] = [
  {
    key: "impressions",
    label: "Impressions",
    color: "#5b2d8e",
    group: "discovery",
    value: (p) => (p.impressions_maps || 0) + (p.impressions_search || 0),
  },
  { key: "impressions_search", label: "Search views", color: "#0ea5e9", group: "discovery", value: (p) => p.impressions_search || 0 },
  { key: "impressions_maps", label: "Map views", color: "#8b5cf6", group: "discovery", value: (p) => p.impressions_maps || 0 },
  { key: "website_clicks", label: "Website", color: "#10b981", group: "actions", value: (p) => p.website_clicks || 0 },
  { key: "direction_requests", label: "Directions", color: "#f59e0b", group: "actions", value: (p) => p.direction_requests || 0 },
  { key: "call_clicks", label: "Calls", color: "#ff4f6e", group: "actions", value: (p) => p.call_clicks || 0 },
  { key: "messages", label: "Messages", color: "#d946a8", group: "actions", value: (p) => p.messages || 0 },
  { key: "bookings", label: "Bookings", color: "#0f766e", group: "actions", value: (p) => p.bookings || 0 },
  { key: "reviews_count", label: "Reviews", color: "#d97706", group: "actions", value: (p) => p.reviews_count || 0 },
  { key: "replies_count", label: "Replies", color: "#6366f1", group: "actions", value: (p) => p.replies_count || 0 },
];

// Branch comparison needs a few distinguishable hues; cycled when a tenant
// has more locations than colours.
const BRANCH_COLORS = ["#5b2d8e", "#0ea5e9", "#10b981", "#f59e0b", "#ff4f6e", "#8b5cf6", "#0f766e", "#d946a8"];

const CHART_H = 190;
const PAD = { top: 10, right: 6, bottom: 22, left: 32 };

/** Localized tab names; falls back to the built-in English label. */
const METRIC_LABEL_KEYS: Record<MetricKey, keyof PresenceChartLabels | null> = {
  impressions: "impressions",
  impressions_search: "searchViews",
  impressions_maps: "mapViews",
  website_clicks: "websiteClicks",
  direction_requests: "directionRequests",
  call_clicks: "phoneCalls",
  messages: "messages",
  bookings: "bookings",
  reviews_count: "reviewsMetric",
  replies_count: "repliesMetric",
};

function fmtNum(n: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: n >= 10000 ? "compact" : "standard" }).format(n);
}

function fmtDay(iso: string, locale: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/** Rounded "nice" axis maximum so gridlines land on readable numbers. */
function niceMax(max: number): number {
  if (max <= 0) return 4;
  const mag = Math.pow(10, Math.floor(Math.log10(max)));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (max <= step * mag) return step * mag;
  }
  return 10 * mag;
}

export default function PresenceChart({
  points,
  channelLabels,
  labels,
  group,
  locale = "en",
  loading = false,
  scopeLabel,
}: {
  points: TimeseriesPoint[];
  channelLabels: Record<string, string>;
  labels: PresenceChartLabels;
  group: "discovery" | "actions";
  locale?: string;
  loading?: boolean;
  scopeLabel: string;
}) {
  const metrics = useMemo(() => METRICS.filter((m) => m.group === group), [group]);
  const firstKey = metrics[0]?.key ?? "impressions";
  const [metricKey, setMetricKey] = useState<MetricKey>(firstKey);
  const [byBranch, setByBranch] = useState(false);
  const [hover, setHover] = useState<number | null>(null);

  // Switching chart (group) resets the tab to that group's first metric.
  const activeKey = metrics.some((m) => m.key === metricKey) ? metricKey : firstKey;
  const metric = metrics.find((m) => m.key === activeKey) ?? metrics[0];
  const metricLabel = (() => {
    const k = METRIC_LABEL_KEYS[metric?.key ?? "impressions"];
    const localized = k ? labels[k] : "";
    return localized || metric?.label || "";
  })();

  // Group by date, summing across channels, so "All locations" is a real total
  // per day rather than a per-channel stack.
  const daily = useMemo(() => {
    const byDate = new Map<string, number>();
    for (const p of points) {
      byDate.set(p.date, (byDate.get(p.date) ?? 0) + metric.value(p));
    }
    return [...byDate.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([date, value]) => ({ date, value }));
  }, [points, metric]);

  const branchSeries = useMemo(() => {
    const map = new Map<string, Map<string, number>>();
    for (const p of points) {
      const label = channelLabels[p.channel_id] ?? p.channel_id;
      if (!map.has(label)) map.set(label, new Map());
      const series = map.get(label)!;
      series.set(p.date, (series.get(p.date) ?? 0) + metric.value(p));
    }
    return [...map.entries()]
      .map(([label, series]) => ({
        label,
        color: "",
        values: [...series.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([date, value]) => ({ date, value })),
      }))
      .sort((a, b) => (a.label < b.label ? -1 : 1))
      .map((s, i) => ({ ...s, color: BRANCH_COLORS[i % BRANCH_COLORS.length] }));
  }, [points, metric, channelLabels]);

  const series = useMemo(
    () =>
      byBranch
        ? branchSeries
        : [{ label: scopeLabel, color: metric.color, values: daily }],
    [byBranch, branchSeries, daily, metric.color, scopeLabel]
  );
  const showLegend = byBranch && branchSeries.length > 1;

  const maxValue = useMemo(() => {
    let m = 0;
    for (const s of series) for (const v of s.values) if (v.value > m) m = v.value;
    return niceMax(m);
  }, [series]);

  const dates = daily.map((d) => d.date);
  const innerW = 100; // percentage-based x, so the SVG scales without math
  const plotH = CHART_H - PAD.top - PAD.bottom;

  const xPct = (i: number) => (dates.length <= 1 ? 0 : (i / (dates.length - 1)) * innerW);
  const yPx = (v: number) => PAD.top + plotH - (Math.max(0, v) / maxValue) * plotH;

  // Smooth-ish path: straight segments keep small daily counts honest.
  const linePath = (values: { value: number }[]) =>
    values
      .map((p, i) => {
        const x = (xPct(i) / innerW) * 100;
        return `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${yPx(p.value).toFixed(2)}`;
      })
      .join(" ");

  const totals = useMemo(() => {
    const sum = series.reduce((acc, s) => acc + s.values.reduce((a, v) => a + v.value, 0), 0);
    const daysWithData = dates.length || 1;
    const best = series.reduce(
      (acc, s) => {
        const top = s.values.reduce((m, v) => (v.value > m.value ? v : m), { date: "", value: -1 });
        return top.value > acc.value ? top : acc;
      },
      { date: "", value: -1 }
    );
    return { sum, avg: sum / (byBranch ? Math.max(1, series.length) * daysWithData : daysWithData), best };
  }, [series, dates.length, byBranch]);

  const hasData = daily.length > 0 && daily.some((d) => d.value > 0);

  if (loading) {
    return (
      <section aria-label={group === "discovery" ? labels.discovery : labels.actions} className="rounded-2xl border-2 border-white bg-white/80 p-3.5 backdrop-blur-sm sm:p-4">
        <div className="h-3.5 w-28 animate-pulse rounded bg-ink/[0.07]" />
        <div className="mt-3 h-9 animate-pulse rounded-lg bg-ink/[0.04]" />
        <div className="mt-2 h-40 animate-pulse rounded-lg bg-ink/[0.04]" />
      </section>
    );
  }

  return (
    <section
      aria-label={group === "discovery" ? labels.discovery : labels.actions}
      className="rounded-2xl border-2 border-white bg-white/80 p-3.5 backdrop-blur-sm sm:p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold text-ink">
          {group === "discovery" ? labels.discovery : labels.actions}
        </h3>
        {branchSeries.length > 1 && (
          <div className="flex rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.06]" role="group" aria-label={scopeLabel}>
            {[
              { key: false, label: labels.scopeTotal },
              { key: true, label: labels.scopeByBranch },
            ].map((s) => (
              <button
                key={String(s.key)}
                onClick={() => setByBranch(s.key)}
                aria-pressed={byBranch === s.key}
                className={`rounded-md px-2 py-0.5 text-[10px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  byBranch === s.key ? "bg-white text-deep-violet shadow-sm dark:bg-ink" : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Metric filter — one tab per line */}
      <div className="-mx-1 mt-2.5 flex gap-1 overflow-x-auto px-1 pb-1">
        {metrics.map((m) => {
          const k = METRIC_LABEL_KEYS[m.key];
          const localized = k ? labels[k] : "";
          return (
            <button
              key={m.key}
              onClick={() => setMetricKey(m.key)}
              aria-pressed={activeKey === m.key}
              className={`shrink-0 whitespace-nowrap rounded-md px-2 py-1 text-[10px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                activeKey === m.key
                  ? "bg-deep-violet text-white shadow-sm"
                  : "bg-ink/[0.04] text-ink/55 hover:bg-ink/[0.07] dark:bg-fog/[0.08] dark:text-fog/55"
              }`}
            >
              {localized || m.label}
            </button>
          );
        })}
      </div>

      {/* Headline numbers for the selected metric */}
      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <p className="text-[20px] font-bold leading-none text-ink sm:text-[22px]">
          {fmtNum(totals.sum, locale)}
        </p>
        <p className="text-[10px] text-ink/45">
          {byBranch ? labels.perBranchDay : labels.totalLabel} ·{" "}
          <span className="font-semibold text-ink/70">{fmtNum(totals.avg, locale)}</span> {labels.dailyAvg}
          {totals.best.value > 0 && totals.best.date && (
            <>
              {" · "}
              {labels.peak} <span className="font-semibold text-ink/70">{fmtNum(totals.best.value, locale)}</span>{" "}
              {labels.on} {fmtDay(totals.best.date, locale)}
            </>
          )}
        </p>
      </div>

      {/* Chart */}
      {!hasData ? (
        <div className="mt-3 flex h-32 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-ink/10 px-3 text-center dark:border-fog/10">
          <p className="text-[11px] font-semibold text-ink/60">
            {labels.noMetricYet.replace("{metric}", metricLabel.toLowerCase())}
          </p>
          <p className="max-w-[15rem] text-[10px] leading-snug text-ink/40">{labels.noMetricHint}</p>
        </div>
      ) : (
        <div className="relative mt-2">
          <svg
            viewBox={`0 0 100 ${CHART_H}`}
            preserveAspectRatio="none"
            className="h-36 w-full sm:h-44"
            role="img"
            aria-label={`${metric.label} over time`}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const frac = (e.clientX - rect.left) / rect.width;
              const idx = Math.round(frac * (dates.length - 1));
              setHover(Math.min(dates.length - 1, Math.max(0, idx)));
            }}
            onTouchStart={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const frac = (e.touches[0].clientX - rect.left) / rect.width;
              const idx = Math.round(frac * (dates.length - 1));
              setHover(Math.min(dates.length - 1, Math.max(0, idx)));
            }}
            onTouchMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const frac = (e.touches[0].clientX - rect.left) / rect.width;
              const idx = Math.round(frac * (dates.length - 1));
              setHover(Math.min(dates.length - 1, Math.max(0, idx)));
            }}
            onTouchEnd={() => setHover(null)}
          >
            <defs>
              {series.map((s) => (
                <linearGradient key={`g-${s.label}`} id={`pg-${s.label.replace(/\W/g, "")}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity={byBranch ? 0.12 : 0.26} />
                  <stop offset="100%" stopColor={s.color} stopOpacity="0.02" />
                </linearGradient>
              ))}
            </defs>

            {/* Horizontal gridlines + y labels */}
            {[0, 0.25, 0.5, 0.75, 1].map((f) => {
              const y = PAD.top + plotH - f * plotH;
              const val = maxValue * f;
              return (
                <g key={f}>
                  <line x1="0" x2={innerW} y1={y} y2={y} stroke="#1a1230" strokeOpacity="0.06" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  <text
                    x="0"
                    y={y - 2}
                    className="fill-ink/35 text-[7px]"
                    style={{ fontSize: 7 }}
                    textAnchor="start"
                    transform={`translate(-2, 0)`}
                  >
                    {val >= 1000 ? `${Math.round(val / 1000)}k` : Math.round(val)}
                  </text>
                </g>
              );
            })}

            {/* Series */}
            {series.map((s) => {
              const d = linePath(s.values);
              const area = `${d} L${innerW} ${PAD.top + plotH} L0 ${PAD.top + plotH} Z`;
              const gid = `pg-${s.label.replace(/\W/g, "")}`;
              return (
                <g key={s.label}>
                  {!byBranch && <path d={area} fill={`url(#${gid})`} />}
                  <path
                    d={d}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={byBranch ? 1.75 : 2}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              );
            })}

            {/* Crosshair + dots */}
            {hover !== null && dates[hover] && (
              <g>
                <line
                  x1={xPct(hover)}
                  x2={xPct(hover)}
                  y1={PAD.top}
                  y2={PAD.top + plotH}
                  stroke="#5b2d8e"
                  strokeOpacity="0.3"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                />
                {series.map((s) => {
                  const v = s.values[hover]?.value;
                  if (v === undefined) return null;
                  return (
                    <circle
                      key={s.label}
                      cx={xPct(hover)}
                      cy={yPx(v)}
                      r="2.5"
                      fill={s.color}
                      stroke="#fff"
                      strokeWidth="1.5"
                      vectorEffect="non-scaling-stroke"
                    />
                  );
                })}
              </g>
            )}
          </svg>

          {/* X labels (CSS so they don't stretch with preserveAspectRatio) */}
          <div className="mt-0.5 flex justify-between text-[8px] text-ink/35">
            <span>{dates[0] ? fmtDay(dates[0], locale) : ""}</span>
            {dates.length > 2 && <span>{fmtDay(dates[Math.floor(dates.length / 2)], locale)}</span>}
            <span>{dates[dates.length - 1] ? fmtDay(dates[dates.length - 1], locale) : ""}</span>
          </div>

          {/* Tooltip */}
          {hover !== null && dates[hover] && (
            <div
              className="pointer-events-none absolute top-0.5 z-10 rounded-lg border border-deep-violet/10 bg-white/95 px-2 py-1 shadow-lg backdrop-blur-sm"
              style={{
                left: `min(max(${xPct(hover)}%, 62px), calc(100% - 62px))`,
                transform: "translateX(-50%)",
              }}
            >
              <p className="text-[10px] font-semibold text-ink/70">{fmtDay(dates[hover], locale)}</p>
              {series.map((s) => {
                const v = s.values[hover]?.value ?? 0;
                return (
                  <p key={s.label} className="flex items-center gap-1.5 text-[10px] text-ink/55">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden />
                    {showLegend ? `${s.label}: ` : ""}
                    <span className="font-semibold text-ink">{fmtNum(v, locale)}</span>
                  </p>
                );
              })}
            </div>
          )}
        </div>
      )}

      {showLegend && (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5">
          {branchSeries.map((s) => (
            <li key={s.label} className="flex items-center gap-1.5 text-[10px] text-ink/55">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} aria-hidden />
              {s.label}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
