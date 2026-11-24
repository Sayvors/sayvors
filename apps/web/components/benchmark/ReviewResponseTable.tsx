"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { SubjectReviews } from "@/lib/api-benchmark";

/** Response coverage per business. Counts are explicit about their evidence:
 *  total is public/stored lifetime volume; answered/unanswered use the cached
 *  review sample for competitors and stored rows for own locations. */
export default function ReviewResponseTable({
  subjects,
  loading,
}: {
  subjects: SubjectReviews[];
  loading: boolean;
}) {
  const { t } = useI18n();
  const c = t.benchmark.compare;

  if (loading) {
    return <p className="mt-4 text-[12px] text-[#3B2D5E]">{t.common.loading}</p>;
  }
  if (!subjects.length) {
    return <p className="mt-4 text-[12px] text-[#3B2D5E]">{c.noDataAvailable}</p>;
  }

  const rows: Array<{
    label: string;
    value: (subject: SubjectReviews) => string;
  }> = [
    { label: c.totalReviews, value: (s) => (s.summary.total ?? "—").toString() },
    { label: c.sampledReviews, value: (s) => s.summary.sampled.toString() },
    {
      label: c.answeredReviews,
      value: (s) => (s.summary.sampled > 0 ? s.summary.answered.toString() : c.noResponseSample),
    },
    {
      label: c.unansweredReviews,
      value: (s) => (s.summary.sampled > 0 ? s.summary.unanswered.toString() : c.noResponseSample),
    },
    {
      label: c.responseRate,
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
                {subjects.map((subject) => (
                  <td
                    key={subject.key}
                    className="border-b border-r border-[var(--ui-line)] px-3 py-2 font-mono text-[11px] text-[#3B2D5E] last:border-r-0"
                  >
                    {row.value(subject)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
