"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import {
  getLedger,
  type BillingLedgerEntry,
  type LedgerSort,
  type TenantBilling,
} from "@/lib/api-billing";

/** Rows per page. Small enough to stay readable on a phone. */
const PAGE_SIZE = 20;

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

const PURPOSE_LABELS: Record<string, string> = {
  "review_engine.generate": "Review reply",
  "review_engine.analysis": "Review analysis",
  "review_engine.relevance_judge": "Review relevance",
  "analytics.enrichment": "Review enrichment",
  "analytics.meaning": "Review meaning",
  "analytics.intelligence": "Analytics insight",
  "analytics.summary": "Analytics summary",
  "analytics.mine_conversations": "Conversation mining",
  "analytics.abuse_triage": "Abuse triage",
  "conversation.context": "Conversation context",
  "review.qa": "Review Q&A",
  "review_request.template": "Review request",
  "chat.message": "Assistant chat",
  "assistant.chat": "Assistant chat",
  "posts.ai_draft": "Post draft",
  "memory.extract": "Memory extraction",
  "databank.business_profile": "Business profile",
  "databank.ask": "Databank answer",
  "whatsapp.render_style": "Reply style",
  "whatsapp.thread_stats": "Thread stats",
  "instagram.caption_suggest": "Instagram caption",
  meta_voice_note: "Voice note",
  "voice.tts": "Text to speech",
  "tts.job": "Text to speech",
  "admin.test": "Admin test",
};

function purposeLabel(purpose: string | null): string | null {
  if (!purpose) return null;
  return PURPOSE_LABELS[purpose] ?? purpose.replaceAll("_", " ").replaceAll(".", " · ");
}

function statusPillClass(status: string): string {
  if (status === "settled") return "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300";
  if (status === "pending") return "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300";
  if (status === "released") return "bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-300";
  if (status === "expired") return "bg-coral/10 text-coral";
  return "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50";
}

function amountText(cents: number): string {
  return cents === 0 ? "—" : `${cents > 0 ? "+" : ""}${fmtCents(cents)}`;
}

function amountTone(cents: number): string {
  if (cents < 0) return "text-coral";
  if (cents > 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-ink/30 dark:text-fog/30";
}

const SORT_OPTIONS: { value: LedgerSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "cost_high", label: "Highest cost" },
  { value: "cost_low", label: "Lowest cost" },
];

export default function CreditLedgerPage() {
  const [billing, setBilling] = useState<TenantBilling | null>(null);
  const [sort, setSort] = useState<LedgerSort>("newest");
  const [offset, setOffset] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [pageLoading, setPageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // One page at a time. Sorting and paging refetch only the ledger slice;
  // the wallet cards above stay stable while the request is in flight.
  useEffect(() => {
    let cancelled = false;
    setPageLoading(true);
    getLedger({ limit: PAGE_SIZE, offset, sort })
      .then((bl) => {
        if (cancelled) return;
        setBilling(bl);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Load failed.");
      })
      .finally(() => {
        if (cancelled) return;
        setPageLoading(false);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset, sort, reloadKey]);

  // A deleted row (or a stale page in another tab) can leave the offset past
  // the end. Snap back to the last page that still has entries.
  useEffect(() => {
    if (!billing || offset === 0 || offset < billing.total) return;
    setOffset(Math.max(0, Math.floor((billing.total - 1) / PAGE_SIZE) * PAGE_SIZE));
  }, [billing, offset]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LogoLoader />
      </div>
    );
  }
  if (!billing) {
    return (
      <div className="p-6">
        <div className="rounded-2xl border border-coral/30 bg-coral/5 p-6 text-center">
          <p className="text-[14px] font-bold text-ink dark:text-fog">{error ?? "Load failed."}</p>
          <p className="mt-1 text-[12px] text-ink/45 dark:text-fog/45">Could not load your credit ledger.</p>
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            className="mt-4 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  const st = statusStyle(billing.status);
  const total = billing.total ?? billing.ledger.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const firstRow = total === 0 ? 0 : offset + 1;
  const lastRow = Math.min(offset + billing.ledger.length, total);

  return (
    <div className="mx-auto h-full max-w-5xl space-y-6 overflow-y-auto p-4 pb-24 sm:p-6 sm:pb-8">
      {/* Header */}
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40 dark:text-fog/40">Billing · AI credit</p>
        <h1 className="mt-1 text-[24px] font-bold tracking-tight text-ink dark:text-fog">Credit ledger</h1>
        <p className="mt-2 max-w-[640px] text-[13px] font-medium leading-relaxed text-ink/60 dark:text-fog/60">
          Your AI credit is held in a durable balance. Every LLM call reserves a small hold, then settles to the real cost.
          Redis is only a cache — deleting it never changes your balance.
        </p>
        <p className="mt-2 max-w-[640px] text-[12px] font-medium leading-relaxed text-ink/45 dark:text-fog/45">
          The “Used for” column shows what consumed the credit: review analysis, reply generation, assistant chat, and so on.
          Review enrichment runs on imported reviews even when every review already has a reply.
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
            <p className="mt-1 text-[18px] font-bold capitalize text-ink dark:text-fog">{billing.plan}</p>
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
                  <th className="px-3 py-2 text-right">Reserved</th>
                  <th className="px-3 py-2 text-right">Expires</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                {billing.holds.map((h) => (
                  <tr key={h.id}>
                    <td className="px-3 py-2 font-mono text-[10px] text-ink/45 dark:text-fog/45">{h.id.slice(0, 8)}…</td>
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
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">Ledger history</h2>
            <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">
              {total} {total === 1 ? "entry" : "entries"}. Each AI call is one row: reserved on request, settled to the real cost.
            </p>
          </div>
          <label className="flex shrink-0 items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">
              Sort
            </span>
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as LedgerSort);
                setOffset(0);
              }}
              aria-label="Sort ledger entries"
              className="h-9 flex-1 rounded-xl border border-ink/[0.08] bg-white px-2.5 text-[12px] font-semibold text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog sm:flex-none"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
        </div>

        {error && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-coral/30 bg-coral/5 px-3 py-2">
            <p className="text-[12px] font-semibold text-coral">Could not load this page of the ledger.</p>
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              className="text-[12px] font-bold text-deep-violet dark:text-violet-soft"
            >
              Try again
            </button>
          </div>
        )}

        {billing.ledger.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-ink/[0.1] p-8 text-center dark:border-fog/[0.1]">
            <p className="text-[13px] font-semibold text-ink/70 dark:text-fog/70">
              {total > 0 ? "No entries on this page" : "No ledger entries yet"}
            </p>
            <p className="mx-auto mt-1 max-w-[360px] text-[12px] leading-relaxed text-ink/45 dark:text-fog/45">
              {total > 0
                ? "Use the page controls below to return to a page with entries."
                : "Make an AI call and it will appear here with the reserved hold and the final charge."}
            </p>
          </div>
        ) : (
          <div className={`mt-4 hidden overflow-x-auto transition-opacity sm:block ${pageLoading ? "opacity-50" : ""}`}>
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">Kind</th>
                  <th className="px-3 py-2">Used for</th>
                  <th className="px-3 py-2">Status</th>
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
                    <td className="px-3 py-2 text-ink/60 dark:text-fog/60">
                      {purposeLabel(e.purpose) ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${statusPillClass(e.status)}`}>
                        {e.status}
                      </span>
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums font-semibold ${amountTone(e.amount_cents)}`}>
                      {amountText(e.amount_cents)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/45 dark:text-fog/45">{e.reserved_cents > 0 ? fmtCents(e.reserved_cents) : "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/60 dark:text-fog/60">{e.balance_after_cents == null ? "—" : fmtCents(e.balance_after_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Phones: a card per row, because the seven-column table would hide
            the amount and balance behind a horizontal scroll. */}
        {billing.ledger.length > 0 && (
          <div className={`mt-4 space-y-2 transition-opacity sm:hidden ${pageLoading ? "opacity-50" : ""}`}>
            {billing.ledger.map((e: BillingLedgerEntry) => (
              <div
                key={e.id}
                className="rounded-xl border border-ink/[0.06] bg-white p-3 dark:border-fog/[0.08] dark:bg-ink"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-ink dark:text-fog">
                      {purposeLabel(e.purpose) ?? kindLabel(e.kind)}
                    </p>
                    <p className="mt-0.5 text-[10px] tabular-nums text-ink/40 dark:text-fog/40">
                      {e.created_at ? new Date(e.created_at).toLocaleString() : "—"}
                    </p>
                  </div>
                  <p className={`shrink-0 text-[14px] font-bold tabular-nums ${amountTone(e.amount_cents)}`}>
                    {amountText(e.amount_cents)}
                  </p>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink/45 dark:text-fog/45">
                  <span className={`rounded-full px-2 py-0.5 font-bold uppercase ${statusPillClass(e.status)}`}>
                    {e.status}
                  </span>
                  {e.reserved_cents > 0 && <span>Reserved {fmtCents(e.reserved_cents)}</span>}
                  {e.balance_after_cents != null && (
                    <span>Balance {fmtCents(e.balance_after_cents)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {total > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-ink/[0.06] pt-3 dark:border-fog/[0.06]">
            <p className="text-[11px] tabular-nums text-ink/45 dark:text-fog/45">
              Showing {firstRow}–{lastRow} of {total}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0 || pageLoading}
                className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 disabled:cursor-not-allowed disabled:opacity-40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                Previous
              </button>
              <span className="text-[11px] font-semibold tabular-nums text-ink/45 dark:text-fog/45">
                Page {currentPage} of {pageCount}
              </span>
              <button
                type="button"
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total || pageLoading}
                className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 disabled:cursor-not-allowed disabled:opacity-40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>

      <p className="pb-2 text-center text-[11px] text-ink/30 dark:text-fog/30">
        Balance is authoritative in Postgres · Redis is a cache · Holds expire after 15 minutes
      </p>
    </div>
  );
}