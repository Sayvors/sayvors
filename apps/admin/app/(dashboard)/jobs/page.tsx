"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  fetchAdminJobs,
  replayAdminJob,
  cancelAdminJob,
  type AdminJob,
} from "@/lib/jobs-api";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function statusStyle(s: string): { pill: string; dot: string; label: string } {
  switch (s) {
    case "succeeded": return { pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200", dot: "bg-emerald-500", label: "Succeeded" };
    case "running": return { pill: "bg-sky-50 text-sky-700 ring-1 ring-sky-200", dot: "bg-sky-500", label: "Running" };
    case "queued": return { pill: "bg-violet-50 text-violet-700 ring-1 ring-violet-200", dot: "bg-violet-500", label: "Queued" };
    case "retrying": return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", dot: "bg-amber-400", label: "Retrying" };
    case "blocked": return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", dot: "bg-amber-400", label: "Blocked" };
    case "failed": return { pill: "bg-red-50 text-red-700 ring-1 ring-red-200", dot: "bg-red-500", label: "Failed" };
    case "dead": return { pill: "bg-red-50 text-red-700 ring-1 ring-red-200", dot: "bg-red-500", label: "Dead" };
    case "cancelled": return { pill: "bg-ink/[0.05] text-ink/50 ring-1 ring-ink/10", dot: "bg-ink/30", label: "Cancelled" };
    default: return { pill: "bg-ink/[0.05] text-ink/50 ring-1 ring-ink/10", dot: "bg-ink/30", label: s };
  }
}

type FilterKey = "all" | "queued" | "running" | "failed" | "dead" | "succeeded";

export default function JobsPage() {
  const [rows, setRows] = useState<AdminJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [lane, setLane] = useState<string>("all");
  const [busy, setBusy] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchAdminJobs({ status: filter === "all" ? undefined : filter, lane: lane === "all" ? undefined : lane, limit: 100 })
      .then((r) => { setRows(r); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Load failed."); setLoading(false); });
  };

  useEffect(() => { load(); }, [filter, lane]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) c[r.status] = (c[r.status] || 0) + 1;
    return c;
  }, [rows]);

  const handleReplay = async (id: string) => {
    setBusy(id);
    try { await replayAdminJob(id); load(); } catch (e) { setError(e instanceof Error ? e.message : "Replay failed."); }
    finally { setBusy(null); }
  };
  const handleCancel = async (id: string) => {
    setBusy(id);
    try { await cancelAdminJob(id); load(); } catch (e) { setError(e instanceof Error ? e.message : "Cancel failed."); }
    finally { setBusy(null); }
  };

  if (loading) {
    return (
      <div className="space-y-4" aria-hidden aria-label="Loading jobs">
        <div className="h-6 w-40 animate-pulse rounded-full bg-[var(--ui-sunken)]" />
        <div className="panel h-64 animate-pulse" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="panel p-10 text-center">
        <p className="text-[14px] font-bold text-ink">{error}</p>
        <button onClick={load} className={`mt-3 rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white ${FOCUS_RING}`}>Retry</button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="admin-rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">Jobs · unified queue</p>
          <h1 className="mt-1 text-[26px] font-bold leading-none tracking-tight text-ink">Job queue</h1>
          <p className="mt-2 max-w-[640px] text-[13px] font-medium leading-relaxed text-ink/60">
            Postgres is the source of truth. Jobs are claimed with FOR UPDATE SKIP LOCKED, leased, and retried with backoff. Dead jobs can be replayed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {counts.dead ? <span className="rounded-full bg-red-50 px-3 py-1.5 text-[11px] font-bold text-red-700 ring-1 ring-red-200">{counts.dead} dead</span> : null}
          {counts.failed ? <span className="rounded-full bg-red-50 px-3 py-1.5 text-[11px] font-bold text-red-700 ring-1 ring-red-200">{counts.failed} failed</span> : null}
          <span className="rounded-full bg-ink/[0.04] px-3 py-1.5 text-[11px] font-bold text-ink/60 ring-1 ring-ink/10">{rows.length} shown</span>
        </div>
      </div>

      <section className="admin-rise panel p-3 sm:p-4" style={{ animationDelay: "60ms" }}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Status filter">
            {(["all", "queued", "running", "failed", "dead", "succeeded"] as FilterKey[]).map((k) => {
              const count = k === "all" ? rows.length : rows.filter((r) => r.status === k).length;
              const active = filter === k;
              return (
                <button
                  key={k}
                  onClick={() => setFilter(k)}
                  aria-pressed={active}
                  className={`rounded-[2px] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition ${active ? "bg-deep-violet text-white" : `text-ink/50 hover:bg-ink/[0.04] hover:text-ink ${FOCUS_RING}`}`}
                >
                  {k} <span className="ml-1 tabular-nums opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
          <select
            value={lane}
            onChange={(e) => setLane(e.target.value)}
            className="rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1.5 text-[11px] font-semibold text-ink/70 focus:border-deep-violet focus:outline-none"
          >
            <option value="all">All lanes</option>
            <option value="realtime">Realtime</option>
            <option value="publishing">Publishing</option>
            <option value="media">Media</option>
            <option value="bulk">Bulk</option>
          </select>
        </div>
      </section>

      <section className="admin-rise panel overflow-hidden" style={{ animationDelay: "120ms" }}>
        {rows.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-[13px] font-semibold text-ink/70">No jobs match</p>
            <p className="mt-1 text-[12px] text-ink/45">Try a different filter.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-[var(--ui-line)] bg-ink/[0.02] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">
                  <th className="px-4 py-2.5">Job</th>
                  <th className="px-4 py-2.5">Type</th>
                  <th className="px-4 py-2.5">Lane</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5 text-right">Attempts</th>
                  <th className="px-4 py-2.5">Tenant</th>
                  <th className="px-4 py-2.5">Created</th>
                  <th className="px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--ui-line)]">
                {rows.map((j) => {
                  const st = statusStyle(j.status);
                  const canReplay = j.status === "dead" || j.status === "failed";
                  const canCancel = j.status === "queued" || j.status === "retrying" || j.status === "blocked";
                  return (
                    <tr key={j.id} className="transition hover:bg-ink/[0.02]">
                      <td className="px-4 py-3 font-mono text-[10px] text-ink/50">{j.id.slice(0, 8)}…</td>
                      <td className="px-4 py-3 text-ink/70">{j.job_type}</td>
                      <td className="px-4 py-3">
                        <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/60">{j.lane}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${st.pill}`}>
                          <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} aria-hidden />
                          {st.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-ink/55">{j.attempts}/{j.max_attempts}</td>
                      <td className="px-4 py-3 font-mono text-[10px] text-ink/40">{j.tenant_id.slice(0, 8)}…</td>
                      <td className="px-4 py-3 tabular-nums text-ink/45">{j.created_at ? new Date(j.created_at).toLocaleString() : "—"}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {canReplay && (
                            <button
                              onClick={() => handleReplay(j.id)}
                              disabled={busy === j.id}
                              className={`rounded-[2px] border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-50 ${FOCUS_RING}`}
                            >
                              Replay
                            </button>
                          )}
                          {canCancel && (
                            <button
                              onClick={() => handleCancel(j.id)}
                              disabled={busy === j.id}
                              className={`rounded-[2px] border border-red-200 bg-red-50 px-2.5 py-1 text-[10px] font-bold text-red-700 transition hover:bg-red-100 disabled:opacity-50 ${FOCUS_RING}`}
                            >
                              Cancel
                            </button>
                          )}
                          {j.last_error && (
                            <span className="ml-1 max-w-[120px] truncate text-[10px] text-ink/35" title={j.last_error}>{j.last_error.slice(0, 40)}</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="pb-2 text-center text-[11px] text-ink/25">
        {rows.length} jobs shown · Postgres is the source of truth · Leases expire after 5 min
      </p>
    </div>
  );
}