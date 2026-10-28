"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import { getBudget, getLedger, type Budget, type TenantBilling, type BillingLedgerEntry } from "@/lib/api-billing";

function fmtCents(c: number): string {
  const sign = c < 0 ? "-" : "";
  const abs = Math.abs(c);
  return `${sign}$${(abs / 100).toFixed(2)}`;
}

function statusStyle(s: TenantBilling["status"]): { pill: string; dot: string; label: string } {
  switch (s) {
    case "debt":
      return { pill: "bg-coral/10 text-coral ring-1 ring-coral/30", dot: "bg-coral", label: "In debt" };
    case "empty":
      return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-900/20 dark:text-amber-300", dot: "bg-amber-400", label: "Empty" };
    case "low":
      return { pill: "bg-sky-50 text-sky-700 ring-1 ring-sky-200 dark:bg-sky-900/20 dark:text-sky-300", dot: "bg-sky-500", label: "Low" };
    default:
      return { pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300", dot: "bg-emerald-500", label: "Healthy" };
  }
}

function kindLabel(k: string): string {
  switch (k) {
    case "ai_usage": return "AI usage";
    case "plan_grant": return "Plan grant";
    case "credit_topup": return "Top-up";
    case "credit_adjust": return "Adjustment";
    case "balance_resync": return "Opening balance";
    case "balance_reconcile": return "Reconcile";
    default: return k;
  }
}

export default function CreditLedgerPage() {
  const [budget, setBudget] = useState<Budget | null>(null);
  const [billing, setBilling] = useState<TenantBilling | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getBudget(), getLedger()])
      .then(([b, bl]) => { if (!cancelled) { setBudget(b); setBilling(bl); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e instanceof Error ? e.message : "Load failed."); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LogoLoader />
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-2xl border border-coral/30 bg-coral/5 p-6 text-center">
          <p className="text-[14px] font-bold text-ink dark:text-fog">{error}</p>
          <p className="mt-1 text-[12px] text-ink/45 dark:text-fog/45">Could not load your credit ledger.</p>
        </div>
      </div>
    );
  }

  const st = billing ? statusStyle(billing.status) : null;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      {/* Header */}
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40 dark:text-fog/40">Billing · AI credit</p>
        <h1 className="mt-1 text-[24px] font-bold tracking-tight text-ink dark:text-fog">Credit ledger</h1>
        <p className="mt-2 max-w-[640px] text-[13px] font-medium leading-relaxed text-ink/60 dark:text-fog/60">
          Your AI credit is held in a durable balance. Every LLM call reserves a small hold, then settles to the real cost.
          Redis is only a cache — deleting it never changes your balance.
        </p>
      </div>

      {/* Wallet cards */}
      <section className="grid gap-3 sm:grid-cols-3">
        {[
          { label: "Available", value: fmtCents(billing?.balance_cents ?? 0), note: st ? st.label : "—", tone: (billing?.balance_cents ?? 0) < 0 ? "text-coral" : "text-ink dark:text-fog" },
          { label: "Held in flight", value: billing && billing.held_cents > 0 ? fmtCents(billing.held_cents) : "—", note: `${billing?.holds.length ?? 0} pending hold${(billing?.holds.length ?? 0) === 1 ? "" : "s"}`, tone: "text-deep-violet dark:text-violet-soft" },
          { label: "Total committed", value: fmtCents(billing?.total_cents ?? 0), note: "Available + held", tone: "text-ink dark:text-fog" },
        ].map((c) => (
          <div key={c.label} className="rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-sm dark:border-fog/[0.06] dark:bg-ink">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40 dark:text-fog/40">{c.label}</p>
            <p className={`mt-2 text-[26px] font-bold tabular-nums leading-none ${c.tone}`}>{c.value}</p>
            <p className="mt-1.5 text-[11px] text-ink/45 dark:text-fog/45">{c.note}</p>
          </div>
        ))}
      </section>

      {/* Plan + status */}
      <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40 dark:text-fog/40">Plan</p>
            <p className="mt-1 text-[18px] font-bold capitalize text-ink dark:text-fog">{budget?.plan ?? "—"}</p>
          </div>
          {st && (
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wide ${st.pill}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} aria-hidden />
              {st.label}
            </span>
          )}
          <Link
            href="/dashboard/billing"
            className="inline-flex items-center gap-1.5 rounded-[14px] bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 active:translate-y-px"
          >
            Manage payment methods
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </Link>
        </div>
      </section>

      {/* Pending holds */}
      {billing && billing.holds.length > 0 && (
        <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
          <h2 className="text-[15px] font-bold text-ink dark:text-fog">Pending holds · {billing.holds.length}</h2>
          <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">Credit reserved by in-flight LLM calls. Released automatically on completion or expiry.</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
                  <th className="px-3 py-2">Hold</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2 text-right">Reserved</th>
                  <th className="px-3 py-2 text-right">Expires</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                {billing.holds.map((h) => (
                  <tr key={h.id}>
                    <td className="px-3 py-2 font-mono text-[10px] text-ink/45 dark:text-fog/45">{h.id.slice(0, 8)}…</td>
                    <td className="px-3 py-2 text-ink/70 dark:text-fog/70">{h.model_id ?? "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-semibold text-deep-violet dark:text-violet-soft">{fmtCents(h.reserved_cents)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/45 dark:text-fog/45">{h.expires_at ? new Date(h.expires_at).toLocaleTimeString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Ledger history */}
      <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
        <h2 className="text-[15px] font-bold text-ink dark:text-fog">Ledger history</h2>
        <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">
          {billing?.ledger.length ?? 0} recent entries. Each AI call is one row: reserved on request, settled to the real cost.
        </p>
        {!billing || billing.ledger.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-ink/[0.1] p-8 text-center dark:border-fog/[0.1]">
            <p className="text-[13px] font-semibold text-ink/70 dark:text-fog/70">No ledger entries yet</p>
            <p className="mx-auto mt-1 max-w-[360px] text-[12px] leading-relaxed text-ink/45 dark:text-fog/45">
              Make an AI call and it will appear here with the reserved hold and the final charge.
            </p>
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">Kind</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2 text-right">Amount</th>
                  <th className="px-3 py-2 text-right">Reserved</th>
                  <th className="px-3 py-2 text-right">Balance after</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                {billing.ledger.map((e: BillingLedgerEntry) => (
                  <tr key={e.id} className="transition hover:bg-ink/[0.02] dark:hover:bg-fog/[0.03]">
                    <td className="px-3 py-2 tabular-nums text-ink/45 dark:text-fog/45">{e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
                    <td className="px-3 py-2">
                      <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/60 dark:bg-fog/[0.08] dark:text-fog/60">{kindLabel(e.kind)}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${e.status === "settled" ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300" : e.status === "pending" ? "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300" : e.status === "released" ? "bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-300" : e.status === "expired" ? "bg-coral/10 text-coral" : "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50"}`}>
                        {e.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-ink/60 dark:text-fog/60">{e.model_id ?? "—"}</td>
                    <td className={`px-3 py-2 text-right tabular-nums font-semibold ${e.amount_cents < 0 ? "text-coral" : e.amount_cents > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-ink/30 dark:text-fog/30"}`}>
                      {e.amount_cents === 0 ? "—" : `${e.amount_cents > 0 ? "+" : ""}${fmtCents(e.amount_cents)}`}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/45 dark:text-fog/45">{e.reserved_cents > 0 ? fmtCents(e.reserved_cents) : "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/60 dark:text-fog/60">{e.balance_after_cents == null ? "—" : fmtCents(e.balance_after_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="pb-2 text-center text-[11px] text-ink/30 dark:text-fog/30">
        Balance is authoritative in Postgres · Redis is a cache · Holds expire after 15 minutes
      </p>
    </div>
  );
}