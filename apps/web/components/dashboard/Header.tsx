"use client";

import { useState } from "react";

const quickStats = [
  { label: "Messages today", value: "142", icon: MessageIcon },
  { label: "Active chats", value: "23", icon: ChatIcon },
  { label: "Unread", value: "8", icon: BellIcon },
];

export default function Header() {
  const [searchFocused, setSearchFocused] = useState(false);

  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-ink/[0.06] bg-white px-4">
      {/* Left: Search */}
      <div className="relative w-full max-w-sm">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 transition-colors ${
            searchFocused ? "text-deep-violet" : "text-ink/25"
          }`}
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          placeholder="Search..."
          onFocus={() => setSearchFocused(true)}
          onBlur={() => setSearchFocused(false)}
          className="h-8 w-full rounded-md border border-ink/[0.08] bg-fog/40 pl-8 pr-8 text-[12px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06]"
        />
        <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-ink/[0.08] bg-white px-1 py-0.5 text-[9px] font-medium text-ink/25">
          ⌘K
        </kbd>
      </div>

      {/* Center: Quick stats */}
      <div className="hidden items-center gap-4 md:flex">
        {quickStats.map((s) => (
          <div key={s.label} className="flex items-center gap-1.5">
            <s.icon className="h-3.5 w-3.5 text-ink/25" />
            <span className="text-[11px] text-ink/40">{s.label}:</span>
            <span className="text-[12px] font-semibold text-ink">{s.value}</span>
          </div>
        ))}
      </div>

      {/* Right: Actions + Avatar */}
      <div className="flex items-center gap-1.5">
        <button className="relative flex h-7 w-7 items-center justify-center rounded-md text-ink/35 transition hover:bg-ink/[0.04] hover:text-ink/60">
          <BellIcon className="h-3.5 w-3.5" />
          <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-coral" />
        </button>

        <button className="relative flex h-7 w-7 items-center justify-center rounded-md text-ink/35 transition hover:bg-ink/[0.04] hover:text-ink/60">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
            <circle cx="12" cy="12" r="1" />
            <circle cx="12" cy="5" r="1" />
            <circle cx="12" cy="19" r="1" />
          </svg>
        </button>

        <div className="mx-1 h-4 w-px bg-ink/[0.06]" />

        <button className="flex items-center gap-1.5 rounded-md px-1.5 py-1 transition hover:bg-ink/[0.04]">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[10px] font-semibold text-white">
            SS
          </div>
          <span className="hidden text-[12px] font-medium text-ink/70 sm:inline">Syed</span>
        </button>
      </div>
    </header>
  );
}

function MessageIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
      <polyline points="22,6 12,13 2,6" />
    </svg>
  );
}

function ChatIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function BellIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 01-3.46 0" />
    </svg>
  );
}
