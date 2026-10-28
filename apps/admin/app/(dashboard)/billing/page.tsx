"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  fetchBillingOverview,
  type BillingOverviewRow,
} from "@/lib/billing-api";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function fmtCents(c: number): string {
  const sign = c < 0 ? "-" : "";
  const abs = Math.abs(c);
  const dollars = (abs / 100).toFixed(2);
  return `${sign}$${dollars}`;
}

function statusStyle(s: BillingOverviewRow["status"]): { pill: string; dot: string; label: string } {
  switch (s) {
    case "debt":
      return { pill: "bg-red-50 text-red-700 ring-1 ring-red-200", dot: "bg-red-500", label: "Debt" };
    case "empty":
      return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", dot: "bg-amber-400", label: "Empty" };
    case "low":
      return { pill: "bg-sky-50 text-sky-700 ring-1 ring-sky-200", dot: "bg-sky-500", label: "Low" };
    default:
      return { pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200", dot: "bg-emerald-500", label: "Healthy" };
  }
}

type FilterKey = "all" | "debt" | "empty" | "low" | "ok";

export default function BillingOverviewPage() {
  const [rows, setRows] = useState<BillingOverviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<"balance" | "held" | "email">("balance");

  useEffect(() => {
    let cancelled = false;
    fetchBillingOverview()
      .then((r) => { if (!cancelled) { setRows(r); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e instanceof Error ? e.message : "Load failed."); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = rows.filter((r) => {
      if (filter !== "all" && r.status !== filter) return false;
      if (!q) return true;
      return r.email.toLowerCase().includes(q) || r.tenant_id.toLowerCase().includes(q);
    });
    out = [...out].sort((a, b) => {
      if (sort === "balance") return a.balance_cents - b.balance_cents;
      if (sort === "held") return b.held_cents - a.held_cents;
      return a.email.localeCompare(b.email);
    });
    return out;
  }, [rows, query, filter, sort]);

  const totals = useMemo(() => {
    return rows.reduce(
      (acc, r) => {
        acc.tenants += 1;
        acc.available += r.balance_cents;
        acc.held += r.held_cents;
        if (r.status === "debt") acc.debt += 1;
        if (r.status === "empty") acc.empty += 1;
        if (r.status === "low") acc.low += 1;
        return acc;
      },
      { tenants: 0, available: 0, held: 0, debt: 0, empty: 0, low: 0 },
    );
  }, [rows]);

  if (loading) {
    return (
      <div className="space-y-4" aria-hidden aria-label="Loading billing">
        <div className="h-6 w-48 animate-pulse rounded-full bg-[var(--ui-sunken)]" />
        <div className="grid gap-3 sm:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="panel h-24 animate-pulse" />)}
        </div>
        <div className="panel h-64 animate-pulse" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="panel p-10 text-center">
        <p className="text-[14px] font-bold text-ink">{error}</p>
        <p className="mt-1 text-[12px] text-ink/45">Could not load billing overview.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* ── header ─────────────────────────────────────────── */}
      <div className="admin-rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">Billing · AI credit ledger</p>
          <h1 className="mt-1 text-[26px] font-bold leading-none tracking-tight text-ink">Wallets &amp; ledger</h1>
          <p className="mt-2 max-w-[640px] text-[13px] font-medium leading-relaxed text-ink/60">
            Postgres is the source of truth. Available balance is what a tenant can spend right now; held credit is
            reserved by in-flight LLM calls. A negative balance is real debt, not a display quirk.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-[11px] font-bold text-emerald-700 ring-1 ring-emerald-200">
            {totals.tenants} tenants
          </span>
          {totals.debt > 0 && (
            <span className="rounded-full bg-red-50 px-3 py-1.5 text-[11px] font-bold text-red-700 ring-1 ring-red-200">
              {totals.debt} in debt
            </span>
          )}
        </div>
      </div>

      {/* ── summary cards ──────────────────────────────────── */}
      <section className="admin-rise grid gap-3 sm:grid-cols-2 lg:grid-cols-4" style={{ animationDelay: "60ms" }}>
        {[
          { label: "Available credit", value: fmtCents(totals.available), note: "Sum of all tenant wallets", tone: "text-ink" },
          { label: "Held in flight", value: fmtCents(totals.held), note: "Reserved by pending calls", tone: "text-deep-violet" },
          { label: "Total committed", value: fmtCents(totals.available + totals.held), note: "Available + held", tone: "text-ink" },
          { label: "Attention", value: `${totals.debt + totals.empty + totals.low}`, note: `${totals.debt} debt · ${totals.empty} empty · ${totals.low} low`, tone: totals.debt > 0 ? "text-red-600" : "text-ink" },
        ].map((c) => (
          <div key={c.label} className="panel p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">{c.label}</p>
            <p className={`mt-2 text-[24px] font-bold tabular-nums leading-none ${c.tone}`}>{c.value}</p>
            <p className="mt-1.5 text-[11px] text-ink/45">{c.note}</p>
          </div>
        ))}
      </section>

      {/* ── filters ────────────────────────────────────────── */}
      <section className="admin-rise panel p-3 sm:p-4" style={{ animationDelay: "120ms" }}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Status filter">
            {(["all", "debt", "empty", "low", "ok"] as FilterKey[]).map((k) => {
              const count = k === "all" ? rows.length : rows.filter((r) => r.status === k).length;
              const active = filter === k;
              return (
                <button
                  key={k}
                  onClick={() => setFilter(k)}
                  aria-pressed={active}
                  className={`rounded-[2px] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition ${active ? "bg-deep-violet text-white" : `text-ink/50 hover:bg-ink/[0.04] hover:text-ink ${FOCUS_RING}`}`}
                >
                  {k === "all" ? "All" : k === "ok" ? "Healthy" : k} <span className="ml-1 tabular-nums opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search email or tenant id…"
              className="w-full rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] text-ink placeholder:text-ink/30 focus:border-deep-violet focus:outline-none sm:w-64"
            />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "balance" | "held" | "email")}
              className="rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1.5 text-[11px] font-semibold text-ink/70 focus:border-deep-violet focus:outline-none"
            >
              <option value="balance">Sort: balance ↑</option>
              <option value="held">Sort: held ↓</option>
              <option value="email">Sort: email</option>
            </select>
          </div>
        </div>
      </section>

      {/* ── table ──────────────────────────────────────────── */}
      <section className="admin-rise panel overflow-hidden" style={{ animationDelay: "180ms" }}>
        {filtered.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-[13px] font-semibold text-ink/70">No tenants match</p>
            <p className="mt-1 text-[12px] text-ink/45">Try a different filter or search term.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-[var(--ui-line)] bg-ink/[0.02] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">
                  <th className="px-4 py-2.5">Tenant</th>
                  <th className="px-4 py-2.5">Plan</th>
                  <th className="px-4 py-2.5 text-right">Available</th>
                  <th className="px-4 py-2.5 text-right">Held</th>
                  <th className="px-4 py-2.5 text-right">Total</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--ui-line)]">
                {filtered.map((r) => {
                  const st = statusStyle(r.status);
                  return (
                    <tr key={r.tenant_id} className="transition hover:bg-ink/[0.02]">
                      <td className="px-4 py-3">
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-ink" title={r.email}>{r.email}</p>
                          <p className="truncate font-mono text-[10px] text-ink/35" title={r.tenant_id}>{r.tenant_id.slice(0, 8)}…{r.tenant_id.slice(-4)}</p>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/60">{r.plan}</span>
                      </td>
                      <td className={`px-4 py-3 text-right tabular-nums font-bold ${r.balance_cents < 0 ? "text-red-600" : "text-ink"}`}>
                        {fmtCents(r.balance_cents)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-ink/55">
                        {r.held_cents > 0 ? fmtCents(r.held_cents) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink/80">
                        {fmtCents(r.total_cents)}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${st.pill}`}>
                          <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} aria-hidden />
                          {st.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/tenants/${encodeURIComponent(r.tenant_id)}#billing`}
                          className={`inline-flex items-center gap-1 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2.5 py-1 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
                        >
                          Ledger
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        </Link>
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
        {filtered.length} of {rows.length} tenants shown · Balances are authoritative in Postgres · Redis is a cache
      </p>
    </div>
  );
}