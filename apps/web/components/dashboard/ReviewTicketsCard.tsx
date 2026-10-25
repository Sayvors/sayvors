"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchReviewIssues,
  type ReviewIssue,
} from "@/lib/api-review-issues";
import { useInboxRealtime } from "@/lib/use-inbox-realtime";

/**
 * Review tickets — a compact information card, not a ticket list.
 *
 * The dashboard answers "how bad is it right now?"; the queue itself lives at
 * /dashboard/reviews/issues. So this card carries the numbers a merchant acts
 * on (unresolved, waiting, urgent, resolved), the status split, and the oldest
 * open ticket — never individual rows.
 */

const STATUSES = ["new", "open", "in_progress", "resolved", "closed"] as const;
const UNRESOLVED = new Set(["new", "open", "in_progress"]);

const label = (value: string) => value.replace(/_/g, " ");

interface TicketStats {
  total: number;
  unresolved: number;
  waiting: number;
  urgent: number;
  resolved: number;
  byStatus: { key: string; count: number }[];
  oldestTicket: string | null;
  oldestDays: number | null;
}

const EMPTY_STATS: TicketStats = {
  total: 0,
  unresolved: 0,
  waiting: 0,
  urgent: 0,
  resolved: 0,
  byStatus: [],
  oldestTicket: null,
  oldestDays: null,
};

function daysSince(iso: string): number {
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 86_400_000)) : 0;
}

export default function ReviewTicketsCard() {
  const [stats, setStats] = useState<TicketStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // A card the merchant checks every day; collapsing it keeps the dashboard
  // scannable without losing the numbers (they stay in the collapsed header).
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

  // `silent` refreshes keep the card mounted: this sits next to the rest of the
  // day's numbers, and a ticket moving must not flash placeholders. The request
  // id guards against a slow first load landing after a newer realtime refresh.
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

      const unresolvedIssues = STATUSES.filter((s) => UNRESOLVED.has(s)).flatMap(
        (s) => byStatus[s].issues
      );
      const unresolved = STATUSES.filter((s) => UNRESOLVED.has(s))
        .map((s) => byStatus[s].total)
        .reduce((sum, value) => sum + value, 0);

      // The API caps a page at 200; counts above that still come from `total`,
      // but per-ticket attributes (attention, urgent, age) use the page.
      const waiting = unresolvedIssues.filter((i) => i.needs_attention).length;
      const urgent = unresolvedIssues.filter(
        (i) => (i.priority === "urgent" || i.priority === "high")
      ).length;
      const oldest = unresolvedIssues.reduce<ReviewIssue | null>(
        (acc, issue) => (!acc || issue.created_at < acc.created_at ? issue : acc),
        null
      );

      setStats({
        total: Object.values(byStatus).reduce((sum, value) => sum + value.total, 0),
        unresolved,
        waiting,
        urgent,
        resolved: (byStatus.resolved?.total ?? 0) + (byStatus.closed?.total ?? 0),
        byStatus: STATUSES.map((key) => ({ key, count: byStatus[key].total })).filter(
          (row) => row.count > 0
        ),
        oldestTicket: oldest?.ticket_number ?? null,
        oldestDays: oldest ? daysSince(oldest.created_at) : null,
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

  // Counts a merchant acts on, refreshed the moment a ticket appears or moves.
  // Coalesced because one new ticket arrives as several events.
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

  const tiles = [
    { key: "unresolved", label: "Unresolved", value: stats.unresolved, tone: "text-coral" },
    { key: "waiting", label: "Waiting on you", value: stats.waiting, tone: "text-amber-600" },
    { key: "urgent", label: "Urgent", value: stats.urgent, tone: stats.urgent > 0 ? "text-red-600" : "text-ink dark:text-fog" },
    { key: "resolved", label: "Resolved", value: stats.resolved, tone: "text-emerald-600" },
  ] as const;

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
        {loading && (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="aspect-square rounded-[2px] bg-ink/[0.03] ring-1 ring-ink/[0.06] dark:bg-fog/[0.04] dark:ring-fog/[0.06]"
              />
            ))}
          </div>
        )}

        {!loading && error && (
          <p className="mt-3 text-[12px] font-medium text-coral">
            Ticket queue unavailable: {error}
          </p>
        )}

        {!loading && !error && stats.total === 0 && (
          <p className="mt-4 rounded-[2px] border border-dashed border-ink/10 bg-ink/[0.02] px-4 py-6 text-center text-[12px] text-ink/55 dark:border-fog/10 dark:bg-fog/[0.03] dark:text-fog/55">
            No review tickets yet. They appear after a review needs attention.
          </p>
        )}

        {!loading && !error && stats.total > 0 && (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch">
            {/* Four fixed squares: the queue in one glance. */}
            <div className="grid shrink-0 grid-cols-2 gap-2">
              {tiles.map((tile) => (
                <div
                  key={tile.key}
                  className="flex h-28 w-28 flex-col justify-between rounded-[2px] border border-ink/[0.06] bg-ink/[0.02] p-2.5 dark:border-fog/[0.06] dark:bg-fog/[0.04]"
                >
                  <span className="text-[10px] font-bold uppercase leading-tight tracking-wide text-ink/45 dark:text-fog/45">
                    {tile.label}
                  </span>
                  <span className={`text-[26px] font-bold leading-none tabular-nums ${tile.tone}`}>
                    {tile.value}
                  </span>
                </div>
              ))}
            </div>

            {/* Status split + the one age that matters, in the rest of the row. */}
            <div className="flex min-w-0 flex-1 flex-col justify-between rounded-[2px] border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.04]">
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                    Status split
                  </span>
                  <span className="text-[10px] font-semibold tabular-nums text-ink/40 dark:text-fog/40">
                    {stats.total} ticket{stats.total === 1 ? "" : "s"}
                  </span>
                </div>
                <div
                  className="mt-2 flex h-2 w-full overflow-hidden rounded-[2px] bg-ink/[0.06] dark:bg-fog/[0.08]"
                  role="img"
                  aria-label={`Status split: ${stats.byStatus.map((s) => `${label(s.key)} ${s.count}`).join(", ")}`}
                >
                  {stats.byStatus.map((row) => (
                    <span
                      key={row.key}
                      className={
                        row.key === "new"
                          ? "bg-coral"
                          : row.key === "open"
                            ? "bg-amber-500"
                            : row.key === "in_progress"
                              ? "bg-deep-violet"
                              : "bg-emerald-600"
                      }
                      style={{ width: `${(row.count / Math.max(1, stats.total)) * 100}%` }}
                    />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink/50 dark:text-fog/50">
                  {stats.byStatus.map((row) => (
                    <span key={row.key} className="inline-flex items-center gap-1.5">
                      <span
                        aria-hidden
                        className={`h-1.5 w-1.5 rounded-full ${
                          row.key === "new"
                            ? "bg-coral"
                            : row.key === "open"
                              ? "bg-amber-500"
                              : row.key === "in_progress"
                                ? "bg-deep-violet"
                                : "bg-emerald-600"
                        }`}
                      />
                      {label(row.key)}{" "}
                      <strong className="tabular-nums text-ink/70 dark:text-fog/70">{row.count}</strong>
                    </span>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-ink/55 dark:text-fog/55">
                  <span>
                    <strong className="tabular-nums text-ink dark:text-fog">{stats.waiting}</strong> of{" "}
                    <strong className="tabular-nums text-ink dark:text-fog">{stats.unresolved}</strong> open
                    need attention
                  </span>
                  {stats.urgent > 0 && (
                    <span className="rounded-[2px] bg-red-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-600 dark:text-red-400">
                      {stats.urgent} urgent
                    </span>
                  )}
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-ink/[0.05] pt-2.5 text-[11.5px] dark:border-fog/[0.06]">
                <span className="text-ink/50 dark:text-fog/50">
                  {stats.oldestTicket ? (
                    <>
                      Oldest open:{" "}
                      <strong className="font-mono text-[11px] text-deep-violet dark:text-violet-soft">
                        {stats.oldestTicket}
                      </strong>
                      {stats.oldestDays !== null && (
                        <> · {stats.oldestDays === 0 ? "today" : `${stats.oldestDays}d old`}</>
                      )}
                    </>
                  ) : (
                    "No open ticket"
                  )}
                </span>
                <Link
                  href="/dashboard/reviews/issues"
                  className="font-semibold text-deep-violet hover:underline dark:text-violet-soft"
                >
                  Open the queue →
                </Link>
              </div>
            </div>
          </div>
        )}

        {!loading && !error && stats.total > 0 && stats.unresolved === 0 && (
          <p className="mt-2 text-[12px] font-medium text-emerald-700 dark:text-emerald-400">
            All review tickets are resolved.
          </p>
        )}
      </div>
    </section>
  );
}
