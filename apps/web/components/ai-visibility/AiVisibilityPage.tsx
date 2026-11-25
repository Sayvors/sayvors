"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { formatRate, isActiveStatus } from "@/lib/ai-visibility-metrics";
import PromptLibrary from "./PromptLibrary";
import ResearchRunPanel from "./ResearchRunPanel";

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
  });
  const prompts = useQuery({
    queryKey: queryKeys.aiVisibility.prompts(channelId ?? "none", false),
    queryFn: () => fetchPrompts(channelId!),
    enabled: !!channelId,
  });
  const runs = useQuery({
    queryKey: queryKeys.aiVisibility.runs(channelId ?? "none", "", "", 20, 0),
    queryFn: () => fetchRuns(channelId!, { limit: 20 }),
    enabled: !!channelId,
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
      <div className="ui-card p-6 text-[13px] text-[var(--ui-ink-2)]">
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
    <div className="space-y-5 p-4 sm:p-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)]">
            {copy.title}
          </h1>
          <p className="mt-1 text-[13px] text-[var(--ui-ink-2)]">
            {copy.subtitle}
          </p>
          <p className="mt-2 max-w-3xl rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink-2)]">
            {copy.disclosure}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            aria-label={copy.branch}
            value={channelId}
            onChange={(event) => setChannelId(event.target.value)}
            className="rounded-[8px] border border-[var(--ui-line)] bg-white px-3 py-2 text-[12px]"
          >
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.label}
              </option>
            ))}
          </select>
          <select
            aria-label={copy.range}
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className="rounded-[8px] border border-[var(--ui-line)] bg-white px-3 py-2 text-[12px]"
          >
            <option value={30}>{copy.range30}</option>
            <option value={90}>{copy.range90}</option>
            <option value={365}>{copy.range365}</option>
            <option value={0}>{copy.rangeAll}</option>
          </select>
          <button
            type="button"
            onClick={() => void runAll()}
            className="rounded-[8px] bg-[var(--ui-ink)] px-3.5 py-2 text-[12px] font-bold text-white"
          >
            {copy.runAll}
          </button>
        </div>
      </header>

      {actionError && (
        <p
          role="alert"
          className="rounded-[8px] border border-red-200 bg-red-50 p-3 text-[12px] text-red-700"
        >
          {actionError}
        </p>
      )}

      <section className="grid gap-3 sm:grid-cols-3" aria-label={copy.evidenceCoverage}>
        {[
          [copy.mentionRate, overview.data?.mention_rate],
          [copy.citationRate, overview.data?.citation_rate],
          [copy.recommendationRate, overview.data?.recommendation_rate],
        ].map(([label, value]) => (
          <div key={label} className="ui-card p-4">
            <p className="text-[11px] font-semibold text-[var(--ui-ink-2)]">
              {label}
            </p>
            <p className="mt-1 text-[24px] font-bold tabular-nums text-[var(--ui-ink)]">
              {formatRate(value as number | null)}
            </p>
          </div>
        ))}
      </section>

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <PromptLibrary
          channelId={channelId}
          copy={copy}
          prompts={prompts.data?.items ?? []}
          suggestions={suggestions}
          selectedId={selectedPromptId}
          onSelect={setSelectedPromptId}
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
        <section className="ui-card p-5">
          <h2 className="text-[15px] font-bold text-[var(--ui-ink)]">
            {copy.answer}
          </h2>
          {selectedPrompt ? (
            <>
              <p className="mt-3 whitespace-pre-wrap text-[13px] text-[var(--ui-ink)]">
                {selectedPrompt.prompt_text}
              </p>
              <button
                type="button"
                onClick={() => void runPrompt(selectedPrompt)}
                className="mt-4 rounded-[8px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-bold text-white"
              >
                {copy.runResearch}
              </button>
            </>
          ) : (
            <p className="mt-3 text-[13px] text-[var(--ui-ink-2)]">
              {copy.noRuns}
            </p>
          )}
          <ResearchRunPanel
            runId={selectedRunId}
            copy={copy}
            onRetry={invalidate}
          />
        </section>
      </div>
    </div>
  );
}
