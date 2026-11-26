"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";

function fmtDelta(n: number | null | undefined, suffix = ""): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  const val = Math.abs(n) % 1 === 0 ? n.toFixed(0) : n.toFixed(1);
  return `${sign}${val}${suffix}`;
}

export default function PeriodDeltaCards({ subjects, mainKey, days }: { subjects: ComparisonSubject[]; mainKey?: string | null; days: number | null }) {
  const { t } = useI18n();
  const b = t.benchmark;
  if (!days) return null;
  const rows = subjects.filter((s) => s.available && (s.key === mainKey || s.kind === "own" || typeof s.metrics.period_reviews === "number"));
  if (rows.length === 0) return null;
  const hasAnyDelta = rows.some((s) => s.metrics.period_reviews_delta != null || s.metrics.period_avg_rating_delta != null);
  if (!hasAnyDelta) return null;

  return (
    <section aria-labelledby="period-delta-title" className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5">
      <h2 id="period-delta-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.periodDeltaTitle || "Period change"}</h2>
      <p className="mt-1 text-[11px] text-[#3B2D5E]">{(b.periodDeltaDesc || "Compared with previous same-length period.")} ({days}d)</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-left text-[11px]">
          <thead>
            <tr className="border-b border-[var(--ui-line)] text-[#3B2D5E]">
              <th className="px-2 py-2 font-semibold">{b.compare.business}</th>
              <th className="px-2 py-2 font-semibold">{b.metricVelocity}</th>
              <th className="px-2 py-2 font-semibold">Δ vs prev</th>
              <th className="px-2 py-2 font-semibold">{b.metricRating}</th>
              <th className="px-2 py-2 font-semibold">Δ vs prev</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const own = s.key === mainKey;
              const rd = s.metrics.period_reviews_delta;
              const ad = s.metrics.period_avg_rating_delta;
              return (
                <tr key={s.key} className="border-b border-[var(--ui-line)] last:border-0">
                  <td className={`px-2 py-2 ${own ? "font-bold text-[#14101F]" : "text-[#3B2D5E]"}`}>{s.name || "—"}</td>
                  <td className="px-2 py-2 font-mono text-[#3B2D5E]">{s.metrics.period_reviews ?? "—"}</td>
                  <td className={`px-2 py-2 font-mono font-semibold ${rd == null ? "text-[#8A8496]" : rd > 0 ? "text-[#116631]" : rd < 0 ? "text-[#B3123A]" : "text-[#3B2D5E]"}`}>{fmtDelta(rd)}</td>
                  <td className="px-2 py-2 font-mono text-[#3B2D5E]">{s.metrics.period_avg_rating ?? "—"}</td>
                  <td className={`px-2 py-2 font-mono font-semibold ${ad == null ? "text-[#8A8496]" : ad > 0 ? "text-[#116631]" : ad < 0 ? "text-[#B3123A]" : "text-[#3B2D5E]"}`}>{fmtDelta(ad)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}