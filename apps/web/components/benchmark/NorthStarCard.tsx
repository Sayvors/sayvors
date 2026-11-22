"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { CompareSummary } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";
const PILL: Record<CompareSummary["health"], string> = {
  good: "bg-[#E7F6EC] text-[#116631]",
  warn: "bg-[#FFF3D6] text-[#8A6100]",
  bad: "bg-[#FDE8EC] text-[#B3123A]",
};

/** Rank "X of Y", gap-to-leader per metric, health pill, fix-first CTA. */
export default function NorthStarCard({
  summary,
  problemTopic,
}: {
  summary: CompareSummary;
  problemTopic: string | null;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const gapLabels: Array<[keyof CompareSummary["gaps"], string]> = [
    ["avg_rating", b.metricRating],
    ["reviews_per_month", b.metricVelocity],
    ["total_reviews", b.metricTotalReviews],
    ["positive_pct", b.metricSentiment],
  ];
  const worst = gapLabels
    .map(([key, label]) => ({ key, label, gap: summary.gaps[key] }))
    .filter((g): g is { key: keyof CompareSummary["gaps"]; label: string; gap: number } => typeof g.gap === "number" && g.gap > 0)
    .sort((a, c) => c.gap - a.gap)[0];
  return (
    <section className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <div className="flex items-center gap-3">
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${PILL[summary.health]}`}>
          {b[`health_${summary.health}` as const]}
        </span>
        <p className="text-[14px] font-bold text-[#14101F]">
          {b.rankLine
            .replace("{rank}", String(summary.rank))
            .replace("{of}", String(summary.of))}
        </p>
        {summary.leader?.name ? (
          <p className="text-[12px] text-[#3B2D5E]">{b.leaderLine.replace("{leader}", summary.leader.name)}</p>
        ) : null}
      </div>
      {worst ? (
        <Link
          href="/dashboard/reviews"
          className={`rounded-[24px] bg-[#3D1D6E] px-4 py-2 text-[12px] font-bold text-white ${FOCUS}`}
        >
          {b.fixFirst.replace("{metric}", worst.label)}
        </Link>
      ) : null}
    </section>
  );
}
