"use client";

/**
 * AI summary of the current comparison: one plain-text read of the numbers,
 * fetched once per selection. The endpoint is fail-open (a template built
 * from the same numbers when the LLM is unavailable), so the UI never shows
 * a source badge — ai and template render identically.
 */
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { fetchAiSummary } from "@/lib/api-benchmark";

export default function AiSummaryCard({ subjects }: { subjects: string[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const queryKey = subjects.join("|");
  const summaryQuery = useQuery({
    queryKey: ["benchmark", "ai-summary", queryKey],
    queryFn: () => fetchAiSummary(subjects),
    enabled: subjects.length > 0,
  });

  // A missing summary is a quiet nothing: the numeric cards around it already
  // carry the message, and an empty box would read as a broken state.
  if (subjects.length === 0 || summaryQuery.isError) return null;
  const summary = summaryQuery.data?.summary?.trim();
  if (!summaryQuery.isPending && !summary) return null;

  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.aiSummaryTitle}</h2>
      {summaryQuery.isPending ? (
        <p className="mt-2 text-[12px] text-[#3B2D5E]">{t.common.loading}</p>
      ) : (
        <p className="mt-2 text-[13px] leading-relaxed text-[#14101F]">{summary}</p>
      )}
    </section>
  );
}
