"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { CompareDistribution } from "@/lib/api-benchmark";

/** Best / Median / Worst / Gap bars for the four headline metrics. */
export default function DistributionStrip({ distribution }: { distribution: CompareDistribution }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const rows: Array<[keyof CompareDistribution, string]> = [
    ["avg_rating", b.metricRating],
    ["reviews_per_month", b.metricVelocity],
    ["total_reviews", b.metricTotalReviews],
    ["positive_pct", b.metricSentiment],
  ];
  const visible = rows.filter(([key]) => distribution[key]);
  if (visible.length === 0) return null;
  const fmt = (key: string, v: number) =>
    key === "avg_rating" ? v.toFixed(1) : key === "positive_pct" ? `${v.toFixed(0)}%` : String(Math.round(v));
  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.distributionTitle}</h2>
      <div className="mt-3 space-y-3">
        {visible.map(([key, label]) => {
          const row = distribution[key];
          const scale = row.max_scale ?? (row.best.value || 1);
          return (
            <div key={key}>
              <div className="flex items-center justify-between text-[11px] text-[#3B2D5E]">
                <span className="font-bold text-[#14101F]">{label}</span>
                <span>{b.gapLine.replace("{gap}", fmt(key, row.gap))}</span>
              </div>
              {([
                [b.distBest, row.best, "#116631"],
                [b.distMedian, { name: "", value: row.median }, "#8A6100"],
                [b.distWorst, row.worst, "#B3123A"],
              ] as const).map(([tag, cell, color]) => (
                <div key={tag} className="mt-1 flex items-center gap-2">
                  <span className="w-12 shrink-0 text-[10px] font-bold uppercase text-[#3B2D5E]">{tag}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded-full bg-[#F1F2F5]">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.max(2, Math.min(100, (cell.value / scale) * 100))}%`, background: color }}
                    />
                  </div>
                  <span className="w-28 shrink-0 truncate text-[11px] text-[#3B2D5E]">
                    {cell.name ? `${cell.name} · ` : ""}{fmt(key, cell.value)}
                  </span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}
