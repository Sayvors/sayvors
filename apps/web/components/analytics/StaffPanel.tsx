"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  rankStaff,
  sentimentShares,
  staffVerdict,
  type StaffSummaryLike,
} from "@/lib/staff-performance";

/* Staff performance panel (§33): per-employee review cards, the
 * unassigned-names bucket, and the backfill trigger. Cards link to the full
 * employee profile (picture, contact details, AI analysis, credited reviews).
 *
 * Theme: the analytics tab system's flat style — --ui-* vars, hairlines,
 * no shadows. All copy is merchant-facing and states the promise, never
 * the machinery ("we'll show this name so you can assign it"). */

interface Employee {
  id: string;
  listing_id: string;
  name: string;
  aliases: string[];
  active: boolean;
}

interface SummaryRow extends StaffSummaryLike {
  listing_id: string;
}

const VERDICT_STYLE: Record<string, string> = {
  great: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  good: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  mixed: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
  watch: "bg-red-500/15 text-red-700 dark:text-red-400",
  new: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), s);
}

/** Monochrome weight-ramp sentiment bar, consistent with the other analytics charts. */
function MiniSentimentBar({ positive, neutral, negative, aria }: {
  positive: number; neutral: number; negative: number; aria: string;
}) {
  const total = positive + neutral + negative;
  const seg = (n: number) => (total ? (n / total) * 100 : 0);
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-[var(--ui-sunken)]" role="img" aria-label={aria}>
      <div className="h-full bg-emerald-500" style={{ width: `${seg(positive)}%` }} />
      <div className="h-full bg-[var(--ui-line-strong)]" style={{ width: `${seg(neutral)}%` }} />
      <div className="h-full bg-red-500" style={{ width: `${seg(negative)}%` }} />
    </div>
  );
}

interface UnmatchedName {
  name_normalized: string;
  name_display: string;
  mentions: number;
  latest: string | null;
}

interface ChannelRow {
  id: string;
  platform: string;
  listing_id?: string | null;
  display_name?: string | null;
}

export default function StaffPanel() {
  const { t } = useI18n();
  const sc = t.analytics.staffChart;
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [summary, setSummary] = useState<SummaryRow[]>([]);
  const [unmatched, setUnmatched] = useState<UnmatchedName[]>([]);
  const [branches, setBranches] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [emp, sum, unm, chans] = await Promise.all([
        apiFetch("/api/v1/staff"),
        apiFetch("/api/v1/staff/summary?days=30"),
        apiFetch("/api/v1/staff/unmatched"),
        apiFetch("/api/v1/channels?limit=100"),
      ]);
      setEmployees(emp.employees ?? []);
      setSummary(sum.employees ?? []);
      setUnmatched(unm.names ?? []);
      const google = (chans.channels ?? []).filter(
        (c: ChannelRow) => c.platform === "google_reviews",
      );
      setBranches(
        google.map((c: ChannelRow) => ({
          id: c.listing_id ?? c.id,
          name: c.display_name ?? "Branch",
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Could not load staff data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const runBackfill = async () => {
    setBackfilling(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch("/api/v1/staff/backfill", {
        method: "POST",
        body: JSON.stringify({ days: 90, limit: 300, reextract: false }),
      });
      setNotice(
        `Scanned ${result.scanned} reviews, linked ${result.mentions} mentions. Run again any time — it is safe to repeat.`,
      );
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Backfill failed.");
    } finally {
      setBackfilling(false);
    }
  };

  const assignName = async (nameNormalized: string, staffMemberId: string) => {
    setError(null);
    try {
      const result = await apiFetch("/api/v1/staff/unmatched/assign", {
        method: "POST",
        body: JSON.stringify({ name_normalized: nameNormalized, staff_member_id: staffMemberId }),
      });
      setNotice(`Linked ${result.linked} mention(s) to your employee.`);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Assign failed.");
    }
  };

  const branchName = (listingId: string) =>
    branches.find((b) => b.id === listingId)?.name ?? listingId;

  if (loading) {
    return <p className="py-10 text-center text-[13px] text-[var(--ui-ink-2)]">Loading staff…</p>;
  }

  return (
    <div className="h-full space-y-5 overflow-y-auto px-4 pb-4 sm:px-6 sm:pb-6">
      {notice && (
        <p role="status" className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-2 text-[12px] font-medium text-[var(--ui-ink)]">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-[10px] border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] font-medium text-red-700 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="space-y-5">
          {/* Ranked team chart — who is doing great, who needs attention */}
          {summary.length > 0 && (() => {
            const ranked = rankStaff(summary);
            const verdictCopy: Record<string, string> = {
              great: sc.top,
              good: "",
              mixed: "",
              watch: sc.needsAttention,
              new: sc.newHire,
            };
            return (
              <section aria-labelledby="staff-chart-h" className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4">
                <h3 id="staff-chart-h" className="text-[14px] font-bold text-[var(--ui-ink)]">{sc.title}</h3>
                <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">{sc.subtitle}</p>
                <ul className="mt-4 space-y-3">
                  {ranked.map((row, i) => {
                    const s = sentimentShares(row);
                    const verdict = staffVerdict(row);
                    const badge = verdictCopy[verdict];
                    return (
                      <li key={row.staff_member_id} className="flex items-center gap-3">
                        <span className="w-5 shrink-0 text-center text-[12px] font-bold tabular-nums text-[var(--ui-ink-2)]">{i + 1}</span>
                        <div className="min-w-0 flex-1">
                          <div className="mb-1 flex items-center justify-between gap-2">
                            <Link
                              href={`/dashboard/analytics/staff/${row.staff_member_id}`}
                              className="truncate text-[12.5px] font-bold text-[var(--ui-ink)] hover:underline focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                            >
                              {row.name}
                            </Link>
                            <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-semibold tabular-nums text-[var(--ui-ink-2)]">
                              {badge && (
                                <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${VERDICT_STYLE[verdict]}`}>
                                  {badge}
                                </span>
                              )}
                              {row.avg_rating !== null ? fill(sc.rating, { n: row.avg_rating }) : ""}
                            </span>
                          </div>
                          <MiniSentimentBar
                            positive={row.positive}
                            neutral={row.neutral}
                            negative={row.negative}
                            aria={fill(sc.aria, { name: row.name, positive: s.positive, neutral: s.neutral, negative: s.negative })}
                          />
                          <div className="mt-1 flex justify-between text-[10px] tabular-nums text-[var(--ui-ink-2)]">
                            <span className="text-emerald-600 dark:text-emerald-400">{s.positive}%</span>
                            <span>{s.neutral}%</span>
                            <span className="text-red-600 dark:text-red-400">{s.negative}%</span>
                          </div>
                        </div>
                        <span className="w-16 shrink-0 text-right text-[10px] text-[var(--ui-ink-2)]">
                          {fill(sc.mentions, { n: row.mentions })}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })()}

          {/* Employee cards */}
          {summary.length === 0 ? (
            <p className="rounded-[10px] border border-dashed border-[var(--ui-line)] px-4 py-8 text-center text-[13px] text-[var(--ui-ink-2)]">
              No employees yet — add them on the Team page, then run the backfill below to link past reviews.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {summary.map((row) => (
                <Link
                  key={row.staff_member_id}
                  href={`/dashboard/analytics/staff/${row.staff_member_id}`}
                  className="block rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 text-left transition hover:border-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[14px] font-bold text-[var(--ui-ink)]">{row.name}</span>
                    <span className="shrink-0 text-[12px] font-bold text-[var(--ui-ink)]">
                      {row.avg_rating !== null ? `★${row.avg_rating}` : "—"}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-[var(--ui-ink-2)]">{branchName(row.listing_id)}</p>
                  {(() => {
                    const s = sentimentShares(row);
                    return (
                      <>
                        <div className="mt-3">
                          <MiniSentimentBar
                            positive={row.positive}
                            neutral={row.neutral}
                            negative={row.negative}
                            aria={fill(sc.aria, { name: row.name, positive: s.positive, neutral: s.neutral, negative: s.negative })}
                          />
                          <div className="mt-1 flex justify-between text-[10px] tabular-nums text-[var(--ui-ink-2)]">
                            <span className="text-emerald-600 dark:text-emerald-400">{s.positive}%</span>
                            <span>{s.neutral}%</span>
                            <span className="text-red-600 dark:text-red-400">{s.negative}%</span>
                          </div>
                        </div>
                        <div className="mt-2 flex items-center gap-2 text-[11px] text-[var(--ui-ink-2)]">
                          <span className="font-bold text-[var(--ui-ink)]">{row.mentions}</span> mentions
                          <span className="text-emerald-600">{row.positive}+</span>
                          <span>{row.neutral}~</span>
                          <span className="text-red-600">{row.negative}−</span>
                        </div>
                      </>
                    );
                  })()}
                  <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    {row.trend === "up" ? "▲ trending up" : row.trend === "down" ? "▼ trending down" : "— steady"} vs previous 30d
                  </p>
                </Link>
              ))}
            </div>
          )}

          {/* Backfill */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-[var(--ui-line)] px-4 py-3">
            <p className="text-[12px] text-[var(--ui-ink-2)]">
              Link your last 90 days of reviews to employees. Safe to run again.
            </p>
            <button
              type="button"
              onClick={runBackfill}
              disabled={backfilling}
              className="rounded-[10px] bg-[var(--ui-ink)] px-4 py-1.5 text-[12px] font-bold text-[var(--ui-on-ink)] transition hover:opacity-90 disabled:opacity-50"
            >
              {backfilling ? "Working…" : "Link past reviews"}
            </button>
          </div>

          {/* Unassigned names */}
          <div>
            <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">Names we found but you have not added</h3>
            <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
              Customers mentioned these names. Assign one to an employee, or add them as a new employee — their history links automatically.
            </p>
            {unmatched.length === 0 ? (
              <p className="mt-2 rounded-[10px] border border-dashed border-[var(--ui-line)] px-4 py-6 text-center text-[12px] text-[var(--ui-ink-2)]">
                Nothing to resolve — every mentioned name is on your list.
              </p>
            ) : (
              <ul className="mt-2 space-y-2">
                {unmatched.map((u) => (
                  <li key={u.name_normalized} className="flex flex-wrap items-center gap-2 rounded-[10px] border border-[var(--ui-line)] px-3 py-2.5">
                    <span className="text-[13px] font-bold text-[var(--ui-ink)]">{u.name_display}</span>
                    <span className="text-[11px] text-[var(--ui-ink-2)]">
                      {u.mentions} mention{u.mentions === 1 ? "" : "s"}
                      {u.latest ? ` · last ${new Date(u.latest).toLocaleDateString()}` : ""}
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      <select
                        aria-label={`Assign ${u.name_display} to`}
                        defaultValue=""
                        onChange={(e) => { if (e.target.value) void assignName(u.name_normalized, e.target.value); }}
                        className="rounded-[10px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1.5 text-[12px] text-[var(--ui-ink)]"
                      >
                        <option value="">Assign to…</option>
                        {employees.map((emp) => (
                          <option key={emp.id} value={emp.id}>{emp.name}</option>
                        ))}
                      </select>
                      <Link
                        href={`/dashboard/team?addName=${encodeURIComponent(u.name_display)}`}
                        className="rounded-[10px] border border-[var(--ui-line-strong)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)]"
                      >
                        Add as employee
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
    </div>
  );
}
