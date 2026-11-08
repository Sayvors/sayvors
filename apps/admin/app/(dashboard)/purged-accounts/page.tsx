"use client";

import { useCallback, useEffect, useState } from "react";

import {
  fetchPurgedAccounts,
  runUnverifiedPurge,
  type PurgedAccount,
} from "@/lib/admin-api";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";
const PAGE_SIZE = 50;

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function statusStyle(status: PurgedAccount["status"]): string {
  switch (status) {
    case "purged":
      return "bg-emerald-50 text-emerald-700";
    case "failed":
      return "bg-red-50 text-red-700";
    default:
      return "bg-amber-50 text-amber-700";
  }
}

export default function PurgedAccountsPage() {
  const [items, setItems] = useState<PurgedAccount[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPurgedAccounts(PAGE_SIZE, offset, appliedQuery);
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load purged accounts.");
    } finally {
      setLoading(false);
    }
  }, [offset, appliedQuery]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const runNow = async () => {
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const result = await runUnverifiedPurge();
      setNotice(
        result.purged === 0
          ? "No unverified accounts are older than the grace period."
          : `Purged ${result.purged} account(s). Their trace is listed below.`,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not run the purge.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[18px] font-bold tracking-tight text-ink">Purged accounts</h1>
          <p className="mt-0.5 text-[12px] text-ink/45">
            Accounts deleted by the platform, never by the owner. Never-verified
            signups are removed after the grace period; this table is the trace.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void runNow()}
          disabled={running}
          className={`h-9 rounded-[2px] bg-deep-violet px-3 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
        >
          {running ? "Running…" : "Run purge now"}
        </button>
      </div>

      {error && (
        <div role="alert" className="rounded-[2px] border border-red-200 bg-red-50 p-3 text-[12px] text-red-800">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-[2px] border border-sky-200 bg-sky-50 p-3 text-[12px] text-sky-800">
          {notice}
        </div>
      )}

      <section className="panel p-4">
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            setAppliedQuery(query.trim());
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by email"
            className="h-9 w-full max-w-xs rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] text-ink"
          />
          <button
            type="submit"
            className={`h-9 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 text-[12px] font-semibold text-ink ${FOCUS}`}
          >
            Search
          </button>
          <span className="text-[10.5px] text-ink/40">
            {loading ? "Loading…" : `${total.toLocaleString()} record(s)`}
          </span>
        </form>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-[11.5px]">
            <thead>
              <tr className="border-b border-[var(--ui-line)] text-[10px] uppercase tracking-[0.08em] text-ink/40">
                <th className="py-2 pr-3 font-bold">Email</th>
                <th className="py-2 pr-3 font-bold">Name</th>
                <th className="py-2 pr-3 font-bold">Status</th>
                <th className="py-2 pr-3 font-bold">Signed up</th>
                <th className="py-2 pr-3 font-bold">Purged</th>
                <th className="py-2 font-bold">Reason / error</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-[var(--ui-line)]/60 last:border-0">
                  <td className="py-2 pr-3 font-mono text-[11px] text-ink">{item.email}</td>
                  <td className="py-2 pr-3 text-ink/65">
                    {[item.first_name, item.last_name].filter(Boolean).join(" ") || "—"}
                  </td>
                  <td className="py-2 pr-3">
                    <span className={`rounded-full px-1.5 py-0.5 text-[9.5px] font-bold ${statusStyle(item.status)}`}>
                      {item.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-ink/55">{fmtDate(item.signed_up_at)}</td>
                  <td className="py-2 pr-3 text-ink/55">{fmtDate(item.purged_at)}</td>
                  <td className="py-2 text-ink/55">
                    {item.error || item.reason}
                    {item.metadata?.plan ? (
                      <span className="ml-2 text-ink/35">· plan {String(item.metadata.plan)}</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!loading && items.length === 0 && (
          <p className="mt-3 text-[12px] text-ink/45">
            No purged accounts yet. Accounts older than the grace period will appear
            here after the purge worker runs.
          </p>
        )}

        <div className="mt-3 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className={`h-8 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 text-[11px] font-semibold text-ink disabled:opacity-40 ${FOCUS}`}
          >
            Previous
          </button>
          <span className="text-[10.5px] text-ink/40">
            {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of{" "}
            {total.toLocaleString()}
          </span>
          <button
            type="button"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className={`h-8 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 text-[11px] font-semibold text-ink disabled:opacity-40 ${FOCUS}`}
          >
            Next
          </button>
        </div>
      </section>
    </div>
  );
}
