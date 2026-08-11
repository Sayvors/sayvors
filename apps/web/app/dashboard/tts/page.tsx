"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

export default function TtsPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <Breadcrumbs items={[{ label: "Text to Speech" }]} />
      <div className="flex flex-col items-center justify-center rounded-xl border border-ink/[0.06] bg-white py-20 dark:bg-ink dark:border-fog/[0.06]">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-magenta to-coral text-white mb-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07" />
          </svg>
        </div>
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Text to Speech</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">Convert text to natural-sounding speech.</p>
        <span className="mt-3 rounded-full bg-ink/[0.06] px-3 py-1 text-[10px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Coming Soon</span>
      </div>
    </div>
  );
}
