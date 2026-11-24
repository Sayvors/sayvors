"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject, HistoryPoint } from "@/lib/api-benchmark";
import {
  LOW_SAMPLE_THRESHOLD,
  formatHeadlineGap,
  formatHeadlineValue,
  headlineMetricValue,
  median,
} from "@/lib/benchmark-chart-data";
import Sparkline, { drawablePoints } from "@/components/benchmark/Sparkline";

const FOCUS =
  "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-[#3D1D6E]";
const VARIANCE_FLAG_THRESHOLD = 0.35;

function fill(template: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, value),
    template,
  );
}

/** One action scorecard per own branch. The comparison baseline is the
 *  owner's own median — a national average or an unrelated competitor is not
 *  a useful target for "which branch needs help this week?". */
export default function OwnScorecards({
  subjects,
  historyBySubject,
  mainKey,
}: {
  subjects: ComparisonSubject[];
  historyBySubject?: Record<string, HistoryPoint[]>;
  mainKey?: string | null;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const own = subjects.filter((subject) => subject.kind === "own" && subject.available);
  const ratings = own
    .map((subject) => headlineMetricValue(subject, "avg_rating"))
    .filter((value): value is number => value !== null);
  const velocities = own
    .map((subject) => headlineMetricValue(subject, "reviews_per_month"))
    .filter((value): value is number => value !== null);
  const ownMedian = median(ratings);
  const velocityMedian = median(velocities);

  if (own.length === 0) {
    return (
      <section aria-labelledby="own-scorecards-title" className="mt-4">
        <h2
          id="own-scorecards-title"
          className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]"
        >
          {b.ownScorecardsTitle}
        </h2>
        <p className="mt-3 rounded-[8px] border border-dashed border-[var(--ui-line)] bg-white px-4 py-6 text-center text-[12px] text-[#3B2D5E]">
          {b.ownScorecardsEmpty}
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="own-scorecards-title" className="mt-4">
      <header>
        <h2
          id="own-scorecards-title"
          className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]"
        >
          {b.ownScorecardsTitle}
        </h2>
        <p className="mt-1 text-[11px] text-[#3B2D5E]">{b.ownScorecardsSubtitle}</p>
      </header>

      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {own.map((subject) => {
          const rating = headlineMetricValue(subject, "avg_rating");
          const velocity = headlineMetricValue(subject, "reviews_per_month");
          const ratingCount = subject.metrics.total_ratings ?? subject.metrics.total_reviews ?? 0;
          const fiveShare = ratingCount > 0
            ? Math.round(((subject.metrics.five_star ?? 0) / ratingCount) * 100)
            : null;
          const lowSample = ratingCount < LOW_SAMPLE_THRESHOLD;
          const delta = rating !== null && ownMedian !== null ? rating - ownMedian : null;
          const variance = delta !== null && ownMedian !== null && ownMedian > 0
            ? (ownMedian - rating!) / ownMedian
            : null;
          const flagged = !lowSample && rating !== null && variance !== null && variance > VARIANCE_FLAG_THRESHOLD;
          const selected = subject.key === mainKey;
          const topProblem = subject.facts.top_problems[0] ?? null;
          const history = historyBySubject?.[subject.key] ?? [];
          const drawableHistory = drawablePoints(history).length >= 2;

          let gapLabel = b.noRatingYet;
          if (delta !== null) {
            gapLabel = Math.abs(delta) < 0.005
              ? b.branchMedianGapFlat
              : fill(delta > 0 ? b.branchMedianGapAbove : b.branchMedianGapBelow, {
                  gap: formatHeadlineGap("avg_rating", delta),
                });
          }

          let action = b.keepMomentum;
          if (rating === null) action = b.requestFirstReviews;
          else if (flagged || topProblem) action = b.reviewLowStars;
          else if (velocity !== null && velocityMedian !== null && velocity < velocityMedian) {
            action = b.askRecentCustomers;
          }

          return (
            <article
              key={subject.key}
              className={`flex h-full flex-col rounded-[8px] border bg-white p-4 ${
                flagged ? "border-[#B3123A]/45" : "border-[var(--ui-line)]"
              }`}
            >
              <header className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-[13px] font-bold text-[#14101F]" title={subject.name ?? undefined}>
                    {subject.name ?? subject.key}
                  </h3>
                  <p className="mt-0.5 font-mono text-[10px] text-[#6F6685]">n={ratingCount}</p>
                </div>
                <div className="flex flex-wrap justify-end gap-1">
                  {selected && (
                    <span className="rounded-full bg-[#3D1D6E] px-2 py-0.5 text-[9px] font-bold text-white">
                      {b.selectedBranch}
                    </span>
                  )}
                  {flagged && (
                    <span className="rounded-full bg-[#FDE8EC] px-2 py-0.5 text-[9px] font-bold text-[#B3123A]">
                      {b.needsAttention}
                    </span>
                  )}
                  {lowSample && (
                    <span className="rounded-full bg-[#FFF3D6] px-2 py-0.5 text-[9px] font-bold text-[#8A6100]">
                      {b.lowSampleBadge}
                    </span>
                  )}
                </div>
              </header>

              <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-[8px] bg-[#F4F2F7] px-2 py-2.5">
                  <dt className="text-[9px] font-bold uppercase tracking-wide text-[#3B2D5E]">{b.metricRating}</dt>
                  <dd className="mt-1 font-mono text-[18px] font-bold leading-none text-[#14101F]">
                    {rating !== null ? rating.toFixed(1) : "—"}
                  </dd>
                  <p className="mt-1 text-[8px] font-semibold leading-tight text-[#3B2D5E]">{gapLabel}</p>
                </div>
                <div className="rounded-[8px] bg-[#F4F2F7] px-2 py-2.5">
                  <dt className="text-[9px] font-bold uppercase tracking-wide text-[#3B2D5E]">{b.metricVelocityShort}</dt>
                  <dd className="mt-1 font-mono text-[18px] font-bold leading-none text-[#14101F]">
                    {velocity !== null ? formatHeadlineValue("reviews_per_month", velocity) : "—"}
                  </dd>
                  <p className="mt-1 text-[8px] font-semibold text-[#3B2D5E]">{b.metricVelocity}</p>
                </div>
                <div className="rounded-[8px] bg-[#F4F2F7] px-2 py-2.5">
                  <dt className="text-[9px] font-bold uppercase tracking-wide text-[#3B2D5E]">{b.metricFiveStar}</dt>
                  <dd className="mt-1 font-mono text-[18px] font-bold leading-none text-[#14101F]">
                    {fiveShare !== null ? `${fiveShare}%` : "—"}
                  </dd>
                  <p className="mt-1 text-[8px] font-semibold text-[#3B2D5E]">{b.metricFiveStar}</p>
                </div>
              </dl>

              {drawableHistory && (
                <div className="mt-3 flex items-center gap-2 border-t border-[#EFEDF2] pt-3">
                  <Sparkline
                    points={history}
                    label={b.sparklineAria.replace("{name}", subject.name ?? "")}
                  />
                  <span className="text-[10px] text-[#3B2D5E]">{b.trendRatingLabel}</span>
                </div>
              )}

              {topProblem && (
                <p className="mt-3 rounded-[8px] bg-[#FFF3D6] px-2.5 py-2 text-[10px] font-semibold text-[#8A6100]">
                  {b.topProblemLine.replace("{problem}", topProblem)}
                </p>
              )}

              <footer className="mt-auto border-t border-[var(--ui-line)] pt-3">
                <Link
                  href="/dashboard/reviews"
                  className={`inline-flex min-h-9 items-center rounded-[8px] bg-[#3D1D6E] px-3 text-[10px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
                >
                  {action}
                </Link>
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}
