"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import { median } from "@/lib/benchmark-stats";
import type { ComparisonSubject, HistoryPoint } from "@/lib/api-benchmark";
import Sparkline from "@/components/benchmark/Sparkline";

// One-sided on purpose: a branch above the own-set median is healthy, so the
// flag fires only when a rating trails the median by more than 35%.
const VARIANCE_FLAG_THRESHOLD = 0.35;

/** One scorecard per own branch + a variance flag (>35% off the own median). */
export default function OwnScorecards({
  subjects,
  historyBySubject,
}: {
  subjects: ComparisonSubject[];
  /** Subject key → stored history points, for the inline rating sparkline. */
  historyBySubject?: Record<string, HistoryPoint[]>;
}) {
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
          const belowMedian = rating != null && ownMedian != null && ownMedian > 0 && rating < ownMedian;
          const variance = belowMedian ? (ownMedian - rating) / ownMedian : null;
          const flagged = variance != null && variance > VARIANCE_FLAG_THRESHOLD;
          const history = historyBySubject?.[s.key] ?? [];
          // Same drawable rule Sparkline applies: one rated point is a dot,
          // not a trend, so the whole caption row stays hidden.
          const drawableHistory = history.filter((p) => p.at && p.rating != null).length >= 2;
          return (
            <article key={s.key} className={`rounded-[8px] border bg-white p-3 ${flagged ? "border-[#B3123A]" : "border-[var(--ui-line)]"}`}>
              <header className="flex items-center justify-between">
                <h3 className="text-[13px] font-bold text-[#14101F]">{s.name}</h3>
                {flagged ? (
                  <span className="rounded-full bg-[#FDE8EC] px-2 py-0.5 text-[10px] font-bold text-[#B3123A]">
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
              {drawableHistory ? (
                <div className="mt-2 flex items-center gap-2 border-t border-[#EFEDF2] pt-2">
                  <Sparkline
                    points={history}
                    label={b.sparklineAria.replace("{name}", s.name ?? "")}
                  />
                  <p className="min-w-0 flex-1 truncate text-[10px] text-[#3B2D5E]">{b.trendRatingLabel}</p>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
