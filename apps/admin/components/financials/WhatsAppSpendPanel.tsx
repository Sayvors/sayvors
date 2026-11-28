"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  WHATSAPP_SPEND_PERIODS,
  fetchAdminWhatsAppSpend,
  summarizeWhatsAppSpend,
  type CostAvailability,
  type CurrencySpendTotal,
  type SpendAmount,
  type WhatsAppSpendPeriod,
  type WhatsAppSpendResponse,
} from "@/lib/whatsapp-spend";
import {
  WHATSAPP_SPEND_COPY,
  type WhatsAppSpendCopy,
  type WhatsAppSpendLocale,
} from "@/lib/whatsapp-spend-copy";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function fill(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, String(value)),
    template,
  );
}

function numericAmount(amount: SpendAmount): number | null {
  if (amount === null) return null;
  const value = Number(amount);
  return Number.isFinite(value) ? value : null;
}

function formatAmount(amount: SpendAmount, currency: string | null, locale: string): string | null {
  const value = numericAmount(amount);
  if (value === null || !currency) return null;
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency }).format(value);
  } catch {
    // Keep the native amount visible even if a provider currency code is malformed.
    return value.toLocaleString(locale, { maximumFractionDigits: 2 });
  }
}

function formatTotals(totals: CurrencySpendTotal[], locale: string, copy: WhatsAppSpendCopy): string {
  if (totals.length === 0) return copy.noSpend;
  return totals.map((total) => formatAmount(total.approximateCost, total.currency, locale) ?? copy.unavailableCost).join(" · ");
}

function formatSync(value: string | null, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div role="group" aria-label={label} className="panel p-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/45">{label}</p>
      <p className="mt-1 text-[20px] font-black tabular-nums text-ink">{value}</p>
    </div>
  );
}

function Availability({ status, copy }: { status: CostAvailability; copy: WhatsAppSpendCopy }) {
  const tone = status === "available"
    ? "bg-emerald-100 text-emerald-700"
    : status === "unavailable"
      ? "bg-amber-100 text-amber-700"
      : "bg-violet-100 text-violet-800";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${tone}`}>
      {copy[status]}
    </span>
  );
}

export default function WhatsAppSpendPanel() {
  const [days, setDays] = useState<WhatsAppSpendPeriod>(30);
  const [locale, setLocale] = useState<WhatsAppSpendLocale>("en");
  const [data, setData] = useState<WhatsAppSpendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const requestVersion = useRef(0);
  const titleId = useId();
  const periodId = useId();
  const languageId = useId();
  const copy = WHATSAPP_SPEND_COPY[locale];

  const request = useCallback(async (version: number) => {
    try {
      const response = await fetchAdminWhatsAppSpend(days);
      if (version === requestVersion.current) setData(response);
    } catch {
      if (version === requestVersion.current) setError(true);
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [days]);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(false);
    void request(++requestVersion.current);
  }, [request]);

  useEffect(() => {
    void request(++requestVersion.current);
    return () => { requestVersion.current += 1; };
  }, [request]);

  const summary = useMemo(() => data ? summarizeWhatsAppSpend(data) : null, [data]);
  const numberFormat = new Intl.NumberFormat(locale);
  const directValue = summary
    ? summary.directClientByCurrency.length > 0
      ? formatTotals(summary.directClientByCurrency, locale, copy)
      : summary.directClientUnavailableCostVolume > 0 ? copy.unavailableCost : copy.noSpend
    : "—";
  const payableValue = summary
    ? summary.sayvorsPayableByCurrency.length > 0
      ? formatTotals(summary.sayvorsPayableByCurrency, locale, copy)
      : summary.sayvorsPayableUnavailableCostVolume > 0 ? copy.unavailableCost : copy.noSpend
    : "—";

  return (
    <section
      role="region"
      aria-labelledby={titleId}
      aria-busy={loading}
      lang={locale}
      dir={locale === "ar" ? "rtl" : "ltr"}
      className="panel space-y-4 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={titleId} className="text-[15px] font-bold text-ink">{copy.title}</h2>
          <p className="mt-0.5 text-[11px] text-ink/50">{copy.subtitle}</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor={periodId} className="mb-1 block text-[10px] font-medium text-ink/50">{copy.periodLabel}</label>
            <select
              id={periodId}
              value={days}
              onChange={(event) => {
                setDays(Number(event.target.value) as WhatsAppSpendPeriod);
                setLoading(true);
                setError(false);
              }}
              className={`h-9 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface-solid)] px-2 text-[11px] text-ink ${FOCUS_RING}`}
            >
              {WHATSAPP_SPEND_PERIODS.map((period) => (
                <option key={period} value={period}>{fill(copy.periodDays, { days: period })}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={languageId} className="mb-1 block text-[10px] font-medium text-ink/50">{copy.languageLabel}</label>
            <select
              id={languageId}
              value={locale}
              onChange={(event) => setLocale(event.target.value as WhatsAppSpendLocale)}
              className={`h-9 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface-solid)] px-2 text-[11px] text-ink ${FOCUS_RING}`}
            >
              <option value="en">English</option>
              <option value="ar">العربية</option>
            </select>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className={`h-9 rounded-[2px] border border-[var(--ui-line-strong)] px-3 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-50 ${FOCUS_RING}`}
          >
            {loading && data ? copy.updating : copy.refresh}
          </button>
        </div>
      </div>

      {loading && !data && (
        <div role="status" aria-live="polite" className="space-y-3">
          <p className="text-[12px] text-ink/50">{copy.loading}</p>
          <div className="h-24 animate-pulse rounded-[2px] bg-[var(--ui-sunken)]" aria-hidden />
        </div>
      )}

      {error && !data && (
        <div role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          <p>{copy.loadError}</p>
          <button type="button" onClick={refresh} className={`mt-2 min-h-8 rounded-[2px] border border-red-300 px-3 font-semibold ${FOCUS_RING}`}>
            {copy.retry}
          </button>
        </div>
      )}

      {error && data && (
        <p role="alert" className="text-[11px] text-red-700">
          {copy.refreshError}{" "}
          <button type="button" onClick={refresh} className={`min-h-6 font-semibold underline ${FOCUS_RING}`}>{copy.retry}</button>
        </p>
      )}

      {data && summary && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryCard label={copy.deliveredVolume} value={numberFormat.format(summary.deliveredVolume)} />
            <SummaryCard label={copy.directSpend} value={directValue} />
            <SummaryCard label={copy.payableSpend} value={payableValue} />
            <SummaryCard
              label={copy.lastSync}
              value={formatSync(summary.lastSyncAt, locale) ?? copy.neverSynced}
            />
          </div>
          <p className="rounded-[2px] bg-[var(--ui-sunken)] px-3 py-2 text-[11px] font-medium text-ink/70">
            {copy.marginNote}
          </p>
          {summary.partial && (
            <p role="status" className="rounded-[2px] border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-medium text-amber-800">
              {copy.partialNote}
            </p>
          )}
          <p className="text-[10px] text-ink/45">{copy.approximateNote}</p>

          {data.items.length === 0 ? (
            <p className="panel px-3 py-6 text-center text-[12px] text-ink/50">{copy.empty}</p>
          ) : (
            <div role="region" aria-label={copy.tableLabel} tabIndex={0} className="panel overflow-x-auto">
              <table aria-label={copy.tableLabel} className="w-full min-w-[900px] text-[12px]">
                <caption className="sr-only">{copy.tableLabel}</caption>
                <thead>
                  <tr className="border-b border-[var(--ui-line)] text-left text-[10px] font-semibold uppercase tracking-wide text-ink/50">
                    <th scope="col" className="px-3 py-2">{copy.tenant}</th>
                    <th scope="col" className="px-3 py-2">{copy.waba}</th>
                    <th scope="col" className="px-3 py-2">{copy.funding}</th>
                    <th scope="col" className="px-3 py-2">{copy.volume}</th>
                    <th scope="col" className="px-3 py-2">{copy.availability}</th>
                    <th scope="col" className="px-3 py-2">{copy.approximateSpend}</th>
                    <th scope="col" className="px-3 py-2">{copy.sync}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row, index) => {
                    const cost = row.cost_availability === "unavailable"
                      ? null
                      : formatAmount(row.approximate_cost, row.currency, locale);
                    const lastSync = formatSync(row.last_meta_sync_at, locale);
                    const pending = row.sync_status === "pending" || row.sync_status === "syncing";
                    return (
                      <tr key={`${row.tenant_id}-${row.waba_id}-${row.funding_mode}-${index}`} className="border-b border-[var(--ui-line)] last:border-0">
                        <td className="px-3 py-2">
                          <p className="font-medium text-ink">{row.tenant_name ?? row.tenant_email ?? row.tenant_id}</p>
                          <p className="font-mono text-[10px] text-ink/40">{row.tenant_id}</p>
                        </td>
                        <td className="px-3 py-2">
                          <p className="font-medium text-ink">{row.waba_name ?? row.waba_id}</p>
                          <p className="font-mono text-[10px] text-ink/40">{row.waba_id}</p>
                        </td>
                        <td className="px-3 py-2 text-ink/70">
                          {row.funding_mode === "direct_client" ? copy.fundingDirect : copy.fundingPayable}
                        </td>
                        <td className="px-3 py-2 font-semibold tabular-nums text-ink">{numberFormat.format(row.volume)}</td>
                        <td className="px-3 py-2"><Availability status={row.cost_availability} copy={copy} /></td>
                        <td className={`px-3 py-2 font-semibold tabular-nums ${cost ? "text-ink" : "text-amber-700"}`}>
                          {cost ?? copy.unavailableCost}
                        </td>
                        <td className="px-3 py-2 text-ink/60">
                          {pending && <span>{copy.syncing}</span>}
                          {lastSync && (
                            <time dateTime={row.last_meta_sync_at ?? undefined} className="block">{lastSync}</time>
                          )}
                          {!pending && !lastSync && copy.neverSynced}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
