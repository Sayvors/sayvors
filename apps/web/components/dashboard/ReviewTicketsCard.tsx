"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchReviewIssues,
  type ReviewIssue,
} from "@/lib/api-review-issues";
import { useInboxRealtime } from "@/lib/use-inbox-realtime";
import { queryKeys } from "@/lib/query-keys";

/**
 * Review tickets — a compact information card, not a ticket list.
 *
 * Data layer: TanStack Query caches the per-status fetches under a single key
 * so navigating away and back reuses the cache instead of re-downloading.
 * Realtime invalidates the key, which triggers a background refetch.
 */

const STATUSES = ["new", "open", "in_progress", "resolved", "closed"] as const;
const UNRESOLVED = new Set(["new", "open", "in_progress"]);

interface TicketStats {
  total: number;
  unresolved: number;
  waiting: number;
  urgent: number;
  resolved: number;
  oldestTicket: string | null;
  oldestDays: number | null;
}

const EMPTY_STATS: TicketStats = {
  total: 0,
  unresolved: 0,
  waiting: 0,
  urgent: 0,
  resolved: 0,
  oldestTicket: null,
  oldestDays: null,
};

function daysSince(iso: string): number {
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 86_400_000)) : 0;
}

async function fetchTicketStats(): Promise<TicketStats> {
  const responses = await Promise.all(
    STATUSES.map((status) =>
      fetchReviewIssues({ status, ticketed: true, limit: 200 })
    )
  );
  const byStatus = Object.fromEntries(
    STATUSES.map((status, index) => [status, responses[index]])
  ) as Record<string, { issues: ReviewIssue[]; total: number }>;

  const unresolvedIssues = STATUSES.filter((s) => UNRESOLVED.has(s)).flatMap(
    (s) => byStatus[s].issues
  );
  const unresolved = STATUSES.filter((s) => UNRESOLVED.has(s))
    .map((s) => byStatus[s].total)
    .reduce((sum, value) => sum + value, 0);

  const waiting = unresolvedIssues.filter((i) => i.needs_attention).length;
  const urgent = unresolvedIssues.filter(
    (i) => (i.priority === "urgent" || i.priority === "high")
  ).length;
  const oldest = unresolvedIssues.reduce<ReviewIssue | null>(
    (acc, issue) => (!acc || issue.created_at < acc.created_at ? issue : acc),
    null
  );

  return {
    total: Object.values(byStatus).reduce((sum, value) => sum + value.total, 0),
    unresolved,
    waiting,
    urgent,
    resolved: (byStatus.resolved?.total ?? 0) + (byStatus.closed?.total ?? 0),
    oldestTicket: oldest?.ticket_number ?? null,
    oldestDays: oldest ? daysSince(oldest.created_at) : null,
  };
}

export default function ReviewTicketsCard() {
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return (
        typeof window !== "undefined" &&
        window.localStorage.getItem("sayvors.dashboard.reviewTickets.collapsed") === "1"
      );
    } catch {
      return false;
    }
  });

  const { data: stats = EMPTY_STATS, isPending, isError, error } = useQuery({
    queryKey: queryKeys.reviewIssues.all(),
    queryFn: fetchTicketStats,
    staleTime: 30 * 1000,
  });

  // Coalesced realtime invalidation: a new ticket arrives as several events,
  // so debounce before refetching.
  const burst = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshQuietly = useCallback(() => {
    if (burst.current) clearTimeout(burst.current);
    burst.current = setTimeout(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.reviewIssues.all() });
    }, 400);
  }, [queryClient]);

  useEffect(() => () => {
    if (burst.current) clearTimeout(burst.current);
  }, []);

  useInboxRealtime(useCallback((e) => {
    if (e.type === "review_issue") refreshQuietly();
  }, [refreshQuietly]));

  const loading = isPending;
  const errorMessage = isError ? (error instanceof Error ? error.message : "Could not load review tickets.") : null;

  return (
    <section
      aria-label="Review tickets"
      className="rounded-[2px] border border-ink/[0.08] bg-white p-4 shadow-sm shadow-ink/[0.04] dark:border-fog/[0.08] dark:bg-[#1d1636] dark:shadow-none"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <button
          type="button"
          onClick={() =>
            setCollapsed((open) => {
              const next = !open;
              try {
                window.localStorage.setItem(
                  "sayvors.dashboard.reviewTickets.collapsed",
                  next ? "1" : "0",
                );
              } catch {
                /* storage unavailable — this session still toggles */
              }
              return next;
            })
          }
          aria-expanded={!collapsed}
          aria-controls="review-tickets-body"
          className="flex min-w-0 flex-1 items-start gap-2 rounded-[2px] text-left outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:focus-visible:ring-violet-soft/40"
        >
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-[14px] font-bold tracking-wide text-ink dark:text-fog">
                Review tickets
              </span>
              {collapsed && (
                <span className="rounded-[2px] bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold tabular-nums text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50">
                  {stats.unresolved} unresolved · {stats.waiting} waiting on you
                </span>
              )}
            </span>
            <span className="mt-0.5 block max-w-2xl text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
              Customer complaints classified from Google reviews that need action, with
              WhatsApp handoff for the ones needing care. Praise and neutral reviews are not tickets.
            </span>
          </span>
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden
            className={`mt-1 h-4 w-4 shrink-0 text-ink/30 transition-transform dark:text-fog/30 ${collapsed ? "" : "rotate-180"}`}
          >
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <Link
          href="/dashboard/reviews/issues"
          className="shrink-0 rounded-[2px] bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/20 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] dark:focus-visible:ring-violet-soft/40"
        >
          Open ticket queue
        </Link>
      </div>

      <div id="review-tickets-body" hidden={collapsed}>
        {loading && <p className="mt-3 text-[12px] text-ink/55 dark:text-fog/55">Loading tickets…</p>}

        {!loading && errorMessage && (
          <p className="mt-3 text-[12px] font-medium text-coral">
            Ticket queue unavailable: {errorMessage}
          </p>
        )}

        {!loading && !errorMessage && stats.total === 0 && (
          <p className="mt-3 rounded-[2px] border border-dashed border-ink/10 bg-ink/[0.02] px-4 py-4 text-center text-[12px] text-ink/55 dark:border-fog/10 dark:bg-fog/[0.03] dark:text-fog/55">
            No review tickets yet. They appear after a review needs attention.
          </p>
        )}

        {!loading && !errorMessage && stats.total > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span className="text-[22px] font-bold tabular-nums text-ink dark:text-fog">
              {stats.total} ticket{stats.total === 1 ? "" : "s"}
            </span>
            {stats.oldestTicket && (
              <span className="text-[11.5px] text-ink/50 dark:text-fog/50">
                Oldest: <strong className="font-mono text-[11px] text-deep-violet dark:text-violet-soft">{stats.oldestTicket}</strong>
                {stats.oldestDays !== null && (stats.oldestDays === 0 ? " · today" : ` · ${stats.oldestDays}d old`)}
              </span>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
