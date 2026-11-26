"use client";

import { useMemo, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useGoogleChannels } from "@/components/analytics/Controls";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { queryKeys } from "@/lib/query-keys";
import {
  fetchLatestQuerySet,
  startQuerySet,
  type AiVisibilityQuerySetLatest,
} from "@/lib/api-ai-visibility";
import { researchErrorMessage } from "@/lib/ai-visibility-errors";
import AiVisibilitySummary from "./AiVisibilitySummary";
import IntentCoverageChart from "./IntentCoverageChart";
import QuestionResults from "./QuestionResults";
import ResearchFacts from "./ResearchFacts";
import ResearchRunPanel from "./ResearchRunPanel";
import ResearchStatus from "./ResearchStatus";

const QUERY_STALE_TIME = 30_000;
const QUERY_GC_TIME = 5 * 60_000;
const ACTIVE_QUERY_SET_STATUSES = new Set(["generating", "running"]);

function summaryData(data: AiVisibilityQuerySetLatest) {
  const completed = data.questions.filter(
    (row) => row.status === "completed" || row.status === "insufficient_evidence",
  ).length;
  return {
    completed_runs: data.metrics.completed_runs,
    mention_rate: data.metrics.mention_rate,
    citation_rate: data.metrics.citation_rate,
    recommendation_rate: data.metrics.recommendation_rate,
    active_prompts: data.questions.length,
    covered_prompts: completed,
    prompt_coverage:
      data.questions.length > 0 ? (completed / data.questions.length) * 100 : null,
    failed_runs: data.query_set.failed_questions,
    insufficient_runs: data.questions.filter((row) => row.status === "insufficient_evidence").length,
    source_count: data.metrics.source_count,
    validated_claim_count: data.metrics.validated_claim_count,
  };
}

export default function AiVisibilityPage() {
  const { t } = useI18n();
  const copy = t.aiVisibility;
  const channels = useGoogleChannels();
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const queryClient = useQueryClient();
  const channelId = useMemo(() => {
    if (selectedChannelId && channels.some((row) => row.id === selectedChannelId)) {
      return selectedChannelId;
    }
    return channels[0]?.id ?? null;
  }, [channels, selectedChannelId]);

  const latest = useQuery({
    queryKey: queryKeys.aiVisibility.latestQuerySet(channelId ?? "none"),
    queryFn: () => fetchLatestQuerySet(channelId!),
    enabled: !!channelId,
    staleTime: QUERY_STALE_TIME,
    gcTime: QUERY_GC_TIME,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.data && ACTIVE_QUERY_SET_STATUSES.has(query.state.data.query_set.status)
        ? 5000
        : false,
  });

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
      queryKey: queryKeys.aiVisibility.latestQuerySet(channelId),
    });
  };
  const researchBranch = async () => {
    setActionError(null);
    setStarting(true);
    try {
      await startQuerySet({ channel_id: channelId, depth: "quick" });
      setSelectedRunId(null);
      invalidate();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveError);
    } finally {
      setStarting(false);
    }
  };
  const notFound =
    latest.isError &&
    latest.error instanceof Error &&
    latest.error.message.includes("query_set_not_found");
  const data = latest.data;
  const classification = data?.query_set.classification ?? {};
  const uncertainties = Array.isArray(classification.uncertainties)
    ? classification.uncertainties.map(String)
    : [];

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
            onChange={(event) => {
              setSelectedChannelId(event.target.value);
              setSelectedRunId(null);
            }}
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
              <path d="M3 10h3l2-5 4 10 2-5h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {starting ? copy.running : copy.researchMyBranch}
          </button>
        </div>
      </header>

      {actionError && (
        <p role="alert" className="rounded-[var(--ai-radius-control)] border border-[var(--ai-danger)] bg-[var(--ai-surface)] px-4 py-3 text-[12px] font-semibold text-[var(--ai-danger)]">
          {researchErrorMessage(actionError)}
        </p>
      )}

      {latest.isPending && !data ? (
        <div className="ai-panel space-y-3 p-6" role="status" aria-label={copy.loading}>
          <div className="ai-skeleton h-4 w-40" />
          <div className="ai-skeleton h-24 w-full" />
        </div>
      ) : latest.isError && !notFound ? (
        <div className="ai-panel p-5" role="alert">
          <p className="text-[13px] font-semibold text-[var(--ai-danger)]">{copy.loadError}</p>
          <button type="button" onClick={() => void latest.refetch()} className="mt-2 text-[12px] font-bold underline">
            {copy.retry}
          </button>
        </div>
      ) : data ? (
        <>
          <ResearchStatus
            status={data.query_set.status}
            phase={data.query_set.phase}
            version={data.query_set.version}
            completed={data.query_set.completed_questions}
            total={data.query_set.total_questions}
            error={data.query_set.error}
            copy={copy}
          />
          <AiVisibilitySummary
            data={summaryData(data)}
            isPending={false}
            isError={false}
            onRetry={invalidate}
            copy={copy}
          />
          <ResearchFacts coverage={data.coverage} copy={copy} />
          <IntentCoverageChart questions={data.questions} copy={copy} />
          <QuestionResults
            questions={data.questions}
            selectedRunId={selectedRunId}
            onSelect={setSelectedRunId}
            copy={copy}
          />
          {selectedRunId && (
            <section className="ai-panel p-5 sm:p-7">
              <div className="mb-5">
                <p className="ai-eyebrow">{copy.decisionBrief}</p>
                <h2 className="mt-1 text-[20px] font-bold text-[var(--ai-ink)]">{copy.answer}</h2>
              </div>
              <ResearchRunPanel
                runId={selectedRunId}
                copy={copy}
                onRetry={(id) => {
                  setSelectedRunId(id);
                  invalidate();
                }}
              />
            </section>
          )}
          <details className="ai-panel group">
            <summary className="cursor-pointer list-none px-5 py-4 text-[12px] font-bold marker:content-none">
              {copy.classificationTitle}
            </summary>
            <div className="space-y-3 border-t border-[var(--ai-line)] px-5 py-4 text-[12px] text-[var(--ai-ink-2)]">
              <div className="flex flex-wrap gap-x-6 gap-y-2">
                <span>{copy.classificationIndustry}: <strong>{String(classification.industry ?? "—")}</strong></span>
                <span>{copy.classificationType}: <strong>{String(classification.business_type ?? "—")}</strong></span>
                <span>{copy.classificationConfidence}: <strong>{Math.round(Number(classification.confidence ?? 0) * 100)}%</strong></span>
              </div>
              <p>{copy.classificationUncertain}: {uncertainties.length ? uncertainties.join(" · ") : "—"}</p>
              <p className="text-[11px] text-[var(--ai-muted)]">
                {copy.versionHistory}: {data.versions.map((row) => `v${row.version} (${row.status})`).join(" · ")}
              </p>
            </div>
          </details>
        </>
      ) : (
        <section className="ai-panel p-6">
          <p className="ai-eyebrow">{copy.noResearchYet}</p>
          <p className="mt-2 max-w-2xl text-[13px] leading-6 text-[var(--ai-ink-2)]">{copy.noResearchYetBody}</p>
        </section>
      )}
    </div>
  );
}
