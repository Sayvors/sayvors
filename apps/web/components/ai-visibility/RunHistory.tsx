"use client";

import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import Modal from "@/components/dashboard/media/Modal";
import {
  deleteRun,
  fetchRun,
  fetchRuns,
  retryRun,
  clearRuns,
  type AiVisibilityRunDetail,
  type AiVisibilityRunListItem,
} from "@/lib/api-ai-visibility";
import { queryKeys } from "@/lib/query-keys";
import { researchErrorMessage } from "@/lib/ai-visibility-errors";

type Copy = {
  history: string;
  historyEyebrow: string;
  tipRetry: string;
  noRuns: string;
  retry: string;
  deleteRun: string;
  clearHistory: string;
  confirmClear: string;
  confirmDelete: string;
  comparePrevious: string;
  stages: Record<string, string>;
  loading: string;
  loadError: string;
  mentioned: string;
  cited: string;
  sources?: string;
  all: string;
  cancel: string;
};

export default function RunHistory({
  channelId,
  selectedId,
  copy,
  onSelect,
  onChanged,
  loading = false,
  embedded = false,
}: {
  channelId: string;
  selectedId: string | null;
  copy: Copy;
  onSelect: (id: string) => void;
  onChanged: () => void;
  loading?: boolean;
  embedded?: boolean;
}) {
  const [status, setStatus] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<{
    current: AiVisibilityRunDetail;
    previous: AiVisibilityRunDetail;
  } | null>(null);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.aiVisibility.runs(channelId, status, "", 50, 0),
    queryFn: () =>
      fetchRuns(channelId, { status: status || undefined, limit: 50 }),
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  });

  const compare = async (run: AiVisibilityRunListItem) => {
    setError(null);
    try {
      const list = await fetchRuns(channelId, {
        promptId: run.prompt_id,
        status: "completed",
        limit: 2,
      });
      const previousId = list.items.find((row) => row.id !== run.id)?.id;
      if (!previousId) return;
      const [current, previous] = await Promise.all([
        fetchRun(run.id),
        fetchRun(previousId),
      ]);
      setComparison({ current, previous });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : copy.loadError);
    }
  };
  const confirmDelete = async () => {
    if (!deleting) return;
    setError(null);
    try {
      await deleteRun(deleting);
      setDeleting(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.aiVisibility.all(),
      });
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : copy.loadError);
    }
  };
  const confirmClear = async () => {
    setError(null);
    try {
      await clearRuns(channelId);
      setClearing(false);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.aiVisibility.all(),
      });
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : copy.loadError);
    }
  };

  if (query.isPending || loading) {
    return (
      <section className={embedded ? "" : "ai-panel p-5 sm:p-6"} aria-label={copy.history}>
        <p className="ai-eyebrow">{copy.historyEyebrow}</p>
        <h2 className="mt-1 text-[18px] font-bold">{copy.history}</h2>
        <div role="status" aria-label={copy.loading} className="mt-4 space-y-2">
          <div className="ai-skeleton h-16 w-full" />
          <div className="ai-skeleton h-16 w-full" />
        </div>
      </section>
    );
  }
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
  return (
    <section className={embedded ? "" : "ai-panel p-5 sm:p-6"} aria-label={copy.history}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="ai-eyebrow">{copy.historyEyebrow}</p>
          <h2 className="mt-1 text-[18px] font-bold tracking-[-0.02em] text-[var(--ai-ink)]">{copy.history}</h2>
        </div>
        <select
          aria-label={copy.history}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="ai-control min-h-10 px-3 text-[11px] font-semibold"
        >
          <option value="">{copy.all}</option>
          <option value="completed">{copy.stages.completed}</option>
          <option value="failed">{copy.stages.failed}</option>
          <option value="insufficient_evidence">
            {copy.stages.insufficient_evidence}
          </option>
        </select>
        <button
          type="button"
          onClick={() => setClearing(true)}
          disabled={query.data?.items.length === 0}
          className="min-h-10 rounded-[var(--ai-radius-control)] border border-[var(--ai-line-strong)] px-3 text-[11px] font-bold text-[var(--ai-danger)] hover:bg-[var(--ai-sunken)]"
        >
          {copy.clearHistory}
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-3 rounded-[var(--ai-radius-control)] bg-[var(--ai-sunken)] px-3 py-2 text-[12px] text-[var(--ai-danger)]">
          {researchErrorMessage(error)}
        </p>
      )}
      <div className="mt-3 space-y-2">
        {query.data!.items.map((run) => (
          <article
            key={run.id}
            className={`rounded-[var(--ai-radius-control)] border p-3 transition-colors ${
              selectedId === run.id
                ? "border-[var(--ai-accent)] bg-[var(--ai-sunken)]"
                : "border-[var(--ai-line)] hover:border-[var(--ai-line-strong)]"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(run.id)}
              className="block w-full text-start"
            >
              <span className="block text-[12px] font-bold text-[var(--ai-ink)]">
                {run.prompt_title}
              </span>
              <span className="mt-1 block font-mono text-[10px] text-[var(--ai-muted)]">
                {copy.stages[run.status] ?? run.status} · {run.source_count} {(copy.sources ?? copy.stages.completed).toLowerCase()}
              </span>
            </button>
            <div className="mt-2 flex flex-wrap gap-1 text-[10px] font-bold">
              {run.status === "completed" && (
                <button type="button" onClick={() => void compare(run)} className="min-h-8 rounded-md px-2 text-[var(--ai-accent)] hover:bg-[var(--ai-surface)]">
                  {copy.comparePrevious}
                </button>
              )}
              {(run.status === "failed" ||
                run.status === "insufficient_evidence") && (
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await retryRun(run.id);                      await queryClient.invalidateQueries({
                        queryKey: queryKeys.aiVisibility.all(),
                      });
                      onChanged();
                    } catch (exc) {
                      setError(exc instanceof Error ? exc.message : copy.loadError);
                    }
                  }}
                  className="min-h-8 rounded-md px-2 text-[var(--ai-accent)] hover:bg-[var(--ai-surface)]"
                  title={copy.tipRetry}
                >
                  {copy.retry}
                </button>
              )}
              <button type="button" onClick={() => setDeleting(run.id)} className="min-h-8 rounded-md px-2 text-[var(--ai-danger)] hover:bg-[var(--ai-surface)]">
                {copy.deleteRun}
              </button>
            </div>
          </article>
        ))}
        {query.data!.items.length === 0 && (
          <p className="text-[12px] leading-5 text-[var(--ai-ink-2)]">{copy.noRuns}</p>
        )}
      </div>

      <Modal
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={copy.deleteRun}
      >
        <p className="text-[13px]">{copy.confirmDelete}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={() => setDeleting(null)}>
            {copy.cancel}
          </button>
          <button
            type="button"
            onClick={() => void confirmDelete()}
            className="rounded-[8px] bg-red-600 px-3.5 py-2 text-[12px] font-bold text-white"
          >
            {copy.deleteRun}
          </button>
        </div>
      </Modal>

      <Modal open={clearing} onClose={() => setClearing(false)} title={copy.clearHistory}>
        <p className="text-[13px]">{copy.confirmClear}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={() => setClearing(false)}>
            {copy.cancel}
          </button>
          <button
            type="button"
            onClick={() => void confirmClear()}
            className="rounded-[8px] bg-red-600 px-3.5 py-2 text-[12px] font-bold text-white"
          >
            {copy.clearHistory}
          </button>
        </div>
      </Modal>

      <Modal
        open={!!comparison}
        onClose={() => setComparison(null)}
        title={copy.comparePrevious}
      >
        {comparison && (
          <div className="space-y-3 text-[12px]">
            {[copy.mentioned, copy.cited].map((label, index) => {
              const key = index === 0 ? "mentioned" : "cited";
              return (
                <p key={key}>
                  {label}: {String(comparison.previous[key])} →{" "}
                  {String(comparison.current[key])}
                </p>
              );
            })}
          </div>
        )}
      </Modal>
    </section>
  );
}
