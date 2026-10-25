"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchReviewIssues,
  type ReviewIssue,
} from "@/lib/api-review-issues";
import { useInboxRealtime } from "@/lib/use-inbox-realtime";

const STATUSES = ["new", "open", "in_progress", "resolved", "closed"] as const;
const UNRESOLVED = new Set(["new", "open", "in_progress"]);

function classifyDemand(issue: ReviewIssue): {
  needsAttention: boolean;
  urgent: boolean;
} {
  return {
    needsAttention: issue.needs_attention && UNRESOLVED.has(issue.status),
    urgent: issue.priority === "urgent" || issue.priority === "high",
  };
}

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function ticketNo(issue: ReviewIssue): string {
  return issue.ticket_number ?? "Unticketed";
}

export default function ReviewTicketsCard() {
  const [issues, setIssues] = useState<ReviewIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState({
    total: 0,
    unresolved: 0,
    waiting: 0,
    resolved: 0,
  });
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // `silent` refreshes keep the card mounted: this sits on the dashboard
  // next to the rest of the day's numbers, and a ticket opening must not
  // make them flash placeholders. The request id guards against a slow
  // first load landing after a newer realtime refresh and overwriting it.
  const requestId = useRef(0);
  const load = useCallback(async (opts?: { silent?: boolean }) => {
    const id = ++requestId.current;
    if (!opts?.silent) setLoading(true);
    setError(null);
    try {
      const responses = await Promise.all(
        STATUSES.map((status) =>
          fetchReviewIssues({ status, ticketed: true, limit: 200 })
        )
      );
      if (id !== requestId.current) return;
      const byStatus = Object.fromEntries(
        STATUSES.map((status, index) => [status, responses[index]])
      ) as Record<string, { issues: ReviewIssue[]; total: number }>;
      const unresolved = STATUSES.filter((status) => UNRESOLVED.has(status))
        .map((status) => byStatus[status].total)
        .reduce((sum, value) => sum + value, 0);
      const resolved = (byStatus.resolved?.total ?? 0) + (byStatus.closed?.total ?? 0);
      const waiting = STATUSES.filter((status) => UNRESOLVED.has(status))
        .flatMap((status) => byStatus[status].issues)
        .filter((issue) => issue.needs_attention).length;
      const recent = STATUSES.filter((status) => UNRESOLVED.has(status))
        .flatMap((status) => byStatus[status].issues)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
        .slice(0, expanded ? 100 : 5);
      setIssues(recent);
      setCounts({
        total: Object.values(byStatus).reduce((sum, value) => sum + value.total, 0),
        unresolved,
        waiting,
        resolved,
      });
    } catch (e) {
      if (id !== requestId.current) return;
      setError(e instanceof Error ? e.message : "Could not load review tickets.");
    } finally {
      if (id === requestId.current && !opts?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Counts a merchant acts on, refreshed the moment a ticket appears or
  // moves. Coalesced because one new ticket arrives as several events.
  const burst = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshQuietly = useCallback(() => {
    if (burst.current) clearTimeout(burst.current);
    burst.current = setTimeout(() => void load({ silent: true }), 400);
  }, [load]);

  useEffect(() => () => {
    if (burst.current) clearTimeout(burst.current);
  }, []);

  useInboxRealtime(useCallback((e) => {
    if (e.type === "review_issue") refreshQuietly();
  }, [refreshQuietly]));

  const allClear = counts.unresolved === 0;

  return (
    <section
      aria-label="Review tickets"
      className="rounded-[2px] border border-ink/[0.08] bg-white p-4 shadow-sm shadow-ink/[0.04] dark:border-fog/[0.08] dark:bg-[#1d1636] dark:shadow-none"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[14px] font-bold tracking-wide text-ink dark:text-fog">
            Review tickets
          </h2>
          <p className="mt-0.5 max-w-2xl text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
            Customer complaints classified from Google reviews that need action, with
            WhatsApp handoff for the ones needing care. Praise and neutral reviews are not tickets.
          </p>
        </div>
        <Link
          href="/dashboard/reviews/issues"
          className="shrink-0 rounded-[2px] bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/20 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] dark:focus-visible:ring-violet-soft/40"
        >
          Open ticket queue
        </Link>
      </div>

      {loading && (
        <div className="mt-4 grid grid-cols-3 gap-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="h-16 rounded-[2px] bg-ink/[0.03] ring-1 ring-ink/[0.06] dark:bg-fog/[0.04] dark:ring-fog/[0.06]"
            />
          ))}
        </div>
      )}

      {!loading && error && (
        <p className="mt-3 text-[12px] font-medium text-coral">
          Ticket queue unavailable: {error}
        </p>
      )}

      {!loading && !error && counts.total === 0 && (
        <p className="mt-4 rounded-[2px] border border-dashed border-ink/10 bg-ink/[0.02] px-4 py-6 text-center text-[12px] text-ink/55 dark:border-fog/10 dark:bg-fog/[0.03] dark:text-fog/55">
          No review tickets yet. They appear after a review needs attention.
        </p>
      )}

      {!loading && !error && counts.total > 0 && (
        <>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <div className="rounded-[2px] border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.04]">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                Unresolved
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums text-coral">
                {counts.unresolved}
              </div>
            </div>
            <div className="rounded-[2px] border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.04]">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                Waiting on you
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums text-amber-600">
                {counts.waiting}
              </div>
            </div>
            <div className="rounded-[2px] border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.04]">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                Resolved
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums text-emerald-600">
                {counts.resolved}
              </div>
            </div>
          </div>

          {issues.length > 0 && (
            <ul className="mt-3 divide-y divide-ink/[0.06] overflow-hidden rounded-[2px] border border-ink/[0.06] bg-ink/[0.01] dark:divide-fog/[0.06] dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              {issues.map((issue) => {
                const { needsAttention } = classifyDemand(issue);
                return (
                  <li key={issue.id}>
                    <Link
                      href="/dashboard/reviews/issues"
                      aria-label={`Open review ticket queue for ${ticketNo(issue)}`}
                      className="block px-3 py-2.5 outline-none transition hover:bg-ink/[0.03] focus-visible:bg-ink/[0.05] dark:hover:bg-fog/[0.04] dark:focus-visible:bg-fog/[0.06]"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[11px] font-bold text-deep-violet dark:text-violet-soft">
                          {ticketNo(issue)}
                        </span>
                        <span className="text-[11px] font-medium text-ink/60 dark:text-fog/60">
                          {label(issue.subcategory)}
                        </span>
                        {needsAttention && (
                          <span className="rounded-[2px] bg-coral/10 px-2 py-0.5 text-[10px] font-bold text-coral">
                            needs attention
                          </span>
                        )}
                        <span className="ml-auto text-[10px] font-medium uppercase tracking-wide text-ink/40 dark:text-fog/40">
                          {label(issue.status)}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-1 text-[12px] text-ink/70 dark:text-fog/70">
                        {issue.summary || issue.review_text || "No summary yet."}
                      </p>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}

          {issues.length > 0 && !expanded && counts.unresolved > 5 && (
            <button
              onClick={() => setExpanded(true)}
              className="mt-2 text-[12px] font-semibold text-deep-violet hover:underline dark:text-violet-soft"
            >
              Show more ({counts.unresolved - 5} more)
            </button>
          )}

          {issues.length > 0 && (
            <Link
              href="/dashboard/reviews/issues"
              className="mt-2 inline-block text-[12px] font-semibold text-deep-violet hover:underline dark:text-violet-soft"
            >
              Show all tickets →
            </Link>
          )}

          {counts.unresolved === 0 && (
            <p className="mt-3 text-[12px] font-medium text-emerald-700 dark:text-emerald-400">
              All review tickets are resolved.
            </p>
          )}
        </>
      )}
    </section>
  );
}