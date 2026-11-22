"use client";

/**
 * Inline-SVG trend lines from /benchmark/history — one line per subject.
 * No chart library: two polylines-worth of math, question-as-title, and no
 * animation so prefers-reduced-motion needs no special case.
 */
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { HistoryPoint, SubjectHistory } from "@/lib/api-benchmark";

const COLORS = ["#3D1D6E", "#B0338A", "#FF4F6E", "#116631", "#8A6100", "#0B5CAD"];
const W = 320, H = 96, PAD = 8;

function perMonth(points: HistoryPoint[]): { x: number; y: number }[] {
  const dated = points
    .filter((p) => p.at && p.reviews != null)
    .map((p) => ({ t: new Date(p.at as string).getTime(), reviews: p.reviews as number }))
    .sort((a, b) => a.t - b.t);
  const out: { x: number; y: number }[] = [];
  for (let i = 1; i < dated.length; i++) {
    const days = (dated[i].t - dated[i - 1].t) / 86_400_000;
    if (days <= 0) continue;
    // Google review removals can make a window net-negative; velocity can't be.
    out.push({ x: dated[i].t, y: Math.max(0, ((dated[i].reviews - dated[i - 1].reviews) / days) * 30) });
  }
  return out;
}

function ratingPoints(points: HistoryPoint[]): { x: number; y: number }[] {
  return points
    .filter((p) => p.at && p.rating != null)
    .map((p) => ({ x: new Date(p.at as string).getTime(), y: p.rating as number }))
    .sort((a, b) => a.x - b.x);
}

function scale(
  series: { x: number; y: number }[],
  xDomain: { x0: number; x1: number },
  yMin: number,
  yMax: number
): string {
  if (series.length === 0) return "";
  // Clamped to 1ms so all-equal timestamps can't divide by zero.
  const spanX = Math.max(xDomain.x1 - xDomain.x0, 1);
  const span = Math.max(yMax - yMin, 0.0001);
  return series
    .map((p) => {
      const px = PAD + ((p.x - xDomain.x0) / spanX) * (W - 2 * PAD);
      const py = H - PAD - ((p.y - yMin) / span) * (H - 2 * PAD);
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

export default function TrendChart({ history, title }: { history: SubjectHistory[]; title: string }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const live = history.filter((s) => s.points.length >= 2);
  if (live.length === 0) return null;
  // One shared x-domain: a competitor with two snapshots must render on the
  // same time scale as a branch with a year of history, or comparison lies.
  const xs = live.flatMap((s) => ratingPoints(s.points).map((p) => p.x));
  if (xs.length === 0) return null;
  const xDomain = { x0: Math.min(...xs), x1: Math.max(...xs) };
  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{title}</h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {([
          { key: "rating", label: b.trendRatingLabel, series: live.map((s) => ratingPoints(s.points)), yMin: 1, yMax: 5 },
          { key: "velocity", label: b.trendVelocityLabel, series: live.map((s) => perMonth(s.points)), yMin: 0, yMax: Math.max(1, ...live.flatMap((s) => perMonth(s.points).map((p) => p.y))) },
        ] as const).map((chart) => (
          <figure key={chart.key} className="m-0">
            <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" role="img" aria-label={`${chart.label}: ${title}`}>
              <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--ui-line)" strokeWidth="1" />
              {chart.series.map((series, i) => (
                <polyline
                  key={i}
                  points={scale(series, xDomain, chart.yMin, chart.yMax)}
                  fill="none"
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth="2"
                  strokeLinejoin="round"
                  strokeDasharray={i % 2 === 1 ? "6 4" : undefined}
                />
              ))}
            </svg>
            <figcaption className="mt-1 text-[11px] text-[#3B2D5E]">{chart.label}</figcaption>
          </figure>
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#3B2D5E]">
        {live.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2 w-4 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            {s.name ?? s.key}
          </li>
        ))}
      </ul>
    </section>
  );
}
