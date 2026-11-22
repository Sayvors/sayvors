"use client";

/**
 * 60×24 inline SVG polyline of a subject's rating history. No axes, no
 * library: it rides inside a scorecard as a glance signal, not a chart —
 * the real chart lives in TrendChart. Fixed 1–5 y-domain so a card's line
 * is never visually inflated by its own narrow range.
 */
import type { HistoryPoint } from "@/lib/api-benchmark";

const W = 60;
const H = 24;
const PAD = 2;
const STROKE = "#3D1D6E";

export default function Sparkline({ points, label }: { points: HistoryPoint[]; label: string }) {
  const series = points
    .filter((p) => p.at && p.rating != null)
    .map((p) => ({ t: new Date(p.at as string).getTime(), y: p.rating as number }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t);
  // One point is a dot, not a trend — drawing it would invent a shape.
  if (series.length < 2) return null;
  const spanX = Math.max(series[series.length - 1].t - series[0].t, 1);
  const polyline = series
    .map((p) => {
      const px = PAD + ((p.t - series[0].t) / spanX) * (W - 2 * PAD);
      const py = H - PAD - ((p.y - 1) / 4) * (H - 2 * PAD);
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="shrink-0">
      <title>{label}</title>
      <polyline
        points={polyline}
        fill="none"
        stroke={STROKE}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
