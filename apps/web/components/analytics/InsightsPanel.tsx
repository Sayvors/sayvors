"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import {
  fetchProblems,
  fetchProducts,
  fetchTopics,
  fetchMessagingOverview,
  fetchConversationInsights,
  fetchInsightsCards,
  type InsightsCards,
  type MessagingOverview,
  type ProblemsResponse,
  type ProductsResponse,
  type TopicsResponse,
} from "@/lib/api-analytics";
import {
  RangeChannelControls,
  useGoogleChannels,
} from "@/components/analytics/Controls";
import InsightsCardsSection from "@/components/analytics/InsightsCards";
import { useI18n } from "@/lib/i18n/I18nProvider";

type InsightsCopy = ReturnType<typeof useI18n>["t"]["analytics"]["insights"];
type ConversationInsights = Awaited<ReturnType<typeof fetchConversationInsights>>;

function TrendChip({ trend, copy }: { trend: number | null; copy: InsightsCopy }) {
  if (trend === null) {
    return (
      <span className="text-[10px] font-medium text-[var(--ui-ink-2)]">
        {copy.badgeNew}
      </span>
    );
  }
  const up = trend > 0;
  const flat = trend === 0;
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-[2px] px-2 py-0.5 text-[10px] font-semibold ${
        flat
          ? "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]"
          : up
            ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
            : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
      }`}
    >
      {!flat && (
        <svg
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          className={`h-2.5 w-2.5 ${up ? "" : "rotate-180"}`}
          aria-hidden
        >
          <path
            d="M6 10V2M2.5 5.5L6 2l3.5 3.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
      {Math.abs(trend)}%
    </span>
  );
}

function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-8 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]"
          style={{ width: `${95 - i * 8}%` }}
        />
      ))}
    </div>
  );
}

function HeroStat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="min-w-0 flex-1 rounded-[2px] bg-[var(--ui-sunken)] px-3.5 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
        {label}
      </p>
      <p
        className="mt-0.5 truncate text-[15px] font-bold capitalize text-[var(--ui-ink)]"
        title={value}
      >
        {value}
      </p>
      <p className="truncate text-[10px] text-[var(--ui-ink-2)]">{sub}</p>
    </div>
  );
}

const COMPLAINT_AREAS: { key: string; label: string }[] = [
  { key: "waiting_time", label: "Waiting time" },
  { key: "staff_service", label: "Staff & service" },
  { key: "order_accuracy", label: "Order accuracy" },
  { key: "cleanliness", label: "Cleanliness" },
  { key: "price_value", label: "Price & value" },
  { key: "quality", label: "Food / product quality" },
  { key: "other", label: "Other" },
];

function areaLabel(category: string): string {
  return (
    COMPLAINT_AREAS.find((a) => a.key === category)?.label ??
    category.replace(/_/g, " ")
  );
}

function ComplaintsByArea({
  areas,
  days,
  loading,
  copy,
}: {
  areas: import("@/lib/api-analytics").ComplaintArea[];
  days: number;
  loading: boolean;
  copy: InsightsCopy;
}) {
  if (loading) {
    return (
      <section aria-label="Complaints by area" className="ui-card p-5">
        <SkeletonList rows={4} />
      </section>
    );
  }
  const top = areas[0];
  return (
    <section aria-label="Complaints by area" className="ui-card p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">
            Complaints by area
          </h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">
            Last {days} days vs the prior {days}. Ranked by serious incidents,
            then volume.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {top && (
            <span className="rounded-[2px] bg-[var(--ui-sunken)] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
              Main complaint: {areaLabel(top.category)}
            </span>
          )}
          <Link
            href="/dashboard/reviews"
            className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-3 py-1.5 text-[11px] font-bold text-[var(--ui-on-ink)]"
          >
            Read reviews
          </Link>
        </div>
      </div>
      <ul className="space-y-3">
        {areas.map((a) => {
          const max = Math.max(...areas.map((x) => x.mentions), 1);
          return (
            <li key={a.category}>
              <div className="flex items-center gap-2">
                <span className="w-36 shrink-0 truncate text-[12px] font-semibold text-[var(--ui-ink)]">
                  {areaLabel(a.category)}
                </span>
                <span className="relative h-2 flex-1 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                  <span
                    className="absolute inset-y-0 left-0 rounded-full bg-[var(--ui-ink)]"
                    style={{ width: `${Math.max(3, (a.mentions / max) * 100)}%` }}
                  />
                </span>
                <span className="w-8 shrink-0 text-right text-[12px] font-bold tabular-nums text-[var(--ui-ink)]">
                  {a.mentions}
                </span>
                <TrendChip trend={a.trend_pct} copy={copy} />
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 pl-[152px] text-[10px] text-[var(--ui-ink-2)]">
                {a.staff_named > 0 && (
                  <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1.5 py-px font-semibold text-[var(--ui-ink)]">
                    {a.staff_named} staff named
                  </span>
                )}
                {a.serious > 0 && (
                  <span className="rounded-[2px] border border-[var(--ui-line-strong)] px-1.5 py-px font-bold text-[var(--ui-ink)]">
                    {a.serious} serious
                  </span>
                )}
                {a.top_terms.length > 0 && (
                  <span className="truncate">
                    {a.top_terms.map((t) => t.name).join(" · ")}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default function InsightsPanel({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n();
  const copy = t.analytics.insights;
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const channels = useGoogleChannels();
  const queryClient = useQueryClient();

  const insightsQuery = useQuery({
    queryKey: queryKeys.insights.all(days, channelId),
    queryFn: async () => {
      const results = await Promise.allSettled([
        fetchTopics(days, channelId),
        fetchProblems(days, channelId),
        fetchProducts(days, channelId),
        fetchMessagingOverview(days, channelId),
        fetchConversationInsights(),
        fetchInsightsCards(days, channelId),
      ]);
      const fulfilled = results.filter((result) => result.status === "fulfilled");
      if (fulfilled.length === 0) {
        const first = results.find((result) => result.status === "rejected");
        throw first?.status === "rejected"
          ? first.reason
          : new Error("Insights are unavailable.");
      }
      const pick = <T,>(index: number): T | null => {
        const result = results[index];
        return result.status === "fulfilled" ? (result.value as T) : null;
      };
      return {
        topics: pick<TopicsResponse>(0),
        problems: pick<ProblemsResponse>(1),
        products: pick<ProductsResponse>(2),
        messaging: pick<MessagingOverview>(3),
        conversationInsights: pick<ConversationInsights>(4),
        cards: pick<InsightsCards>(5),
        failed: results.length - fulfilled.length,
      };
    },
    staleTime: 30 * 1000,
  });

  const topics = insightsQuery.data?.topics ?? null;
  const problems = insightsQuery.data?.problems ?? null;
  const products = insightsQuery.data?.products ?? null;
  const messaging = insightsQuery.data?.messaging ?? null;
  const conversationInsights =
    insightsQuery.data?.conversationInsights ?? null;
  const cards = insightsQuery.data?.cards ?? null;
  const loading = insightsQuery.isPending;
  const error = insightsQuery.isError && !insightsQuery.data;

  const topicRows = topics?.topics ?? [];
  const problemRows = problems?.problems ?? [];
  const areaRows = problems?.by_area ?? [];
  const productRows = products?.products ?? [];
  const topProblem = [...problemRows].sort(
    (a, b) => b.impact_score - a.impact_score,
  )[0];
  const emergingTopics = topicRows.filter((topic) => topic.emerging).length;

  const hasTopics = topicRows.length > 0;
  const hasProblems = problemRows.length > 0 || areaRows.length > 0;
  const hasProducts = productRows.length > 0;
  const hasCards = Boolean(
    cards &&
      ((cards.top_themes?.length ?? 0) > 0 ||
        (cards.sentiment_by_location?.length ?? 0) > 0 ||
        (cards.summary?.bullets?.length ?? 0) > 0 ||
        (cards.action_plan?.length ?? 0) > 0 ||
        (cards.what_changed?.low_reviews ?? 0) > 0 ||
        (cards.what_changed?.prior_low_reviews ?? 0) > 0 ||
        Boolean(cards.what_changed?.theme)),
  );
  const hasMessaging =
    Boolean(messaging) &&
    ((messaging!.totals.messages_in ?? 0) > 0 ||
      (messaging!.totals.messages_out ?? 0) > 0);
  const hasConversation =
    Boolean(conversationInsights) &&
    (conversationInsights!.message_count ?? 0) > 0;
  const hasAny =
    hasTopics ||
    hasProblems ||
    hasProducts ||
    hasCards ||
    hasMessaging ||
    hasConversation;

  const facts: { label: string; value: string; sub: string }[] = [];
  if (products?.most_loved) {
    facts.push({
      label: copy.mostLoved,
      value: products.most_loved,
      sub: copy.mostLovedSub,
    });
  }
  if (topProblem) {
    facts.push({
      label: copy.fixFirst,
      value: topProblem.name,
      sub: copy.impactMentions
        .replace("{impact}", String(topProblem.impact_score))
        .replace("{mentions}", String(topProblem.mentions)),
    });
  }
  if (products?.fastest_growing) {
    facts.push({
      label: copy.fastestGrowing,
      value: products.fastest_growing,
      sub: copy.fastestGrowingSub,
    });
  }
  if (emergingTopics > 0) {
    facts.push({
      label: copy.emergingTopics,
      value: String(emergingTopics),
      sub: copy.newThisPeriod,
    });
  }

  const retry = () => {
    void queryClient.invalidateQueries({ queryKey: ["insights"] });
  };

  return (
    <div
      className={
        embedded
          ? "h-full overflow-y-auto px-4 pb-4 sm:px-6 sm:pb-6"
          : "space-y-5"
      }
    >
      <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
        <RangeChannelControls
          days={days}
          setDays={(next) => setDays(next)}
          channelId={channelId}
          setChannelId={(next) => setChannelId(next)}
          channels={channels}
        />
      </div>

      {error && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[13px] font-semibold text-[var(--ui-ink-2)]">
            {copy.loadError}
          </p>
          <button
            onClick={retry}
            className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            {copy.retry}
          </button>
        </div>
      ) : loading ? (
        <div className="ui-card space-y-3 p-5" aria-hidden>
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="h-9 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]"
            />
          ))}
        </div>
      ) : (
        <>
          {insightsQuery.data?.failed ? (
            <p className="mb-3 rounded-[2px] bg-[var(--ui-sunken)] px-3 py-2 text-[10.5px] leading-relaxed text-[var(--ui-ink-2)]">
              Some intelligence panels could not load just now. Showing what is
              available.
            </p>
          ) : null}

          {facts.length > 0 ? (
            <div className="ui-card mb-6 flex flex-col gap-2 p-3 sm:flex-row">
              {facts.map((fact) => (
                <HeroStat key={fact.label} {...fact} />
              ))}
            </div>
          ) : null}

          {hasTopics ? (
            <section className="ui-card mb-6 p-5" aria-labelledby="top-topics">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2
                    id="top-topics"
                    className="text-[14px] font-bold text-[var(--ui-ink)]"
                  >
                    {copy.topics}
                  </h2>
                  <p className="text-[11px] text-[var(--ui-ink-2)]">
                    What customers mention, ranked by volume.
                  </p>
                </div>
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">
                  {topicRows.length} tracked
                </span>
              </div>
              <ul className="mt-3 divide-y divide-[var(--ui-line)]">
                {topicRows.slice(0, 8).map((topic) => (
                  <li
                    key={topic.name}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 first:pt-0 last:pb-0"
                  >
                    <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold capitalize text-[var(--ui-ink)]">
                      {topic.name}
                    </span>
                    <span className="shrink-0 text-[10.5px] tabular-nums text-[var(--ui-ink-2)]">
                      {copy.positiveMentions
                        .replace("{percent}", String(topic.positive_pct))
                        .replace("{mentions}", String(topic.mentions))}
                    </span>
                    <TrendChip trend={topic.trend_pct} copy={copy} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {areaRows.length > 0 ? (
            <div className="mb-6">
              <ComplaintsByArea
                areas={areaRows}
                days={days}
                loading={false}
                copy={copy}
              />
            </div>
          ) : null}

          {hasCards ? (
            <div className="mb-6">
              <InsightsCardsSection cards={cards} loading={false} />
            </div>
          ) : null}

          {hasMessaging ? (
            <div className="mb-6">
              <div className="mb-3">
                <h2 className="text-[15px] font-bold text-[var(--ui-ink)]">
                  Conversations
                </h2>
                <p className="text-[11px] text-[var(--ui-ink-2)]">
                  How your team and the AI handled inbound messages.
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <div className="ui-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    AI-handled replies
                  </p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                    {messaging!.totals.ai_handled_out ?? 0}
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                    {messaging!.totals.messages_out > 0
                      ? Math.round(
                          ((messaging!.totals.ai_handled_out ?? 0) /
                            messaging!.totals.messages_out) *
                            100,
                        )
                      : 0}
                    % of outbound
                  </p>
                </div>
                <div className="ui-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    Human-handled replies
                  </p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                    {messaging!.totals.human_handled_out ?? 0}
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                    {messaging!.totals.messages_out > 0
                      ? Math.round(
                          ((messaging!.totals.human_handled_out ?? 0) /
                            messaging!.totals.messages_out) *
                            100,
                        )
                      : 0}
                    % of outbound
                  </p>
                </div>
                <div className="ui-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    Unknown / legacy
                  </p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                    {Math.max(
                      0,
                      (messaging!.totals.messages_out ?? 0) -
                        (messaging!.totals.ai_handled_out ?? 0) -
                        (messaging!.totals.human_handled_out ?? 0),
                    )}
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                    Pre-tracking rows
                  </p>
                </div>
                <div className="ui-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    Total outbound
                  </p>
                  <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                    {messaging!.totals.messages_out ?? 0}
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                    {messaging!.totals.messages_in ?? 0} inbound ·{" "}
                    {messaging!.totals.conversations ?? 0} conversations
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {hasConversation ? (
            <div className="ui-card mb-6 p-5">
              <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">
                What customers ask
              </h2>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                Mined from {conversationInsights!.message_count} inbound
                messages
                {conversationInsights!.computed_at
                  ? ` · updated ${new Date(
                      conversationInsights!.computed_at,
                    ).toLocaleDateString()}`
                  : ""}
              </p>
              {Array.isArray(
                (conversationInsights!.insights as Record<string, unknown>)
                  ?.top_questions,
              ) && (
                <ul className="mt-4 space-y-2">
                  {(
                    (conversationInsights!.insights as Record<string, unknown>)
                      .top_questions as { question: string; count: number }[]
                  )
                    .slice(0, 5)
                    .map((question, index) => (
                      <li
                        key={index}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--ui-ink)]">
                          {question.question}
                        </span>
                        <span className="shrink-0 rounded-[2px] bg-[var(--ui-sunken)] px-2 py-0.5 text-[11px] font-bold tabular-nums text-[var(--ui-ink)]">
                          {question.count}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
              {Array.isArray(
                (conversationInsights!.insights as Record<string, unknown>)
                  ?.intents,
              ) && (
                <div className="mt-4 border-t border-[var(--ui-line)] pt-3">
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    Intents
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(
                      (conversationInsights!.insights as Record<string, unknown>)
                        .intents as { intent: string; count: number }[]
                    )
                      .slice(0, 6)
                      .map((intent, index) => (
                        <span
                          key={index}
                          className="rounded-[2px] bg-[var(--ui-sunken)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink)]"
                        >
                          {intent.intent}{" "}
                          <span className="text-[var(--ui-ink-2)]">
                            ({intent.count})
                          </span>
                        </span>
                      ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}

          {!hasAny ? (
            <div className="ui-card flex flex-col items-center gap-3 px-6 py-12 text-center">
              <p className="text-[14px] font-bold text-[var(--ui-ink)]">
                {copy.emptyTitle}
              </p>
              <p className="max-w-md text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
                {copy.emptyBody}
              </p>
              <Link
                href="/dashboard/reviews"
                className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
              >
                {copy.readReviews}
              </Link>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
