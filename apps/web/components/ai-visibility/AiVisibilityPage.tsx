"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useGoogleChannels } from "@/components/analytics/Controls";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";
import { queryKeys } from "@/lib/query-keys";
import {
  fetchLatestQuerySet,
  startQuerySet,
  type AiVisibilityQuerySetLatest,
} from "@/lib/api-ai-visibility";
import { formatRate } from "@/lib/ai-visibility-metrics";
import { researchErrorMessage } from "@/lib/ai-visibility-errors";
import Modal from "@/components/dashboard/media/Modal";
import AiVisibilitySummary from "./AiVisibilitySummary";
import IntentCoverageChart from "./IntentCoverageChart";
import QuestionResults from "./QuestionResults";
import ResearchFacts from "./ResearchFacts";
import ResearchRunPanel from "./ResearchRunPanel";
import ResearchStatus from "./ResearchStatus";

const QUERY_STALE_TIME = 30_000;
const QUERY_GC_TIME = 5 * 60_000;
const ACTIVE_QUERY_SET_STATUSES = new Set(["generating", "running"]);

type BranchResult = {
  channel: { id: string; label: string };
  data: AiVisibilityQuerySetLatest | null;
  error: Error | null;
};

function isQuerySetNotFound(error: unknown) {
  return error instanceof Error && error.message.includes("query_set_not_found");
}

function querySetStatusLabel(status: string, copy: Dict["aiVisibility"]) {
  if (status === "generating" || status === "running") return copy.running;
  if (status === "partial") return copy.researchPartial;
  return copy.stages[status as keyof typeof copy.stages] ?? status;
}

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

function aggregateResults(rows: BranchResult[]) {
  const items = rows.filter((row): row is BranchResult & { data: AiVisibilityQuerySetLatest } => row.data !== null);
  const completedRuns = items.reduce((sum, row) => sum + row.data.metrics.completed_runs, 0);
  const weightedRate = (field: "mention_rate" | "citation_rate" | "recommendation_rate") =>
    completedRuns > 0
      ? items.reduce(
          (sum, row) => sum + (row.data.metrics[field] ?? 0) * row.data.metrics.completed_runs,
          0,
        ) / completedRuns
      : null;
  const questions = items.flatMap((row) =>
    row.data.questions.map((question) => ({ ...question, channel_label: row.channel.label })),
  );
  const completed = questions.filter(
    (row) => row.status === "completed" || row.status === "insufficient_evidence",
  ).length;
  return {
    items,
    questions,
    summary: {
      completed_runs: completedRuns,
      mention_rate: weightedRate("mention_rate"),
      citation_rate: weightedRate("citation_rate"),
      recommendation_rate: weightedRate("recommendation_rate"),
      active_prompts: questions.length,
      covered_prompts: completed,
      prompt_coverage: questions.length > 0 ? (completed / questions.length) * 100 : null,
      failed_runs: items.reduce((sum, row) => sum + row.data.query_set.failed_questions, 0),
      insufficient_runs: questions.filter((row) => row.status === "insufficient_evidence").length,
      source_count: items.reduce((sum, row) => sum + row.data.metrics.source_count, 0),
      validated_claim_count: items.reduce((sum, row) => sum + row.data.metrics.validated_claim_count, 0),
    },
    coverage: {
      third_party_source_count: items.reduce(
        (sum, row) => sum + Number(row.data.coverage.third_party_source_count ?? 0),
        0,
      ),
      owned_source_count: items.reduce(
        (sum, row) => sum + Number(row.data.coverage.owned_source_count ?? 0),
        0,
      ),
      validated_claim_count: items.reduce(
        (sum, row) => sum + Number(row.data.coverage.validated_claim_count ?? 0),
        0,
      ),
      metrics: {
        platforms_found: items.reduce(
          (sum, row) => sum + Number((row.data.coverage.metrics as Record<string, unknown> | undefined)?.platforms_found ?? 0),
          0,
        ),
      },
    },
  };
}

export default function AiVisibilityPage() {
  const { t } = useI18n();
  const copy = t.aiVisibility;
  const channels = useGoogleChannels();
  const [selectedScope, setSelectedScope] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const queryClient = useQueryClient();
  const firstChannelId = channels[0]?.id ?? null;
  const channelId = useMemo(() => {
    if (selectedScope && selectedScope !== "all" && channels.some((row) => row.id === selectedScope)) {
      return selectedScope;
    }
    return firstChannelId;
  }, [channels, firstChannelId, selectedScope]);
  const isAll = selectedScope === "all";

  const latest = useQuery<AiVisibilityQuerySetLatest | BranchResult[]>({
    queryKey: queryKeys.aiVisibility.latestQuerySet(isAll ? "all" : channelId ?? "none"),
    queryFn: async () => {
      if (isAll) {
        return Promise.all(
          channels.map(async (channel) => {
            try {
              return { channel, data: await fetchLatestQuerySet(channel.id), error: null };
            } catch (error) {
              return {
                channel,
                data: null,
                error: error instanceof Error ? error : new Error(String(error)),
              };
            }
          }),
        );
      }
      return fetchLatestQuerySet(channelId!);
    },
    enabled: !!channelId && (!isAll || channels.length > 0),
    staleTime: QUERY_STALE_TIME,
    gcTime: QUERY_GC_TIME,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const value = query.state.data;
      if (Array.isArray(value)) {
        return value.some(
          (row) => row.data && ACTIVE_QUERY_SET_STATUSES.has(row.data.query_set.status),
        )
          ? 5000
          : false;
      }
      return value && ACTIVE_QUERY_SET_STATUSES.has(value.query_set.status) ? 5000 : false;
    },
  });

  const aggregate = useMemo(
    () => aggregateResults(Array.isArray(latest.data) ? latest.data : []),
    [latest.data],
  );
  const branchResults = Array.isArray(latest.data) ? latest.data : [];
  const aggregateLoadErrors = isAll
    ? branchResults.filter((row) => row.error !== null && !isQuerySetNotFound(row.error))
    : [];
  const allOnlyNotFound =
    isAll &&
    branchResults.length > 0 &&
    aggregate.items.length === 0 &&
    branchResults.every((row) => isQuerySetNotFound(row.error));

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
    void queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.all() });
  };
  const researchBranch = async () => {
    if (isAll) return;
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
  const notFound = !isAll && latest.isError && isQuerySetNotFound(latest.error);
  const branchData =
    !isAll &&
    latest.data &&
    !Array.isArray(latest.data) &&
    latest.data.query_set.channel_id === channelId
      ? latest.data
      : undefined;
  const canResume =
    branchData?.query_set.status === "partial" &&
    branchData.questions.some((question) => question.status === "pending");
  const classification = branchData?.query_set.classification ?? {};
  const uncertainties = Array.isArray(classification.uncertainties)
    ? classification.uncertainties.map(String)
    : [];
  const visibleQuestions = isAll ? aggregate.questions : branchData?.questions ?? [];
  const selectedQuestion = visibleQuestions.find((question) => question.run_id === selectedRunId);
  const selectedQuestionSubtitle = selectedQuestion?.channel_label
    ? `${selectedQuestion.channel_label} · ${selectedQuestion.question_text}`
    : selectedQuestion?.question_text;

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
            value={isAll ? "all" : channelId}
            onChange={(event) => {
              setSelectedScope(event.target.value);
              setSelectedRunId(null);
            }}
            className="ai-control min-w-40 flex-1 px-3 text-[12px] font-semibold"
          >
            <option value="all">{copy.allLocations}</option>
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void researchBranch()}
            disabled={starting || isAll}
            title={isAll ? copy.selectBranchToResearch : copy.tipBranch}
            className="ai-btn-primary w-full px-4 text-[12px] sm:w-auto"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
              <path d="M3 10h3l2-5 4 10 2-5h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {isAll
              ? copy.selectBranchToResearch
              : starting
                ? copy.running
                : canResume
                  ? copy.resumeResearch
                  : copy.researchMyBranch}
          </button>
        </div>
      </header>

      {actionError && (
        <p role="alert" className="rounded-[var(--ai-radius-control)] border border-[var(--ai-danger)] bg-[var(--ai-surface)] px-4 py-3 text-[12px] font-semibold text-[var(--ai-danger)]">
          {researchErrorMessage(actionError)}
        </p>
      )}

      {isAll && !latest.isPending && aggregateLoadErrors.length > 0 && (
        <div className="ai-panel p-5" role="alert">
          <p className="text-[13px] font-semibold text-[var(--ai-danger)]">
            {aggregate.items.length > 0 ? copy.someLocationsLoadError : copy.loadError}
          </p>
          <button type="button" onClick={() => void latest.refetch()} className="mt-2 text-[12px] font-bold underline">
            {copy.retry}
          </button>
        </div>
      )}

      {latest.isPending && !branchData ? (
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
      ) : isAll ? (
        aggregate.items.length > 0 ? (
          <section aria-label={copy.branchResults} className="space-y-5">
            <div>
              <h2 className="text-[24px] font-bold tracking-[-0.02em] text-[var(--ai-ink)]">{copy.allLocations}</h2>
              <p className="mt-1 text-[12px] text-[var(--ai-muted)]">{copy.allLocationsHint}</p>
            </div>
            <AiVisibilitySummary
              data={aggregate.summary}
              isPending={false}
              isError={false}
              onRetry={invalidate}
              copy={copy}
            />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {aggregate.items.map(({ channel, data }) => (
                <article key={channel.id} className="ai-panel flex flex-col gap-3 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[13px] font-bold text-[var(--ai-ink)]">{channel.label}</p>
                      <p className="mt-1 text-[10px] text-[var(--ai-muted)]">
                        {copy.version} {data.query_set.version} · {querySetStatusLabel(data.query_set.status, copy)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedScope(channel.id)}
                      className="min-h-9 text-[11px] font-bold text-[var(--ai-accent)] underline"
                    >
                      {copy.viewBranch}
                    </button>
                  </div>
                  <dl className="grid grid-cols-3 gap-2 text-center">
                    {[
                      [copy.mentionRate, data.metrics.mention_rate],
                      [copy.citationRate, data.metrics.citation_rate],
                      [copy.recommendationRate, data.metrics.recommendation_rate],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded-[var(--ai-radius-control)] bg-[var(--ai-sunken)] px-2 py-2">
                        <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ai-muted)]">{label}</dt>
                        <dd className="mt-1 font-mono text-[14px] font-bold text-[var(--ai-ink)]">{formatRate(value as number | null)}</dd>
                      </div>
                    ))}
                  </dl>
                </article>
              ))}
            </div>
            <QuestionResults
              questions={aggregate.questions}
              selectedRunId={selectedRunId}
              onSelect={setSelectedRunId}
              copy={copy}
              hint={copy.allQuestionsHint}
            />
          </section>
        ) : allOnlyNotFound ? (
          <section className="ai-panel p-6">
            <p className="ai-eyebrow">{copy.noResearchYet}</p>
            <p className="mt-2 text-[13px] text-[var(--ai-muted)]">{copy.noBranchResults}</p>
          </section>
        ) : null
      ) : branchData ? (
        <>
          <ResearchStatus
            status={branchData.query_set.status}
            phase={branchData.query_set.phase}
            version={branchData.query_set.version}
            completed={branchData.query_set.completed_questions}
            total={branchData.query_set.total_questions}
            error={branchData.query_set.error}
            copy={copy}
          />
          <AiVisibilitySummary
            data={summaryData(branchData)}
            isPending={false}
            isError={false}
            onRetry={invalidate}
            copy={copy}
          />
          <ResearchFacts coverage={branchData.coverage} copy={copy} />
          <IntentCoverageChart questions={branchData.questions} copy={copy} />
          <QuestionResults
            questions={branchData.questions}
            selectedRunId={selectedRunId}
            onSelect={setSelectedRunId}
            copy={copy}
          />
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
                {copy.versionHistory}: {branchData.versions.map((row) => `v${row.version} (${querySetStatusLabel(row.status, copy)})`).join(" · ")}
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

      <Modal
        open={selectedRunId !== null}
        onClose={() => setSelectedRunId(null)}
        title={copy.decisionBrief}
        subtitle={selectedQuestionSubtitle}
        width="max-w-[920px]"
        className="rounded-[var(--ai-radius-panel)]"
        closeLabel={copy.close}
      >
        {selectedRunId && (
          <ResearchRunPanel
            runId={selectedRunId}
            copy={copy}
            onRetry={(id) => {
              setSelectedRunId(id);
              invalidate();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
