"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useTheme } from "@/components/ThemeProvider";

const languages = [
  { code: "en", label: "English", flag: "🇺🇸" },
  { code: "es", label: "Spanish", flag: "🇪🇸" },
  { code: "fr", label: "French", flag: "🇫🇷" },
  { code: "de", label: "German", flag: "🇩🇪" },
  { code: "ar", label: "Arabic", flag: "🇸🇦" },
  { code: "ur", label: "Urdu", flag: "🇵🇰" },
];

export default function Header() {
  const { theme, toggle } = useTheme();
  const [searchFocused, setSearchFocused] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [lang, setLang] = useState(languages[0]);
  const [createOpen, setCreateOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);
  const createRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
      if (createRef.current && !createRef.current.contains(e.target as Node)) setCreateOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => {
    function handleKeydown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === "Escape" && document.activeElement === searchRef.current) {
        searchRef.current?.blur();
      }
    }
    document.addEventListener("keydown", handleKeydown);
    return () => document.removeEventListener("keydown", handleKeydown);
  }, []);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-deep-violet/[0.06] bg-white px-4 dark:bg-ink dark:border-deep-violet/[0.06]">
      {/* Left: Search */}
      <div className="flex items-center gap-3">
        {/* Search */}
        <div className="relative">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 transition-colors ${
              searchFocused ? "text-deep-violet" : "text-ink/25 dark:text-fog/25"
            }`}
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={searchRef}
            type="text"
            placeholder="Search..."
            aria-label="Search"
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            className="h-8 w-56 rounded-md border border-deep-violet/[0.08] bg-deep-violet/[0.03] pl-8 pr-8 text-[12px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:w-72 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-deep-violet/[0.12] dark:bg-deep-violet/[0.06] dark:text-fog dark:placeholder:text-fog/30 dark:focus:bg-ink"
          />
          <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-deep-violet/[0.1] bg-white px-1 py-0.5 text-[9px] font-medium text-deep-violet/40 dark:border-deep-violet/[0.15] dark:bg-ink dark:text-deep-violet/50">
            ⌘K
          </kbd>
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-1">
        {/* Connect channel */}
        <Link
          href="/dashboard/channels"
          className="flex h-8 items-center gap-1.5 rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white shadow-sm shadow-deep-violet/25 transition hover:bg-deep-violet/90 hover:shadow-md active:scale-[0.98]"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
          Connect
        </Link>

        {/* Subscribe to premium */}
        <button
          aria-label="Subscribe to premium"
          className="flex h-8 items-center gap-1.5 rounded-lg bg-amber-500 px-3 text-[12px] font-semibold text-white shadow-sm shadow-amber-500/25 transition hover:bg-amber-500/90 active:scale-[0.98]"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
          </svg>
          Premium
        </button>

        <div className="mx-1 h-5 w-px bg-deep-violet/[0.08]" />

        {/* Quick create */}
        <div className="relative" ref={createRef}>
          <button
            onClick={() => setCreateOpen(!createOpen)}
            aria-label="Create new"
            aria-expanded={createOpen}
            title="Create new"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
              <path d="M8 3v10M3 8h10" strokeLinecap="round" />
            </svg>
          </button>
          {createOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-deep-violet/[0.08] bg-white py-1 shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
              <CreateMenuItem label="New agent" href="/dashboard/agents/create" />
              <CreateMenuItem label="New databank" href="/dashboard/databank" />
              <CreateMenuItem label="New channel" href="/dashboard/channels" />
              <CreateMenuItem label="New automation" href="/dashboard/automations" />
            </div>
          )}
        </div>

        {/* Notifications */}
        <button
          aria-label="Notifications"
          title="Notifications"
          className="relative flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-coral" />
        </button>

        {/* Theme toggle */}
        <button
          onClick={toggle}
          aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:text-deep-violet"
          title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
        >
          {theme === "light" ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <circle cx="12" cy="12" r="5" />
              <line x1="12" y1="1" x2="12" y2="3" />
              <line x1="12" y1="21" x2="12" y2="23" />
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
              <line x1="1" y1="12" x2="3" y2="12" />
              <line x1="21" y1="12" x2="23" y2="12" />
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </svg>
          )}
        </button>

        {/* Language */}
        <div className="relative" ref={langRef}>
          <button
            onClick={() => setLangOpen(!langOpen)}
            aria-label="Change language"
            aria-expanded={langOpen}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
            title="Change language"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
          </button>
          {langOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-40 overflow-hidden rounded-lg border border-deep-violet/[0.08] bg-white shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
              {languages.map((l) => (
                <button
                  key={l.code}
                  onClick={() => { setLang(l); setLangOpen(false); }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-[12px] transition hover:bg-deep-violet/[0.04] ${
                    lang.code === l.code ? "font-medium text-deep-violet" : "text-ink/60 dark:text-fog/60"
                  }`}
                >
                  <span className="text-[14px]">{l.flag}</span>
                  {l.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mx-1 h-5 w-px bg-deep-violet/[0.08]" />

        {/* Settings */}
        <Link
          href="/dashboard/settings"
          aria-label="Settings"
          title="Settings"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </Link>

        {/* Help */}
        <Link
          href="/dashboard/docs"
          aria-label="Help and documentation"
          title="Help and documentation"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </Link>
      </div>
    </header>
  );
}

function CreateMenuItem({ label, href }: { label: string; href: string }) {
  return (
    <Link
      href={href}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-[12px] text-ink/60 transition hover:bg-deep-violet/[0.04] hover:text-ink focus-visible:bg-deep-violet/[0.04] focus-visible:outline-none dark:text-fog/60 dark:hover:text-fog"
    >
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3 text-ink/30 dark:text-fog/30">
        <path d="M8 3v10M3 8h10" strokeLinecap="round" />
      </svg>
      {label}
    </Link>
  );
}
