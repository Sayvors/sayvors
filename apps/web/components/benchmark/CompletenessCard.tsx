"use client";

/**
 * Per-own-location completeness score (0–100) with the four weighted parts
 * broken out as solid bars. The scoring math lives in lib/benchmark-insights;
 * this card only renders what it returns — a subject with no data at all
 * shows "—" rather than a fake 0.
 */
import { useI18n } from "@/lib/i18n/I18nProvider";
import { completenessScore } from "@/lib/benchmark-insights";
import type { ComparisonSubject } from "@/lib/api-benchmark";

export default function CompletenessCard({ subjects }: { subjects: ComparisonSubject[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const own = subjects.filter((s) => s.kind === "own" && s.available);
  if (own.length === 0) return null;
  const partLabels: Record<string, string> = {
    rating: b.partRating,
    recency: b.partRecency,
    sentiment: b.partSentiment,
    depth: b.partDepth,
  };
  return (
    <section className="mt-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.completenessTitle}</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {own.map((s) => {
          const result = completenessScore(s);
          return (
            <article key={s.key} className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3">
              <header className="flex items-center justify-between gap-2">
                <h3 className="min-w-0 truncate text-[13px] font-bold text-[#14101F]" title={s.name ?? undefined}>
                  {s.name}
                </h3>
                <p className="shrink-0 text-[13px] font-bold text-[#14101F]">
                  <span className="mr-1 text-[10px] font-semibold uppercase text-[#3B2D5E]">{b.scoreLabel}</span>
                  {result ? `${Math.round(result.score)}/100` : "—"}
                </p>
              </header>
              <dl className="mt-2 space-y-1.5">
                {(result?.parts ?? []).map((part) => {
                  const pct = part.max > 0 ? Math.round((part.score / part.max) * 100) : 0;
                  return (
                    <div key={part.key} className="flex items-center gap-2">
                      <dt className="w-20 shrink-0 text-[10px] font-semibold uppercase text-[#3B2D5E]">
                        {partLabels[part.key] ?? part.key}
                      </dt>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#F1F2F5]">
                        <div className="h-full rounded-full bg-[#3D1D6E]" style={{ width: `${pct}%` }} />
                      </div>
                      <dd className="w-10 shrink-0 text-right font-mono text-[10px] text-[#3B2D5E]">
                        {part.score}/{part.max}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}
