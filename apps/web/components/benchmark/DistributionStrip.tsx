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
  index: number;
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
  return Math.max(1, Math.min(99, ((value - min) / span) * 100));
}

/** Best / Median / Worst bars hid the individual businesses. This plot keeps
 *  every peer visible, pins the owner's branch, and excludes missing evidence
 *  instead of plotting the API's empty-location zeros. */
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
    {
      key: "avg_rating",
      label: b.metricRating,
      summary: b.distributionRatingSummary,
      min: 1,
      max: 5,
    },
    {
      key: "reviews_per_month",
      label: b.metricVelocity,
      summary: b.distributionVelocitySummary,
      min: 0,
      max: null,
    },
    {
      key: "total_reviews",
      label: b.metricTotalReviews,
      summary: b.distributionReviewsSummary,
      min: 0,
      max: null,
    },
    {
      key: "positive_pct",
      label: b.metricSentiment,
      summary: b.distributionSentimentSummary,
      min: 0,
      max: 100,
    },
  ];

  const rows = metrics.map((metric) => {
    const points: MetricPoint[] = [];
    available.forEach((subject, index) => {
      const value = headlineMetricValue(subject, metric.key);
      if (value !== null) points.push({ subject, index, value });
    });
    const values = points.map((point) => point.value);
    const peerMedian = median(values);
    const own = points.find((point) => point.subject.key === mainKey) ?? null;
    const max = metric.max ?? Math.max(1, ...values);

    // Equal values stack vertically instead of covering one another. Six
    // subjects maximum keeps the 7px steps inside the 48px plot.
    const counts = new Map<string, number>();
    for (const point of points) {
      const key = point.value.toFixed(2);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const seen = new Map<string, number>();
    const plotted = points.map((point) => {
      const key = point.value.toFixed(2);
      const index = seen.get(key) ?? 0;
      seen.set(key, index + 1);
      const count = counts.get(key) ?? 1;
      return {
        ...point,
        left: position(point.value, metric.min, max),
        offset: (index - (count - 1) / 2) * 7,
      };
    });

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
      plotted,
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
            <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-[#3D1D6E]" />
            {b.distributionYourBranch}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-2.5 rounded-full border border-[#3D1D6E]/40 bg-white" />
            {b.distributionPeer}
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
        <>
          <div className="mt-4 divide-y divide-[var(--ui-line)]">
            {rows.map((row) => (
              <div
                key={row.metric.key}
                className="grid gap-3 py-4 first:pt-0 last:pb-0 md:grid-cols-[190px_minmax(0,1fr)_130px] md:items-center"
              >
                <div>
                  <p className="text-[12px] font-bold text-[#14101F]">{row.metric.label}</p>
                  <p className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span className="font-mono text-[20px] font-bold leading-none text-[#3D1D6E]">
                      {row.own ? formatHeadlineValue(row.metric.key, row.own.value) : "—"}
                    </span>
                    <span className="text-[10px] font-semibold text-[#3B2D5E]">{row.gap}</span>
                  </p>
                </div>

                <div>
                  {row.points.length === 0 ? (
                    <p className="text-[11px] text-[#3B2D5E]">{b.distributionNoData}</p>
                  ) : (
                    <>
                      <div aria-hidden className="relative h-12">
                        <div className="absolute inset-x-0 top-1/2 h-px bg-[var(--ui-line)]" />
                        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
                          <span
                            key={tick}
                            className="absolute top-1/2 h-2 w-px -translate-y-1/2 bg-[var(--ui-line)]"
                            style={{ left: `${tick * 100}%` }}
                          />
                        ))}
                        {row.peerMedian !== null && (
                          <span
                            className="absolute bottom-0 top-0 w-px bg-[#3B2D5E]/70"
                            style={{ left: `${position(row.peerMedian, row.metric.min, row.max)}%` }}
                          />
                        )}
                        {row.plotted.map((point) => {
                          const own = point.subject.key === mainKey;
                          return (
                            <span
                              key={point.subject.key}
                              title={`${point.subject.name ?? point.subject.key}: ${formatHeadlineValue(row.metric.key, point.value)}`}
                              className={`absolute flex h-5 w-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full text-[9px] font-bold ${
                                own
                                  ? "z-10 bg-[#3D1D6E] text-white ring-2 ring-white"
                                  : "bg-white text-[#3B2D5E] ring-1 ring-[#3D1D6E]/35"
                              }`}
                              style={{
                                left: `${point.left}%`,
                                top: `calc(50% + ${point.offset}px)`,
                              }}
                            >
                              {point.index + 1}
                            </span>
                          );
                        })}
                      </div>
                      <div className="mt-1 flex justify-between font-mono text-[9px] text-[#6F6685]">
                        <span>{formatHeadlineValue(row.metric.key, row.metric.min)}</span>
                        <span>{formatHeadlineValue(row.metric.key, row.max)}</span>
                      </div>
                    </>
                  )}
                  <p className="sr-only">{row.summary}</p>
                </div>

                <div className="flex items-center justify-between gap-2 md:justify-end">
                  <span className="rounded-full bg-[#F4F2F7] px-2 py-1 font-mono text-[10px] font-bold text-[#3B2D5E]">
                    n={row.points.length}
                  </span>
                  {row.points.length < LOW_SAMPLE_THRESHOLD && (
                    <span className="text-[9px] font-bold uppercase tracking-wide text-[#8A6100]">
                      {b.distributionSmallSet}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-t border-[var(--ui-line)] pt-3 text-[11px] text-[#3B2D5E]">
            {available.map((subject, index) => (
              <li key={subject.key} className="flex min-w-0 items-center gap-1.5">
                <span
                  aria-hidden
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold ${
                    subject.key === mainKey
                      ? "bg-[#3D1D6E] text-white"
                      : "bg-white text-[#3B2D5E] ring-1 ring-[#3D1D6E]/35"
                  }`}
                >
                  {index + 1}
                </span>
                <span className="max-w-[180px] truncate font-semibold" title={subject.name ?? undefined}>
                  {subject.name ?? subject.key}
                </span>
              </li>
            ))}
          </ul>
          {rows.some((row) => row.points.length < LOW_SAMPLE_THRESHOLD) && (
            <p className="mt-2 text-[10px] font-semibold text-[#8A6100]">
              {b.distributionSmallSample}
            </p>
          )}
          <p className="mt-1 text-[10px] leading-relaxed text-[#6F6685]">
            {b.distributionEvidenceNote}
          </p>
        </>
      )}
    </section>
  );
}
