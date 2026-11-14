"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchFinancials, patchFinance, type FinanceResponse, type FinanceRow } from "@/lib/admin-api";

/* Admin financials: per-tenant monthly finance rows + rollups. Admin marks
 * paid, sets collected amounts and adds extra-cost adjustments/notes. */

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";
const PAGE_SIZE = 50;

const STATUS_CHIP: Record<string, string> = {
  unpaid: "bg-red-100 text-red-700",
  paid: "bg-emerald-100 text-emerald-700",
  partial: "bg-amber-100 text-amber-700",
};

function fmtDollars(cents: number): string {
  return `$${((cents ?? 0) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function fmtMicro(micro: number): string {
  return `$${((micro ?? 0) / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function FinancialsPage() {
  const [month, setMonth] = useState(currentMonth());
  const [items, setItems] = useState<FinanceRow[]>([]);
  const [totals, setTotals] = useState<FinanceResponse["totals"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<FinanceRow | null>(null);
  const [edStatus, setEdStatus] = useState("unpaid");
  const [edCollected, setEdCollected] = useState("");
  const [edExtra, setEdExtra] = useState("");
  const [edNote, setEdNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchFinancials(month, PAGE_SIZE, 0)
      .then((data) => { setItems(data.items ?? []); setTotals(data.totals ?? null); })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load financials."))
      .finally(() => setLoading(false));
  }, [month]);

  useEffect(() => { load(); }, [load]);

  const openEdit = (row: FinanceRow) => {
    setEditing(row);
    setEdStatus(row.status);
    setEdCollected((row.collected_cents / 100).toFixed(2));
    setEdExtra((((row.adjustments?.extra_cost_cents as number) ?? 0) / 100).toFixed(2));
    setEdNote(row.note ?? "");
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    setError(null);
    try {
      const extraCents = Math.round((parseFloat(edExtra) || 0) * 100);
      const collectedCents = Math.round((parseFloat(edCollected) || 0) * 100);
      await patchFinance(editing.tenant_id, month, {
        status: edStatus,
        collected_cents: collectedCents,
        adjustments: { extra_cost_cents: extraCents },
        note: edNote,
      });
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const card = (label: string, value: string, ok = true) => (
    <div className="panel p-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/45">{label}</p>
      <p className={`mt-1 text-[22px] font-black tabular-nums ${ok ? "text-ink" : "text-red-700"}`}>{value}</p>
    </div>
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Financials</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Per-tenant monthly rows: plan price billed, real delivered cost, and what was collected.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(e) => { if (e.target.value) setMonth(e.target.value); }}
            className="h-9 rounded-[2px] border border-[var(--ui-line)] bg-white px-2.5 text-[12px] text-ink outline-none focus:border-deep-violet"
            aria-label="Month"
          />
          <button onClick={load} disabled={loading} className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-50 ${FOCUS_RING}`}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {card("Expected revenue", totals ? fmtDollars(totals.expected_revenue_cents) : "—")}
        {card("Collected", totals ? fmtDollars(totals.collected_cents) : "—")}
        {card("Infra + provider cost", totals ? fmtMicro(totals.infra_cost_micro) : "—")}
        {card("Margin (billed − cost)", totals ? fmtMicro(totals.margin_micro) : "—",
          (totals?.margin_micro ?? 0) >= 0)}
      </div>

      <div className="panel overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--ui-line)] text-left text-[11px] font-semibold uppercase tracking-wide text-ink/50">
              <th className="px-3 py-2">Tenant</th>
              <th className="px-3 py-2">Plan</th>
              <th className="px-3 py-2">Billed</th>
              <th className="px-3 py-2">Credits used</th>
              <th className="px-3 py-2">Actual cost</th>
              <th className="px-3 py-2">Collected</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-ink/40">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-ink/40">No rows for this month.</td></tr>
            ) : (
              items.map((row) => (
                <tr key={`${row.tenant_id}-${row.month}`} className="border-b border-[var(--ui-line)] last:border-0">
                  <td className="px-3 py-2">
                    <p className="font-medium text-ink">{row.email ?? row.tenant_id}</p>
                    <p className="font-mono text-[10px] text-ink/40">{row.tenant_id}</p>
                  </td>
                  <td className="px-3 py-2 text-ink/70">{row.plan_name ?? "—"}</td>
                  <td className="px-3 py-2 font-semibold tabular-nums text-ink">{fmtDollars(row.billed_cents)}</td>
                  <td className="px-3 py-2 text-ink/60 tabular-nums">{fmtDollars(row.credits_used_cents)}</td>
                  <td className="px-3 py-2 text-ink/60 tabular-nums">{fmtMicro(row.actual_cost_micro)}</td>
                  <td className="px-3 py-2 font-semibold tabular-nums text-ink">{fmtDollars(row.collected_cents)}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_CHIP[row.status]}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => openEdit(row)} className="text-[11px] font-semibold text-deep-violet hover:underline">
                      Edit
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button type="button" aria-label="Close" onClick={() => setEditing(null)} className={`absolute inset-0 bg-[var(--ui-scrim)] ${FOCUS_RING}`} />
          <div role="dialog" aria-modal="true" aria-labelledby="finance-title" className="panel relative w-full max-w-md p-5 bg-[var(--ui-surface-solid)]">
            <h2 id="finance-title" className="text-[13px] font-bold text-ink">
              {editing.email ?? editing.tenant_id} · {editing.month}
            </h2>
            <div className="mt-4 space-y-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-ink/60">Payment status</label>
                <select value={edStatus} onChange={(e) => setEdStatus(e.target.value)}
                  className="w-full h-9 rounded-[2px] border border-[var(--ui-line)] bg-white px-2.5 text-[12px] text-ink outline-none focus:border-deep-violet">
                  <option value="unpaid">Unpaid</option>
                  <option value="paid">Paid</option>
                  <option value="partial">Partial</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-ink/60">Collected ($)</label>
                <input value={edCollected} onChange={(e) => setEdCollected(e.target.value)} type="number" min="0" step="0.01"
                  className="w-full h-9 rounded-[2px] border border-[var(--ui-line)] bg-white px-2.5 text-[12px] text-ink outline-none focus:border-deep-violet" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-ink/60">Extra cost / adjustment ($)</label>
                <input value={edExtra} onChange={(e) => setEdExtra(e.target.value)} type="number" step="0.01"
                  className="w-full h-9 rounded-[2px] border border-[var(--ui-line)] bg-white px-2.5 text-[12px] text-ink outline-none focus:border-deep-violet" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-ink/60">Note</label>
                <textarea value={edNote} onChange={(e) => setEdNote(e.target.value)} rows={3} maxLength={1000}
                  className="w-full rounded-[2px] border border-[var(--ui-line)] bg-white px-2.5 py-2 text-[12px] text-ink outline-none focus:border-deep-violet" />
              </div>
            </div>
            <div className="mt-5 flex gap-2">
              <button onClick={save} disabled={saving} className={`rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50 ${FOCUS_RING}`}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button onClick={() => setEditing(null)} className={`rounded-[2px] border border-[var(--ui-line-strong)] px-4 py-2 text-[12px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
