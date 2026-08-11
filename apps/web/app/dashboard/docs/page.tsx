"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

export default function DocsPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <Breadcrumbs items={[{ label: "Chat with Docs" }]} />
      <div className="flex flex-col items-center justify-center rounded-xl border border-ink/[0.06] bg-white py-20 dark:bg-ink dark:border-fog/[0.06]">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 text-white mb-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        </div>
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Chat with Docs</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">Ask questions about your documents.</p>
        <span className="mt-3 rounded-full bg-ink/[0.06] px-3 py-1 text-[10px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Coming Soon</span>
      </div>
    </div>
  );
}
