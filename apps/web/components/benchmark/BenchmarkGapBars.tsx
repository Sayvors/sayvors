"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";

type MetricKey = "avg_rating" | "reviews_last_month" | "positive_pct" | "response_rate";

function getValue(subject: ComparisonSubject, metric: MetricKey, responseRate: number | null): number | null {
  if (metric === "response_rate") return responseRate;
  if (metric === "positive_pct") return subject.facts.positive_pct;
  if (metric === "avg_rating") return subject.metrics.avg_rating;
  if (metric === "reviews_last_month") return subject.metrics.reviews_last_month ?? (subject.metrics.reviews_last_year != null ? subject.metrics.reviews_last_year / 12 : null);
  return null;
}

function fmt(metric: MetricKey, v: number): string {
  if (metric === "avg_rating") return v.toFixed(1);
  if (metric === "positive_pct" || metric === "response_rate") return `${Math.round(v)}%`;
  return Math.round(v).toString();
}

export default function BenchmarkGapBars({
  subjects,
  mainKey,
  responseRates,
}: {
  subjects: ComparisonSubject[];
  mainKey?: string | null;
  responseRates?: Record<string, number | null>;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const own = subjects.find((s) => s.key === mainKey && s.available) ?? subjects.find((s) => s.kind === "own" && s.available);
  const peers = subjects.filter((s) => s.available);
  if (!own || peers.length < 2) return null;

  const metrics: Array<{ key: MetricKey; label: string; max: number | null }> = [
    { key: "avg_rating", label: b.metricRating, max: 5 },
    { key: "reviews_last_month", label: b.metricVelocity, max: null },
    { key: "positive_pct", label: b.metricSentiment, max: 100 },
    { key: "response_rate", label: b.compare.responseRate, max: 100 },
  ];

  return (
    <section aria-labelledby="gap-bars-title" className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-4 sm:p-5">
      <h2 id="gap-bars-title" className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">
        {b.gapToLeader || "Gap to leader"}
      </h2>
      <p className="mt-1 text-[11px] text-[#3B2D5E]">{b.gapToLeaderDesc || "Your branch versus the leader for each key metric."}</p>
      <div className="mt-4 space-y-4">
        {metrics.map((metric) => {
          const rows = peers
            .map((s) => ({ key: s.key, name: s.name ?? s.key, value: getValue(s, metric.key, responseRates?.[s.key] ?? null) }))
            .filter((r): r is { key: string; name: string; value: number } => typeof r.value === "number");
          if (rows.length < 2) return null;
          const leader = rows.reduce((a, c) => (c.value > a.value ? c : a), rows[0]);
          const mine = rows.find((r) => r.key === own.key);
          const max = metric.max ?? Math.max(...rows.map((r) => r.value), 1);
          return (
            <div key={metric.key}>
              <div className="mb-1 flex items-center justify-between text-[10px] font-semibold text-[#3B2D5E]">
                <span>{metric.label}</span>
                {mine ? (
                  <span className={mine.key === leader.key ? "text-[#116631]" : "text-[#B3123A]"}>
                    {mine.key === leader.key ? b.healthLeader : `${b.compare.gap} ${fmt(metric.key, leader.value - mine.value)}`}
                  </span>
                ) : <span>—</span>}
              </div>
              <div className="space-y-1.5">
                {rows.sort((a, c) => c.value - a.value).slice(0, 6).map((r) => {
                  const isOwn = r.key === own.key;
                  const isLeader = r.key === leader.key;
                  const width = Math.max(2, (r.value / Math.max(max, 0.0001)) * 100);
                  return (
                    <div key={r.key} className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)_auto] items-center gap-2">
                      <span className={`truncate text-[10px] ${isOwn ? "font-bold text-[#14101F]" : "text-[#3B2D5E]"}`} title={r.name}>{r.name}</span>
                      <div className="relative h-2.5 rounded-full bg-[#F1F2F5]">
                        <div className={`h-full rounded-full ${isOwn ? "bg-[#3D1D6E]" : "bg-[#A9A3B2]"}`} style={{ width: `${width}%` }} />
                        {!isOwn && mine ? (
                          <div className="absolute top-[-2px] h-3.5 w-px bg-[#3D1D6E]" style={{ left: `${Math.max(0, Math.min(100, (mine.value / Math.max(max, 0.0001)) * 100))}%` }} aria-hidden />
                        ) : null}
                      </div>
                      <span className={`font-mono text-[10px] ${isLeader ? "font-bold text-[#14101F]" : "text-[#3B2D5E]"}`}>{fmt(metric.key, r.value)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}