"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

export default function TemplatesPage() {
  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Templates" }]} />
      <div className="flex flex-col items-center justify-center rounded-xl border border-ink/[0.06] bg-white py-20 dark:bg-ink dark:border-fog/[0.06]">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-400 to-orange-500 text-white mb-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
          </svg>
        </div>
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Agent Templates</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">Pre-built templates for common agent use cases.</p>
        <span className="mt-3 rounded-full bg-ink/[0.06] px-3 py-1 text-[10px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Coming Soon</span>
      </div>
    </div>
  );
}
