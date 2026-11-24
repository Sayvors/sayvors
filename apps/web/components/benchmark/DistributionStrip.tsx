"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";
import {
  LOW_SAMPLE_THRESHOLD,
  formatHeadlineGap,
  formatHeadlineValue,
  headlineMetricValue,
  median,
  type HeadlineMetricKey,
} from "@/lib/benchmark-chart-data";

interface MetricPoint {
  subject: ComparisonSubject;
  value: number;
}

function fill(template: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, value),
    template,
  );
}

function position(value: number, min: number, max: number): number {
  const span = Math.max(max - min, 0.0001);
  return Math.max(0, Math.min(100, ((value - min) / span) * 100));
}

/** Horizontal bars keep every business readable without the dot-plot's
 *  numbered legend. The owner's branch is the only filled accent bar; peers
 *  use one neutral tint, and the median is a single aligned tick. */
export default function DistributionStrip({
  subjects,
  mainKey,
}: {
  subjects: ComparisonSubject[];
  mainKey?: string | null;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const available = subjects.filter((subject) => subject.available);
  const metrics: Array<{
    key: HeadlineMetricKey;
    label: string;
    summary: string;
    min: number;
    max: number | null;
  }> = [
    { key: "avg_rating", label: b.metricRating, summary: b.distributionRatingSummary, min: 0, max: 5 },
    { key: "reviews_per_month", label: b.metricVelocity, summary: b.distributionVelocitySummary, min: 0, max: null },
    { key: "total_reviews", label: b.metricTotalReviews, summary: b.distributionReviewsSummary, min: 0, max: null },
    { key: "positive_pct", label: b.metricSentiment, summary: b.distributionSentimentSummary, min: 0, max: 100 },
  ];

  const rows = metrics.map((metric) => {
    const points: MetricPoint[] = [];
    for (const subject of available) {
      const value = headlineMetricValue(subject, metric.key);
      if (value !== null) points.push({ subject, value });
    }
    const values = points.map((point) => point.value);
    const peerMedian = median(values);
    const own = points.find((point) => point.subject.key === mainKey) ?? null;
    const max = metric.max ?? Math.max(1, ...values);

    let gap = b.distributionNoValue;
    if (own && peerMedian !== null) {
      const delta = own.value - peerMedian;
      if (Math.abs(delta) < 0.005) {
        gap = b.distributionAtMedian;
      } else {
        gap = fill(delta > 0 ? b.distributionAboveMedian : b.distributionBelowMedian, {
          gap: formatHeadlineGap(metric.key, delta),
        });
      }
    }

    return {
      metric,
      points,
      peerMedian,
      own,
      max,
      gap,
      summary: fill(metric.summary, {
        n: String(points.length),
        total: String(available.length),
      }),
    };
  });

  return (
    <section
      aria-labelledby="distribution-title"
      className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5"
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2
            id="distribution-title"
            className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]"
          >
            {b.distributionTitle}
          </h2>
          <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-[#3B2D5E]">
            {b.distributionSubtitle}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] font-semibold text-[#3B2D5E]">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-4 rounded-full bg-[#3D1D6E]" />
            {b.distributionYourBranch}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="h-3 w-px bg-[#3B2D5E]" />
            {b.distributionMedian}
          </span>
        </div>
      </header>

      {available.length < 2 ? (
        <p className="mt-5 rounded-[8px] border border-dashed border-[var(--ui-line)] bg-[#F4F2F7] px-4 py-6 text-center text-[12px] text-[#3B2D5E]">
          {b.distributionEmpty}
        </p>
      ) : (
        <div className="mt-5 space-y-6">
          {rows.map((row) => (
            <section key={row.metric.key} aria-labelledby={`distribution-${row.metric.key}`}>
              <header className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h3
                    id={`distribution-${row.metric.key}`}
                    className="text-[12px] font-bold text-[#14101F]"
                  >
                    {row.metric.label}
                  </h3>
                  <p className="mt-0.5 text-[10px] font-semibold text-[#6F6685]">
                    n={row.points.length}
                    {row.points.length < LOW_SAMPLE_THRESHOLD ? ` · ${b.distributionSmallSet}` : ""}
                  </p>
                </div>
                <div className="text-end">
                  <p className="font-mono text-[20px] font-bold leading-none text-[#3D1D6E]">
                    {row.own ? formatHeadlineValue(row.metric.key, row.own.value) : "—"}
                  </p>
                  <p className="mt-1 text-[10px] font-semibold text-[#3B2D5E]">{row.gap}</p>
                </div>
              </header>

              {row.points.length === 0 ? (
                <p className="mt-3 text-[11px] text-[#3B2D5E]">{b.distributionNoData}</p>
              ) : (
                <div className="mt-3 space-y-2">
                  {row.points.map((point) => {
                    const own = point.subject.key === mainKey;
                    const name = point.subject.name ?? point.subject.key;
                    const width = position(point.value, row.metric.min, row.max);
                    return (
                      <div
                        key={point.subject.key}
                        className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)_52px] items-center gap-3"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className="truncate text-[11px] font-semibold text-[#14101F]"
                            title={name}
                          >
                            {name}
                          </span>
                          {own && (
                            <span className="shrink-0 rounded-full bg-[#3D1D6E]/10 px-1.5 py-0.5 text-[8px] font-bold text-[#3D1D6E]">
                              {b.distributionYourBranch}
                            </span>
                          )}
                        </div>
                        <div
                          role="img"
                          aria-label={`${name}: ${formatHeadlineValue(row.metric.key, point.value)}`}
                          className="relative h-3 overflow-hidden rounded-full bg-[#F1F2F5]"
                        >
                          <span
                            className={`block h-full rounded-full ${
                              own ? "bg-[#3D1D6E]" : "bg-[#D8D0E8]"
                            }`}
                            style={{ width: `${width}%` }}
                          />
                          {row.peerMedian !== null && (
                            <span
                              aria-hidden
                              className="absolute bottom-0 top-0 w-px bg-[#3B2D5E]/70"
                              style={{ left: `${position(row.peerMedian, row.metric.min, row.max)}%` }}
                            />
                          )}
                        </div>
                        <span className="text-end font-mono text-[11px] font-bold text-[#3B2D5E]">
                          {formatHeadlineValue(row.metric.key, point.value)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
              <p className="sr-only">{row.summary}</p>
            </section>
          ))}
        </div>
      )}

      {rows.some((row) => row.points.length < LOW_SAMPLE_THRESHOLD) && (
        <p className="mt-4 text-[10px] font-semibold text-[#8A6100]">
          {b.distributionSmallSample}
        </p>
      )}
      <p className="mt-1 text-[10px] leading-relaxed text-[#6F6685]">
        {b.distributionEvidenceNote}
      </p>
    </section>
  );
}
