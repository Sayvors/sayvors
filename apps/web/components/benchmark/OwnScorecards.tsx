"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import { median } from "@/lib/benchmark-stats";
import type { ComparisonSubject } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

/** One scorecard per own branch + a variance flag (>35% off the own median). */
export default function OwnScorecards({ subjects }: { subjects: ComparisonSubject[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const own = subjects.filter((s) => s.kind === "own" && s.available);
  if (own.length === 0) return null;
  const ratings = own.map((s) => s.metrics.avg_rating).filter((v): v is number => v != null);
  const ownMedian = median(ratings);
  return (
    <section className="mt-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.ownScorecardsTitle}</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {own.map((s) => {
          const rating = s.metrics.avg_rating;
          const velocity = s.metrics.reviews_last_month ?? (s.metrics.reviews_last_year != null ? Math.round(s.metrics.reviews_last_year / 12) : null);
          const fiveShare = s.metrics.total_ratings ? Math.round(((s.metrics.five_star ?? 0) / s.metrics.total_ratings) * 100) : null;
          const variance = rating != null && ownMedian != null && ownMedian > 0
            ? Math.abs(rating - ownMedian) / ownMedian : null;
          const flagged = variance != null && variance > 0.35;
          return (
            <article key={s.key} className={`rounded-[8px] border bg-white p-3 ${flagged ? "border-[#B3123A]" : "border-[var(--ui-line)]"}`}>
              <header className="flex items-center justify-between">
                <h3 className="text-[13px] font-bold text-[#14101F]">{s.name}</h3>
                {flagged ? (
                  <span className={`rounded-full bg-[#FDE8EC] px-2 py-0.5 text-[10px] font-bold text-[#B3123A] ${FOCUS}`}>
                    {b.varianceFlag.replace("{pct}", String(Math.round((variance ?? 0) * 100)))}
                  </span>
                ) : null}
              </header>
              <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div><dt className="text-[10px] uppercase text-[#3B2D5E]">{b.metricRating}</dt><dd className="text-[15px] font-bold text-[#14101F]">{rating?.toFixed(1) ?? "—"}</dd></div>
                <div><dt className="text-[10px] uppercase text-[#3B2D5E]">{b.metricVelocityShort}</dt><dd className="text-[15px] font-bold text-[#14101F]">{velocity ?? "—"}</dd></div>
                <div><dt className="text-[10px] uppercase text-[#3B2D5E]">{b.metricFiveStar}</dt><dd className="text-[15px] font-bold text-[#14101F]">{fiveShare != null ? `${fiveShare}%` : "—"}</dd></div>
              </dl>
              {s.facts.top_problems.length > 0 ? (
                <p className="mt-2 text-[11px] text-[#3B2D5E]">{b.topProblemLine.replace("{problem}", s.facts.top_problems[0])}</p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
