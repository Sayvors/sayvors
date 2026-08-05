"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

export default function SharedTemplatesPage() {
  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Templates" }, { label: "Shared" }]} />
      <div className="flex flex-col items-center justify-center rounded-xl border border-ink/[0.06] bg-white py-20 dark:bg-ink dark:border-fog/[0.06]">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet/60 to-magenta/60 text-white mb-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
          </svg>
        </div>
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Shared Templates</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">Templates shared by the community.</p>
        <span className="mt-3 rounded-full bg-ink/[0.06] px-3 py-1 text-[10px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Coming Soon</span>
      </div>
    </div>
  );
}
