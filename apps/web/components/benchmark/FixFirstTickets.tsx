"use client";

/**
 * Fix-first tickets: the top actionable gaps from rankFixFirst, worst first.
 * Each ticket names the one action that closes the gap and links straight to
 * the reviews inbox — the place the fix actually happens.
 */
import Link from "next/link";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { rankFixFirst, type FixMetric } from "@/lib/benchmark-insights";
import type { CompareSummary, ComparisonSubject } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

/** Gap copy per metric: the action, not the number's name. */
const FIX_COPY: Record<FixMetric, { key: "fixRating" | "fixVelocity" | "fixSentiment"; suffix: string; decimals: number }> = {
  avg_rating: { key: "fixRating", suffix: "", decimals: 1 },
  reviews_per_month: { key: "fixVelocity", suffix: "", decimals: 0 },
  positive_pct: { key: "fixSentiment", suffix: "%", decimals: 0 },
};

export default function FixFirstTickets({
  summary,
  subjects,
}: {
  summary: CompareSummary;
  subjects: ComparisonSubject[];
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const tickets = rankFixFirst(summary, subjects);
  if (tickets.length === 0) return null;
  return (
    <section className="mt-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.fixFirstTitle}</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {tickets.map(({ metric, gap }) => {
          const copy = FIX_COPY[metric];
          const gapText = `+${gap.toFixed(copy.decimals)}${copy.suffix}`;
          return (
            <Link
              key={metric}
              href="/dashboard/reviews"
              className={`block rounded-[8px] border border-[var(--ui-line)] bg-white p-3 transition-colors hover:bg-[#F4F2F7] ${FOCUS}`}
            >
              <p className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-[13px] font-bold text-[#14101F]">{b[copy.key]}</span>
                <span className="shrink-0 rounded-full bg-[#FDE8EC] px-2 py-0.5 text-[10px] font-bold text-[#B3123A]">
                  {gapText}
                </span>
              </p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
