"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";
import {
  LOW_SAMPLE_THRESHOLD,
  formatHeadlineValue,
  headlineMetricValue,
} from "@/lib/benchmark-chart-data";

interface Row {
  subject: ComparisonSubject;
  index: number;
}

function fill(template: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, value),
    template,
  );
}
function clampPct(value: number): number {
  return Math.max(0, Math.min(100, value));
}

/** Reputation mix and review momentum answer different owner questions.
 *  Keeping them in one cramped row implied a direct relationship and hid the
 *  fact that saved sentiment is star-derived while own sentiment is classified
 *  from review text. The two panels now share subjects, not semantics. */
export default function SentimentVelocityBars({
  subjects,
  mainKey,
}: {
  subjects: ComparisonSubject[];
  mainKey?: string | null;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const available = subjects.filter((subject) => subject.available);

  const sentimentRows = available.flatMap((subject, index) => {
    const reviewBase = subject.metrics.total_reviews ?? subject.metrics.total_ratings ?? 0;
    if (reviewBase <= 0) return [];
    const positive = headlineMetricValue(subject, "positive_pct");
    const negative = subject.facts.negative_pct;
    if (positive === null && negative === null) return [];
    const p = clampPct(positive ?? 0);
    const n = clampPct(negative ?? 0);
    return [{
      subject,
      index,
      positive: p,
      negative: n,
      neutral: Math.max(0, 100 - p - n),
    }];
  });

  const velocityRows: Array<Row & { velocity: number }> = [];
  available.forEach((subject, index) => {
    const velocity = headlineMetricValue(subject, "reviews_per_month");
    if (velocity !== null) velocityRows.push({ subject, index, velocity });
  });
  const maxVelocity = Math.max(1, ...velocityRows.map((row) => row.velocity));

  const sampleSize = (subject: ComparisonSubject) =>
    subject.metrics.total_reviews ?? subject.metrics.total_ratings ?? 0;
  const lowSample = (subject: ComparisonSubject) =>
    sampleSize(subject) < LOW_SAMPLE_THRESHOLD;

  if (available.length === 0) {
    return (
      <section
        aria-labelledby="sentiment-velocity-title"
        className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5"
      >
        <h2
          id="sentiment-velocity-title"
          className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]"
        >
          {b.sentimentVolumeTitle}
        </h2>
        <p className="mt-3 text-[12px] text-[#3B2D5E]">{b.sentimentEmpty}</p>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="sentiment-velocity-title"
      className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5"
    >
      <header>
        <h2
          id="sentiment-velocity-title"
          className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]"
        >
          {b.sentimentVolumeTitle}
        </h2>
        <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-[#3B2D5E]">
          {b.sentimentVolumeSubtitle}
        </p>
      </header>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-[8px] border border-[var(--ui-line)] bg-[#FCFBFE] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[12px] font-bold text-[#14101F]">{b.reputationMixTitle}</h3>
            <div className="flex flex-wrap gap-2 text-[9px] font-semibold text-[#3B2D5E]">
              <span className="inline-flex items-center gap-1">
                <span aria-hidden className="h-2 w-2 rounded-full bg-[#116631]" />
                {b.sentimentPositive}
              </span>
              <span className="inline-flex items-center gap-1">
                <span aria-hidden className="h-2 w-2 rounded-full bg-[#D8D8DC]" />
                {b.sentimentNeutral}
              </span>
              <span className="inline-flex items-center gap-1">
                <span aria-hidden className="h-2 w-2 rounded-full bg-[#B3123A]" />
                {b.sentimentNegative}
              </span>
            </div>
          </div>

          {sentimentRows.length === 0 ? (
            <p className="mt-4 text-[11px] text-[#3B2D5E]">{b.distributionNoData}</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {sentimentRows.map((row) => {
                const own = row.subject.key === mainKey;
                const name = row.subject.name ?? row.subject.key;
                return (
                  <li
                    key={row.subject.key}
                    className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5"
                  >
                    <span
                      aria-hidden
                      className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold ${
                        own
                          ? "bg-[#3D1D6E] text-white"
                          : "bg-white text-[#3B2D5E] ring-1 ring-[#3D1D6E]/30"
                      }`}
                    >
                      {row.index + 1}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="truncate text-[11px] font-bold text-[#14101F]" title={name}>
                          {name}
                        </span>
                        <span className="text-[9px] font-semibold text-[#6F6685]">
                          {row.subject.kind === "saved"
                            ? b.sentimentSourceStars
                            : b.sentimentSourceClassified}
                        </span>
                      </div>
                      <div
                        role="img"
                        aria-label={`${name}: ${Math.round(row.positive)}% ${b.sentimentPositive}, ${Math.round(row.neutral)}% ${b.sentimentNeutral}, ${Math.round(row.negative)}% ${b.sentimentNegative}`}
                        className="mt-1.5 flex h-3 overflow-hidden rounded-full bg-[#F1F2F5]"
                      >
                        <span className="h-full bg-[#116631]" style={{ width: `${row.positive}%` }} />
                        <span className="h-full bg-[#D8D8DC]" style={{ width: `${row.neutral}%` }} />
                        <span className="h-full bg-[#B3123A]" style={{ width: `${row.negative}%` }} />
                      </div>
                      <p className="mt-1 font-mono text-[9px] text-[#3B2D5E]">
                        {Math.round(row.positive)}% {b.sentimentPositive} · {Math.round(row.neutral)}% {b.sentimentNeutral} · {Math.round(row.negative)}% {b.sentimentNegative}
                      </p>
                    </div>
                    <div className="text-end">
                      <p className="font-mono text-[10px] font-bold text-[#3B2D5E]">
                        {fill(b.basedOnReviews, { n: String(sampleSize(row.subject)) })}
                      </p>
                      {lowSample(row.subject) && (
                        <p className="mt-0.5 text-[8px] font-bold uppercase tracking-wide text-[#8A6100]">
                          {b.lowSampleBadge}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mt-3 border-t border-[var(--ui-line)] pt-2 text-[9px] leading-relaxed text-[#6F6685]">
            {b.sentimentSourceNote}
          </p>
        </div>

        <div className="rounded-[8px] border border-[var(--ui-line)] bg-[#FCFBFE] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[12px] font-bold text-[#14101F]">{b.reviewMomentumTitle}</h3>
            <span className="text-[9px] font-semibold text-[#6F6685]">{b.metricVelocityShort}</span>
          </div>

          {velocityRows.length === 0 ? (
            <p className="mt-4 text-[11px] text-[#3B2D5E]">{b.distributionNoData}</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {velocityRows.map((row) => {
                const own = row.subject.key === mainKey;
                const name = row.subject.name ?? row.subject.key;
                return (
                  <li
                    key={row.subject.key}
                    className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5"
                  >
                    <span
                      aria-hidden
                      className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold ${
                        own
                          ? "bg-[#3D1D6E] text-white"
                          : "bg-white text-[#3B2D5E] ring-1 ring-[#3D1D6E]/30"
                      }`}
                    >
                      {row.index + 1}
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[11px] font-bold text-[#14101F]" title={name}>
                          {name}
                        </span>
                        {lowSample(row.subject) && (
                          <span className="shrink-0 text-[8px] font-bold uppercase tracking-wide text-[#8A6100]">
                            {b.lowSampleBadge}
                          </span>
                        )}
                      </div>
                      <div
                        role="img"
                        aria-label={`${name}: ${formatHeadlineValue("reviews_per_month", row.velocity)} ${b.metricVelocityShort}`}
                        className="mt-1.5 h-3 overflow-hidden rounded-full bg-[#F1F2F5]"
                      >
                        <span
                          className="block h-full rounded-full bg-[#3D1D6E]"
                          style={{ width: `${(row.velocity / maxVelocity) * 100}%` }}
                        />
                      </div>
                    </div>
                    <span className="min-w-8 text-end font-mono text-[12px] font-bold text-[#3D1D6E]">
                      {formatHeadlineValue("reviews_per_month", row.velocity)}
                      <span className="ml-1 text-[9px] font-semibold text-[#6F6685]">
                        {b.metricVelocityShort}
                      </span>
                    </span>
                    <span className="shrink-0 text-[8px] font-semibold text-[#6F6685]">
                      {row.subject.metrics.reviews_last_month != null
                        ? b.velocityWindow30
                        : b.velocityWindowYear}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mt-3 border-t border-[var(--ui-line)] pt-2 text-[9px] leading-relaxed text-[#6F6685]">
            {b.velocitySourceNote}
          </p>
        </div>
      </div>
    </section>
  );
}
