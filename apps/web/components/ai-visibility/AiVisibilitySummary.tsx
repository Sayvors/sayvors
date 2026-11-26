import type { AiVisibilityOverview } from "@/lib/api-ai-visibility";
import { formatRate } from "@/lib/ai-visibility-metrics";

type Copy = {
  mentionRate: string;
  citationRate: string;
  recommendationRate: string;
  evidenceCoverage: string;
  retry: string;
  loadError: string;
};

export default function AiVisibilitySummary({
  data,
  isPending,
  isError,
  onRetry,
  copy,
}: {
  data: AiVisibilityOverview | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  copy: Copy;
}) {
  const metrics = [
    [copy.mentionRate, data?.mention_rate],
    [copy.citationRate, data?.citation_rate],
    [copy.recommendationRate, data?.recommendation_rate],
  ] as const;

  return (
    <section aria-label={copy.evidenceCoverage} aria-busy={isPending} className="space-y-2">
      <div className="ai-metric-strip">
        {metrics.map(([label, value], index) => (
          <div key={label} className="ai-metric">
            <div className="flex items-center gap-2">
              <span className="ai-eyebrow">0{index + 1}</span>
              <p className="ai-metric-label text-[11px] font-semibold text-[var(--ai-ink-2)]">
                {label}
              </p>
            </div>
            {isPending ? (
              <div className="ai-skeleton mt-3 h-8 w-24" aria-hidden="true" />
            ) : (
              <p className="ai-metric-value">{formatRate(value)}</p>
            )}
          </div>
        ))}
      </div>
      {isError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--ai-radius-control)] border border-[var(--ai-line)] bg-[var(--ai-surface)] px-4 py-3 text-[12px]"
        >
          <span>{copy.loadError}</span>
          <button type="button" onClick={onRetry} className="font-bold underline">
            {copy.retry}
          </button>
        </div>
      )}
    </section>
  );
}
