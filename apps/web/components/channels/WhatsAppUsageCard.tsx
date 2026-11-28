"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { queryKeys } from "@/lib/query-keys";
import {
  WHATSAPP_USAGE_PERIODS,
  fetchWhatsAppUsage,
  type CostAvailability,
  type FundingMode,
  type SpendAmount,
  type WhatsAppSpendBreakdownRow,
  type WhatsAppSpendTotal,
  type WhatsAppUsagePeriod,
  type WhatsAppUsageResponse,
} from "@/lib/api-whatsapp-usage";

const LIVE_REFRESH_MS = 30_000;

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
    // A malformed provider currency must not hide an otherwise usable amount.
    return value.toLocaleString(locale, { maximumFractionDigits: 2 });
  }
}

function hasReportedCost(row: WhatsAppSpendTotal): boolean {
  return (row.cost_availability === "available" || row.cost_availability === "partial")
    && numericAmount(row.approximate_cost) !== null
    && Boolean(row.currency);
}

function formatSync(value: string | null, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function CostLine({
  amount,
  currency,
  availability,
  fundingMode,
}: {
  amount: SpendAmount;
  currency: string | null;
  availability: CostAvailability;
  fundingMode: FundingMode;
}) {
  const { locale, t } = useI18n();
  const copy = t.dashboard.channels.whatsappUsage;
  const formatted = availability === "unavailable" ? null : formatAmount(amount, currency, locale);
  return (
    <div className="rounded-[8px] bg-ink/[0.03] p-3 dark:bg-fog/[0.05]">
      <p className="text-[11px] font-semibold text-ink/55 dark:text-fog/55">{copy.metaSpend}</p>
      <p className="mt-1 text-[18px] font-bold tabular-nums text-ink dark:text-fog">
        {formatted ?? copy.unavailableCost}
      </p>
      <p className="mt-1 text-[11px] text-ink/50 dark:text-fog/50">
        {fundingMode === "direct_client" ? copy.fundingDirect : copy.fundingSayvors}
      </p>
      {(availability === "partial" || availability === "pending") && (
        <p className="mt-1 text-[11px] font-medium text-amber-700 dark:text-amber-300">
          {availability === "partial" ? copy.costPartial : copy.costPending}
        </p>
      )}
    </div>
  );
}

function BreakdownList({ breakdowns }: { breakdowns: WhatsAppUsageResponse["breakdowns"] }) {
  const { locale, t } = useI18n();
  const copy = t.dashboard.channels.whatsappUsage;
  const groups = [
    { key: "waba", title: copy.byWaba, rows: breakdowns.by_waba },
    { key: "phone", title: copy.byPhone, rows: breakdowns.by_phone },
    { key: "category", title: copy.byCategory, rows: breakdowns.by_category },
  ];
  const rowCount = groups.reduce((count, group) => count + group.rows.length, 0);
  if (rowCount === 0) {
    return <p className="text-[12px] text-ink/50 dark:text-fog/50">{copy.breakdownEmpty}</p>;
  }
  const label = (row: WhatsAppSpendBreakdownRow, key: string): string => {
    if (key === "waba") return row.waba_name ?? row.waba_id ?? "—";
    if (key === "phone") return row.phone ?? copy.unknownPhone;
    return row.category ?? copy.uncategorized;
  };
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {groups.filter((group) => group.rows.length > 0).map((group) => (
        <div key={group.key}>
          <h4 className="text-[12px] font-semibold text-ink dark:text-fog">{group.title}</h4>
          <ul className="mt-2 space-y-2">
            {group.rows.map((row, index) => {
              const cost = row.cost_availability === "unavailable"
                ? null
                : formatAmount(row.approximate_cost, row.currency, locale);
              return (
                <li key={`${group.key}-${label(row, group.key)}-${index}`} className="text-[11px]">
                  <p className="font-medium text-ink dark:text-fog">{label(row, group.key)}</p>
                  <p className="mt-0.5 text-ink/50 dark:text-fog/50">
                    {copy.volume}: {row.volume.toLocaleString(locale)}
                  </p>
                  <p className={cost ? "text-ink/60 dark:text-fog/60" : "text-amber-700 dark:text-amber-300"}>
                    {cost ?? copy.unavailableCost}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default function WhatsAppUsageCard() {
  const { locale, t } = useI18n();
  const copy = t.dashboard.channels.whatsappUsage;
  const [days, setDays] = useState<WhatsAppUsagePeriod>(30);
  const titleId = useId();
  const periodId = useId();
  const query = useQuery({
    queryKey: queryKeys.usage.whatsapp(days),
    queryFn: () => fetchWhatsAppUsage(days),
    staleTime: LIVE_REFRESH_MS,
    refetchInterval: LIVE_REFRESH_MS,
    retry: false,
  });
  const data = query.data;
  const totals = data?.totals?.length ? data.totals : data ? [{
    funding_mode: data.funding_mode,
    volume: data.used,
    approximate_cost: data.approximate_cost,
    currency: data.currency,
    cost_availability: data.cost_availability,
    last_meta_sync_at: data.last_meta_sync_at,
  }] : [];
  const spendRows = data ? [
    ...totals,
    ...data.breakdowns.by_waba,
    ...data.breakdowns.by_phone,
    ...data.breakdowns.by_category,
  ] : [];
  const partialCost = data?.cost_availability === "partial" || (
    spendRows.some(hasReportedCost)
    && spendRows.some((row) => !hasReportedCost(row))
  );
  const syncing = data?.sync_status === "syncing" || data?.sync_status === "pending";
  const lastSync = formatSync(data?.last_meta_sync_at ?? null, locale);
  const numberFormat = new Intl.NumberFormat(locale);

  return (
    <section
      role="region"
      aria-labelledby={titleId}
      aria-busy={query.isPending || query.isFetching}
      className="rounded-[8px] border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-[14px] font-semibold text-ink dark:text-fog">{copy.title}</h3>
          <p className="mt-0.5 text-[11px] text-ink/45 dark:text-fog/45">{copy.approximateNote}</p>
        </div>
        <div>
          <label htmlFor={periodId} className="sr-only">{copy.periodLabel}</label>
          <select
            id={periodId}
            value={days}
            onChange={(event) => setDays(Number(event.target.value) as WhatsAppUsagePeriod)}
            className="min-h-8 rounded-[8px] border border-ink/10 bg-white px-2 text-[11px] font-semibold text-ink outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:border-fog/10 dark:bg-ink dark:text-fog"
          >
            {WHATSAPP_USAGE_PERIODS.map((period) => (
              <option key={period} value={period}>{fill(copy.periodDays, { days: period })}</option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && !data && (
        <div role="status" className="mt-4 space-y-3" aria-live="polite">
          <p className="text-[12px] text-ink/50 dark:text-fog/50">{copy.loading}</p>
          <div className="h-16 animate-pulse rounded-[8px] bg-ink/[0.05] dark:bg-fog/[0.06]" aria-hidden />
        </div>
      )}

      {query.error && !data && (
        <div role="alert" className="mt-4 rounded-[8px] border border-red-200 bg-red-50 p-3 dark:border-red-500/30 dark:bg-red-500/10">
          <p className="text-[12px] font-medium text-red-700 dark:text-red-300">{copy.loadError}</p>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="mt-2 min-h-8 rounded-[8px] border border-red-300 px-3 text-[11px] font-semibold text-red-700 outline-none focus-visible:ring-2 focus-visible:ring-red-500/40 dark:text-red-300"
          >
            {t.common.retry}
          </button>
        </div>
      )}

      {query.error && data && (
        <div role="alert" className="mt-3 text-[11px] text-red-700 dark:text-red-300">
          {copy.refreshError}{" "}
          <button type="button" onClick={() => void query.refetch()} className="min-h-6 font-semibold underline focus-visible:outline-2">
            {t.common.retry}
          </button>
        </div>
      )}

      {data && (
        <div className="mt-4 space-y-4">
          <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-ink/45 dark:text-fog/45">{copy.localUsage}</p>
                <span className="rounded-full bg-emerald-600/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
                  {query.isFetching ? copy.updating : copy.live}
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-3">
                <div>
                  <dt className="text-[10px] text-ink/45 dark:text-fog/45">{copy.used}</dt>
                  <dd className="mt-1 text-[20px] font-bold tabular-nums text-ink dark:text-fog">{numberFormat.format(data.used)}</dd>
                </div>
                <div>
                  <dt className="text-[10px] text-ink/45 dark:text-fog/45">{copy.limit}</dt>
                  <dd className="mt-1 text-[20px] font-bold tabular-nums text-ink dark:text-fog">
                    {data.limit == null ? copy.unlimited : numberFormat.format(data.limit)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] text-ink/45 dark:text-fog/45">{copy.remaining}</dt>
                  <dd className="mt-1 text-[20px] font-bold tabular-nums text-ink dark:text-fog">
                    {data.remaining == null ? copy.unlimited : numberFormat.format(data.remaining)}
                  </dd>
                </div>
              </dl>
              {data.limit != null && data.limit > 0 && (
                <progress
                  aria-label={copy.progressLabel}
                  max={data.limit}
                  value={Math.min(Math.max(data.used, 0), data.limit)}
                  className="mt-3 h-2 w-full overflow-hidden rounded-full accent-deep-violet"
                />
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-ink/50 dark:text-fog/50">{copy.attemptsPolicy}</p>
              {data.used === 0 && (
                <p className="mt-2 text-[12px] font-medium text-ink/60 dark:text-fog/60">{copy.noUsage}</p>
              )}
            </div>
            <div className="space-y-2">
              {totals.map((total, index) => (
                <CostLine
                  key={`${total.funding_mode}-${total.currency ?? "unknown"}-${index}`}
                  amount={total.approximate_cost}
                  currency={total.currency}
                  availability={total.cost_availability}
                  fundingMode={total.funding_mode}
                />
              ))}
            </div>
          </div>

          <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
            {syncing && (
              <span className="font-medium text-amber-700 dark:text-amber-300">{copy.syncing}</span>
            )}
            {data.sync_status === "error" && (
              <span className="font-medium text-red-700 dark:text-red-300">{copy.syncError}</span>
            )}
            {lastSync && (
              <>
                <span className="text-ink/50 dark:text-fog/50">{copy.lastSync}</span>
                <time dateTime={data.last_meta_sync_at ?? undefined} className="font-medium text-ink/70 dark:text-fog/70">{lastSync}</time>
              </>
            )}
            {!syncing && data.sync_status !== "error" && !lastSync && (
              <span className="text-ink/50 dark:text-fog/50">{copy.neverSynced}</span>
            )}
          </div>

          {partialCost && (
            <p role="status" className="rounded-[8px] bg-amber-50 p-3 text-[11px] font-medium text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
              {copy.partialCost}
            </p>
          )}

          <details className="border-t border-ink/[0.06] pt-3 dark:border-fog/[0.08]">
            <summary className="min-h-8 cursor-pointer text-[11px] font-semibold text-deep-violet outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-violet-light">
              {copy.breakdownTitle}
            </summary>
            <div className="mt-3">
              <BreakdownList breakdowns={data.breakdowns} />
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
