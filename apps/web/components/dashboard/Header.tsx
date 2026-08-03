"use client";

import Image from "next/image";
import Link from "next/link";
import { useState, useRef, useEffect } from "react";

const languages = [
  { code: "en", label: "English", flag: "🇺🇸" },
  { code: "es", label: "Spanish", flag: "🇪🇸" },
  { code: "fr", label: "French", flag: "🇫🇷" },
  { code: "de", label: "German", flag: "🇩🇪" },
  { code: "ar", label: "Arabic", flag: "🇸🇦" },
  { code: "ur", label: "Urdu", flag: "🇵🇰" },
];

export default function Header() {
  const [searchFocused, setSearchFocused] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [langOpen, setLangOpen] = useState(false);
  const [lang, setLang] = useState(languages[0]);
  const [profileOpen, setProfileOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-ink/[0.06] bg-white px-4">
      {/* Left: Logo + Search */}
      <div className="flex items-center gap-3">
        {/* Logo + Wordmark */}
        <Link href="/dashboard" className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-deep-violet to-magenta">
            <span className="text-[11px] font-bold text-white">S</span>
          </div>
          <Image
            src="/Sayvors_Wordmark_Dark.png"
            alt="Sayvors"
            width={120}
            height={20}
            className="h-5 w-auto"
          />
        </Link>

        <div className="h-5 w-px bg-ink/[0.06]" />

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
            className="h-8 w-56 rounded-md border border-ink/[0.08] bg-fog/40 pl-8 pr-8 text-[12px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:w-72 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06]"
          />
          <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-ink/[0.08] bg-white px-1 py-0.5 text-[9px] font-medium text-ink/25">
            ⌘K
          </kbd>
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-1">
        {/* Create automation */}
        <button className="flex h-8 items-center gap-1.5 rounded-lg bg-gradient-to-r from-deep-violet to-magenta px-3 text-[12px] font-semibold text-white shadow-sm shadow-deep-violet/20 transition hover:shadow-md active:scale-[0.98]">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
          Automation
        </button>

        <div className="mx-1 h-5 w-px bg-ink/[0.06]" />

        {/* Notifications */}
        <button className="relative flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-coral" />
        </button>

        {/* Theme toggle */}
        <button
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60"
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
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60"
            title="Change language"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
          </button>
          {langOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-40 overflow-hidden rounded-lg border border-ink/[0.08] bg-white shadow-lg">
              {languages.map((l) => (
                <button
                  key={l.code}
                  onClick={() => { setLang(l); setLangOpen(false); }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-[12px] transition hover:bg-fog ${
                    lang.code === l.code ? "font-medium text-deep-violet" : "text-ink/60"
                  }`}
                >
                  <span className="text-[14px]">{l.flag}</span>
                  {l.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mx-1 h-5 w-px bg-ink/[0.06]" />

        {/* Profile dropdown */}
        <div className="relative" ref={profileRef}>
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className="flex items-center gap-1.5 rounded-lg px-1.5 py-1 transition hover:bg-ink/[0.04]"
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[10px] font-semibold text-white">
              SS
            </div>
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className={`h-3 w-3 text-ink/30 transition-transform ${profileOpen ? "rotate-180" : ""}`}>
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {profileOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-ink/[0.08] bg-white shadow-lg">
              <div className="border-b border-ink/[0.06] px-3 py-2.5">
                <p className="text-[13px] font-medium text-ink">Syed S.</p>
                <p className="text-[11px] text-ink/40">syed@sayvors.com</p>
              </div>
              <div className="py-1">
                <ProfileMenuItem icon={<UserIcon />} label="My profile" />
                <ProfileMenuItem icon={<SettingsIcon />} label="Settings" />
                <ProfileMenuItem icon={<CreditCardIcon />} label="Billing" />
                <ProfileMenuItem icon={<HelpIcon />} label="Help & support" />
              </div>
              <div className="border-t border-ink/[0.06] py-1">
                <ProfileMenuItem icon={<LogoutIcon />} label="Sign out" danger />
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function ProfileMenuItem({ icon, label, danger }: { icon: React.ReactNode; label: string; danger?: boolean }) {
  return (
    <button className={`flex w-full items-center gap-2.5 px-3 py-2 text-[12px] transition hover:bg-fog ${danger ? "text-coral" : "text-ink/60"}`}>
      {icon}
      {label}
    </button>
  );
}

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  );
}

function CreditCardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
    </svg>
  );
}

function HelpIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}
