"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  getLedger,
  type BillingLedgerEntry,
  type LedgerSort,
  type TenantBilling,
} from "@/lib/api-billing";

/** Rows per page. Small enough to stay readable on a phone. */
const PAGE_SIZE = 20;

function fmtMoney(cents: number, locale: string): string {
  const sign = cents < 0 ? "-" : "";
  const abs = new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(cents) / 100);
  return `${sign}$${abs}`;
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

const PURPOSE_KEYS: Record<string, string> = {
  "review_engine.generate": "reviewGenerate",
  "review_engine.analysis": "reviewAnalysis",
  "review_engine.relevance_judge": "reviewRelevance",
  "analytics.enrichment": "enrichment",
  "analytics.meaning": "meaning",
  "analytics.intelligence": "intelligence",
  "analytics.summary": "summary",
  "analytics.mine_conversations": "mine",
  "analytics.abuse_triage": "abuse",
  "conversation.context": "conversation",
  "review.qa": "qa",
  "review_request.template": "template",
  "chat.message": "assistantChat",
  "assistant.chat": "assistantChat",
  "posts.ai_draft": "postDraft",
  "memory.extract": "memory",
  "databank.business_profile": "businessProfile",
  "databank.ask": "databankAnswer",
  "whatsapp.render_style": "replyStyle",
  "whatsapp.thread_stats": "threadStats",
  "instagram.caption_suggest": "igCaption",
  meta_voice_note: "voiceNote",
  "voice.tts": "tts",
  "tts.job": "tts",
  "admin.test": "adminTest",
};

function purposeLabel(
  purpose: string | null,
  purposes: Record<string, string>,
): string | null {
  if (!purpose) return null;
  const key = PURPOSE_KEYS[purpose];
  return (
    (key && purposes[key]) ??
    purpose.replaceAll("_", " ").replaceAll(".", " · ")
  );
}

function kindLabel(kind: string, kinds: Record<string, string>): string {
  const labels: Record<string, string> = {
    ai_usage: kinds.aiUsage,
    plan_grant: kinds.planGrant,
    credit_topup: kinds.creditTopup,
    credit_adjust: kinds.creditAdjust,
    balance_resync: kinds.balanceResync,
    balance_reconcile: kinds.balanceReconcile,
  };
  return labels[kind] ?? kind;
}

function statusPillLabel(
  status: string,
  statuses: Record<string, string>,
): string {
  return statuses[status] ?? status;
}

function statusStyle(
  s: TenantBilling["status"],
  statuses: { debt: string; empty: string; low: string; healthy: string },
): { pill: string; dot: string; label: string } {
  switch (s) {
    case "debt":
      return { pill: "bg-coral/10 text-coral ring-1 ring-coral/30", dot: "bg-coral", label: statuses.debt };
    case "empty":
      return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-900/20 dark:text-amber-300", dot: "bg-amber-400", label: statuses.empty };
    case "low":
      return { pill: "bg-sky-50 text-sky-700 ring-1 ring-sky-200 dark:bg-sky-900/20 dark:text-sky-300", dot: "bg-sky-500", label: statuses.low };
    default:
      return { pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300", dot: "bg-emerald-500", label: statuses.healthy };
  }
}

function statusPillClass(status: string): string {
  if (status === "settled") return "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300";
  if (status === "pending") return "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300";
  if (status === "released") return "bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-300";
  if (status === "expired") return "bg-coral/10 text-coral";
  return "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50";
}

function amountText(cents: number, locale: string): string {
  return cents === 0 ? "—" : `${cents > 0 ? "+" : ""}${fmtMoney(cents, locale)}`;
}

function amountTone(cents: number): string {
  if (cents < 0) return "text-coral";
  if (cents > 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-ink/30 dark:text-fog/30";
}

export default function CreditLedgerPage() {
  const { t, locale } = useI18n();
  const c = t.dashboard.billing.credit;
  const SORT_OPTIONS: { value: LedgerSort; label: string }[] = [
    { value: "newest", label: c.sorts.newest },
    { value: "oldest", label: c.sorts.oldest },
    { value: "cost_high", label: c.sorts.costHigh },
    { value: "cost_low", label: c.sorts.costLow },
  ];
  const fmtDate = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString(locale === "ar" ? "ar-SA" : "en-US") : "—";
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
        setError(e instanceof Error ? e.message : c.loadFailed);
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
          <p className="text-[14px] font-bold text-ink dark:text-fog">{error ?? c.loadFailed}</p>
          <p className="mt-1 text-[12px] text-ink/45 dark:text-fog/45">{c.couldNot}</p>
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            className="mt-4 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white"
          >
            {c.tryAgain}
          </button>
        </div>
      </div>
    );
  }

  const st = statusStyle(billing.status, c.statuses);
  const total = billing.total ?? billing.ledger.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const firstRow = total === 0 ? 0 : offset + 1;
  const lastRow = Math.min(offset + billing.ledger.length, total);

  return (
    <div className="mx-auto h-full max-w-5xl space-y-6 overflow-y-auto p-4 pb-24 sm:p-6 sm:pb-8">
      {/* Header */}
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40 dark:text-fog/40">{c.eyebrow}</p>
        <h1 className="mt-1 text-[24px] font-bold tracking-tight text-ink dark:text-fog">{c.title}</h1>
        <p className="mt-2 max-w-[640px] text-[13px] font-medium leading-relaxed text-ink/60 dark:text-fog/60">
          {c.subtitle1}
        </p>
        <p className="mt-2 max-w-[640px] text-[12px] font-medium leading-relaxed text-ink/45 dark:text-fog/45">
          {c.subtitle2}
        </p>
      </div>

      {/* Wallet cards */}
      <section className="grid gap-3 sm:grid-cols-3">
        {[
          { label: c.available, value: fmtMoney(billing?.balance_cents ?? 0, locale), note: st ? st.label : "—", tone: (billing?.balance_cents ?? 0) < 0 ? "text-coral" : "text-ink dark:text-fog" },
          { label: c.held, value: billing && billing.held_cents > 0 ? fmtMoney(billing.held_cents, locale) : "—", note: fill(c.holds, { count: billing?.holds.length ?? 0 }), tone: "text-deep-violet dark:text-violet-soft" },
          { label: c.committed, value: fmtMoney(billing?.total_cents ?? 0, locale), note: c.heldNote, tone: "text-ink dark:text-fog" },
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
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40 dark:text-fog/40">{c.plan}</p>
            <p className="mt-1 text-[18px] font-bold text-ink dark:text-fog">{billing.plan}</p>
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
            {c.manageMethods}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </Link>
        </div>
      </section>

      {/* Pending holds */}
      {billing && billing.holds.length > 0 && (
        <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
          <h2 className="text-[15px] font-bold text-ink dark:text-fog">{fill(c.holdsTitle, { count: billing.holds.length })}</h2>
          <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">{c.holdsDesc}</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
                  <th className="px-3 py-2">{c.hold}</th>
                  <th className="px-3 py-2 text-right">{c.reserved}</th>
                  <th className="px-3 py-2 text-right">{c.expires}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                {billing.holds.map((h) => (
                  <tr key={h.id}>
                    <td className="px-3 py-2 font-mono text-[10px] text-ink/45 dark:text-fog/45">{h.id.slice(0, 8)}…</td>
                    <td className="px-3 py-2 text-right tabular-nums font-semibold text-deep-violet dark:text-violet-soft">{fmtMoney(h.reserved_cents, locale)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/45 dark:text-fog/45">{fmtDate(h.expires_at)}</td>
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
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">{c.history}</h2>
            <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">
              {total === 1 ? c.entriesOne : fill(c.entriesMany, { count: total })}. {c.historyDesc}
            </p>
          </div>
          <label className="flex shrink-0 items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">
              {c.sort}
            </span>
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as LedgerSort);
                setOffset(0);
              }}
              aria-label={c.sortAria}
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
            <p className="text-[12px] font-semibold text-coral">{c.pageError}</p>
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              className="text-[12px] font-bold text-deep-violet dark:text-violet-soft"
            >
              {c.tryAgain}
            </button>
          </div>
        )}

        {billing.ledger.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-ink/[0.1] p-8 text-center dark:border-fog/[0.1]">
            <p className="text-[13px] font-semibold text-ink/70 dark:text-fog/70">
              {total > 0 ? c.emptyPage : c.emptyAll}
            </p>
            <p className="mx-auto mt-1 max-w-[360px] text-[12px] leading-relaxed text-ink/45 dark:text-fog/45">
              {total > 0 ? c.emptyPageHint : c.emptyAllHint}
            </p>
          </div>
        ) : (
          <div className={`mt-4 hidden overflow-x-auto transition-opacity sm:block ${pageLoading ? "opacity-50" : ""}`}>
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:border-fog/[0.06] dark:text-fog/40">
                  <th className="px-3 py-2">{c.when}</th>
                  <th className="px-3 py-2">{c.kind}</th>
                  <th className="px-3 py-2">{c.usedFor}</th>
                  <th className="px-3 py-2">{c.status}</th>
                  <th className="px-3 py-2 text-right">{c.amount}</th>
                  <th className="px-3 py-2 text-right">{c.reservedCol}</th>
                  <th className="px-3 py-2 text-right">{c.balanceAfter}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                {billing.ledger.map((e: BillingLedgerEntry) => (
                  <tr key={e.id} className="transition hover:bg-ink/[0.02] dark:hover:bg-fog/[0.03]">
                    <td className="px-3 py-2 tabular-nums text-ink/45 dark:text-fog/45">{fmtDate(e.created_at)}</td>
                    <td className="px-3 py-2">
                      <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/60 dark:bg-fog/[0.08] dark:text-fog/60">{kindLabel(e.kind, c.kinds)}</span>
                    </td>
                    <td className="px-3 py-2 text-ink/60 dark:text-fog/60">
                      {purposeLabel(e.purpose, c.purposes) ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${statusPillClass(e.status)}`}>
                        {statusPillLabel(e.status, c.entryStatuses)}
                      </span>
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums font-semibold ${amountTone(e.amount_cents)}`}>
                      {amountText(e.amount_cents, locale)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/45 dark:text-fog/45">{e.reserved_cents > 0 ? fmtMoney(e.reserved_cents, locale) : "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink/60 dark:text-fog/60">{e.balance_after_cents == null ? "—" : fmtMoney(e.balance_after_cents, locale)}</td>
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
                      {purposeLabel(e.purpose, c.purposes) ?? kindLabel(e.kind, c.kinds)}
                    </p>
                    <p className="mt-0.5 text-[10px] tabular-nums text-ink/40 dark:text-fog/40">
                      {fmtDate(e.created_at)}
                    </p>
                  </div>
                  <p className={`shrink-0 text-[14px] font-bold tabular-nums ${amountTone(e.amount_cents)}`}>
                    {amountText(e.amount_cents, locale)}
                  </p>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink/45 dark:text-fog/45">
                  <span className={`rounded-full px-2 py-0.5 font-bold uppercase ${statusPillClass(e.status)}`}>
                    {statusPillLabel(e.status, c.entryStatuses)}
                  </span>
                  {e.reserved_cents > 0 && <span>{c.reservedPrefix} {fmtMoney(e.reserved_cents, locale)}</span>}
                  {e.balance_after_cents != null && (
                    <span>{c.balancePrefix} {fmtMoney(e.balance_after_cents, locale)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {total > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-ink/[0.06] pt-3 dark:border-fog/[0.06]">
            <p className="text-[11px] tabular-nums text-ink/45 dark:text-fog/45">
              {fill(c.showing, { first: firstRow, last: lastRow, total })}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0 || pageLoading}
                className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 disabled:cursor-not-allowed disabled:opacity-40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                {c.previous}
              </button>
              <span className="text-[11px] font-semibold tabular-nums text-ink/45 dark:text-fog/45">
                {fill(c.pageOf, { page: currentPage, total: pageCount })}
              </span>
              <button
                type="button"
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total || pageLoading}
                className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 disabled:cursor-not-allowed disabled:opacity-40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                {c.next}
              </button>
            </div>
          </div>
        )}
      </section>

      <p className="pb-2 text-center text-[11px] text-ink/30 dark:text-fog/30">
        {c.footer}
      </p>
    </div>
  );
}