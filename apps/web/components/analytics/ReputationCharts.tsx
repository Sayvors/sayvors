"use client";

/** Shared, dependency-free chart primitives for reputation analytics.

 * Color is data ink here, not surface decoration: every hue has a text label,
 * every SVG has a finding-style accessible name, and no chart relies on color
 * alone. No gradients, 3D, or animation that needs a pause control.
 */
import type { CSSProperties } from "react";

export const CHART_COLORS = {
  violet: "#3D1D6E",
  magenta: "#B0338A",
  coral: "#FF4F6E",
  blue: "#0B5CAD",
  green: "#116631",
  teal: "#0F766E",
  amber: "#8A6100",
  orange: "#C2410C",
  red: "#B3123A",
  grid: "#E8E5EE",
  surface: "#FFFFFF",
} as const;

export type DonutSegment = {
  label: string;
  value: number;
  color: string;
};

function safeValue(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function pct(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

export function DonutChart({
  segments,
  centerValue,
  centerLabel,
  ariaLabel,
  emptyLabel = "No data yet",
  size = 168,
  thickness = 18,
  segmentAttribute,
}: {
  segments: DonutSegment[];
  centerValue: string;
  centerLabel: string;
  ariaLabel: string;
  emptyLabel?: string;
  size?: number;
  thickness?: number;
  segmentAttribute?: string;
}) {
  const safe = segments.map((segment) => ({
    ...segment,
    value: safeValue(segment.value),
  }));
  const total = safe.reduce((sum, segment) => sum + segment.value, 0);
  if (total <= 0) {
    return (
      <div className="flex min-h-40 items-center justify-center rounded-[8px] bg-[var(--ui-sunken,#F4F2F7)] px-4 text-center text-[12px] text-[var(--ui-ink-2,#3B2D5E)]">
        {emptyLabel}
      </div>
    );
  }

  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const summary = safe
    .map((segment) => `${segment.label}: ${pct(segment.value, total)}%`)
    .join(", ");

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:gap-5">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg
          viewBox={`0 0 ${size} ${size}`}
          width={size}
          height={size}
          role="img"
          aria-label={`${ariaLabel}: ${summary}`}
        >
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={CHART_COLORS.grid}
            strokeWidth={thickness}
          />
          {safe.filter((segment) => segment.value > 0).map((segment) => {
            const length = (segment.value / total) * circumference;
            const dash = Math.max(0, length - 2);
            const dashOffset = -offset;
            offset += length;
            return (
              <circle
                key={segment.label}
                data-donut-segment
                {...(segmentAttribute ? { [`data-${segmentAttribute}`]: "" } : {})}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={segment.color}
                strokeWidth={thickness}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={dashOffset}
                strokeLinecap="butt"
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              />
            );
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="font-mono text-[26px] font-bold leading-none text-[var(--ui-ink,#14101F)]">{centerValue}</span>
          <span className="mt-1 max-w-24 text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2,#3B2D5E)]">
            {centerLabel}
          </span>
        </div>
      </div>
      <ul className="w-full space-y-2">
        {safe.map((segment) => (
          <li key={segment.label} className="flex items-center justify-between gap-3 text-[11px]">
            <span className="flex min-w-0 items-center gap-2 text-[var(--ui-ink-2,#3B2D5E)]">
              <span
                aria-hidden
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: segment.color }}
              />
              <span className="truncate">{segment.label}</span>
            </span>
            <span className="shrink-0 font-mono font-bold text-[var(--ui-ink,#14101F)]">
              {pct(segment.value, total)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ImportOutcomesDonut({
  counts,
  labels,
}: {
  counts: {
    unanswered: number;
    published: number;
    alreadyAnswered: number;
    needsAttention: number;
  };
  labels: {
    unanswered: string;
    published: string;
    alreadyAnswered: string;
    needsAttention: string;
  };
}) {
  const segments: DonutSegment[] = [
    { label: labels.published, value: counts.published, color: CHART_COLORS.green },
    { label: labels.alreadyAnswered, value: counts.alreadyAnswered, color: CHART_COLORS.blue },
    { label: labels.unanswered, value: counts.unanswered, color: CHART_COLORS.amber },
    { label: labels.needsAttention, value: counts.needsAttention, color: CHART_COLORS.red },
  ];
  const total = segments.reduce((sum, segment) => sum + safeValue(segment.value), 0);
  return (
    <DonutChart
      ariaLabel="Import outcomes"
      centerValue={String(total)}
      centerLabel="Reviews"
      emptyLabel="No import outcomes yet"
      segments={segments}
      size={156}
      thickness={16}
    />
  );
}

export function ReviewVolumeBars({
  data,
  ariaLabel,
  emptyLabel = "No review volume yet",
}: {
  data: Array<{ label: string; value: number }>;
  ariaLabel: string;
  emptyLabel?: string;
}) {
  if (data.length === 0) {
    return <p className="mt-3 text-[11px] text-[var(--ui-ink-2,#3B2D5E)]">{emptyLabel}</p>;
  }
  const safe = data.map((row) => ({ ...row, value: safeValue(row.value) }));
  const max = Math.max(1, ...safe.map((row) => row.value));
  const summary = safe.map((row) => `${row.label}: ${row.value}`).join(", ");
  return (
    <figure className="m-0">
      <div
        className="mt-3 flex h-28 items-end gap-2"
        role="img"
        aria-label={`${ariaLabel}: ${summary}`}
      >
        {safe.map((row, index) => {
          const highlight = index === safe.length - 1;
          const height = Math.max(4, (row.value / max) * 88);
          return (
            <div key={row.label} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1.5">
              <span className="font-mono text-[9px] font-bold text-[var(--ui-ink-2,#3B2D5E)]">{row.value}</span>
              <div
                data-highlight={highlight ? "true" : "false"}
                title={`${row.label}: ${row.value}`}
                className="w-full rounded-t-[6px] transition-[height] duration-300"
                style={{
                  height,
                  background: highlight ? CHART_COLORS.coral : CHART_COLORS.violet,
                  opacity: highlight ? 1 : 0.72,
                }}
              />
              <span className="max-w-full truncate text-[8px] text-[var(--ui-ink-2,#3B2D5E)]/70">{row.label}</span>
            </div>
          );
        })}
      </div>
      <figcaption className="mt-2 flex items-center gap-2 text-[9px] text-[var(--ui-ink-2,#3B2D5E)]/70">
        <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: CHART_COLORS.violet }} />
        Earlier
        <span aria-hidden className="ms-1 h-2 w-2 rounded-full" style={{ background: CHART_COLORS.coral }} />
        Latest
      </figcaption>
    </figure>
  );
}

const RATING_COLORS: Record<number, string> = {
  5: CHART_COLORS.green,
  4: CHART_COLORS.teal,
  3: CHART_COLORS.amber,
  2: CHART_COLORS.orange,
  1: CHART_COLORS.red,
};

export function RatingTrend({
  data,
  ariaLabel,
  emptyLabel = "No rating history yet",
}: {
  data: Array<{ date: string; rating: number }>;
  ariaLabel: string;
  emptyLabel?: string;
}) {
  if (data.length === 0) {
    return <p className="mt-3 text-[11px] text-[var(--ui-ink-2,#3B2D5E)]">{emptyLabel}</p>;
  }
  const points = data.slice(0, 80).map((point) => ({
    ...point,
    rating: Math.max(1, Math.min(5, Math.round(safeValue(point.rating) || 1))),
  }));
  const average = points.reduce((sum, point) => sum + point.rating, 0) / points.length;
  const averageY = 96 - (average - 1) * 20;
  const summary = `${points.length} reviews, average ${average.toFixed(1)} stars`;

  return (
    <figure className="m-0">
      <svg
        viewBox="0 0 300 110"
        className="mt-2 h-28 w-full"
        role="img"
        aria-label={`${ariaLabel}: ${summary}`}
      >
        {[1, 2, 3, 4, 5].map((rating) => (
          <line
            key={rating}
            x1="6"
            x2="294"
            y1={96 - (rating - 1) * 20}
            y2={96 - (rating - 1) * 20}
            stroke={CHART_COLORS.grid}
            strokeWidth="1"
          />
        ))}
        <line
          data-average-line
          x1="6"
          x2="294"
          y1={averageY}
          y2={averageY}
          stroke={CHART_COLORS.violet}
          strokeWidth="1.5"
          strokeDasharray="5 4"
          opacity="0.65"
        />
        {points.map((point, index) => {
          const x = 8 + (index / Math.max(1, points.length - 1)) * 284;
          const y = 96 - (point.rating - 1) * 20;
          return (
            <circle
              key={`${point.date}-${index}`}
              data-rating-point
              cx={x}
              cy={y}
              r="3.2"
              fill={RATING_COLORS[point.rating]}
              stroke={CHART_COLORS.surface}
              strokeWidth="1"
            >
              <title>{`${point.date}: ${point.rating} stars`}</title>
            </circle>
          );
        })}
      </svg>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[9px] text-[var(--ui-ink-2,#3B2D5E)]/70">
        <span className="font-mono font-bold text-[#3D1D6E] dark:text-[#C9A8FF]">Avg {average.toFixed(1)}</span>
        {[5, 4, 3, 2, 1].map((rating) => (
          <span key={rating} className="inline-flex items-center gap-1">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: RATING_COLORS[rating] }} />
            {rating}★
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
