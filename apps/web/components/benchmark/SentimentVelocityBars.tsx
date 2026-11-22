"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";

/** Reputation mix (stacked) + review velocity per compared business. */
export default function SentimentVelocityBars({ subjects }: { subjects: ComparisonSubject[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const rows = subjects
    .filter((s) => s.available)
    .map((s) => {
      const pos = s.facts.positive_pct;
      const neg = s.facts.negative_pct;
      if (pos == null && neg == null) return null;
      const p = pos ?? 0;
      const n = neg ?? 0;
      const neutral = Math.max(0, 100 - p - n);
      const velocity = s.metrics.reviews_last_month
        ?? (s.metrics.reviews_last_year != null
          ? Math.round(s.metrics.reviews_last_year / 12)
          : null);
      return { subject: s, p, neutral, n, velocity };
    })
    .filter((r): r is NonNullable<typeof r> => r !== null);
  if (rows.length === 0) return null;
  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.sentimentVolumeTitle}</h2>
      <div className="mt-3 space-y-2.5">
        {rows.map(({ subject, p, neutral, n, velocity }) => (
          <div key={subject.key} className="flex items-center gap-3">
            <span className="w-40 min-w-0 shrink-0 truncate text-[12px] font-semibold text-[#14101F]" title={subject.name ?? undefined}>
              {subject.name ?? subject.key}
            </span>
            <div className="flex h-4 flex-1 overflow-hidden rounded-full bg-[#F1F2F5]" role="img"
              aria-label={`${subject.name ?? subject.key}: ${Math.round(p)}% ${b.sentimentPositive}, ${Math.round(neutral)}% ${b.sentimentNeutral}, ${Math.round(n)}% ${b.sentimentNegative}`}>
              <div className="h-full" style={{ width: `${p}%`, background: "#116631" }} />
              <div className="h-full" style={{ width: `${neutral}%`, background: "#D8D8DC" }} />
              <div className="h-full" style={{ width: `${n}%`, background: "#B3123A" }} />
            </div>
            <span className="w-24 shrink-0 text-right text-[11px] text-[#3B2D5E]">
              {velocity != null ? `${velocity} ${b.metricVelocityShort}` : "\u2014"}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-[#3B2D5E]">
        {[
          { key: "pos", color: "#116631", label: b.sentimentPositive },
          { key: "neu", color: "#D8D8DC", label: b.sentimentNeutral },
          { key: "neg", color: "#B3123A", label: b.sentimentNegative },
        ].map((item) => (
          <span key={item.key} className="mr-3 inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </p>
    </section>
  );
}
