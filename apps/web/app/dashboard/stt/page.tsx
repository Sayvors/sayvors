"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

export default function SttPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <Breadcrumbs items={[{ label: "Speech to Text" }]} />
      <div className="flex flex-col items-center justify-center rounded-xl border border-ink/[0.06] bg-white py-20 dark:bg-ink dark:border-fog/[0.06]">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-white mb-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
            <path d="M19 10v2a7 7 0 01-14 0v-2" />
            <path d="M12 19v4M8 23h8" />
          </svg>
        </div>
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Speech to Text</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">Audio transcription powered by AI.</p>
        <span className="mt-3 rounded-full bg-ink/[0.06] px-3 py-1 text-[10px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Coming Soon</span>
      </div>
    </div>
  );
}
