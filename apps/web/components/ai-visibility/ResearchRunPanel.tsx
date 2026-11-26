"use client";

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { Dict } from "@/lib/i18n/en";
import { fetchRun, retryRun } from "@/lib/api-ai-visibility";
import { isActiveStatus } from "@/lib/ai-visibility-metrics";
import { queryKeys } from "@/lib/query-keys";
import { researchErrorMessage } from "@/lib/ai-visibility-errors";
import DecisionBrief from "./DecisionBrief";

const PROGRESS: Record<string, number> = {
  queued: 8,
  searching: 25,
  fetching: 40,
  reading: 58,
  validating: 74,
  writing: 88,
  completed: 100,
};

function progressFor(status: string): number {
  return PROGRESS[status] ?? 10;
}

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
              {detail.status === "insufficient_evidence"
                ? ` · ${copy.ownedEvidenceOnly}`
                : ""}
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
          <div className="flex items-center justify-between gap-3">
            <p className="text-[12px] font-semibold text-[var(--ai-ink)]">{stage}</p>
            <span className="font-mono text-[10px] text-[var(--ai-muted)]">
              {progressFor(detail.status)}%
            </span>
          </div>
          <progress
            value={progressFor(detail.status)}
            max={100}
            aria-label={stage}
            className="h-2 w-full overflow-hidden rounded-full accent-[var(--ai-signal)]"
          />
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[9px] uppercase tracking-wide text-[var(--ai-muted)]">
            <span>Scan public pages</span>
            <span>Check claims</span>
            <span>Draft brief</span>
          </div>
          <div className="space-y-2 pt-1">
            <div className="ai-skeleton h-3 w-2/3" />
            <div className="ai-skeleton h-3 w-full" />
          </div>
        </div>
      )}
      {(actionError ||
        (detail.error && detail.status !== "insufficient_evidence")) && (
        <p role="alert" className="rounded-[var(--ai-radius-control)] bg-[var(--ai-sunken)] px-4 py-3 text-[12px] leading-5 text-[var(--ai-danger)]">
          {researchErrorMessage(actionError ?? detail.error)}
        </p>
      )}
      {(detail.status === "completed" ||
        detail.status === "insufficient_evidence") && (
        <DecisionBrief detail={detail} copy={copy} />
      )}
    </div>
  );
}
