"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { SubjectReviews } from "@/lib/api-benchmark";

const RESPONSE_RATE_GOOD = 80;
const RESPONSE_RATE_WATCH = 50;

type ResponseTone = "good" | "watch" | "weak" | "unknown";

function responseTone(rate: number | null): ResponseTone {
  if (rate == null) return "unknown";
  if (rate >= RESPONSE_RATE_GOOD) return "good";
  if (rate >= RESPONSE_RATE_WATCH) return "watch";
  return "weak";
}

const RESPONSE_TONE_CLASS: Record<ResponseTone, string> = {
  good: "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  watch: "bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  weak: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  unknown: "text-[#6F6685]",
};

/** Response coverage per business. Counts are explicit about their evidence:
 *  total is public/stored lifetime volume; answered/unanswered use the cached
 *  review sample for competitors and stored rows for own locations. */
export default function ReviewResponseTable({
  subjects,
  loading,
  error,
  onRetry,
}: {
  subjects: SubjectReviews[];
  loading: boolean;
  error?: unknown;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  const c = t.benchmark.compare;

  if (error) {
    return (
      <div role="alert" className="mt-4 rounded-[8px] border border-[#FF4F6E]/35 bg-white px-3 py-2">
        <p className="text-[12px] font-semibold text-[#B3123A]">{c.couldNotLoadReviewResponses}</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[11px] font-bold text-[#3D1D6E] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]"
        >
          {t.common.retry}
        </button>
      </div>
    );
  }

  if (loading) {
    return <p className="mt-4 text-[12px] text-[#3B2D5E]">{t.common.loading}</p>;
  }
  if (!subjects.length) {
    return <p className="mt-4 text-[12px] text-[#3B2D5E]">{c.noDataAvailable}</p>;
  }

  const rows: Array<{
    label: string;
    kind?: "answered" | "unanswered" | "rate";
    value: (subject: SubjectReviews) => string;
  }> = [
    { label: c.totalReviews, value: (s) => (s.summary.total ?? "—").toString() },
    { label: c.sampledReviews, value: (s) => s.summary.sampled.toString() },
    {
      label: c.answeredReviews,
      kind: "answered",
      value: (s) => (s.summary.sampled > 0 ? s.summary.answered.toString() : c.noResponseSample),
    },
    {
      label: c.unansweredReviews,
      kind: "unanswered",
      value: (s) => (s.summary.sampled > 0 ? s.summary.unanswered.toString() : c.noResponseSample),
    },
    {
      label: c.responseRate,
      kind: "rate",
      value: (s) => (s.summary.response_rate != null ? `${s.summary.response_rate}%` : "—"),
    },
  ];

  return (
    <section
      aria-labelledby="review-responses-title"
      className="mt-4 overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white"
    >
      <div className="border-b border-[var(--ui-line)] px-3 py-2">
        <h2
          id="review-responses-title"
          className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]"
        >
          {c.reviewResponsesTitle}
        </h2>
        <p className="mt-0.5 text-[10px] leading-relaxed text-[#3B2D5E]">
          {c.reviewResponsesDesc}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left" style={{ minWidth: 720 }}>
          <caption className="sr-only">{c.reviewResponsesTitle}</caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-10 min-w-[150px] border-b border-r border-[var(--ui-line)] bg-[#FAFAFB] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E]"
              >
                {c.business}
              </th>
              {subjects.map((subject) => (
                <th
                  key={subject.key}
                  scope="col"
                  className={`min-w-[150px] border-b border-r border-[var(--ui-line)] px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-[#3B2D5E] last:border-r-0 ${
                    subject.key.startsWith("own:") ? "bg-[#F3EEFB]" : "bg-[#FAFAFB]"
                  }`}
                >
                  <span className="block truncate" title={subject.name ?? undefined}>
                    {subject.name || "—"}
                  </span>
                  <span className="mt-0.5 block text-[8px] font-semibold normal-case tracking-normal text-[#6F6685]">
                    {subject.key.startsWith("own:") ? c.yourLocation : c.googleListing}
                  </span>
                  <span className="mt-0.5 block text-[8px] font-semibold normal-case tracking-normal text-[#6F6685]">
                    {subject.summary.evidence_basis === "stored_lifetime"
                      ? c.responseBasisStoredLifetime
                      : subject.summary.evidence_basis === "cached_sample"
                        ? c.responseBasisCachedSample
                        : c.responseBasisUnavailable}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th
                  scope="row"
                  className="sticky left-0 z-10 border-b border-r border-[var(--ui-line)] bg-white px-3 py-2 text-[11px] font-semibold text-[#14101F]"
                >
                  {row.label}
                </th>
                {subjects.map((subject) => {
                  const tone = row.kind === "rate" ? responseTone(subject.summary.response_rate) : null;
                  const value = row.value(subject);
                  const countTone =
                    row.kind === "answered" && subject.summary.answered > 0
                      ? "text-emerald-700 dark:text-emerald-400"
                      : row.kind === "unanswered" && subject.summary.unanswered === 0
                        ? "text-emerald-700 dark:text-emerald-400"
                        : row.kind === "unanswered" && subject.summary.unanswered > 0
                          ? "text-amber-700 dark:text-amber-400"
                          : "text-[#3B2D5E]";
                  return (
                    <td
                      key={subject.key}
                      data-tone={tone ?? undefined}
                      className={`border-b border-r border-[var(--ui-line)] px-3 py-2 font-mono text-[11px] last:border-r-0 ${
                        tone ? RESPONSE_TONE_CLASS[tone] : countTone
                      }`}
                    >
                      {row.kind === "rate" && tone !== "unknown" ? (
                        <span className="inline-flex rounded-full px-2 py-0.5 font-bold">{value}</span>
                      ) : (
                        value
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
