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
} from "@/lib/api-analytics";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";
import { useI18n } from "@/lib/i18n/I18nProvider";

type InsightsCopy = ReturnType<typeof useI18n>["t"]["analytics"]["insights"];

function TrendChip({ trend, copy }: { trend: number | null; copy: InsightsCopy }) {
  if (trend === null) {
    return <span className="text-[10px] font-medium text-[var(--ui-ink-2)]">{copy.badgeNew}</span>;
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
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2.5 w-2.5 ${up ? "" : "rotate-180"}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {Math.abs(trend)}%
    </span>
  );
}

const SEVERITY_BADGE: Record<string, string> = {
  high: "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]",
  medium: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  low: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

/** Severity / status arrive from the API as English slugs — label them here. */
function severityLabel(severity: string, copy: InsightsCopy): string {
  if (severity === "high") return copy.severityHigh;
  if (severity === "medium") return copy.severityMedium;
  if (severity === "low") return copy.severityLow;
  return severity;
}

function statusLabel(status: string, copy: InsightsCopy): string {
  if (status === "emerging") return copy.statusEmerging;
  if (status === "increasing") return copy.statusIncreasing;
  if (status === "decreasing") return copy.statusDecreasing;
  if (status === "recurring") return copy.statusRecurring;
  return status;
}

function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" style={{ width: `${95 - i * 8}%` }} />
      ))}
    </div>
  );
}

function HeroStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="min-w-0 flex-1 rounded-[2px] bg-[var(--ui-sunken)] px-3.5 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{label}</p>
      <p className="mt-0.5 truncate text-[15px] font-bold capitalize text-[var(--ui-ink)]" title={value}>{value}</p>
      <p className="truncate text-[10px] text-[var(--ui-ink-2)]">{sub}</p>
    </div>
  );
}

function MomentumBars({
  items,
  days,
  copy,
}: {
  items: { name: string; trend: number | null }[];
  days: number;
  copy: InsightsCopy;
}) {
  const movers = items
    .filter((t) => t.trend !== null && t.trend !== 0)
    .sort((a, b) => Math.abs(b.trend as number) - Math.abs(a.trend as number))
    .slice(0, 6);
  if (movers.length === 0) return null;
  const max = Math.max(...movers.map((m) => Math.abs(m.trend as number)), 1);
  return (
    <section aria-label={copy.momentum} className="ui-card p-5">
      <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">{copy.momentum}</h3>
      <p className="text-[11px] text-[var(--ui-ink-2)]">{copy.momentumSub.replace("{days}", String(days))}</p>
      <ul className="mt-3 space-y-2">
        {movers.map((m) => {
          const v = m.trend as number;
          const up = v > 0;
          return (
            <li key={m.name} className="flex items-center gap-2">
              <span className="w-28 shrink-0 truncate text-right text-[11px] font-semibold capitalize text-[var(--ui-ink-2)]">{m.name}</span>
              <span className="relative h-4 flex-1 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                <span className="absolute left-1/2 top-0 h-full w-px bg-[var(--ui-line-strong)]" aria-hidden />
                <span
                  className={`absolute top-1 h-2 rounded-full ${up ? "bg-[var(--ui-ink)]" : "bg-[var(--ui-ink-2)]"}`}
                  style={up
                    ? { left: "50%", width: `${Math.max(2, (v / max) * 48)}%` }
                    : { right: "50%", width: `${Math.max(2, (Math.abs(v) / max) * 48)}%` }}
                />
              </span>
              <span className={`w-12 shrink-0 text-[11px] font-bold tabular-nums ${up ? "text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}`}>
                {up ? "+" : ""}{v}%
              </span>
            </li>
          );
        })}
      </ul>
    </section>
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
  return COMPLAINT_AREAS.find((a) => a.key === category)?.label ?? category.replace(/_/g, " ");
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
          <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">Complaints by area</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">
            Last {days} days vs the prior {days}. Ranked by serious incidents, then volume.
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
      {areas.length === 0 ? (
        <div className="py-6 text-center">
          <p className="text-[12px] font-semibold text-[var(--ui-ink)]">{copy.noProblemsTitle}</p>
          <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{copy.noProblemsBody}</p>
        </div>
      ) : (
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
      )}
    </section>
  );
}

export default function InsightsPage() {
  const { t } = useI18n();
  const copy = t.analytics.insights;
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const channels = useGoogleChannels();
  const queryClient = useQueryClient();

  const insightsQuery = useQuery({
    queryKey: queryKeys.insights.all(days, channelId),
    queryFn: async () => {
      const [t, p, pr, m, ci] = await Promise.all([
        fetchTopics(days, channelId),
        fetchProblems(days, channelId),
        fetchProducts(days, channelId),
        fetchMessagingOverview(days, channelId),
        fetchConversationInsights(),
      ]);
      return { topics: t, problems: p, products: pr, messaging: m, conversationInsights: ci };
    },
    staleTime: 30 * 1000,
  });
  const topics = insightsQuery.data?.topics ?? null;
  const problems = insightsQuery.data?.problems ?? null;
  const products = insightsQuery.data?.products ?? null;
  const messaging = insightsQuery.data?.messaging ?? null;
  const conversationInsights = insightsQuery.data?.conversationInsights ?? null;
  const loading = insightsQuery.isPending;
  const error = insightsQuery.isError && !insightsQuery.data;

  const hasData = !!topics && topics.topics.length > 0;

  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">{copy.title}</h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">{copy.subtitle}</p>
        </div>
        <RangeChannelControls
          days={days}
          setDays={(d) => {
            setDays(d);
          }}
          channelId={channelId}
          setChannelId={(c) => {
            setChannelId(c);
          }}
          channels={channels}
        />
      </div>

      {error && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[13px] font-semibold text-[var(--ui-ink-2)]">{copy.loadError}</p>
          <button
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ["insights"] });
            }}
            className="ui-btn rounded-[2px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)]"
          >
            {copy.retry}
          </button>
        </div>
      ) : !hasData && !loading ? (
        <div className="ui-card flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-[14px] font-bold text-[var(--ui-ink)]">{copy.emptyTitle}</p>
          <p className="max-w-sm text-[12px] text-[var(--ui-ink-2)]">{copy.emptyBody}</p>
        </div>
      ) : (
        <>
          {/* At-a-glance: best, worst, fastest-moving */}
          {(() => {
            const emergingTopics = (topics?.topics ?? []).filter((t) => t.emerging).length;
            const topProblem = [...(problems?.problems ?? [])].sort((a, b) => b.impact_score - a.impact_score)[0];
            return (
              <div className="ui-card mb-6 flex flex-col gap-2 p-3 sm:flex-row">
                <HeroStat
                  label={copy.mostLoved}
                  value={products?.most_loved ?? "—"}
                  sub={copy.mostLovedSub}
                />
                <HeroStat
                  label={copy.fixFirst}
                  value={topProblem?.name ?? (problems && problems.problems.length === 0 ? copy.nothingAllClear : "—")}
                  sub={
                    topProblem
                      ? copy.impactMentions
                          .replace("{impact}", String(topProblem.impact_score))
                          .replace("{mentions}", String(topProblem.mentions))
                      : copy.noProblemsDetected
                  }
                />
                <HeroStat
                  label={copy.fastestGrowing}
                  value={products?.fastest_growing ?? "—"}
                  sub={copy.fastestGrowingSub}
                />
                <HeroStat
                  label={copy.emergingTopics}
                  value={loading ? "…" : String(emergingTopics)}
                  sub={copy.newThisPeriod}
                />
              </div>
            );
          })()}
          <div className="mb-6">
            <ComplaintsByArea
              areas={problems?.by_area ?? []}
              days={days}
              loading={loading}
              copy={copy}
            />
          </div>
          <div className="mb-3 mt-2 flex items-end justify-between">
            <div>
              <h2 className="text-[15px] font-bold text-[var(--ui-ink)]">Conversations</h2>
              <p className="text-[11px] text-[var(--ui-ink-2)]">How your team and the AI handled inbound messages.</p>
            </div>
          </div>
          {messaging && (messaging.totals.messages_out ?? 0) > 0 && (
            <div className="mb-6 grid gap-3 sm:grid-cols-4">
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">AI-handled replies</p>
                <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{messaging.totals.ai_handled_out ?? 0}</p>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                  {messaging.totals.messages_out > 0 ? Math.round(((messaging.totals.ai_handled_out ?? 0) / messaging.totals.messages_out) * 100) : 0}% of outbound
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Human-handled replies</p>
                <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{messaging.totals.human_handled_out ?? 0}</p>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                  {messaging.totals.messages_out > 0 ? Math.round(((messaging.totals.human_handled_out ?? 0) / messaging.totals.messages_out) * 100) : 0}% of outbound
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Unknown / legacy</p>
                <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                  {Math.max(0, (messaging.totals.messages_out ?? 0) - (messaging.totals.ai_handled_out ?? 0) - (messaging.totals.human_handled_out ?? 0))}
                </p>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                  Pre-migration rows (not tracked)
                </p>
              </div>
              <div className="ui-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Total outbound</p>
                <p className="mt-1 text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{messaging.totals.messages_out ?? 0}</p>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                  {messaging.totals.messages_in ?? 0} inbound · {messaging.totals.conversations ?? 0} conversations
                </p>
              </div>
            </div>
          )}
          {conversationInsights && conversationInsights.message_count > 0 && (
            <div className="mb-6 ui-card p-5">
              <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">What customers ask</h3>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                Mined from {conversationInsights.message_count} inbound messages
                {conversationInsights.computed_at ? ` · updated ${new Date(conversationInsights.computed_at).toLocaleDateString()}` : ""}
              </p>
              {Array.isArray((conversationInsights.insights as Record<string, unknown>)?.top_questions) && (
                <ul className="mt-4 space-y-2">
                  {((conversationInsights.insights as Record<string, unknown>).top_questions as { question: string; count: number }[]).slice(0, 5).map((q, i) => (
                    <li key={i} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--ui-ink)]">{q.question}</span>
                      <span className="shrink-0 rounded-[2px] bg-[var(--ui-sunken)] px-2 py-0.5 text-[11px] font-bold tabular-nums text-[var(--ui-ink)]">{q.count}</span>
                    </li>
                  ))}
                </ul>
              )}
              {Array.isArray((conversationInsights.insights as Record<string, unknown>)?.intents) && (
                <div className="mt-4 border-t border-[var(--ui-line)] pt-3">
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Intents</p>
                  <div className="flex flex-wrap gap-2">
                    {((conversationInsights.insights as Record<string, unknown>).intents as { intent: string; count: number }[]).slice(0, 6).map((intent, i) => (
                      <span key={i} className="rounded-[2px] bg-[var(--ui-sunken)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink)]">
                        {intent.intent} <span className="text-[var(--ui-ink-2)]">({intent.count})</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="mb-3 mt-2 flex items-end justify-between">
            <div>
              <h2 className="text-[15px] font-bold text-[var(--ui-ink)]">Themes</h2>
              <p className="text-[11px] text-[var(--ui-ink-2)]">What customers talk about, what breaks, and which products stand out.</p>
            </div>
          </div>
          <div className="grid gap-5 sm:gap-6 lg:grid-cols-3">
          {/* Topics */}
          <section aria-label={copy.topics} className="ui-card p-5">
            <h3 className="mb-4 text-[14px] font-bold text-[var(--ui-ink)]">{copy.topics}</h3>
            {loading || !topics ? (
              <SkeletonList />
            ) : topics.topics.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{copy.noTopics}</p>
            ) : (
              <ul className="space-y-3">
                {topics.topics.slice(0, 8).map((t) => {
                  const total = Math.max(1, t.positive + t.neutral + t.negative);
                  return (
                    <li key={t.name} className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-1.5 truncate text-[12px] font-semibold capitalize text-[var(--ui-ink)]">
                          {t.name}
                          {t.emerging && (
                            <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1 py-px text-[9px] font-bold uppercase text-[var(--ui-ink)]">{copy.badgeNew}</span>
                          )}
                        </p>
                        <div
                          className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-[var(--ui-sunken)]"
                          role="img"
                          aria-label={copy.sentimentSplit
                            .replace("{positive}", String(t.positive))
                            .replace("{neutral}", String(t.neutral))
                            .replace("{negative}", String(t.negative))}
                        >
                          <div className="h-full bg-[var(--ui-ink)]" style={{ width: `${(t.positive / total) * 100}%` }} />
                          <div className="h-full bg-[var(--ui-ink-2)]" style={{ width: `${(t.neutral / total) * 100}%` }} />
                          <div className="h-full bg-[var(--ui-line-strong)]" style={{ width: `${(t.negative / total) * 100}%` }} />
                        </div>
                      </div>
                      <span className="text-[11px] tabular-nums text-[var(--ui-ink-2)]">{t.mentions}</span>
                      <TrendChip trend={t.trend_pct} copy={copy} />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Problems */}
          <section aria-label={copy.problems} className="ui-card p-5">
            <h3 className="mb-4 text-[14px] font-bold text-[var(--ui-ink)]">{copy.problems}</h3>
            {loading || !problems ? (
              <SkeletonList />
            ) : problems.problems.length === 0 ? (
              <div className="py-6 text-center">
                <p className="text-[12px] font-semibold text-[var(--ui-ink)]">{copy.noProblemsTitle}</p>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{copy.noProblemsBody}</p>
              </div>
            ) : (
              <ul className="space-y-3">
                {problems.problems.slice(0, 8).map((p) => (
                  <li key={p.name} className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-1.5 truncate text-[12px] font-semibold capitalize text-[var(--ui-ink)]">
                        {p.name}
                        <span className={`rounded px-1 py-px text-[9px] font-bold uppercase ${SEVERITY_BADGE[p.severity]}`}>
                          {severityLabel(p.severity, copy)}
                        </span>
                      </p>
                      <p className="text-[10px] text-[var(--ui-ink-2)]">
                        {statusLabel(p.status, copy)} · {copy.impactMentions
                          .replace("{impact}", String(p.impact_score))
                          .replace("{mentions}", String(p.mentions))}
                      </p>
                    </div>
                    <span className="text-[11px] tabular-nums text-[var(--ui-ink-2)]">{p.mentions}</span>
                    <TrendChip trend={p.trend_pct} copy={copy} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Products */}
          <section aria-label={copy.productsServices} className="ui-card p-5">
            <h3 className="mb-4 text-[14px] font-bold text-[var(--ui-ink)]">{copy.productsServices}</h3>
            {loading || !products ? (
              <SkeletonList />
            ) : products.products.length === 0 ? (
              <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{copy.noProducts}</p>
            ) : (
              <ul className="space-y-3">
                {products.products.slice(0, 8).map((p) => {
                  const loved = p.name === products.most_loved;
                  const criticized = p.name === products.most_criticized;
                  const growing = p.name === products.fastest_growing;
                  return (
                    <li key={p.name} className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-center gap-1.5 text-[12px] font-semibold capitalize text-[var(--ui-ink)]">
                          {p.name}
                          {loved && <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1 py-px text-[9px] font-bold uppercase text-[var(--ui-ink)]">{copy.badgeLoved}</span>}
                          {criticized && <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1 py-px text-[9px] font-bold uppercase text-[var(--ui-ink)]">{copy.badgeCriticized}</span>}
                          {growing && <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1 py-px text-[9px] font-bold uppercase text-[var(--ui-ink)]">{copy.badgeRising}</span>}
                          {p.emerging && <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1 py-px text-[9px] font-bold uppercase text-[var(--ui-ink)]">{copy.badgeNew}</span>}
                        </p>
                        <p className="text-[10px] text-[var(--ui-ink-2)]">
                          {copy.positiveMentions
                            .replace("{percent}", String(p.positive_pct))
                            .replace("{mentions}", String(p.mentions))}
                          {p.avg_rating !== null && ` · ${copy.avgRating.replace("{rating}", String(p.avg_rating))}`}
                        </p>
                      </div>
                      <TrendChip trend={p.trend_pct} copy={copy} />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
        {!loading && (topics || products) && (
          <div className="mt-6">
            <MomentumBars
              days={days}
              copy={copy}
              items={[
                ...(topics?.topics ?? []).map((t) => ({ name: t.name, trend: t.trend_pct })),
                ...(products?.products ?? []).map((p) => ({ name: p.name, trend: p.trend_pct })),
              ]}
            />
          </div>
        )}
        </>
      )}
    </div>
  );
}
