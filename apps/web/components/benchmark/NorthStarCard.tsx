"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { rankFixFirst, type FixMetric } from "@/lib/benchmark-insights";
import type { CompareSummary, ComparisonSubject } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";
const PILL: Record<CompareSummary["health"], string> = {
  good: "bg-[#E7F6EC] text-[#116631]",
  warn: "bg-[#FFF3D6] text-[#8A6100]",
  bad: "bg-[#FDE8EC] text-[#B3123A]",
};

const FIX_COPY: Record<FixMetric, { key: "fixRating" | "fixVelocity" | "fixSentiment"; suffix: string; decimals: number }> = {
  avg_rating: { key: "fixRating", suffix: "", decimals: 1 },
  reviews_per_month: { key: "fixVelocity", suffix: "", decimals: 0 },
  positive_pct: { key: "fixSentiment", suffix: "%", decimals: 0 },
};

/** Rank "X of Y", health, and top actionable fix-first tickets. */
export default function NorthStarCard({
  summary,
  subjects = [],
}: {
  summary: CompareSummary;
  subjects?: ComparisonSubject[];
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const leading = summary.rank === 1;
  const health = leading ? "good" : summary.health;
  const tickets = subjects.length > 0 ? rankFixFirst(summary, subjects) : [];

  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${PILL[health]}`}>
          {leading ? b.healthLeader : b[`health_${summary.health}` as const]}
        </span>
        <p className="text-[14px] font-bold text-[#14101F]" title={summary.own.name ?? undefined}>
          {b.rankLine
            .replace("{rank}", String(summary.rank))
            .replace("{of}", String(summary.of))}
        </p>
        {summary.leader?.name ? (
          <p className="text-[12px] text-[#3B2D5E]">{b.leaderLine.replace("{leader}", summary.leader.name)}</p>
        ) : null}
      </div>

      {tickets.length > 0 ? (
        <div className="mt-3">
          <h3 className="text-[11px] font-bold uppercase tracking-wide text-[#3B2D5E]">{b.fixFirstTitle}</h3>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {tickets.map(({ metric, gap }) => {
              const copy = FIX_COPY[metric];
              const gapText = `+${gap.toFixed(copy.decimals)}${copy.suffix}`;
              return (
                <Link
                  key={metric}
                  href="/dashboard/reviews"
                  className={`block rounded-[8px] border border-[var(--ui-line)] bg-[#FAFAFB] p-3 transition-colors hover:bg-[#F4F2F7] ${FOCUS}`}
                >
                  <p className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-[12px] font-bold text-[#14101F]">{b[copy.key]}</span>
                    <span className="shrink-0 rounded-full bg-[#FDE8EC] px-2 py-0.5 text-[10px] font-bold text-[#B3123A]">
                      {gapText}
                    </span>
                  </p>
                </Link>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}
