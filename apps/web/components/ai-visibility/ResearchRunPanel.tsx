"use client";

import { useQuery } from "@tanstack/react-query";
import type { Dict } from "@/lib/i18n/en";
import { fetchRun, retryRun } from "@/lib/api-ai-visibility";
import { isActiveStatus } from "@/lib/ai-visibility-metrics";
import { queryKeys } from "@/lib/query-keys";
import DecisionBrief from "./DecisionBrief";

export default function ResearchRunPanel({
  runId,
  copy,
  onRetry,
}: {
  runId: string | null;
  copy: Dict["aiVisibility"];
  onRetry: () => void;
}) {
  const query = useQuery({
    queryKey: queryKeys.aiVisibility.detail(runId ?? "none"),
    queryFn: () => fetchRun(runId!),
    enabled: !!runId,
    refetchInterval: (item) => {
      const status = item.state.data?.status;
      return status && isActiveStatus(status) ? 3000 : false;
    },
  });
  if (!runId) return null;
  if (query.isPending) return <p role="status">{copy.loading}</p>;
  if (query.isError) {
    return (
      <div role="alert">
        <p>{copy.loadError}</p>
        <button type="button" onClick={() => void query.refetch()}>
          {copy.retry}
        </button>
      </div>
    );
  }
  const detail = query.data!;
  const stage =
    copy.stages[detail.status as keyof typeof copy.stages] ?? detail.status;
  return (
    <div className="space-y-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] bg-[var(--ui-sunken)] p-3">
        <span className="text-[12px] font-bold">{stage}</span>
        <span className="text-[11px] text-[var(--ui-ink-2)]">
          {detail.evidence_coverage.source_count ?? 0}{" "}
          {copy.sources.toLowerCase()}
        </span>
        {(detail.status === "failed" ||
          detail.status === "insufficient_evidence") && (
          <button
            type="button"
            onClick={async () => {
              await retryRun(detail.id);
              onRetry();
            }}
            className="text-[11px] font-bold text-[var(--ui-ink)] underline"
          >
            {copy.retry}
          </button>
        )}
      </div>
      {detail.error && (
        <p role="alert" className="text-[12px] text-red-700">
          {detail.error}
        </p>
      )}
      {(detail.status === "completed" ||
        detail.status === "insufficient_evidence") && (
        <DecisionBrief detail={detail} copy={copy} />
      )}
    </div>
  );
}
