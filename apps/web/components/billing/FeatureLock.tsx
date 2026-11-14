"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import LogoLoader from "@/components/LogoLoader";
import { queryKeys } from "@/lib/query-keys";
import { getEntitlements } from "@/lib/api-billing";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { featureLabel } from "@/lib/feature-labels";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

/* Page-level plan gate. If the tenant's effective plan lacks `feature`, the
 * page is replaced with a premium-locked state instead of rendering content —
 * the API gates are the backstop; this is what the user actually sees.
 */
export default function FeatureLock({
  feature,
  children,
}: {
  feature: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const { data: entitlements, isLoading } = useQuery({
    queryKey: queryKeys.billing.entitlements(),
    queryFn: getEntitlements,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LogoLoader />
      </div>
    );
  }

  const enabled = !!entitlements?.features?.[feature];
  if (!enabled) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <h1 className="max-w-md text-[20px] font-bold text-ink dark:text-fog">
          {t.dashboard.plans.premiumTitle}
        </h1>
        <p className="max-w-sm text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
          {fill(t.dashboard.plans.premiumBody, { feature: featureLabel(feature) })}
        </p>
        <Link
          href="/dashboard/plans"
          className="mt-1 rounded-2xl bg-deep-violet px-5 py-2.5 text-[13px] font-bold text-white transition hover:bg-deep-violet/90 active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
        >
          {t.dashboard.plans.viewPremiumPlans}
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}
