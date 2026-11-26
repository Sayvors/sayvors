"use client";

import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useGoogleChannels } from "@/components/analytics/Controls";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { queryKeys } from "@/lib/query-keys";
import {
  createPrompt,
  createRun,
  deletePrompt,
  fetchOverview,
  fetchPrompts,
  fetchRuns,
  updatePrompt,
  type AiVisibilityPrompt,
} from "@/lib/api-ai-visibility";
import { isActiveStatus } from "@/lib/ai-visibility-metrics";
import { researchErrorMessage } from "@/lib/ai-visibility-errors";
import AiVisibilitySummary from "./AiVisibilitySummary";
import PromptLibrary from "./PromptLibrary";
import ResearchRunPanel from "./ResearchRunPanel";
import RunHistory from "./RunHistory";

const QUERY_STALE_TIME = 30_000;
const QUERY_GC_TIME = 5 * 60_000;

export default function AiVisibilityPage() {
  const { t } = useI18n();
  const copy = t.aiVisibility;
  const channels = useGoogleChannels();
  const [channelId, setChannelId] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!channelId && channels[0]) setChannelId(channels[0].id);
  }, [channelId, channels]);

  const overview = useQuery({
    queryKey: queryKeys.aiVisibility.overview(channelId ?? "none", days),
    queryFn: () => fetchOverview(channelId!, days),
    enabled: !!channelId,
    staleTime: QUERY_STALE_TIME,
    gcTime: QUERY_GC_TIME,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  });
  const prompts = useQuery({
    queryKey: queryKeys.aiVisibility.prompts(channelId ?? "none", false),
    queryFn: () => fetchPrompts(channelId!),
    enabled: !!channelId,
    staleTime: QUERY_STALE_TIME,
    gcTime: QUERY_GC_TIME,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  });
  const runs = useQuery({
    queryKey: queryKeys.aiVisibility.runs(channelId ?? "none", "", "", 20, 0),
    queryFn: () => fetchRuns(channelId!, { limit: 20 }),
    enabled: !!channelId,
    staleTime: QUERY_STALE_TIME,
    gcTime: QUERY_GC_TIME,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => isActiveStatus(run.status))
        ? 3000
        : false,
  });

  useEffect(() => {
    const latest =
      runs.data?.items.find((run) => isActiveStatus(run.status)) ??
      runs.data?.items[0];
    if (latest && !selectedRunId) setSelectedRunId(latest.id);
  }, [runs.data, selectedRunId]);

  useEffect(() => {
    const firstActive = prompts.data?.items.find((row) => row.is_active);
    if (firstActive && !selectedPromptId) setSelectedPromptId(firstActive.id);
  }, [prompts.data, selectedPromptId]);

  const selectedPrompt = useMemo(
    () =>
      prompts.data?.items.find((row) => row.id === selectedPromptId) ?? null,
    [prompts.data, selectedPromptId],
  );
  const suggestions = useMemo(() => {
    const branch =
      channels.find((row) => row.id === channelId)?.label ?? "this branch";
    return [
      `What are the best options near ${branch}?`,
      `Is ${branch} recommended by reliable sources?`,
      `Compare ${branch} with nearby alternatives.`,
    ];
  }, [channels, channelId]);

  if (!channelId) {
    return (
      <div className="ai-visibility-ui h-full overflow-y-auto overscroll-contain p-4 sm:p-6">
        <div className="ai-panel p-6 text-[13px] text-[var(--ai-ink-2)]">
        {channels.length === 0 ? copy.noBranch : copy.loading}
        {channels.length === 0 && (
          <a
            className="ms-2 font-bold underline"
            href="/dashboard/locations"
          >
            {copy.connectLocation}
          </a>
        )}
        </div>
      </div>
    );
  }

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.aiVisibility.all(),
    });
  };
  const runPrompt = async (prompt: AiVisibilityPrompt) => {
    setActionError(null);
    try {
      const run = await createRun({
        channel_id: channelId,
        prompt_id: prompt.id,
      });
      setSelectedPromptId(prompt.id);
      setSelectedRunId(run.id);
      invalidate();
      return run;
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveError);
      return null;
    }
  };
  const runAll = async () => {
    const active = prompts.data?.items.filter((row) => row.is_active) ?? [];
    for (let index = 0; index < active.length; index += 3) {
      await Promise.all(active.slice(index, index + 3).map(runPrompt));
    }
  };

  return (
    <div className="ai-visibility-ui h-full space-y-5 overflow-y-auto overscroll-contain p-4 sm:p-6 lg:p-8">
      <header className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="max-w-3xl">
          <p className="ai-eyebrow">{copy.workspaceEyebrow}</p>
          <h1 className="mt-2 text-[32px] font-bold leading-[1.05] tracking-[-0.04em] text-[var(--ai-ink)] sm:text-[40px]">
            {copy.title}
          </h1>
          <p className="mt-3 max-w-2xl text-[14px] leading-6 text-[var(--ai-ink-2)]">
            {copy.subtitle}
          </p>
          <p className="mt-4 max-w-2xl border-s-4 border-[var(--ai-signal)] bg-[var(--ai-surface)] px-4 py-3 text-[12px] leading-5 text-[var(--ai-ink-2)] shadow-[var(--ai-shadow-panel)]">
            {copy.disclosure}
          </p>
        </div>
        <div className="ai-panel flex flex-wrap items-center gap-2 p-3">
          <select
            aria-label={copy.branch}
            title={copy.tipBranch}
            value={channelId}
            onChange={(event) => setChannelId(event.target.value)}
            className="ai-control min-w-40 flex-1 px-3 text-[12px] font-semibold"
          >
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.label}
              </option>
            ))}
          </select>
          <select
            aria-label={copy.range}
            title={copy.tipRange}
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className="ai-control min-w-28 px-3 text-[12px] font-semibold"
          >
            <option value={30}>{copy.range30}</option>
            <option value={90}>{copy.range90}</option>
            <option value={365}>{copy.range365}</option>
            <option value={0}>{copy.rangeAll}</option>
          </select>
          <button
            type="button"
            onClick={() => void runAll()}
            title={copy.tipRunAll}
            disabled={!prompts.data?.items.some((row) => row.is_active)}
            className="ai-btn-primary w-full px-4 text-[12px] sm:w-auto"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
              <path d="M3 10h3l2-5 4 10 2-5h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {copy.runAll}
          </button>
        </div>
      </header>

      {actionError && (
        <p
          role="alert"
          className="rounded-[var(--ai-radius-control)] border border-[var(--ai-danger)] bg-[var(--ai-surface)] px-4 py-3 text-[12px] font-semibold text-[var(--ai-danger)]"
        >
          {researchErrorMessage(actionError)}
        </p>
      )}

      <AiVisibilitySummary
        data={overview.data}
        isPending={overview.isPending}
        isError={overview.isError}
        onRetry={() => void overview.refetch()}
        copy={copy}
      />

      <section className="ai-panel p-5 sm:p-7">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="ai-eyebrow">{copy.decisionBrief}</p>
            <h2 className="mt-1 text-[20px] font-bold tracking-[-0.02em] text-[var(--ai-ink)]">
              {copy.answer}
            </h2>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full border border-[var(--ai-line)] px-3 py-1.5 text-[10px] font-bold text-[var(--ai-muted)]">
            <span className="ai-status-dot" data-tone="ok" />
            Sayvors Grounded AI
          </span>
        </div>
        {selectedPrompt ? (
          <div className="mt-5 flex flex-col gap-4 rounded-[var(--ai-radius-control)] border border-[var(--ai-line)] bg-[var(--ai-sunken)] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="ai-eyebrow">{copy.promptLabel}</p>
              <p className="mt-1 whitespace-pre-wrap text-[13px] leading-6 text-[var(--ai-ink)]">
                {selectedPrompt.prompt_text}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void runPrompt(selectedPrompt)}
              title={copy.tipRun}
              className="ai-btn-primary shrink-0 px-4 text-[12px]"
            >
              {copy.findWithProof}
            </button>
          </div>
        ) : (
          <div className="mt-5 flex items-start gap-4 rounded-[var(--ai-radius-control)] border border-dashed border-[var(--ai-line-strong)] bg-[var(--ai-sunken)] p-5">
            <svg viewBox="0 0 48 48" className="h-12 w-12 shrink-0 text-[var(--ai-accent)]" fill="none" aria-hidden="true">
              <path d="M12 7h18l6 6v28H12V7Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              <path d="M30 7v7h6M18 22h12M18 28h12M18 34h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <div>
              <h3 className="text-[14px] font-bold">{copy.choosePrompt}</h3>
              <p className="mt-1 max-w-md text-[12px] leading-5 text-[var(--ai-ink-2)]">
                {copy.noRuns}
              </p>
            </div>
          </div>
        )}
        <div className="mt-6">
          <ResearchRunPanel
            runId={selectedRunId}
            copy={copy}
            onRetry={invalidate}
          />
        </div>
      </section>

      <details className="ai-panel group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-[13px] font-bold marker:content-none">
          <span>{copy.promptLibrary}</span>
          <span className="text-[11px] font-normal text-[var(--ai-muted)]">
            {prompts.data?.items.length ?? 0}
          </span>
        </summary>
        <div className="border-t border-[var(--ai-line)] p-5">
          <PromptLibrary
            channelId={channelId}
            copy={copy}
            prompts={prompts.data?.items ?? []}
            suggestions={suggestions}
            selectedId={selectedPromptId}
            onSelect={setSelectedPromptId}
            loading={prompts.isPending}
            embedded
            onCreate={async (body) => {
              await createPrompt(body);
              invalidate();
            }}
            onUpdate={async (id, body) => {
              await updatePrompt(id, body);
              invalidate();
            }}
            onDelete={async (id) => {
              await deletePrompt(id);
              invalidate();
            }}
          />
        </div>
      </details>

      <details className="ai-panel group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-[13px] font-bold marker:content-none">
          <span>{copy.history}</span>
          <span className="text-[11px] font-normal text-[var(--ai-muted)]">
            {runs.data?.total ?? 0}
          </span>
        </summary>
        <div className="border-t border-[var(--ai-line)] p-5">
          <RunHistory
            channelId={channelId}
            selectedId={selectedRunId}
            copy={copy}
            loading={runs.isPending}
            embedded
            onSelect={setSelectedRunId}
            onChanged={invalidate}
          />
        </div>
      </details>
    </div>
  );
}
