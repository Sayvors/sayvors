"use client";

import { useState } from "react";

interface WidgetPreviewProps {
  position: "bottom-right" | "bottom-left" | "top-right" | "top-left";
  primaryColor: string;
  font: string;
  launcherIcon: string;
  welcomeText: string;
}

const posClass: Record<string, string> = {
  "bottom-right": "bottom-3 right-3",
  "bottom-left": "bottom-3 left-3",
  "top-right": "top-3 right-3",
  "top-left": "top-3 left-3",
};

const chatPos: Record<string, string> = {
  "bottom-right": "bottom-14 right-3",
  "bottom-left": "bottom-14 left-3",
  "top-right": "top-14 right-3",
  "top-left": "top-14 left-3",
};

export default function WidgetPreview({ position, primaryColor, font, launcherIcon, welcomeText }: WidgetPreviewProps) {
  const [open, setOpen] = useState(false);

  const iconMap: Record<string, React.ReactNode> = {
    chat: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-white">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      </svg>
    ),
    question: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-white">
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
        <circle cx="12" cy="17" r="0.5" fill="currentColor" />
      </svg>
    ),
    headphones: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-white">
        <path d="M3 18v-6a9 9 0 0118 0v6" />
        <path d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3z" />
      </svg>
    ),
  };

  return (
    <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
      <p className="mb-2 text-[11px] font-medium text-ink/30 dark:text-fog/30">Widget Preview</p>
      <div className="relative mx-auto h-52 w-64 overflow-hidden rounded-lg border border-ink/[0.08] bg-white shadow-sm dark:border-fog/[0.08] dark:bg-ink">
        {/* Fake page content */}
        <div className="space-y-2 p-3">
          <div className="h-2.5 w-16 rounded bg-ink/[0.06] dark:bg-fog/[0.06]" />
          <div className="h-2 w-full rounded bg-ink/[0.04] dark:bg-fog/[0.04]" />
          <div className="h-2 w-3/4 rounded bg-ink/[0.04] dark:bg-fog/[0.04]" />
          <div className="mt-3 h-16 w-full rounded bg-ink/[0.03] dark:bg-fog/[0.03]" />
          <div className="h-2 w-full rounded bg-ink/[0.04] dark:bg-fog/[0.04]" />
          <div className="h-2 w-2/3 rounded bg-ink/[0.04] dark:bg-fog/[0.04]" />
        </div>

        {/* Chat window */}
        {open && (
          <div
            className={`absolute ${chatPos[position]} z-10 w-44 rounded-lg border border-ink/[0.08] bg-white shadow-xl dark:border-fog/[0.08] dark:bg-ink`}
            style={{ fontFamily: font === "system" ? "system-ui" : font }}
          >
            <div className="flex items-center gap-2 rounded-t-lg px-3 py-2" style={{ backgroundColor: primaryColor }}>
              <div className="flex h-5 w-5 items-center justify-center rounded-full bg-white/20 text-[9px] text-white">A</div>
              <span className="text-[11px] font-semibold text-white">Agent</span>
            </div>
            <div className="p-2.5">
              <div className="rounded-lg bg-ink/[0.04] px-2.5 py-1.5 dark:bg-fog/[0.04]">
                <p className="text-[10px] text-ink/70 dark:text-fog/70">{welcomeText || "Hi! How can I help you today?"}</p>
              </div>
              <div className="mt-2 flex gap-1">
                <div className="h-5 flex-1 rounded border border-ink/[0.08] bg-white dark:border-fog/[0.08] dark:bg-ink" />
                <div className="h-5 w-5 rounded" style={{ backgroundColor: primaryColor }} />
              </div>
            </div>
          </div>
        )}

        {/* Launcher button */}
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={`absolute z-20 flex h-10 w-10 items-center justify-center rounded-full shadow-lg transition-transform hover:scale-110 ${posClass[position]}`}
          style={{ backgroundColor: primaryColor }}
        >
          {iconMap[launcherIcon] || iconMap.chat}
        </button>
      </div>
    </div>
  );
}
