"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { PressureRow } from "@/lib/api-benchmark";

export default function CompetitorPressureCard({ rows }: { rows: PressureRow[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  if (!rows.length) return null;
  const top = rows.slice(0, 4);

  return (
    <section aria-labelledby="pressure-title" className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5">
      <h2 id="pressure-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.pressureTitle || "Competitor pressure"}</h2>
      <p className="mt-1 text-[11px] text-[#3B2D5E]">{b.pressureDesc || "Which competitors put the most pressure on your branch."}</p>
      <div className="mt-4 space-y-3">
        {top.map((row) => (
          <div key={row.key} className="rounded-[8px] border border-[var(--ui-line)] bg-[#FAFAFB] p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="min-w-0 truncate text-[12px] font-bold text-[#14101F]" title={row.name ?? undefined}>{row.name || "—"}</p>
              <span className="shrink-0 rounded-full bg-[#3D1D6E]/10 px-2 py-0.5 text-[10px] font-bold text-[#3D1D6E]">
                {b.pressureScore || "Pressure"} {Math.round(row.score)}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#EFEDF2]" aria-hidden>
              <div className="h-full rounded-full bg-[#3D1D6E]" style={{ width: `${Math.max(0, Math.min(100, row.score))}%` }} />
            </div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[#3B2D5E]">
              <span>{b.pressureConfidence || "Confidence"} {Math.round(row.confidence * 100)}%</span>
              <span>{row.distance_km == null ? "Distance —" : `${row.distance_km.toFixed(1)} km`}</span>
              <span>{b.metricRating} {row.rating_gap == null ? "—" : `${row.rating_gap > 0 ? "+" : ""}${row.rating_gap.toFixed(1)}`}</span>
              <span>{b.metricVelocity} {row.velocity_gap == null ? "—" : `${row.velocity_gap > 0 ? "+" : ""}${row.velocity_gap.toFixed(1)}`}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}