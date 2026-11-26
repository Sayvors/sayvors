"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";

type StarBucket = {
  key: string;
  label: string;
  value: number;
  color: string;
};

function buckets(subject: ComparisonSubject): StarBucket[] | null {
  const m = subject.metrics;
  const base = m.star_share_base ?? 0;
  const five = m.five_star ?? 0;
  const four = m.four_star ?? 0;
  const one = m.one_star ?? 0;
  const mid = Math.max(0, base - five - four - one);
  if (base <= 0) return null;
  return [
    { key: "5", label: "5★", value: five, color: "#116631" },
    { key: "4", label: "4★", value: four, color: "#4D9B6A" },
    { key: "23", label: "2-3★", value: mid, color: "#D8D8DC" },
    { key: "1", label: "1★", value: one, color: "#B3123A" },
  ];
}

export default function StarDistributionBars({
  subjects,
  mainKey,
}: {
  subjects: ComparisonSubject[];
  mainKey?: string | null;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const rows = subjects
    .filter((s) => s.available)
    .map((s) => ({ subject: s, buckets: buckets(s) }))
    .filter((r): r is { subject: ComparisonSubject; buckets: StarBucket[] } => r.buckets !== null);

  if (rows.length === 0) return null;

  return (
    <section aria-labelledby="star-distribution-title" className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="star-distribution-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
            {b.ratingDistribution || "Rating distribution"}
          </h2>
          <p className="mt-1 text-[11px] leading-relaxed text-[#3B2D5E]">
            {b.ratingDistributionDesc || "How star ratings break down for each business."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[9px] font-semibold text-[#3B2D5E]">
          {[
            ["5★", "#116631"],
            ["4★", "#4D9B6A"],
            ["2-3★", "#D8D8DC"],
            ["1★", "#B3123A"],
          ].map(([label, color]) => (
            <span key={label} className="inline-flex items-center gap-1">
              <span aria-hidden className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
              {label}
            </span>
          ))}
        </div>
      </header>

      <ul className="mt-4 space-y-3">
        {rows.map(({ subject, buckets: bks }) => {
          const own = subject.key === mainKey;
          const name = subject.name ?? subject.key;
          const total = bks.reduce((sum, x) => sum + x.value, 0);
          return (
            <li key={subject.key} className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)_auto] items-center gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-[11px] font-bold text-[#14101F]" title={name}>{name}</span>
                {own ? <span className="shrink-0 rounded-full bg-[#3D1D6E]/10 px-1.5 py-0.5 text-[8px] font-bold text-[#3D1D6E]">{b.distributionYourBranch || "Your branch"}</span> : null}
              </div>
              <div
                role="img"
                aria-label={`${name}: ${bks.map((k) => `${k.label} ${Math.round((k.value / Math.max(1, total)) * 100)}%`).join(", ")}`}
                className="flex h-3 overflow-hidden rounded-full bg-[#F1F2F5]"
              >
                {bks.map((k) => {
                  const pct = total > 0 ? (k.value / total) * 100 : 0;
                  return pct > 0 ? <span key={k.key} className="h-full" style={{ width: `${pct}%`, backgroundColor: k.color }} /> : null;
                })}
              </div>
              <span className="font-mono text-[10px] font-semibold text-[#3B2D5E]">{total}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
