"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { queryKeys } from "@/lib/query-keys";
import LogoLoader from "@/components/LogoLoader";
import {
  createBillingRequest,
  getBudget,
  getEntitlements,
  getPlans,
  type Budget,
  type Entitlements as EntitlementsType,
  type WebPlan,
} from "@/lib/api-billing";
import { apiFetch } from "@/lib/api-rag";

interface ApiChannel {
  id: string;
  status: string;
}

import { FEATURE_LABELS, FEATURE_LABELS_AR, FEATURE_ORDER } from "@/lib/feature-labels";
import { useI18n } from "@/lib/i18n/I18nProvider";

function fmtCents(c: number, locale: string): string {
  const n = new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    maximumFractionDigits: 0,
  }).format(c / 100);
  return `$${n}`;
}

function fmtNum(n: number, locale: string): string {
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    maximumFractionDigits: 0,
  }).format(n);
}

const PLAN_SLUG_KEYS: Record<string, keyof NonNullable<ReturnType<typeof useI18n>["t"]["dashboard"]["plans"]["planNames"]>> = {
  "free-trial": "trial",
  free: "free",
  starter: "starter",
  pro: "pro",
  growth: "growth",
  enterprise: "enterprise",
};

function planLabel(slug: string | undefined, names: { trial: string; free: string; starter: string; pro: string; growth: string; enterprise: string }, fallback = ""): string {
  const key = slug ? PLAN_SLUG_KEYS[slug] : undefined;
  return (key && names[key]) || fallback || slug || names.trial;
}

// Online card payments are not connected yet. Until they are, only the
// included free trial and the sales-assisted Enterprise plan are actionable,
// so only those are listed. Starter/Pro/Growth stay seeded in the catalog for
// when payments land, but showing a price with no way to buy it reads as a
// broken checkout.
const ENABLED_PLAN_SLUGS = new Set(["free-trial", "enterprise"]);
const TRIAL_CREDIT_CENTS = 1000; // $10 - keep in step with TRIAL_CREDIT_CENTS

function PlanCard({
  plan,
  current,
  onSelect,
  scPerUsd,
  selectBusy,
  selectNotice,
  selectError,
}: {
  plan: WebPlan;
  current: boolean;
  onSelect: () => void;
  scPerUsd: number;
  selectBusy: boolean;
  selectNotice: string | null;
  selectError: string | null;
}) {
  const { t, locale } = useI18n();
  const labels = locale === "ar" ? FEATURE_LABELS_AR : FEATURE_LABELS;
  const features = FEATURE_ORDER.filter((k) => (plan.features || {})[k]);
  const isEnterprise = plan.slug === "enterprise";
  const isTrial = plan.slug === "free-trial";
  const creditCents = isTrial ? TRIAL_CREDIT_CENTS : plan.included_credit_cents;
  return (
    <div
      className={`relative flex flex-col rounded-3xl border border-ink/[0.08] bg-white p-6 ${
        current ? "ring-2 ring-emerald-400/60" : ""
      }`}
    >
      {current && (
        <div className="absolute -top-3 right-4 rounded-full bg-emerald-500 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-white shadow-lg">
          {t.dashboard.plans.currentBadge}
        </div>
      )}

      <div className="mb-4">
        <h3 className="text-[18px] font-bold text-ink dark:text-fog">
          {planLabel(plan.slug, t.dashboard.plans.planNames, plan.name)}
        </h3>
        <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">{plan.description}</p>
      </div>

      <div className="mb-5 flex items-baseline gap-1">
        <span className="text-[34px] font-extrabold tracking-tight text-ink dark:text-fog">
          {isEnterprise ? t.dashboard.plans.custom : plan.price_cents === 0 ? t.dashboard.plans.free : fmtCents(plan.price_cents, locale)}
        </span>
        {!isEnterprise && plan.price_cents > 0 && (
          <span className="text-[13px] text-ink/45 dark:text-fog/45">{t.dashboard.plans.perMonth}</span>
        )}
      </div>

      <div className="mb-5 grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">{t.dashboard.plans.aiCredit}</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise
              ? t.dashboard.plans.custom
              : `${fmtNum(Math.round((creditCents / 100) * scPerUsd), locale)} SC`}
          </div>
        </div>
        <div className="rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">{t.dashboard.plans.channels}</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise ? t.dashboard.plans.custom : plan.max_channels == null ? t.dashboard.plans.unlimited : plan.max_channels}
          </div>
        </div>
        <div className="col-span-2 rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">{t.dashboard.plans.whatsappMonthly}</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise
              ? t.dashboard.plans.custom
              : plan.max_messages_per_month == null
                ? t.dashboard.plans.unlimited
                : fmtNum(plan.max_messages_per_month, locale)}
          </div>
        </div>
        <div className="col-span-2 rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">{t.dashboard.plans.locations}</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise
              ? t.dashboard.plans.custom
              : plan.max_locations == null
                ? t.dashboard.plans.unlimited
                : fmtNum(plan.max_locations, locale)}
          </div>
        </div>
        <div className="col-span-2 rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">{t.dashboard.plans.teamMembers}</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise
              ? t.dashboard.plans.custom
              : plan.max_team_members == null
                ? t.dashboard.plans.unlimited
                : fmtNum(plan.max_team_members, locale)}
          </div>
        </div>
        <div className="col-span-2 rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">{t.dashboard.plans.regenerations}</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise
              ? t.dashboard.plans.custom
              : plan.max_regenerations_day == null
                ? t.dashboard.plans.unlimited
                : fmtNum(plan.max_regenerations_day, locale)}
          </div>
        </div>
      </div>

      <ul className="mb-6 flex-1 space-y-2">
        {features.map((k) => (
          <li key={k} className="flex items-center gap-2 text-[12px] text-ink/75 dark:text-fog/75">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
              <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M2.5 6l2.5 2.5L9.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            {labels[k] || k}
          </li>
        ))}
      </ul>

      <button
        onClick={onSelect}
        disabled={current || (isEnterprise && selectBusy)}
        className={`w-full rounded-2xl px-4 py-3 text-[13px] font-bold transition-all ${
          current
            ? "cursor-default bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : "bg-deep-violet text-white hover:bg-deep-violet/90 active:scale-[0.98] disabled:opacity-50"
        }`}
      >
        {current
          ? t.dashboard.plans.currentPlanCta
          : isEnterprise
            ? selectBusy
              ? t.dashboard.billing.topup.sending
              : t.dashboard.plans.request
            : t.dashboard.plans.included}
      </button>
      {isEnterprise && (selectNotice || selectError) && (
        <p
          role="status"
          className={`mt-2 text-[11px] leading-snug ${
            selectError ? "text-coral" : "text-emerald-600 dark:text-emerald-400"
          }`}
        >
          {selectError ?? selectNotice}
        </p>
      )}
    </div>
  );
}

export default function PlansPage() {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();
  const [requestBusy, setRequestBusy] = useState(false);
  const [requestNotice, setRequestNotice] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const { data: plans, isLoading: plansLoading } = useQuery({
    queryKey: queryKeys.billing.plans(),
    queryFn: getPlans,
  });
  const { data: entitlements } = useQuery({
    queryKey: queryKeys.billing.entitlements(),
    queryFn: getEntitlements,
  });
  const { data: budget } = useQuery({
    queryKey: queryKeys.billing.budget(),
    queryFn: getBudget,
  });
  const { data: channels } = useQuery({
    queryKey: ["channels", "list", 100],
    queryFn: () => apiFetch("/api/v1/channels?limit=100") as Promise<{ items?: ApiChannel[]; total?: number }>,
  });

  const currentSlug = entitlements?.plan_slug;
  const channelCount = channels?.items?.length ?? channels?.total ?? 0;
  const maxChannels = entitlements?.max_channels ?? null;

  const handleSelect = async (plan: WebPlan) => {
    if (plan.slug !== "enterprise") return;
    setRequestBusy(true);
    setRequestNotice(null);
    setRequestError(null);
    try {
      const result = await createBillingRequest({ kind: "plan", plan_slug: "enterprise" });
      setRequestNotice(result.duplicate ? t.dashboard.billing.topup.duplicate : t.dashboard.billing.topup.sent);
      await queryClient.invalidateQueries({ queryKey: ["billing", "requests"] });
    } catch (e) {
      setRequestError(e instanceof Error ? e.message : t.dashboard.billing.topup.sendFailed);
    } finally {
      setRequestBusy(false);
    }
  };

  if (plansLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LogoLoader />
      </div>
    );
  }

  const sortedPlans = [...(plans || [])]
    // Only plans that can actually be actioned are listed; see ENABLED_PLAN_SLUGS.
    .filter((p) => ENABLED_PLAN_SLUGS.has(p.slug))
    .sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="relative h-full overflow-y-auto">
      <div className="relative mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* header */}
        <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-deep-violet/10 px-3 py-1 text-[11px] font-semibold text-deep-violet dark:bg-deep-violet/20 dark:text-fuchsia-300">
              <span className="h-1.5 w-1.5 rounded-full bg-deep-violet animate-pulse" />
              {t.dashboard.plans.eyebrow}
            </div>
            <h1 className="mt-3 text-[30px] font-extrabold tracking-tight text-ink dark:text-fog">
              {t.dashboard.plans.title}
            </h1>
            <p className="mt-1 max-w-2xl text-[14px] text-ink/55 dark:text-fog/55">
              {t.dashboard.plans.subtitle}
            </p>
          </div>
          {entitlements && (
            <div className="rounded-2xl border border-ink/[0.08] bg-white px-4 py-3 dark:border-fog/[0.08] dark:bg-ink/60">
              <div className="text-[10px] uppercase tracking-wider text-ink/45 dark:text-fog/45">{t.dashboard.plans.currentPlan}</div>
              <div className="mt-0.5 text-[16px] font-bold text-ink dark:text-fog">
                {planLabel(currentSlug, t.dashboard.plans.planNames, entitlements.plan_name)}
              </div>
              <div className="text-[11px] text-ink/50 dark:text-fog/50">
                {entitlements.promo_active ? t.dashboard.plans.promoActive : entitlements.status}
              </div>
            </div>
          )}
        </div>

        {/* usage strip */}
        {entitlements && (
          <div className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <UsageMeter
              label={t.dashboard.plans.channels}
              used={channelCount}
              max={maxChannels}
              barClass="bg-sky-500"
            />
            <UsageMeter
              label={t.dashboard.plans.sayvorsCredits}
              used={budget ? (budget.balance_cents / 100) * (budget.credits_per_usd ?? 1000) : 0}
              max={null}
              barClass="bg-emerald-500"
              display={
                budget
                  ? `${fmtNum(Math.round((budget.balance_cents / 100) * (budget.credits_per_usd ?? 1000)), locale)} SC`
                  : "—"
              }
            />
            <UsageMeter
              label={t.dashboard.plans.whatsappMonthly}
              used={entitlements.messages_used_this_month}
              max={entitlements.max_messages_per_month ?? null}
              barClass="bg-amber-500"
              display={
                entitlements.max_messages_per_month == null
                  ? `${fmtNum(entitlements.messages_used_this_month, locale)} / ${t.dashboard.plans.unlimited}`
                  : `${fmtNum(entitlements.messages_used_this_month, locale)} / ${fmtNum(entitlements.max_messages_per_month, locale)}`
              }
            />
          </div>
        )}

        <div className="-mt-4 mb-8 flex justify-end">
          <Link
            href="/dashboard/billing/topup"
            className="inline-flex items-center gap-1.5 rounded-xl border border-ink/[0.08] bg-white px-3.5 py-2 text-[12px] font-semibold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
          >
            {t.dashboard.plans.topup}
            <span aria-hidden>→</span>
          </Link>
        </div>

        {/* plan grid */}
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {sortedPlans.map((p) => (
            <PlanCard
              key={p.id}
              plan={p}
              current={p.slug === currentSlug}
              scPerUsd={budget?.credits_per_usd ?? 1000}
              onSelect={() => void handleSelect(p)}
              selectBusy={requestBusy}
              selectNotice={requestNotice}
              selectError={requestError}
            />
          ))}
        </div>

        {/* feature matrix */}
        <div className="mt-12">
          <h2 className="mb-4 text-[18px] font-bold text-ink dark:text-fog">{t.dashboard.plans.featureComparison}</h2>
          <div className="overflow-x-auto rounded-3xl border border-ink/[0.08] bg-white dark:border-fog/[0.08] dark:bg-ink/60">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] dark:border-fog/[0.06]">
                  <th className="px-4 py-3 text-left font-semibold text-ink/60 dark:text-fog/60">{t.dashboard.plans.feature}</th>
                  {sortedPlans.map((p) => (
                    <th
                      key={p.id}
                      className={`px-3 py-3 text-center font-semibold ${
                        p.slug === currentSlug ? "text-emerald-600 dark:text-emerald-400" : "text-ink/70 dark:text-fog/70"
                      }`}
                    >
                      {planLabel(p.slug, t.dashboard.plans.planNames, p.name)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURE_ORDER.map((k) => (
                  <tr key={k} className="border-b border-ink/[0.04] last:border-0 dark:border-fog/[0.04]">
                    <td className="px-4 py-2.5 text-ink/75 dark:text-fog/75">{(locale === "ar" ? FEATURE_LABELS_AR : FEATURE_LABELS)[k]}</td>
                    {sortedPlans.map((p) => {
                      const on = !!(p.features || {})[k];
                      return (
                        <td key={p.id} className="px-3 py-2.5 text-center">
                          {on ? (
                            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                              <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <path d="M2.5 6l2.5 2.5L9.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </span>
                          ) : (
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-ink/15 dark:bg-fog/15" />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <p className="mt-8 text-center text-[11px] text-ink/40 dark:text-fog/40">
          {t.dashboard.plans.footer}
        </p>
      </div>
    </div>
  );
}

function UsageMeter({
  label,
  used,
  max,
  barClass,
  suffix,
  display,
}: {
  label: string;
  used: number;
  max: number | null;
  barClass: string;
  suffix?: string;
  display?: string;
}) {
  const pct = max && max > 0 ? Math.min(100, (used / max) * 100) : 0;
  return (
    <div className="rounded-2xl border border-ink/[0.08] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-ink/55 dark:text-fog/55">{label}</span>
        <span className="text-[12px] font-bold text-ink dark:text-fog">
          {display ?? `${used}${suffix ? suffix : ""}${max != null ? ` / ${max}` : ""}`}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.08]">
        <div
          className={`h-full rounded-full ${barClass} transition-all duration-700`}
          style={{ width: `${max == null ? 0 : pct}%` }}
        />
      </div>
    </div>
  );
}
