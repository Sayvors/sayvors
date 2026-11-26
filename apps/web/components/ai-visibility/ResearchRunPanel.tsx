"use client";

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
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
  const [actionError, setActionError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: queryKeys.aiVisibility.detail(runId ?? "none"),
    queryFn: () => fetchRun(runId!),
    enabled: !!runId,
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    refetchInterval: (item) => {
      const status = item.state.data?.status;
      return status && isActiveStatus(status) ? 3000 : false;
    },
  });
  if (!runId) return null;
  if (query.isPending) {
    return (
      <div className="space-y-3" role="status" aria-label={copy.loading}>
        <div className="ai-skeleton h-4 w-40" />
        <div className="ai-skeleton h-24 w-full" />
        <div className="ai-skeleton h-4 w-3/4" />
        <div className="ai-skeleton h-4 w-2/3" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div
        role="alert"
        className="rounded-[var(--ai-radius-control)] border border-[var(--ai-line)] bg-[var(--ai-sunken)] p-4"
      >
        <p className="text-[12px] font-semibold text-[var(--ai-ink)]">{copy.loadError}</p>
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="mt-2 min-h-9 text-[11px] font-bold text-[var(--ai-accent)] underline"
        >
          {copy.retry}
        </button>
      </div>
    );
  }
  const detail = query.data!;
  const stage =
    copy.stages[detail.status as keyof typeof copy.stages] ?? detail.status;
  const active = isActiveStatus(detail.status);
  const tone = active
    ? "active"
    : detail.status === "completed"
      ? "ok"
      : detail.status === "insufficient_evidence"
        ? "warn"
        : "danger";
  return (
    <div className="space-y-5" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ai-line)] pb-4">
        <div className="flex items-center gap-3">
          <span className="ai-status-dot" data-tone={tone} />
          <div>
            <p className="text-[12px] font-bold text-[var(--ai-ink)]">{stage}</p>
            <p className="mt-0.5 font-mono text-[10px] text-[var(--ai-muted)]">
              {detail.evidence_coverage.source_count ?? 0} {copy.sources.toLowerCase()}
            </p>
          </div>
        </div>
        {(detail.status === "failed" ||
          detail.status === "insufficient_evidence") && (
          <button
            type="button"
            onClick={async () => {
              setActionError(null);              try {
                await retryRun(detail.id);
                onRetry();
              } catch (exc) {
                setActionError(exc instanceof Error ? exc.message : copy.loadError);
              }
            }}
            className="ai-btn-primary min-h-10 px-3 text-[11px]"
            title={copy.tipRetry}
          >
            {copy.retry}
          </button>
        )}
      </div>
      {active && (
        <div className="space-y-3" role="status">
          <div className="ai-skeleton h-4 w-2/3" />
          <div className="ai-skeleton h-4 w-full" />
          <div className="ai-skeleton h-4 w-5/6" />
        </div>
      )}
      {(detail.error || actionError) && (
        <p role="alert" className="rounded-[var(--ai-radius-control)] bg-[var(--ai-sunken)] px-4 py-3 text-[12px] leading-5 text-[var(--ai-danger)]">
          {actionError ?? detail.error}
        </p>
      )}
      {(detail.status === "completed" ||
        detail.status === "insufficient_evidence") && (
        <DecisionBrief detail={detail} copy={copy} />
      )}
    </div>
  );
}
