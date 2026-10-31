"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  subscribeEntitlementDenied,
  type EntitlementDeniedDetail,
} from "@/lib/entitlements";
import { featureLabel } from "@/lib/feature-labels";

/* Global "this is premium" dialog.
 *
 * Fires on any API 403/429 carrying X-Entitlement-Denied, no matter which
 * call site triggered it. Mounted once in the dashboard layout. Dismissing
 * never retries the blocked action — the caller already surfaced its own
 * error state.
 */
export default function UpgradePrompt() {
  const router = useRouter();
  const [denial, setDenial] = useState<EntitlementDeniedDetail | null>(null);

  useEffect(() => subscribeEntitlementDenied((d) => setDenial(d)), []);

  useEffect(() => {
    if (!denial) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDenial(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [denial]);

  if (!denial) return null;

  const isQuota = denial.feature === "quota";
  const title = isQuota ? "You've hit your plan limit" : "This feature is premium";
  const body = isQuota
    ? denial.message
    : `${featureLabel(denial.feature ?? "")} isn't included in your current plan.`;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-ink/60 p-4 dark:bg-black/70"
      role="dialog"
      aria-modal="true"
      aria-label="Plan limit"
      onClick={() => setDenial(null)}
    >
      <div
        className="w-full max-w-sm rounded-[24px] bg-white p-6 text-ink shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_24px_48px_-16px_rgba(20,16,31,0.45)] dark:bg-ink dark:text-fog dark:shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_24px_48px_-16px_rgba(0,0,0,0.8)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-deep-violet/10 text-[20px] dark:bg-deep-violet/25">
          <span aria-hidden="true">⭐</span>
        </div>
        <h2 className="mt-4 text-[18px] font-bold tracking-tight">{title}</h2>
        <p className="mt-1.5 text-[13px] leading-5 text-ink/60 dark:text-fog/60">{body}</p>
        <p className="mt-1 text-[13px] leading-5 text-ink/60 dark:text-fog/60">
          Upgrade to unlock it — it takes effect immediately.
        </p>
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            autoFocus
            onClick={() => {
              setDenial(null);
              router.push("/dashboard/plans");
            }}
            className="h-11 flex-1 rounded-[20px] bg-deep-violet text-[13px] font-bold text-white shadow-[0_1px_0_rgba(255,255,255,0.25)_inset,0_8px_16px_-8px_rgba(61,29,110,0.8)] transition active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
          >
            View plans
          </button>
          <button
            type="button"
            onClick={() => setDenial(null)}
            className="h-11 rounded-[20px] border border-ink/10 px-5 text-[13px] font-bold text-ink/70 transition hover:bg-ink/[0.04] active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/15 dark:text-fog/70 dark:hover:bg-fog/[0.06]"
          >
            Later
          </button>
        </div>
      </div>
    </div>
  );
}
