"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Modal from "@/components/dashboard/media/Modal";
import {
  deleteRun,
  fetchRun,
  fetchRuns,
  retryRun,
  type AiVisibilityRunDetail,
  type AiVisibilityRunListItem,
} from "@/lib/api-ai-visibility";
import { queryKeys } from "@/lib/query-keys";

type Copy = {
  history: string;
  noRuns: string;
  retry: string;
  deleteRun: string;
  confirmDelete: string;
  comparePrevious: string;
  stages: Record<string, string>;
  loading: string;
  loadError: string;
  mentioned: string;
  cited: string;
  all: string;
  cancel: string;
};

export default function RunHistory({
  channelId,
  selectedId,
  copy,
  onSelect,
  onChanged,
}: {
  channelId: string;
  selectedId: string | null;
  copy: Copy;
  onSelect: (id: string) => void;
  onChanged: () => void;
}) {
  const [status, setStatus] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
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
  return (
    <section className="ui-card p-5" aria-label={copy.history}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-bold">{copy.history}</h2>
        <select
          aria-label={copy.history}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded-[8px] border border-[var(--ui-line)] bg-white px-3 py-2 text-[11px]"
        >
          <option value="">{copy.all}</option>
          <option value="completed">{copy.stages.completed}</option>
          <option value="failed">{copy.stages.failed}</option>
          <option value="insufficient_evidence">
            {copy.stages.insufficient_evidence}
          </option>
        </select>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-[12px] text-red-700">
          {error}
        </p>
      )}
      <div className="mt-3 space-y-2">
        {query.data!.items.map((run) => (
          <article
            key={run.id}
            className={`rounded-[8px] border p-3 ${
              selectedId === run.id
                ? "border-[var(--ui-ink)]"
                : "border-[var(--ui-line)]"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(run.id)}
              className="block w-full text-start"
            >
              <span className="block text-[12px] font-bold">
                {run.prompt_title}
              </span>
              <span className="mt-1 block text-[11px] text-[var(--ui-ink-2)]">
                {copy.stages[run.status] ?? run.status} · {run.source_count}{" "}
                {copy.stages.completed.toLowerCase()}
              </span>
            </button>
            <div className="mt-2 flex gap-3 text-[10px] font-bold">
              {run.status === "completed" && (
                <button type="button" onClick={() => void compare(run)}>
                  {copy.comparePrevious}
                </button>
              )}
              {(run.status === "failed" ||
                run.status === "insufficient_evidence") && (
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await retryRun(run.id);
                      await queryClient.invalidateQueries({
                        queryKey: queryKeys.aiVisibility.all(),
                      });
                      onChanged();
                    } catch (exc) {
                      setError(exc instanceof Error ? exc.message : copy.loadError);
                    }
                  }}
                >
                  {copy.retry}
                </button>
              )}
              <button type="button" onClick={() => setDeleting(run.id)}>
                {copy.deleteRun}
              </button>
            </div>
          </article>
        ))}
        {query.data!.items.length === 0 && (
          <p className="text-[12px] text-[var(--ui-ink-2)]">{copy.noRuns}</p>
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
