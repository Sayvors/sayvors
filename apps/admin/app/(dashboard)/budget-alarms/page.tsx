"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBudgetAlarms, type BudgetAlarm } from "@/lib/admin-api";

/* AI-credit alarm list: tenants whose wallet is low, empty, or in debt,
 * worst first. Same status classification as the billing overview. */

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

type Filter = "all" | "low" | "empty" | "debt";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All alarms" },
  { id: "low", label: "Low" },
  { id: "empty", label: "Empty" },
  { id: "debt", label: "Debt" },
];

const STATUS_CHIP: Record<string, string> = {
  low: "bg-amber-100 text-amber-700",
  empty: "bg-orange-100 text-orange-700",
  debt: "bg-red-100 text-red-700",
};

const PAGE_SIZE = 50;

function fmtDollars(cents: number): string {
  return `$${((cents ?? 0) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function BudgetAlarmsPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<BudgetAlarm[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchBudgetAlarms(filter, PAGE_SIZE, offset)
      .then((data) => { setItems(data.items ?? []); setTotal(data.total ?? 0); })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load budget alarms."))
      .finally(() => setLoading(false));
  }, [filter, offset]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Budget alarms</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Tenants whose AI-credit wallet is low, empty, or in debt — worst first.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => { setFilter(f.id); setOffset(0); }}
              className={`rounded-[2px] px-3 py-1.5 text-[11px] font-semibold capitalize transition ${
                filter === f.id
                  ? "bg-deep-violet text-white"
                  : "border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] text-ink/60 hover:border-deep-violet hover:text-deep-violet"
              } ${FOCUS_RING}`}
            >
              {f.label}
              {f.id !== "all" && items.filter((i) => i.status === f.id).length > 0
                ? ` (${items.filter((i) => i.status === f.id).length})`
                : ""}
            </button>
          ))}
          <button onClick={load} disabled={loading} className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-50 ${FOCUS_RING}`}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--ui-line)] text-left text-[11px] font-semibold uppercase tracking-wide text-ink/50">
              <th className="px-3 py-2">Tenant</th>
              <th className="px-3 py-2">Plan</th>
              <th className="px-3 py-2">Balance</th>
              <th className="px-3 py-2">Held</th>
              <th className="px-3 py-2">Total committed</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-ink/40">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-ink/40">No tenants match this filter.</td></tr>
            ) : (
              items.map((item) => (
                <tr key={item.tenant_id} className="border-b border-[var(--ui-line)] last:border-0">
                  <td className="px-3 py-2">
                    <p className="font-medium text-ink">{item.email ?? item.tenant_id}</p>
                    <p className="font-mono text-[10px] text-ink/40">{item.tenant_id}</p>
                  </td>
                  <td className="px-3 py-2 text-ink/70">{item.plan_name}</td>
                  <td className="px-3 py-2 font-semibold tabular-nums text-ink">{fmtDollars(item.balance_cents)}</td>
                  <td className="px-3 py-2 text-ink/60 tabular-nums">{fmtDollars(item.held_cents)}</td>
                  <td className="px-3 py-2 text-ink/60 tabular-nums">{fmtDollars(item.total_cents)}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_CHIP[item.status] ?? "bg-ink/[0.06] text-ink/50"}`}>
                      {item.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-[11px] text-ink/50">
          <span>{total} tenant(s) total</span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              disabled={offset === 0}
              className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-40 ${FOCUS_RING}`}
            >
              ← Prev
            </button>
            <button
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total}
              className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-40 ${FOCUS_RING}`}
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
