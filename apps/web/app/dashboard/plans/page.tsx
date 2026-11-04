"use client";

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import LogoLoader from "@/components/LogoLoader";
import {
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

import { FEATURE_LABELS, FEATURE_ORDER } from "@/lib/feature-labels";

function fmtCents(c: number): string {
  return `$${(c / 100).toFixed(0)}`;
}

const PLAN_LABELS: Record<string, string> = {
  "free-trial": "Free Trial",
  "free": "Free",
  starter: "Starter",
  pro: "Pro",
  growth: "Growth",
  enterprise: "Enterprise",
};

// Online card payments are not connected yet. Until they are, only the
// included free trial and the sales-assisted Enterprise plan are actionable;
// showing "pay" for Starter/Pro/Growth would be a fake checkout.
const ENABLED_PLAN_SLUGS = new Set(["free-trial", "enterprise"]);
const TRIAL_CREDIT_CENTS = 1000; // $10 - keep in step with TRIAL_CREDIT_CENTS

function planLabel(slug: string | undefined, fallback = ""): string {
  return (slug && PLAN_LABELS[slug]) || fallback || slug || "Free Trial";
}

function PlanCard({
  plan,
  current,
  onSelect,
}: {
  plan: WebPlan;
  current: boolean;
  onSelect: () => void;
}) {
  const features = FEATURE_ORDER.filter((k) => (plan.features || {})[k]);
  const isEnterprise = plan.slug === "enterprise";
  const isTrial = plan.slug === "free-trial";
  const enabled = ENABLED_PLAN_SLUGS.has(plan.slug);
  const creditCents = isTrial ? TRIAL_CREDIT_CENTS : plan.included_credit_cents;
  return (
    <div
      className={`relative flex flex-col rounded-3xl border border-ink/[0.08] bg-white p-6 ${
        current ? "ring-2 ring-emerald-400/60" : ""
      }`}
    >
      {current && (
        <div className="absolute -top-3 right-4 rounded-full bg-emerald-500 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-white shadow-lg">
          Current
        </div>
      )}

      <div className="mb-4">
        <h3 className="text-[18px] font-bold text-ink dark:text-fog">{plan.name}</h3>
        <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">{plan.description}</p>
      </div>

      <div className="mb-5 flex items-baseline gap-1">
        <span className="text-[34px] font-extrabold tracking-tight text-ink dark:text-fog">
          {isEnterprise ? "Custom" : plan.price_cents === 0 ? "Free" : fmtCents(plan.price_cents)}
        </span>
        {!isEnterprise && plan.price_cents > 0 && (
          <span className="text-[13px] text-ink/45 dark:text-fog/45">/month</span>
        )}
      </div>

      <div className="mb-5 grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">AI credit</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise ? "Custom" : fmtCents(creditCents)}
          </div>
        </div>
        <div className="rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">Channels</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise ? "Custom" : plan.max_channels == null ? "Unlimited" : plan.max_channels}
          </div>
        </div>
        <div className="col-span-2 rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">Messages / month</div>
          <div className="font-semibold text-ink dark:text-fog">
            {isEnterprise
              ? "Custom"
              : plan.max_messages_per_month == null
                ? "Unlimited"
                : plan.max_messages_per_month.toLocaleString()}
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
            {FEATURE_LABELS[k] || k}
          </li>
        ))}
      </ul>

      <button
        onClick={onSelect}
        disabled={current || !enabled}
        className={`w-full rounded-2xl px-4 py-3 text-[13px] font-bold transition-all ${
          current
            ? "cursor-default bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : enabled
              ? "bg-deep-violet text-white hover:bg-deep-violet/90 active:scale-[0.98]"
              : "cursor-not-allowed bg-ink/[0.06] text-ink/45 dark:bg-fog/[0.08] dark:text-fog/45"
        }`}
      >
        {current
          ? "Your current plan"
          : isEnterprise
            ? "Contact us"
            : enabled
              ? "Included"
              : "Coming soon"}
      </button>
    </div>
  );
}

export default function PlansPage() {
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

  const handleSelect = (plan: WebPlan) => {
    if (plan.slug === "enterprise") {
      window.location.href =
        "mailto:sales@sayvors.com?subject=" +
        encodeURIComponent("Sayvors Enterprise plan inquiry");
      return;
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
    // A legacy "free" row duplicates the free trial card and invites a
    // downgrade we do not offer. The trial is the only entry plan.
    .filter((p) => p.slug !== "free")
    .sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="relative h-full overflow-y-auto">
      <div className="relative mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* header */}
        <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-deep-violet/10 px-3 py-1 text-[11px] font-semibold text-deep-violet dark:bg-deep-violet/20 dark:text-fuchsia-300">
              <span className="h-1.5 w-1.5 rounded-full bg-deep-violet animate-pulse" />
              Plans &amp; billing
            </div>
            <h1 className="mt-3 text-[30px] font-extrabold tracking-tight text-ink dark:text-fog">
              Choose the plan that fits your business
            </h1>
            <p className="mt-1 max-w-2xl text-[14px] text-ink/55 dark:text-fog/55">
              Every new business starts with a free trial and $10 of AI credit. Upgrade when you are ready.
            </p>
          </div>
          {entitlements && (
            <div className="rounded-2xl border border-ink/[0.08] bg-white px-4 py-3 dark:border-fog/[0.08] dark:bg-ink/60">
              <div className="text-[10px] uppercase tracking-wider text-ink/45 dark:text-fog/45">Current plan</div>
              <div className="mt-0.5 text-[16px] font-bold text-ink dark:text-fog">
                {planLabel(currentSlug, entitlements.plan_name)}
              </div>
              <div className="text-[11px] text-ink/50 dark:text-fog/50">
                {entitlements.promo_active ? "Promo active" : entitlements.status}
              </div>
            </div>
          )}
        </div>

        {/* usage strip */}
        {entitlements && (
          <div className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <UsageMeter
              label="Channels"
              used={channelCount}
              max={maxChannels}
              barClass="bg-sky-500"
            />
            <UsageMeter
              label="AI credit balance"
              used={budget ? (budget.balance_cents / 100) : 0}
              max={null}
              suffix="$"
              barClass="bg-emerald-500"
              display={budget ? `$${(budget.balance_cents / 100).toFixed(2)}` : "—"}
            />
            <UsageMeter
              label="Messages / month"
              used={0}
              max={entitlements.max_messages_per_month ?? null}
              barClass="bg-amber-500"
              display={
                entitlements.max_messages_per_month == null
                  ? "Unlimited"
                  : `0 / ${entitlements.max_messages_per_month.toLocaleString()}`
              }
            />
          </div>
        )}

        {/* plan grid */}
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
          {sortedPlans.map((p) => (
            <PlanCard
              key={p.id}
              plan={p}
              current={p.slug === currentSlug}
              onSelect={() => handleSelect(p)}
            />
          ))}
        </div>

        {/* feature matrix */}
        <div className="mt-12">
          <h2 className="mb-4 text-[18px] font-bold text-ink dark:text-fog">Feature comparison</h2>
          <div className="overflow-x-auto rounded-3xl border border-ink/[0.08] bg-white dark:border-fog/[0.08] dark:bg-ink/60">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-ink/[0.06] dark:border-fog/[0.06]">
                  <th className="px-4 py-3 text-left font-semibold text-ink/60 dark:text-fog/60">Feature</th>
                  {sortedPlans.map((p) => (
                    <th
                      key={p.id}
                      className={`px-3 py-3 text-center font-semibold ${
                        p.slug === currentSlug ? "text-emerald-600 dark:text-emerald-400" : "text-ink/70 dark:text-fog/70"
                      }`}
                    >
                      {p.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURE_ORDER.map((k) => (
                  <tr key={k} className="border-b border-ink/[0.04] last:border-0 dark:border-fog/[0.04]">
                    <td className="px-4 py-2.5 text-ink/75 dark:text-fog/75">{FEATURE_LABELS[k]}</td>
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
          Prices in USD. The free trial includes $10 of AI credit. Online upgrades for Starter, Pro and Growth
          are coming soon; Enterprise is custom — contact us.
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
