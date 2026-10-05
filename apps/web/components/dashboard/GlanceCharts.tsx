"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchTimeseries, type TimeseriesPoint } from "@/lib/api-analytics";

function fmtDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en", { month: "short", day: "numeric" });
}

function MiniArea({ values, color, max }: { values: number[]; color: string; max?: number }) {
  const w = 260;
  const h = 64;
  const top = Math.max(...values, 1);
  const m = max ?? top;
  const pts = values.map((v, i) => {
    const x = values.length === 1 ? w / 2 : (i / (values.length - 1)) * w;
    const y = h - 4 - (Math.max(0, v) / m) * (h - 10);
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${w} ${h} L0 ${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-16 w-full" preserveAspectRatio="none" aria-hidden>
      <path d={area} fill={color} opacity={0.15} />
      <path d={line} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}

export default function GlanceCharts() {
  const [points, setPoints] = useState<TimeseriesPoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ts = await fetchTimeseries(30, null);
        if (!cancelled) setPoints(ts ?? []);
      } catch {
        /* leave empty */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const totalMsgs = useMemo(() => points.reduce((s, p) => s + (p.messages ?? p.replies_count ?? 0), 0), [points]);
  const totalReviews = useMemo(() => points.reduce((s, p) => s + p.reviews_count, 0), [points]);
  const avgRating = useMemo(() => {
    const rated = points.filter((p) => p.avg_rating > 0);
    if (!rated.length) return null;
    return rated.reduce((s, p) => s + p.avg_rating, 0) / rated.length;
  }, [points]);

  const labels = [fmtDay(points[0]?.date ?? ""), fmtDay(points[points.length - 1]?.date ?? "")];

  const series: { title: string; value: string; sub: string; color: string; values: number[] }[] = [
    { title: "Messages", value: String(totalMsgs), sub: "last 30 days", color: "#7c3aed", values: points.map((p) => p.messages ?? p.replies_count ?? 0) },
    { title: "Reviews", value: String(totalReviews), sub: "last 30 days", color: "#059669", values: points.map((p) => p.reviews_count) },
    { title: "Avg rating", value: avgRating != null ? avgRating.toFixed(1) : "—", sub: "last 30 days", color: "#d97706", values: points.map((p) => p.avg_rating) },
  ];

  return (
    <section aria-label="Messages, reviews and ratings charts" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {series.map((s) => (
        <div key={s.title} className="rounded-2xl border border-ink/[0.06] bg-white/80 p-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/80">
          <div className="flex items-baseline justify-between">
            <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">{s.title}</p>
            <p className="text-[11px] text-ink/40">{s.sub}</p>
          </div>
          <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{s.value}</p>
          <MiniArea values={s.values.length ? s.values : [0]} color={s.color} max={s.title === "Avg rating" ? 5 : undefined} />
          <div className="mt-1 flex justify-between text-[10px] text-ink/35">
            <span>{labels[0]}</span>
            <span>{labels[1]}</span>
          </div>
        </div>
      ))}
    </section>
  );
}
