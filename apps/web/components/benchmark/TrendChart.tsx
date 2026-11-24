"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { SubjectHistory } from "@/lib/api-benchmark";
import {
  buildTrendSeries,
  seriesDelta,
  sharedTimeDomain,
  type TrendMetric,
  type TrendSeries,
} from "@/lib/benchmark-trend";

const W = 560;
const H = 190;
const PAD = 24;
const LABEL_W = 150;
const PLOT_RIGHT = W - LABEL_W;
const COLORS = ["#3D1D6E", "#B0338A", "#FF4F6E", "#116631", "#8A6100", "#0B5CAD"];

function fill(template: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, value),
    template,
  );
}

function shorten(value: string, max = 22): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function colorFor(series: TrendSeries[], key: string, mainKey?: string | null): string {
  if (key === mainKey) return COLORS[0];
  const peers = series.filter((row) => row.key !== mainKey);
  const index = peers.findIndex((row) => row.key === key);
  return COLORS[1 + (Math.max(0, index) % (COLORS.length - 1))];
}

interface Domain {
  start: number;
  end: number;
}

function TrendPanel({
  metric,
  title,
  series,
  domain,
  mainKey,
  min,
  max,
  formatValue,
  dateLabel,
  noDataLabel,
  deltaLabel,
}: {
  metric: TrendMetric;
  title: string;
  series: TrendSeries[];
  domain: Domain;
  mainKey?: string | null;
  min: number;
  max: number;
  formatValue: (value: number) => string;
  dateLabel: (at: number) => string;
  noDataLabel: string;
  deltaLabel: (series: TrendSeries) => string;
}) {
  const spanX = Math.max(domain.end - domain.start, 1);
  const spanY = Math.max(max - min, 0.0001);
  const x = (at: number) => PAD + ((at - domain.start) / spanX) * (PLOT_RIGHT - PAD);
  const y = (value: number) => H - PAD - ((value - min) / spanY) * (H - 2 * PAD);
  const ticks = metric === "rating" ? [1, 2, 3, 4, 5] : [0, 0.25, 0.5, 0.75, 1].map((t) => min + (max - min) * t);

  // Direct labels share the right gutter. Resolve vertical collisions so five
  // businesses remain readable instead of drawing five names over one line.
  const labels = series
    .map((row) => ({
      key: row.key,
      name: row.name,
      y: y(row.points[row.points.length - 1].value),
      own: row.key === mainKey,
    }))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) {
    labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 16);
  }
  const overflow = Math.max(0, labels[labels.length - 1].y - (H - PAD));
  if (overflow > 0) labels.forEach((label) => { label.y -= overflow; });

  return (
    <figure className="m-0 rounded-[8px] border border-[var(--ui-line)] bg-[#FCFBFE] p-3.5">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[12px] font-bold text-[#14101F]">{title}</h3>
        {series.find((row) => row.key === mainKey) && (
          <span className="rounded-full bg-[#F4F2F7] px-2 py-1 text-[9px] font-bold text-[#3B2D5E]">
            {deltaLabel(series.find((row) => row.key === mainKey)!)}
          </span>
        )}
      </figcaption>

      {series.length === 0 ? (
        <p className="flex h-[180px] items-center justify-center text-center text-[11px] text-[#3B2D5E]">
          {noDataLabel}
        </p>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="mt-2 h-[180px] w-full"
            role="img"
            aria-labelledby={`trend-${metric}-title trend-${metric}-desc`}
          >
            <title id={`trend-${metric}-title`}>{title}</title>
            <desc id={`trend-${metric}-desc`}>
              {`${dateLabel(domain.start)} to ${dateLabel(domain.end)}. ${series
                .map((row) => `${row.name}: ${formatValue(row.points[0].value)} to ${formatValue(row.points[row.points.length - 1].value)}`)
                .join("; ")}`}
            </desc>
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={PAD}
                  x2={PLOT_RIGHT}
                  y1={y(tick)}
                  y2={y(tick)}
                  stroke="var(--ui-line)"
                  strokeWidth="1"
                />
                <text x={PAD - 6} y={y(tick) + 3} textAnchor="end" fontSize="9" fill="#6F6685">
                  {formatValue(tick)}
                </text>
              </g>
            ))}
            <line
              x1={PAD}
              x2={PLOT_RIGHT}
              y1={H - PAD}
              y2={H - PAD}
              stroke="#3B2D5E"
              strokeOpacity="0.35"
            />
            {series.map((row) => {
              const own = row.key === mainKey;
              const color = colorFor(series, row.key, mainKey);
              const points = row.points.map((point) => `${x(point.at).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
              const last = row.points[row.points.length - 1];
              const peerIndex = series.filter((s) => s.key !== mainKey).findIndex((s) => s.key === row.key);
              return (
                <g key={row.key}>
                  <polyline
                    data-chart={metric}
                    data-own={own ? "true" : "false"}
                    data-label={row.name}
                    points={points}
                    fill="none"
                    stroke={color}
                    strokeWidth={own ? 3 : 2}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    strokeDasharray={!own && peerIndex % 2 === 1 ? "6 4" : undefined}
                  />
                  <circle cx={x(last.at)} cy={y(last.value)} r={own ? 4 : 3} fill={color} stroke="#fff" strokeWidth="1.5" />
                </g>
              );
            })}
            {labels.map((label) => (
              <text
                key={label.key}
                x={PLOT_RIGHT + 8}
                y={label.y + 3}
                fontSize="10"
                fontWeight={label.own ? 700 : 600}
                fill={label.own ? "#3D1D6E" : "#3B2D5E"}
              >
                {shorten(label.name)}
              </text>
            ))}
          </svg>
          <div className="mt-1 flex justify-between font-mono text-[9px] text-[#6F6685]">
            <span>{dateLabel(domain.start)}</span>
            <span>{dateLabel(domain.end)}</span>
          </div>
        </>
      )}
    </figure>
  );
}

/** Rating and cumulative review growth on one shared date domain. */
export default function TrendChart({
  history,
  title,
  mainKey,
}: {
  history: SubjectHistory[];
  title: string;
  mainKey?: string | null;
}) {
  const { t, locale } = useI18n();
  const b = t.benchmark;
  const rating = buildTrendSeries(history, "rating");
  const reviews = buildTrendSeries(history, "reviews");
  const domain = sharedTimeDomain([...rating, ...reviews]);
  const dateLabel = (at: number) =>
    new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en-US", {
      month: "short",
      day: "numeric",
    }).format(new Date(at));
  const deltaLabel = (metric: TrendMetric, row: TrendSeries) => {
    const delta = seriesDelta(row);
    const name = shorten(row.name, 28);
    if (metric === "reviews") {
      if (delta > 0) return fill(b.trendDeltaReviews, { name, count: String(Math.round(delta)) });
      if (delta < 0) return fill(b.trendDeltaReviewsLost, { name, count: String(Math.abs(Math.round(delta))) });
      return fill(b.trendDeltaReviewsFlat, { name });
    }
    return fill(b.trendDeltaRating, {
      name,
      delta: `${delta > 0 ? "+" : ""}${delta.toFixed(2)}★`,
    });
  };

  if (rating.length === 0 && reviews.length === 0) {
    return (
      <section
        aria-labelledby="trend-title"
        className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5"
      >
        <h2 id="trend-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
          {title}
        </h2>
        <p className="mt-3 text-[12px] text-[#3B2D5E]">{b.trendEmpty}</p>
      </section>
    );
  }

  const legend = rating.length > 0 ? rating : reviews;
  return (
    <section
      aria-labelledby="trend-title"
      className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5"
    >
      <h2 id="trend-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
        {title}
      </h2>
      <div className="mt-3 grid gap-4 xl:grid-cols-2">
        <TrendPanel
          metric="rating"
          title={b.trendRatingLabel}
          series={rating}
          domain={domain}
          mainKey={mainKey}
          min={1}
          max={5}
          formatValue={(value) => value.toFixed(1)}
          dateLabel={dateLabel}
          noDataLabel={b.trendNoSeries}
          deltaLabel={(row) => deltaLabel("rating", row)}
        />
        <TrendPanel
          metric="reviews"
          title={b.trendReviewGrowthLabel}
          series={reviews}
          domain={domain}
          mainKey={mainKey}
          min={0}
          max={Math.max(1, ...reviews.flatMap((row) => row.points.map((point) => point.value)))}
          formatValue={(value) => String(Math.round(value))}
          dateLabel={dateLabel}
          noDataLabel={b.trendNoSeries}
          deltaLabel={(row) => deltaLabel("reviews", row)}
        />
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2 border-t border-[var(--ui-line)] pt-3 text-[10px] text-[#3B2D5E]">
        {legend.map((row) => (
          <li key={row.key} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-2 w-4 rounded-full"
              style={{ background: colorFor(legend, row.key, mainKey) }}
            />
            <span className="font-semibold">{row.name}</span>
            {row.key === mainKey && <span className="text-[#3D1D6E]">({b.distributionYourBranch})</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[9px] leading-relaxed text-[#6F6685]">{b.trendHistoryNote}</p>
    </section>
  );
}
