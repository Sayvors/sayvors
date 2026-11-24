"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getEntitlements, getPlans } from "@/lib/api-billing";
import { queryKeys } from "@/lib/query-keys";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { featureLabelFor } from "@/lib/feature-labels";
import CrownIcon from "@/components/billing/CrownIcon";
import {
  SURFACE_FEATURES,
  cheapestPlanFor,
  planLabel,
  type GatedSurface,
} from "@/lib/plan-gating";

function fill(template: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, value),
    template,
  );
}

/* Page-level plan gate.
 *
 * Rendered from the route's layout.tsx, so a locked page never mounts: no
 * gated fetches, no 403 toasts behind the overlay, and no flash of content.
 * The overlay covers the page pane only — the sidebar stays usable, so the
 * tenant can leave for a plan they do have instead of being trapped.
 *
 * The UI never decides access on its own: the API still rejects gated calls.
 */
export default function PlanGate({
  surface,
  children,
}: {
  /** Route whose feature gates this subtree. Must exist in SURFACE_FEATURES. */
  surface: GatedSurface;
  children: ReactNode;
}) {
  const feature = SURFACE_FEATURES[surface];
  const { t, locale } = useI18n();
  const router = useRouter();
  const panelRef = useRef<HTMLDivElement>(null);
  const ctaRef = useRef<HTMLAnchorElement>(null);

  const entitlementsQuery = useQuery({
    queryKey: queryKeys.billing.entitlements(),
    queryFn: getEntitlements,
  });
  const entitlements = entitlementsQuery.data;

  /* Unknown plan → not locked (see isPathLocked). The preview still renders
   * instead of children until the answer arrives, because mounting a gated
   * page for a tenant who cannot use it fires requests that 403. */
  const locked = !!entitlements && entitlements.features?.[feature] !== true;

  const plansQuery = useQuery({
    queryKey: queryKeys.billing.plans(),
    queryFn: getPlans,
    enabled: locked,
    // Cheap, public catalog; retrying three times only delays the fallback.
    retry: false,
    staleTime: 5 * 60_000,
  });

  const dismiss = useCallback(() => router.push("/dashboard"), [router]);

  useEffect(() => {
    if (!locked) return;
    ctaRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled])',
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!panelRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [locked, dismiss]);

  if (entitlementsQuery.isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="max-w-sm text-[13px] text-ink/70 dark:text-fog/70">
          {t.dashboard.plans.planGateError}
        </p>
        <button
          type="button"
          onClick={() => void entitlementsQuery.refetch()}
          className="h-10 rounded-[8px] bg-deep-violet px-5 text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
        >
          {t.common.retry}
        </button>
      </div>
    );
  }

  if (!locked) {
    // `isPending` renders the preview, not children: see the comment above.
    return entitlementsQuery.isPending ? <LockedPreview /> : <>{children}</>;
  }

  const label = featureLabelFor(feature, locale);
  const names = t.dashboard.plans.planNames;
  const requiredPlan = cheapestPlanFor(plansQuery.data, feature);
  const requiredName = requiredPlan
    ? planLabel(requiredPlan.slug, names, requiredPlan.name)
    : null;
  const currentName =
    planLabel(entitlements.plan_slug, names, entitlements.plan_name) || null;
  const title = requiredName
    ? fill(t.dashboard.plans.planGateTitle, { feature: label, plan: requiredName })
    : fill(t.dashboard.plans.planGateTitleFallback, { feature: label });
  const body = currentName
    ? fill(t.dashboard.plans.planGateBody, { feature: label, current: currentName })
    : fill(t.dashboard.plans.planGateBodyFallback, { feature: label });

  return (
    <div className="relative h-full">
      <LockedPreview />
      <div
        className="absolute inset-0 z-30 flex items-center justify-center bg-ink/60 p-4 dark:bg-black/70"
        // A click on the dimmed pane returns to the dashboard: every other
        // target under it is inert preview, so there is nothing to preserve.
        onClick={dismiss}
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-labelledby="plan-gate-title"
          // Not aria-modal: the sidebar stays live on purpose.
          onClick={(event) => event.stopPropagation()}
          className="w-full max-w-sm rounded-[8px] bg-white p-6 text-ink shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_24px_48px_-16px_rgba(20,16,31,0.45)] dark:bg-ink dark:text-fog dark:shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_24px_48px_-16px_rgba(0,0,0,0.8)]"
        >
          <div className="flex h-11 w-11 items-center justify-center rounded-[8px] bg-[#FFF4D6] text-[#8A5A00] dark:bg-[#3A2C12] dark:text-[#F2C14E]">
            <CrownIcon className="h-5 w-5" />
          </div>
          <h2
            id="plan-gate-title"
            className="mt-4 text-[18px] font-bold tracking-tight"
          >
            {title}
          </h2>
          <p className="mt-1.5 text-[13px] leading-5 text-ink/60 dark:text-fog/60">
            {body}
          </p>
          <div className="mt-5 flex gap-2">
            <Link
              ref={ctaRef}
              href="/dashboard/plans"
              className="flex h-11 flex-1 items-center justify-center rounded-[8px] bg-deep-violet text-[13px] font-bold text-white shadow-[0_1px_0_rgba(255,255,255,0.25)_inset,0_8px_16px_-8px_rgba(61,29,110,0.8)] transition active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
            >
              {t.dashboard.plans.viewPremiumPlans}
            </Link>
            <button
              type="button"
              onClick={dismiss}
              className="h-11 rounded-[8px] border border-ink/10 px-5 text-[13px] font-bold text-ink/70 transition hover:bg-ink/[0.04] active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/15 dark:text-fog/70 dark:hover:bg-fog/[0.06]"
            >
              {t.dashboard.plans.planGateNotNow}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* Neutral skeleton that sits under the scrim. It is deliberately page-agnostic:
 * showing a real but inactive page would promise controls that do not respond,
 * and would leak the shape of a surface the plan does not include. */
function LockedPreview() {
  return (
    <div aria-hidden className="h-full overflow-hidden p-4 sm:p-6">
      <div className="mx-auto max-w-5xl">
        <div className="h-7 w-44 rounded-full bg-[var(--ui-line)]" />
        <div className="mt-2.5 h-3 w-72 max-w-full rounded-full bg-[var(--ui-line)]" />
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="rounded-[8px] bg-[var(--ui-surface)] p-4 ring-1 ring-[var(--ui-line)]"
            >
              <div className="h-9 w-9 rounded-full bg-[var(--ui-sunken)]" />
              <div className="mt-3 h-3 w-2/3 rounded-full bg-[var(--ui-line)]" />
              <div className="mt-2 h-2.5 w-1/2 rounded-full bg-[var(--ui-line)]" />
            </div>
          ))}
        </div>
        <div className="mt-3 h-56 rounded-[8px] bg-[var(--ui-surface)] ring-1 ring-[var(--ui-line)]" />
      </div>
    </div>
  );
}
