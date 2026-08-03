"use client";

import { useState } from "react";

export default function Header() {
  const [searchFocused, setSearchFocused] = useState(false);

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-ink/[0.06] bg-white px-6">
      {/* Search */}
      <div className="relative flex-1 max-w-xl">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 transition-colors ${
            searchFocused ? "text-deep-violet" : "text-ink/30"
          }`}
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          placeholder="Search conversations, contacts, messages..."
          onFocus={() => setSearchFocused(true)}
          onBlur={() => setSearchFocused(false)}
          className="h-10 w-full rounded-lg border border-ink/[0.08] bg-fog/50 pl-10 pr-4 text-[13px] text-ink outline-none transition placeholder:text-ink/35 focus:border-deep-violet/30 focus:bg-white focus:ring-[3px] focus:ring-deep-violet/[0.06]"
        />
        <kbd className="absolute right-3 top-1/2 -translate-y-1/2 rounded border border-ink/[0.08] bg-white px-1.5 py-0.5 text-[10px] font-medium text-ink/30">
          ⌘K
        </kbd>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {/* Notifications */}
        <button className="relative flex h-9 w-9 items-center justify-center rounded-lg text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-coral" />
        </button>

        {/* Avatar */}
        <button className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition hover:bg-ink/[0.04]">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[13px] font-semibold text-white">
            SS
          </div>
          <div className="hidden text-left sm:block">
            <p className="text-[13px] font-medium text-ink">Syed S.</p>
            <p className="text-[11px] text-ink/40">Pro plan</p>
          </div>
        </button>
      </div>
    </header>
  );
}
