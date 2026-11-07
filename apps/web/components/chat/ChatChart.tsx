"use client";

import { useMemo, useState } from "react";
import {
  chartLabel,
  chartValue,
  truncateLabel,
  type ChatChart as ChatChartData,
  type ChatChartSeries,
  type ChatKpiFormat,
} from "@/lib/chat-charts";

const PALETTE = [
  "#3D1D6E",
  "#B0338A",
  "#0F766E",
  "#D97706",
  "#2563EB",
  "#C4304B",
  "#7C3AED",
  "#0891B2",
];

const W = 360;
const H = 190;
const PAD = { top: 14, right: 10, bottom: 30, left: 40 };

function colorFor(index: number): string {
  return PALETTE[index % PALETTE.length];
}

function num(value: unknown): number {
  return typeof value === "number" ? value : Number(value) || 0;
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const n = value / power;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * power;
}

function formatFor(series: ChatChartSeries | undefined): ChatKpiFormat {
  return series?.format ?? "number";
}

function KpiCard({
  label,
  value,
  format,
  delta,
}: {
  label: string;
  value: number | string | null;
  format?: ChatKpiFormat;
  delta?: number | null;
}) {
  return (
    <div className="min-w-0 rounded-lg bg-ink/[0.035] px-2 py-1.5 dark:bg-fog/[0.06]">
      <p className="truncate text-[8.5px] font-bold uppercase tracking-[0.08em] text-ink/40 dark:text-fog/40">
        {label}
      </p>
      <p className="mt-0.5 truncate text-[14px] font-bold tabular-nums text-ink dark:text-fog">
        {chartValue(value, format)}
      </p>
      {delta != null && Number.isFinite(delta) && (
        <p
          className={`mt-0.5 text-[9px] font-semibold tabular-nums ${
            delta >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-coral"
          }`}
        >
          {delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(1)}%
        </p>
      )}
    </div>
  );
}

function Legend({
  chart,
  hidden,
  toggle,
}: {
  chart: ChatChartData;
  hidden: Set<string>;
  toggle: (key: string) => void;
}) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
      {chart.series.map((series, index) => {
        const off = hidden.has(series.key);
        return (
          <button
            key={series.key}
            type="button"
            onClick={() => toggle(series.key)}
            aria-pressed={!off}
            className={`inline-flex items-center gap-1.5 text-[9.5px] font-semibold transition ${
              off ? "text-ink/30 dark:text-fog/30" : "text-ink/60 dark:text-fog/60"
            }`}
          >
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: colorFor(index), opacity: off ? 0.25 : 1 }}
              aria-hidden
            />
            <span className={off ? "line-through" : ""}>{series.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function Tooltip({
  chart,
  rowIndex,
  xPct,
}: {
  chart: ChatChartData;
  rowIndex: number;
  xPct: number;
}) {
  const row = chart.rows[rowIndex];
  if (!row) return null;
  return (
    <div
      className="pointer-events-none absolute top-0 z-10 w-max max-w-[220px] -translate-x-1/2 rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[10px] shadow-lg dark:border-fog/[0.12] dark:bg-[#241a44]"
      style={{ left: `${Math.min(88, Math.max(12, xPct))}%` }}
    >
      <p className="font-bold text-ink dark:text-fog">{chartLabel(row.label)}</p>
      {chart.series.map((series, index) => (
        <p key={series.key} className="mt-0.5 flex items-center gap-1.5 text-ink/60 dark:text-fog/60">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: colorFor(index) }}
            aria-hidden
          />
          <span className="truncate">{series.label}</span>
          <span className="ml-auto pl-2 font-semibold tabular-nums text-ink dark:text-fog">
            {chartValue(num(row[series.key]), series.format)}
          </span>
        </p>
      ))}
    </div>
  );
}

function AxisChart({ chart }: { chart: ChatChartData }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<number | null>(null);
  const visible = chart.series.filter((s) => !hidden.has(s.key));
  const rows = chart.rows;
  const stacked = chart.type === "stacked_bar";
  const isBar = chart.type === "bar" || stacked || chart.type === "histogram";

  const values = useMemo(() => {
    const perRow = rows.map((row) =>
      stacked
        ? visible.reduce((sum, s) => sum + num(row[s.key]), 0)
        : Math.max(0, ...visible.map((s) => num(row[s.key]))),
    );
    return perRow;
  }, [rows, visible, stacked]);

  const max = niceMax(Math.max(1, ...values));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const n = Math.max(1, rows.length);
  const band = innerW / n;
  const xAt = (index: number) =>
    n === 1 ? PAD.left + innerW / 2 : PAD.left + (index / (n - 1)) * innerW;
  const yAt = (value: number) =>
    PAD.top + innerH - (Math.max(0, value) / max) * innerH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => max * t);
  const format = formatFor(visible[0] ?? chart.series[0]);
  const showDots = rows.length <= 18;

  const labelIndexes = useMemo(() => {
    if (rows.length === 0) return new Set<number>();
    const count = Math.min(isBar ? 6 : 4, rows.length);
    if (count === rows.length) {
      return new Set(rows.map((_, index) => index));
    }
    const out = new Set<number>();
    for (let i = 0; i < count; i++) {
      out.add(Math.round((i * (rows.length - 1)) / (count - 1)));
    }
    return out;
  }, [isBar, rows.length]);

  const toggle = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else if (next.size < chart.series.length - 1) next.add(key);
      return next;
    });
  };

  return (
    <div>
      <div className="relative">
        {hover != null && (
          <Tooltip
            chart={{ ...chart, series: visible }}
            rowIndex={hover}
            xPct={isBar ? ((PAD.left + (hover + 0.5) * band) / W) * 100 : (xAt(hover) / W) * 100}
          />
        )}
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`${chart.title} chart`}
          className="h-auto w-full overflow-visible"
        >
          <title>{chart.title}</title>
          {ticks.map((tick, index) => {
            const y = yAt(tick);
            return (
              <g key={index}>
                <line
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  strokeOpacity={index === 0 ? 0.18 : 0.07}
                  strokeWidth={1}
                />
                <text
                  x={PAD.left - 5}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={8.5}
                  fill="currentColor"
                  opacity={0.45}
                >
                  {chartValue(tick, format, true)}
                </text>
              </g>
            );
          })}

          {isBar
            ? rows.map((row, rowIndex) => {
                const groupW = band * 0.68;
                const groupX = PAD.left + rowIndex * band + (band - groupW) / 2;
                const singleW = groupW / Math.max(1, visible.length);
                let stackY = PAD.top + innerH;
                return (
                  <g key={`${row.label}-${rowIndex}`}>
                    {visible.map((series, seriesIndex) => {
                      const value = num(row[series.key]);
                      const h = (Math.max(0, value) / max) * innerH;
                      if (stacked) {
                        stackY -= h;
                        return (
                          <rect
                            key={series.key}
                            x={groupX}
                            y={stackY}
                            width={groupW}
                            height={Math.max(0, h)}
                            fill={colorFor(chart.series.findIndex((s) => s.key === series.key))}
                            rx={1}
                            opacity={hover == null || hover === rowIndex ? 1 : 0.55}
                          />
                        );
                      }
                      return (
                        <rect
                          key={series.key}
                          x={groupX + seriesIndex * singleW + 1}
                          y={yAt(value)}
                          width={Math.max(1, singleW - 2)}
                          height={Math.max(0, PAD.top + innerH - yAt(value))}
                          fill={colorFor(chart.series.findIndex((s) => s.key === series.key))}
                          rx={1}
                          opacity={hover == null || hover === rowIndex ? 1 : 0.55}
                        />
                      );
                    })}
                    <rect
                      x={PAD.left + rowIndex * band}
                      y={PAD.top}
                      width={band}
                      height={innerH}
                      fill="transparent"
                      onPointerEnter={() => setHover(rowIndex)}
                      onPointerLeave={() => setHover(null)}
                      onClick={() => setHover(rowIndex)}
                    />
                  </g>
                );
              })
            : (() => {
                const points = rows.map((row, index) => ({
                  x: xAt(index),
                  y: yAt(stacked
                    ? visible.reduce((sum, s) => sum + num(row[s.key]), 0)
                    : num(row[visible[0]?.key] ?? 0)),
                  row,
                }));
                return (
                  <>
                    {visible.map((series, seriesIndex) => {
                      const seriesPoints = rows.map((row, index) => ({
                        x: xAt(index),
                        y: yAt(num(row[series.key])),
                      }));
                      const path = seriesPoints
                        .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
                        .join(" ");
                      const areaPath = `${path} L${seriesPoints[seriesPoints.length - 1]?.x ?? PAD.left} ${
                        PAD.top + innerH
                      } L${seriesPoints[0]?.x ?? PAD.left} ${PAD.top + innerH} Z`;
                      const color = colorFor(seriesIndex);
                      return (
                        <g key={series.key}>
                          {chart.type === "area" && (
                            <path d={areaPath} fill={color} opacity={0.12} />
                          )}
                          <path
                            d={path}
                            fill="none"
                            stroke={color}
                            strokeWidth={2}
                            strokeLinejoin="round"
                            strokeLinecap="round"
                          />
                          {showDots &&
                            seriesPoints.map((p, i) => (
                              <circle
                                key={i}
                                cx={p.x}
                                cy={p.y}
                                r={hover === i ? 3.4 : 2.2}
                                fill={color}
                                stroke="white"
                                strokeWidth={1}
                              />
                            ))}
                        </g>
                      );
                    })}
                    <rect
                      x={PAD.left}
                      y={PAD.top}
                      width={innerW}
                      height={innerH}
                      fill="transparent"
                      onPointerMove={(e) => {
                        const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
                        const ratio = (e.clientX - rect.left) / Math.max(1, rect.width);
                        const index = Math.round(ratio * (rows.length - 1));
                        setHover(Math.min(rows.length - 1, Math.max(0, index)));
                      }}
                      onPointerLeave={() => setHover(null)}
                    />
                    {hover != null && points[hover] && (
                      <line
                        x1={points[hover].x}
                        x2={points[hover].x}
                        y1={PAD.top}
                        y2={PAD.top + innerH}
                        stroke="currentColor"
                        strokeOpacity={0.18}
                        strokeDasharray="3 3"
                      />
                    )}
                  </>
                );
              })()}

          {rows.map((row, index) => {
            if (!labelIndexes.has(index)) return null;
            return (
              <text
                key={`${row.label}-x-${index}`}
                x={isBar ? PAD.left + (index + 0.5) * band : xAt(index)}
                y={H - 8}
                textAnchor="middle"
                fontSize={8}
                fill="currentColor"
                opacity={0.45}
              >
                {truncateLabel(row.label, 10)}
              </text>
            );
          })}
        </svg>
      </div>
      {chart.series.length > 1 && <Legend chart={chart} hidden={hidden} toggle={toggle} />}
    </div>
  );
}

function arcPath(
  cx: number,
  cy: number,
  outer: number,
  inner: number,
  start: number,
  end: number,
): string {
  const point = (radius: number, angle: number) => {
    const rad = ((angle - 90) * Math.PI) / 180;
    return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) };
  };
  const span = Math.min(359.999, Math.max(0, end - start));
  const large = span > 180 ? 1 : 0;
  const p1 = point(outer, start);
  const p2 = point(outer, start + span);
  const p3 = point(inner, start + span);
  const p4 = point(inner, start);
  return [
    `M${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`,
    `A${outer} ${outer} 0 ${large} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`,
    `L${p3.x.toFixed(2)} ${p3.y.toFixed(2)}`,
    `A${inner} ${inner} 0 ${large} 0 ${p4.x.toFixed(2)} ${p4.y.toFixed(2)}`,
    "Z",
  ].join(" ");
}

function DonutChart({ chart }: { chart: ChatChartData }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = chart.series[0];
  const rows = chart.rows;
  const total = rows.reduce((sum, row) => sum + Math.max(0, num(row[series?.key])), 0);
  const format = formatFor(series);
  let cursor = 0;
  const slices = rows.map((row, index) => {
    const value = Math.max(0, num(row[series?.key]));
    const share = total > 0 ? value / total : 0;
    const start = cursor;
    const end = cursor + share * 360;
    cursor = end;
    return { row, index, value, share, start, end };
  });
  const active = hover != null ? slices[hover] : null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <svg
          viewBox="0 0 180 180"
          role="img"
          aria-label={`${chart.title} donut chart`}
          className="h-[142px] w-[142px] shrink-0"
        >
          <title>{chart.title}</title>
          {slices.map((slice) => (
            <path
              key={`${slice.row.label}-${slice.index}`}
              d={arcPath(90, 90, 78, 50, slice.start, slice.end)}
              fill={colorFor(slice.index)}
              opacity={hover == null || hover === slice.index ? 1 : 0.45}
              stroke="white"
              strokeWidth={1.5}
              onPointerEnter={() => setHover(slice.index)}
              onPointerLeave={() => setHover(null)}
            />
          ))}
          <text x="90" y="86" textAnchor="middle" fontSize="8" fill="currentColor" opacity="0.45">
            {active ? chartLabel(active.row.label) : "Total"}
          </text>
          <text x="90" y="103" textAnchor="middle" fontSize="14" fontWeight="700" fill="currentColor">
            {chartValue(active ? active.value : total, format, true)}
          </text>
          {active && (
            <text x="90" y="116" textAnchor="middle" fontSize="8" fill="currentColor" opacity="0.45">
              {(active.share * 100).toFixed(1)}%
            </text>
          )}
        </svg>
        <div className="min-w-0 flex-1 space-y-1">
          {slices.slice(0, 8).map((slice) => (
            <button
              key={`${slice.row.label}-legend-${slice.index}`}
              type="button"
              onPointerEnter={() => setHover(slice.index)}
              onPointerLeave={() => setHover(null)}
              onClick={() => setHover(slice.index)}
              className="flex w-full items-center gap-1.5 text-left text-[9.5px] text-ink/60 dark:text-fog/60"
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: colorFor(slice.index) }}
                aria-hidden
              />
              <span className="min-w-0 flex-1 truncate">{truncateLabel(slice.row.label, 15)}</span>
              <span className="shrink-0 font-semibold tabular-nums text-ink dark:text-fog">
                {chartValue(slice.value, format, true)}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function RankingChart({ chart }: { chart: ChatChartData }) {
  const series = chart.series[0];
  const format = formatFor(series);
  const rows = chart.rows.slice(0, 10);
  const max = Math.max(1, ...rows.map((row) => num(row[series?.key])));
  return (
    <div className="space-y-1.5">
      {rows.map((row, index) => {
        const value = num(row[series?.key]);
        return (
          <div
            key={`${row.label}-${index}`}
            className="flex items-center gap-2"
            title={`${chartLabel(row.label)}: ${chartValue(value, format)}`}
          >
            <span className="w-[36%] shrink-0 truncate text-[9.5px] font-medium text-ink/65 dark:text-fog/65">
              {truncateLabel(row.label, 20)}
            </span>
            <span className="relative h-3.5 min-w-0 flex-1 overflow-hidden rounded-full bg-ink/[0.045] dark:bg-fog/[0.07]">
              <span
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${Math.max(2, (value / max) * 100)}%`, background: colorFor(index) }}
              />
            </span>
            <span className="w-9 shrink-0 text-right text-[9.5px] font-semibold tabular-nums text-ink dark:text-fog">
              {chartValue(value, format, true)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ScatterChart({ chart }: { chart: ChatChartData }) {
  const [hover, setHover] = useState<number | null>(null);
  const rows = chart.rows.filter(
    (row) => typeof row.x === "number" && typeof row.y === "number",
  );
  const xs = rows.map((row) => num(row.x));
  const ys = rows.map((row) => num(row.y));
  const minX = Math.min(...xs, 0);
  const maxX = Math.max(...xs, 1);
  const maxY = niceMax(Math.max(1, ...ys));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const xAt = (value: number) =>
    PAD.left + (maxX === minX ? innerW / 2 : ((value - minX) / (maxX - minX)) * innerW);
  const yAt = (value: number) => PAD.top + innerH - (value / maxY) * innerH;
  const format = formatFor(chart.series[0]);
  return (
    <div className="relative">
      {hover != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 w-max max-w-[200px] -translate-x-1/2 rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[10px] shadow-lg dark:border-fog/[0.12] dark:bg-[#241a44]"
          style={{ left: `${Math.min(88, Math.max(12, (xAt(num(rows[hover]?.x)) / W) * 100))}%` }}
        >
          <p className="font-bold text-ink dark:text-fog">{chartLabel(String(rows[hover]?.label ?? ""))}</p>
          <p className="text-ink/60 dark:text-fog/60">
            {chart.x_label || "x"}: {chartValue(num(rows[hover]?.x), "number", true)}
          </p>
          <p className="text-ink/60 dark:text-fog/60">
            {chart.series[0]?.label || "y"}: {chartValue(num(rows[hover]?.y), format)}
          </p>
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title} scatter chart`} className="h-auto w-full">
        <title>{chart.title}</title>
        {[0, 0.25, 0.5, 0.75, 1].map((tick, index) => {
          const value = maxY * tick;
          return (
            <g key={index}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={yAt(value)}
                y2={yAt(value)}
                stroke="currentColor"
                strokeOpacity={index === 0 ? 0.18 : 0.07}
              />
              <text x={PAD.left - 5} y={yAt(value) + 3} textAnchor="end" fontSize={8.5} fill="currentColor" opacity={0.45}>
                {chartValue(value, format, true)}
              </text>
            </g>
          );
        })}
        {[0, 0.5, 1].map((tick, index) => {
          const value = minX + (maxX - minX) * tick;
          return (
            <text
              key={`x-${index}`}
              x={xAt(value)}
              y={H - 10}
              textAnchor={index === 0 ? "start" : index === 2 ? "end" : "middle"}
              fontSize={8}
              fill="currentColor"
              opacity={0.45}
            >
              {chartValue(value, "number", true)}
            </text>
          );
        })}
        {rows.map((row, index) => (
          <circle
            key={`${row.label}-${index}`}
            cx={xAt(num(row.x))}
            cy={yAt(num(row.y))}
            r={hover === index ? 4 : 3}
            fill={colorFor(index)}
            opacity={hover == null || hover === index ? 1 : 0.5}
            onPointerEnter={() => setHover(index)}
            onPointerLeave={() => setHover(null)}
            onClick={() => setHover(index)}
          />
        ))}
        <text x={W / 2} y={H - 1} textAnchor="middle" fontSize={8} fill="currentColor" opacity={0.45}>
          {chart.x_label || "x"}
        </text>
        <text x={PAD.left} y={PAD.top + 2} textAnchor="start" fontSize={8} fill="currentColor" opacity={0.45}>
          {chart.series[0]?.label || "y"}
        </text>
      </svg>
    </div>
  );
}

function BubbleChart({ chart }: { chart: ChatChartData }) {
  const [hover, setHover] = useState<number | null>(null);
  const rows = chart.rows.filter(
    (row) => typeof row.x === "number" && typeof row.y === "number" && typeof row.size === "number",
  );
  const xs = rows.map((row) => num(row.x));
  const ys = rows.map((row) => num(row.y));
  const sizes = rows.map((row) => Math.max(0, num(row.size)));
  const minX = Math.min(...xs, 0);
  const maxX = Math.max(...xs, 1);
  const maxY = niceMax(Math.max(1, ...ys));
  const maxSize = Math.max(1, ...sizes);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const xAt = (value: number) =>
    PAD.left + (maxX === minX ? innerW / 2 : ((value - minX) / (maxX - minX)) * innerW);
  const yAt = (value: number) => PAD.top + innerH - (value / maxY) * innerH;
  const radius = (size: number) => 3 + Math.sqrt(size / maxSize) * 11;
  const format = formatFor(chart.series[0]);
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title} bubble chart`} className="h-auto w-full">
        <title>{chart.title}</title>
        {[0, 0.25, 0.5, 0.75, 1].map((tick, index) => (
          <g key={index}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={yAt(maxY * tick)}
              y2={yAt(maxY * tick)}
              stroke="currentColor"
              strokeOpacity={index === 0 ? 0.18 : 0.07}
            />
            <text x={PAD.left - 5} y={yAt(maxY * tick) + 3} textAnchor="end" fontSize={8.5} fill="currentColor" opacity={0.45}>
              {chartValue(maxY * tick, format, true)}
            </text>
          </g>
        ))}
        {rows.map((row, index) => (
          <g key={`${row.label}-${index}`}>
            <circle
              cx={xAt(num(row.x))}
              cy={yAt(num(row.y))}
              r={radius(sizes[index])}
              fill={colorFor(index)}
              fillOpacity={hover == null || hover === index ? 0.55 : 0.2}
              stroke={colorFor(index)}
              strokeWidth={hover === index ? 2 : 1}
              onPointerEnter={() => setHover(index)}
              onPointerLeave={() => setHover(null)}
            >
              <title>
                {`${chartLabel(String(row.label ?? ""))} — ${chart.x_label || "x"}: ${chartValue(
                  num(row.x), "number", true,
                )}, ${chart.series[0]?.label || "y"}: ${chartValue(num(row.y), format)}, size: ${chartValue(
                  num(row.size), "number", true,
                )}`}
              </title>
            </circle>
            {rows.length <= 6 && (
              <text
                x={Math.min(W - 26, Math.max(26, xAt(num(row.x))))}
                y={yAt(num(row.y)) - radius(sizes[index]) - 3}
                textAnchor="middle"
                fontSize={7}
                fill="currentColor"
                opacity={0.55}
              >
                {truncateLabel(row.label, 10)}
              </text>
            )}
          </g>
        ))}
        <text x={W / 2} y={H - 1} textAnchor="middle" fontSize={8} fill="currentColor" opacity={0.45}>
          {chart.x_label || "x"}
        </text>
        <text x={PAD.left} y={PAD.top + 2} textAnchor="start" fontSize={8} fill="currentColor" opacity={0.45}>
          {chart.series[0]?.label || "y"}
        </text>
      </svg>
    </div>
  );
}

function HeatmapChart({ chart }: { chart: ChatChartData }) {
  const xValues =
    chart.x_values?.length
      ? chart.x_values
      : Array.from(new Set(chart.rows.map((row) => String(row.x ?? "")))).sort();
  const yValues =
    chart.y_values?.length
      ? chart.y_values
      : Array.from(new Set(chart.rows.map((row) => String(row.y ?? ""))));
  const cells = new Map<string, number>();
  for (const row of chart.rows) {
    cells.set(`${String(row.x ?? "")}|${String(row.y ?? "")}`, num(row.value));
  }
  const values = Array.from(cells.values());
  const max = Math.max(1, ...values);
  const left = 30;
  const top = 6;
  const right = 4;
  const bottom = 22;
  const innerW = W - left - right;
  const innerH = H - top - bottom;
  const cellW = innerW / Math.max(1, xValues.length);
  const cellH = innerH / Math.max(1, yValues.length);
  const total = values.reduce((sum, value) => sum + value, 0);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title} heatmap`} className="h-auto w-full">
        <title>{chart.title}</title>
        {yValues.map((day, yIndex) => (
          <text
            key={`day-${day}`}
            x={left - 4}
            y={top + yIndex * cellH + cellH / 2 + 3}
            textAnchor="end"
            fontSize={7.5}
            fill="currentColor"
            opacity={0.5}
          >
            {day}
          </text>
        ))}
        {xValues.map((hour, xIndex) => (
          <text
            key={`hour-${hour}`}
            x={left + xIndex * cellW + cellW / 2}
            y={H - 10}
            textAnchor="middle"
            fontSize={7}
            fill="currentColor"
            opacity={0.5}
          >
            {xIndex % 3 === 0 ? `${hour}` : ""}
          </text>
        ))}
        <text x={W / 2} y={H - 1} textAnchor="middle" fontSize={7.5} fill="currentColor" opacity={0.45}>
          {chart.x_label || "Hour"}
        </text>
        {yValues.map((day, yIndex) =>
          xValues.map((hour, xIndex) => {
            const value = cells.get(`${hour}|${day}`) ?? 0;
            const intensity = max > 0 ? value / max : 0;
            return (
              <rect
                key={`cell-${day}-${hour}`}
                x={left + xIndex * cellW + 0.5}
                y={top + yIndex * cellH + 0.5}
                width={Math.max(1, cellW - 1)}
                height={Math.max(1, cellH - 1)}
                rx={1.5}
                fill="#3D1D6E"
                fillOpacity={value === 0 ? 0.05 : 0.12 + 0.85 * intensity}
              >
                <title>{`${day} ${hour}:00 — ${chartValue(value, "number")} reviews`}</title>
              </rect>
            );
          }),
        )}
      </svg>
      <div className="mt-1 flex items-center justify-end gap-1 text-[8.5px] text-ink/45 dark:text-fog/45">
        <span>Low</span>
        {[0.15, 0.35, 0.55, 0.75, 1].map((step) => (
          <span
            key={step}
            className="h-2 w-3 rounded-[1px] bg-deep-violet"
            style={{ opacity: step }}
            aria-hidden
          />
        ))}
        <span>High</span>
        <span className="ml-2 tabular-nums">{chartValue(total, "number", true)} total</span>
      </div>
    </div>
  );
}

function RadarChart({ chart }: { chart: ChatChartData }) {
  const rows = chart.rows.slice(0, 8);
  const series = chart.series;
  const max = niceMax(
    Math.max(1, ...rows.flatMap((row) => series.map((s) => num(row[s.key])))),
  );
  const S = 220;
  const cx = S / 2;
  const cy = S / 2;
  const radius = S / 2 - 34;
  const angle = (index: number) => (Math.PI * 2 * index) / Math.max(1, series.length) - Math.PI / 2;
  const point = (value: number, index: number) => {
    const r = (Math.max(0, value) / max) * radius;
    return { x: cx + r * Math.cos(angle(index)), y: cy + r * Math.sin(angle(index)) };
  };
  return (
    <div>
      <svg
        viewBox={`0 0 ${S} ${S}`}
        role="img"
        aria-label={`${chart.title} radar chart`}
        className="mx-auto h-auto w-full max-w-[260px]"
      >
        <title>{chart.title}</title>
        {[0.25, 0.5, 0.75, 1].map((step) => (
          <polygon
            key={step}
            points={series
              .map((_, index) => {
                const p = point(max * step, index);
                return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
              })
              .join(" ")}
            fill="none"
            stroke="currentColor"
            strokeOpacity={0.1}
            strokeWidth={1}
          />
        ))}
        {series.map((metric, index) => {
          const p = point(max, index);
          return (
            <g key={`axis-${metric.key}`}>
              <line x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="currentColor" strokeOpacity={0.08} />
              <text
                x={cx + (p.x - cx) * 1.16}
                y={cy + (p.y - cy) * 1.16 + 3}
                textAnchor={Math.abs(p.x - cx) < 4 ? "middle" : p.x > cx ? "start" : "end"}
                fontSize={7.5}
                fill="currentColor"
                opacity={0.55}
              >
                {truncateLabel(metric.label, 12)}
              </text>
            </g>
          );
        })}
        {rows.map((row, rowIndex) => {
          const polygon = series
            .map((metric, index) => {
              const p = point(num(row[metric.key]), index);
              return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
            })
            .join(" ");
          const color = colorFor(rowIndex);
          return (
            <polygon
              key={`${row.label}-${rowIndex}`}
              points={polygon}
              fill={color}
              fillOpacity={0.12}
              stroke={color}
              strokeWidth={1.8}
              strokeLinejoin="round"
            >
              <title>{`${chartLabel(row.label)} — ${series
                .map((metric) => `${metric.label}: ${chartValue(num(row[metric.key]), metric.format)}`)
                .join(", ")}`}</title>
            </polygon>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        {rows.map((row, index) => (
          <span
            key={`${row.label}-legend-${index}`}
            className="inline-flex items-center gap-1.5 text-[9.5px] font-semibold text-ink/60 dark:text-fog/60"
          >
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: colorFor(index) }}
              aria-hidden
            />
            {truncateLabel(row.label, 16)}
          </span>
        ))}
      </div>
    </div>
  );
}

function FunnelChart({ chart }: { chart: ChatChartData }) {
  const series = chart.series[0];
  const rows = chart.rows.slice(0, 8);
  const max = Math.max(1, ...rows.map((row) => num(row[series?.key])));
  const left = 58;
  const right = 46;
  const top = 8;
  const bottom = 6;
  const innerW = W - left - right;
  const innerH = H - top - bottom;
  const stageH = innerH / Math.max(1, rows.length);
  const format = formatFor(series);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title} funnel chart`} className="h-auto w-full">
      <title>{chart.title}</title>
      {rows.map((row, index) => {
        const value = Math.max(0, num(row[series?.key]));
        const next = index + 1 < rows.length ? Math.max(0, num(rows[index + 1][series?.key ?? ""])) : value;
        const wTop = (value / max) * innerW;
        const wBottom = (next / max) * innerW;
        const y = top + index * stageH;
        const cx = left + innerW / 2;
        return (
          <g key={`${row.label}-${index}`}>
            <polygon
              points={[
                `${cx - wTop / 2},${y + 1}`,
                `${cx + wTop / 2},${y + 1}`,
                `${cx + wBottom / 2},${y + stageH - 3}`,
                `${cx - wBottom / 2},${y + stageH - 3}`,
              ].join(" ")}
              fill={colorFor(index)}
              fillOpacity={0.78}
            >
              <title>{`${chartLabel(row.label)}: ${chartValue(value, format)}`}</title>
            </polygon>
            <text x={left - 4} y={y + stageH / 2 + 3} textAnchor="end" fontSize={7.5} fill="currentColor" opacity={0.55}>
              {truncateLabel(row.label, 10)}
            </text>
            <text x={W - right + 4} y={y + stageH / 2 + 3} fontSize={8} fontWeight={700} fill="currentColor" opacity={0.75}>
              {chartValue(value, format, true)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function GaugeChart({ chart }: { chart: ChatChartData }) {
  const series = chart.series[0];
  const value = num(chart.rows[0]?.[series?.key ?? "value"]);
  const max = chart.max_value && chart.max_value > 0 ? chart.max_value : niceMax(Math.max(1, value * 1.2));
  const ratio = Math.min(1, Math.max(0, value / max));
  const cx = W / 2;
  const cy = H / 2 + 24;
  const radius = Math.min(W, H * 1.35) / 2 - 26;
  const start = -180;
  const end = 0;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title} gauge`} className="h-auto w-full">
        <title>{chart.title}</title>
        <path d={arcPath(cx, cy, radius, radius - 16, start, end)} fill="currentColor" fillOpacity={0.07} />
        <path
          d={arcPath(cx, cy, radius, radius - 16, start, start + (end - start) * ratio)}
          fill={colorFor(0)}
          fillOpacity={0.85}
        />
        <text x={cx} y={cy - 16} textAnchor="middle" fontSize={26} fontWeight={700} fill="currentColor">
          {chartValue(value, series?.format)}
        </text>
        <text x={cx} y={cy + 2} textAnchor="middle" fontSize={8.5} fill="currentColor" opacity={0.5}>
          {series?.label || "Value"} · max {chartValue(max, series?.format, true)}
        </text>
      </svg>
    </div>
  );
}

function TreemapChart({ chart }: { chart: ChatChartData }) {
  const series = chart.series[0];
  const rows = chart.rows
    .map((row) => ({ label: String(row.label ?? ""), value: Math.max(0, num(row[series?.key])) }))
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 24);
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const left = 4;
  const top = 4;
  const width = W - 8;
  const height = H - 8;
  const format = formatFor(series);

  interface Box {
    label: string;
    value: number;
    x: number;
    y: number;
    w: number;
    h: number;
  }
  const boxes: Box[] = [];
  let remaining = [...rows];
  let x = left;
  let y = top;
  let w = width;
  let h = height;
  while (remaining.length > 0) {
    const sum = remaining.reduce((acc, row) => acc + row.value, 0);
    if (sum <= 0) break;
    const horizontal = w >= h;
    const first = remaining.shift()!;
    if (remaining.length === 0) {
      boxes.push({ ...first, x, y, w, h });
      break;
    }
    if (horizontal) {
      const slice = Math.max(1, (first.value / sum) * w);
      boxes.push({ ...first, x, y, w: slice, h });
      x += slice;
      w -= slice;
    } else {
      const slice = Math.max(1, (first.value / sum) * h);
      boxes.push({ ...first, x, y, w, h: slice });
      y += slice;
      h -= slice;
    }
  }

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title} treemap`} className="h-auto w-full">
        <title>{chart.title}</title>
        <defs>
          {boxes.map((box, index) => (
            <clipPath key={`clip-${index}`} id={`${chart.id}-clip-${index}`}>
              <rect
                x={box.x + 2}
                y={box.y + 2}
                width={Math.max(0, box.w - 4)}
                height={Math.max(0, box.h - 4)}
              />
            </clipPath>
          ))}
        </defs>
        {boxes.map((box, index) => (
          <g key={`${box.label}-${index}`}>
            <rect
              x={box.x + 1}
              y={box.y + 1}
              width={Math.max(1, box.w - 2)}
              height={Math.max(1, box.h - 2)}
              rx={3}
              fill={colorFor(index)}
              fillOpacity={0.82}
            >
              <title>{`${chartLabel(box.label)}: ${chartValue(box.value, format)} (${(
                (box.value / Math.max(1, total)) * 100
              ).toFixed(1)}%)`}</title>
            </rect>
            {box.h >= 16 && (
              <g clipPath={`url(#${chart.id}-clip-${index})`}>
                <text x={box.x + 5} y={box.y + 12} fontSize={7.5} fill="#fff" opacity={0.92}>
                  {truncateLabel(box.label, Math.max(4, Math.floor((box.w - 10) / 4.4)))}
                </text>
                {box.h >= 30 && (
                  <text x={box.x + 5} y={box.y + 22} fontSize={8.5} fontWeight={700} fill="#fff">
                    {chartValue(box.value, format, true)}
                  </text>
                )}
              </g>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}


export default function ChatChart({ chart }: { chart: ChatChartData }) {
  const kpis = (chart.kpis ?? []).filter((kpi) => kpi.value != null);
  const hasChart = chart.type !== "kpi" && chart.rows.length > 0;
  return (
    <figure className="overflow-hidden rounded-xl border border-ink/[0.08] bg-white p-3 text-ink shadow-sm dark:border-fog/[0.1] dark:bg-[#1d1636] dark:text-fog">
      <figcaption className="mb-2">
        <p className="text-[12.5px] font-bold leading-snug text-ink dark:text-fog">{chart.title}</p>
        {chart.subtitle && (
          <p className="mt-0.5 text-[10px] leading-snug text-ink/45 dark:text-fog/45">{chart.subtitle}</p>
        )}
      </figcaption>

      {kpis.length > 0 && (
        <div
          className={`mb-2 grid gap-1.5 ${
            kpis.length >= 3 && kpis.length % 3 === 0
              ? "grid-cols-3"
              : kpis.length > 1
                ? "grid-cols-2"
                : "grid-cols-1"
          }`}
        >
          {kpis.map((kpi) => (
            <KpiCard
              key={kpi.label}
              label={kpi.label}
              value={kpi.value}
              format={kpi.format}
              delta={kpi.delta}
            />
          ))}
        </div>
      )}

      {hasChart && chart.type === "donut" && <DonutChart chart={chart} />}
      {hasChart && chart.type === "pie" && <DonutChart chart={chart} />}
      {hasChart && chart.type === "ranking" && <RankingChart chart={chart} />}
      {hasChart && chart.type === "scatter" && <ScatterChart chart={chart} />}
      {hasChart && chart.type === "bubble" && <BubbleChart chart={chart} />}
      {hasChart && chart.type === "heatmap" && <HeatmapChart chart={chart} />}
      {hasChart && chart.type === "radar" && <RadarChart chart={chart} />}
      {hasChart && chart.type === "funnel" && <FunnelChart chart={chart} />}
      {hasChart && chart.type === "gauge" && <GaugeChart chart={chart} />}
      {hasChart && chart.type === "treemap" && <TreemapChart chart={chart} />}
      {hasChart &&
        ![
          "donut",
          "pie",
          "ranking",
          "scatter",
          "bubble",
          "heatmap",
          "radar",
          "funnel",
          "gauge",
          "treemap",
        ].includes(chart.type) && <AxisChart chart={chart} />}
      {!hasChart && chart.type !== "kpi" && (
        <p className="py-6 text-center text-[11px] text-ink/40 dark:text-fog/40">
          No data for this period.
        </p>
      )}
      {chart.type === "kpi" && kpis.length === 0 && (
        <p className="py-3 text-center text-[11px] text-ink/40 dark:text-fog/40">
          No summary available.
        </p>
      )}

      <p className="mt-2 text-[8.5px] font-semibold uppercase tracking-[0.08em] text-ink/30 dark:text-fog/30">
        Your live business data
        {chart.window_days ? ` · last ${chart.window_days} days` : ""}
      </p>
    </figure>
  );
}
