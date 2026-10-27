"use client";

import { useEffect, useMemo, useState } from "react";
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

const FEATURE_LABELS: Record<string, string> = {
  channels: "Messaging channels",
  messaging: "Inbox messaging",
  ai_replies: "AI replies",
  reviews: "Review management",
  posts: "Social posts",
  media: "Media library",
  analytics: "Analytics",
  automation: "Automation rules",
  databank: "Knowledge base",
  leads: "Lead pipeline",
  voice: "Voice & TTS",
  scheduling: "Scheduling",
  assistant: "AI assistant",
  priority_support: "Priority support",
  sla: "SLA guarantee",
};

const FEATURE_ORDER = [
  "channels",
  "messaging",
  "ai_replies",
  "reviews",
  "posts",
  "media",
  "analytics",
  "automation",
  "databank",
  "leads",
  "voice",
  "scheduling",
  "assistant",
  "priority_support",
  "sla",
];

function fmtCents(c: number): string {
  return `$${(c / 100).toFixed(0)}`;
}

function PlanCard({
  plan,
  current,
  recommended,
  onSelect,
  busy,
}: {
  plan: WebPlan;
  current: boolean;
  recommended: boolean;
  onSelect: () => void;
  busy: boolean;
}) {
  const features = FEATURE_ORDER.filter((k) => (plan.features || {})[k]);
  return (
    <div
      className={`relative flex flex-col rounded-3xl border p-6 transition-all duration-300 ${
        recommended
          ? "border-transparent bg-gradient-to-b from-deep-violet/10 via-white to-white shadow-[0_20px_60px_-20px_rgba(124,58,237,0.35)] dark:from-deep-violet/20 dark:via-ink dark:to-ink scale-[1.02]"
          : "border-ink/[0.08] bg-white/70 backdrop-blur dark:border-fog/[0.08] dark:bg-ink/60"
      } ${current ? "ring-2 ring-emerald-400/60" : ""}`}
    >
      {recommended && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-gradient-to-r from-deep-violet to-fuchsia-500 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-white shadow-lg">
          Recommended
        </div>
      )}
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
          {plan.price_cents === 0 ? "Free" : fmtCents(plan.price_cents)}
        </span>
        {plan.price_cents > 0 && (
          <span className="text-[13px] text-ink/45 dark:text-fog/45">/month</span>
        )}
      </div>

      <div className="mb-5 grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">AI credit</div>
          <div className="font-semibold text-ink dark:text-fog">{fmtCents(plan.included_credit_cents)}</div>
        </div>
        <div className="rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">Channels</div>
          <div className="font-semibold text-ink dark:text-fog">
            {plan.max_channels == null ? "Unlimited" : plan.max_channels}
          </div>
        </div>
        <div className="col-span-2 rounded-xl bg-ink/[0.03] px-3 py-2 dark:bg-fog/[0.04]">
          <div className="text-ink/45 dark:text-fog/45">Messages / month</div>
          <div className="font-semibold text-ink dark:text-fog">
            {plan.max_messages_per_month == null
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
        disabled={busy || current}
        className={`w-full rounded-2xl px-4 py-3 text-[13px] font-bold transition-all ${
          current
            ? "cursor-default bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : recommended
            ? "bg-gradient-to-r from-deep-violet to-fuchsia-500 text-white shadow-lg hover:shadow-xl hover:scale-[1.02] active:scale-[0.98]"
            : "bg-ink/[0.06] text-ink hover:bg-ink/[0.1] dark:bg-fog/[0.08] dark:text-fog dark:hover:bg-fog/[0.14]"
        } disabled:opacity-60`}
      >
        {current ? "Your current plan" : plan.price_cents === 0 ? "Downgrade to free" : "Request upgrade"}
      </button>
    </div>
  );
}

export default function PlansPage() {
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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

  const recommendedSlug = useMemo(() => {
    if (!plans || !currentSlug) return null;
    const idx = plans.findIndex((p) => p.slug === currentSlug);
    // recommend the next tier up
    if (idx >= 0 && idx + 1 < plans.length) return plans[idx + 1].slug;
    return null;
  }, [plans, currentSlug]);

  const handleSelect = async (plan: WebPlan) => {
    if (plan.slug === currentSlug) return;
    setBusy(true);
    setToast(null);
    try {
      // Self-serve checkout is not wired yet (no payment gateway). Until Phase D,
      // upgrades are activated by an admin via grant-plan; surface a clear request
      // so the tenant knows what to expect instead of silently failing.
      setToast(
        `Upgrade to ${plan.name} requested. Our team will activate it and email you — usually within one business day.`
      );
    } finally {
      setBusy(false);
    }
  };

  if (plansLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LogoLoader />
      </div>
    );
  }

  const sortedPlans = [...(plans || [])].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="relative h-full overflow-y-auto">
      {/* ambient background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 -left-40 h-96 w-96 rounded-full bg-deep-violet/20 blur-3xl animate-pulse" />
        <div className="absolute top-20 right-0 h-80 w-80 rounded-full bg-fuchsia-500/15 blur-3xl animate-pulse" style={{ animationDelay: "1s" }} />
        <div className="absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-sky-500/10 blur-3xl animate-pulse" style={{ animationDelay: "2s" }} />
      </div>

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
              Upgrade anytime. AI credit, channel limits and feature access update instantly.
            </p>
          </div>
          {entitlements && (
            <div className="rounded-2xl border border-ink/[0.08] bg-white/60 px-4 py-3 backdrop-blur dark:border-fog/[0.08] dark:bg-ink/60">
              <div className="text-[10px] uppercase tracking-wider text-ink/45 dark:text-fog/45">Current plan</div>
              <div className="mt-0.5 text-[16px] font-bold text-ink dark:text-fog">{entitlements.plan_name}</div>
              <div className="text-[11px] text-ink/50 dark:text-fog/50">
                {entitlements.promo_active ? "Promo active" : entitlements.status}
              </div>
            </div>
          )}
        </div>

        {toast && (
          <div className="mb-6 rounded-2xl border border-deep-violet/20 bg-deep-violet/5 px-4 py-3 text-[13px] text-deep-violet dark:border-deep-violet/30 dark:bg-deep-violet/10 dark:text-fuchsia-300">
            {toast}
          </div>
        )}

        {/* usage strip */}
        {entitlements && (
          <div className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <UsageMeter
              label="Channels"
              used={channelCount}
              max={maxChannels}
              color="from-sky-400 to-blue-500"
            />
            <UsageMeter
              label="AI credit balance"
              used={budget ? (budget.balance_cents / 100) : 0}
              max={null}
              suffix="$"
              color="from-emerald-400 to-teal-500"
              display={budget ? `$${(budget.balance_cents / 100).toFixed(2)}` : "—"}
            />
            <UsageMeter
              label="Messages / month"
              used={0}
              max={entitlements.max_messages_per_month ?? null}
              color="from-amber-400 to-orange-500"
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
              recommended={p.slug === recommendedSlug}
              onSelect={() => handleSelect(p)}
              busy={busy}
            />
          ))}
        </div>

        {/* feature matrix */}
        <div className="mt-12">
          <h2 className="mb-4 text-[18px] font-bold text-ink dark:text-fog">Feature comparison</h2>
          <div className="overflow-x-auto rounded-3xl border border-ink/[0.08] bg-white/60 backdrop-blur dark:border-fog/[0.08] dark:bg-ink/60">
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
          Prices in USD. Upgrades take effect immediately; downgrades apply at the end of the billing period.
        </p>
      </div>
    </div>
  );
}

function UsageMeter({
  label,
  used,
  max,
  color,
  suffix,
  display,
}: {
  label: string;
  used: number;
  max: number | null;
  color: string;
  suffix?: string;
  display?: string;
}) {
  const pct = max && max > 0 ? Math.min(100, (used / max) * 100) : 0;
  return (
    <div className="rounded-2xl border border-ink/[0.08] bg-white/60 p-4 backdrop-blur dark:border-fog/[0.08] dark:bg-ink/60">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-ink/55 dark:text-fog/55">{label}</span>
        <span className="text-[12px] font-bold text-ink dark:text-fog">
          {display ?? `${used}${suffix ? suffix : ""}${max != null ? ` / ${max}` : ""}`}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.08]">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-700`}
          style={{ width: `${max == null ? 0 : pct}%` }}
        />
      </div>
    </div>
  );
}
