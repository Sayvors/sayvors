"use client";

import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useGoogleChannels } from "@/components/analytics/Controls";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { queryKeys } from "@/lib/query-keys";
import {
  createPrompt,
  createRun,
  fetchOverview,
  fetchPrompts,
  fetchRuns,
} from "@/lib/api-ai-visibility";
import { isActiveStatus } from "@/lib/ai-visibility-metrics";
import { researchErrorMessage } from "@/lib/ai-visibility-errors";
import AiVisibilitySummary from "./AiVisibilitySummary";
import ResearchRunPanel from "./ResearchRunPanel";

const QUERY_STALE_TIME = 30_000;
const QUERY_GC_TIME = 5 * 60_000;

export default function AiVisibilityPage() {
  const { t } = useI18n();
  const copy = t.aiVisibility;
  const channels = useGoogleChannels();
  const [channelId, setChannelId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!channelId && channels[0]) setChannelId(channels[0].id);
  }, [channelId, channels]);

  const overview = useQuery({
    queryKey: queryKeys.aiVisibility.overview(channelId ?? "none", 30),
    queryFn: () => fetchOverview(channelId!, 30),
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

  const branchLabel = useMemo(
    () => channels.find((row) => row.id === channelId)?.label ?? "this branch",
    [channels, channelId],
  );

  if (!channelId) {
    return (
      <div className="ai-visibility-ui h-full overflow-y-auto overscroll-contain p-4 sm:p-6">
        <div className="ai-panel p-6 text-[13px] text-[var(--ai-ink-2)]">
          {channels.length === 0 ? copy.noBranch : copy.loading}
          {channels.length === 0 && (
            <a className="ms-2 font-bold underline" href="/dashboard/locations">
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

  const ensurePrompt = async () => {
    const active = prompts.data?.items.find((row) => row.is_active);
    if (active) return active;
    return createPrompt({
      channel_id: channelId,
      title: "AI visibility check",
      prompt_text: `How visible is ${branchLabel} to AI assistants, and what should be improved?`,
      intent: "visibility",
    });
  };

  const researchBranch = async () => {
    setActionError(null);
    setStarting(true);
    try {
      const prompt = await ensurePrompt();
      const run = await createRun({
        channel_id: channelId,
        prompt_id: prompt.id,
        depth: "quick",
      });
      setSelectedRunId(run.id);
      invalidate();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveError);
    } finally {
      setStarting(false);
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
          <button
            type="button"
            onClick={() => void researchBranch()}
            disabled={starting}
            className="ai-btn-primary w-full px-4 text-[12px] sm:w-auto"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
              <path
                d="M3 10h3l2-5 4 10 2-5h3"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {starting ? copy.running : copy.researchMyBranch}
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
        <div className="mt-6">
          <ResearchRunPanel
            runId={selectedRunId}
            copy={copy}
            onRetry={(id) => {
              setSelectedRunId(id);
              invalidate();
            }}
          />
        </div>
      </section>
    </div>
  );
}
