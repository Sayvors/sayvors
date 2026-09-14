"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "@/components/ThemeProvider";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { LOCALES } from "@/lib/i18n/locales";
import { useAuth } from "@/lib/auth-context";
import AutoPilotDialog from "@/components/dashboard/AutoPilotDialog";
import {
  derivePilotState,
  fetchPilotChannels,
  setPilot,
  type PilotChannel,
  type PilotState,
} from "@/lib/api-autopilot";

export default function Header() {
  const { theme, toggle } = useTheme();
  const { locale, setLocale, t } = useI18n();
  const [searchFocused, setSearchFocused] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);
  const createRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const { user, logout } = useAuth();

  const displayName =
    user && (user.first_name || user.last_name)
      ? `${user.first_name} ${user.last_name}`.trim()
      : t.account.fallbackName;

  const initials = user
    ? `${user.first_name?.[0] ?? ""}${user.last_name?.[0] ?? ""}`.toUpperCase() || "U"
    : "U";

  /* ── Auto Pilot (global approval switch) ── */
  const pathname = usePathname();
  const [pilotChannels, setPilotChannels] = useState<PilotChannel[]>([]);
  const [pilot, setPilotState] = useState<PilotState>("none");
  const [pilotOpen, setPilotOpen] = useState(false);
  const [pilotSaving, setPilotSaving] = useState(false);
  const [pilotError, setPilotError] = useState<string | null>(null);

  const refreshPilot = useCallback(async () => {
    try {
      const channels = await fetchPilotChannels();
      setPilotChannels(channels);
      setPilotState(derivePilotState(channels));
    } catch {
      /* backend down — pill stays neutral */
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync pilot state from API on mount/navigation
    refreshPilot();
  }, [refreshPilot, pathname]);

  async function applyPilot(on: boolean) {
    setPilotSaving(true);
    setPilotError(null);
    try {
      await setPilot(on, pilotChannels);
      await refreshPilot();
      setPilotOpen(false);
    } catch (e) {
      setPilotError(e instanceof Error ? e.message.slice(0, 160) : "Could not apply. Try again.");
    } finally {
      setPilotSaving(false);
    }
  }

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
      if (createRef.current && !createRef.current.contains(e.target as Node)) setCreateOpen(false);
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false);
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
            placeholder={t.header.search}
            aria-label={t.header.searchLabel}
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
        {/* Auto Pilot */}
        <button
          onClick={() => {
            setPilotError(null);
            setPilotOpen(true);
          }}
          title={`Auto Pilot — ${t.pilot.title}`}
          aria-label={`Auto Pilot — ${t.pilot.title}: ${pilot}`}
          className="flex h-8 items-center gap-1.5 rounded-lg border border-ink/10 px-2.5 text-[12px] font-semibold text-ink/60 outline-none transition hover:border-deep-violet/30 hover:text-ink focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:border-fog/10 dark:text-fog/60 dark:hover:text-fog"
        >
          <span
            aria-hidden
            className={`h-1.5 w-1.5 rounded-full ${
              pilot === "on" ? "bg-emerald-500" : pilot === "none" ? "bg-ink/20 dark:bg-fog/20" : "bg-amber-500"
            }`}
          />
          {t.pilot.label}
          <span
            className={`rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
              pilot === "on"
                ? "bg-emerald/10 text-emerald-600"
                : pilot === "none"
                  ? "bg-ink/[0.05] text-ink/35 dark:text-fog/35"
                  : "bg-amber/10 text-amber-600"
            }`}
          >
            {pilot === "on" ? t.pilot.on : pilot === "off" ? t.pilot.off : pilot === "mixed" ? t.pilot.mixed : t.pilot.none}
          </span>
        </button>

        {/* Connect channel */}
        <Link
          href="/dashboard/channels"
          className="flex h-8 items-center gap-1.5 rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white shadow-sm shadow-deep-violet/25 transition hover:bg-deep-violet/90 hover:shadow-md active:scale-[0.98]"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
          {t.header.connect}
        </Link>

        {/* Subscribe to premium */}
        <button
          aria-label={t.header.subscribePremium}
          className="flex h-8 items-center gap-1.5 rounded-lg bg-amber-500 px-3 text-[12px] font-semibold text-white shadow-sm shadow-amber-500/25 transition hover:bg-amber-500/90 active:scale-[0.98]"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
          </svg>
          {t.header.premium}
        </button>

        <div className="mx-1 h-5 w-px bg-deep-violet/[0.08]" />

        {/* Quick create */}
        <div className="relative" ref={createRef}>
          <button
            onClick={() => setCreateOpen(!createOpen)}
            aria-label={t.header.createNew}
            aria-expanded={createOpen}
            title={t.header.createNew}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
              <path d="M8 3v10M3 8h10" strokeLinecap="round" />
            </svg>
          </button>
          {createOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-deep-violet/[0.08] bg-white py-1 shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
              <CreateMenuItem label={t.header.newDatabank} href="/dashboard/databank/new" />
              <CreateMenuItem label={t.header.newChannel} href="/dashboard/channels" />
              <CreateMenuItem label={t.header.newAutomation} href="/dashboard/automations" />
            </div>
          )}
        </div>

        {/* Notifications */}
        <button
          aria-label={t.header.notifications}
          title={t.header.notifications}
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
          aria-label={theme === "light" ? t.header.switchToDark : t.header.switchToLight}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:text-deep-violet"
          title={theme === "light" ? t.header.switchToDark : t.header.switchToLight}
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
            aria-label={t.header.changeLanguage}
            aria-expanded={langOpen}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-deep-violet/[0.1] dark:hover:text-deep-violet"
            title={t.header.changeLanguage}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
          </button>
          {langOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-40 overflow-hidden rounded-lg border border-deep-violet/[0.08] bg-white shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
              {LOCALES.map((l) => (
                <button
                  key={l.code}
                  onClick={() => { setLocale(l.code); setLangOpen(false); }}
                  aria-current={locale === l.code ? "true" : undefined}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-[12px] transition hover:bg-deep-violet/[0.04] ${
                    locale === l.code ? "font-medium text-deep-violet" : "text-ink/60 dark:text-fog/60"
                  }`}
                >
                  <span className="text-[14px]">{l.flag}</span>
                  {l.label}
                  {locale === l.code && (
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="ml-auto h-3 w-3" aria-hidden>
                      <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mx-1 h-5 w-px bg-deep-violet/[0.08]" />

        {/* Profile */}
        <div className="relative" ref={profileRef}>
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            aria-label={t.account.menu}
            aria-expanded={profileOpen}
            title={t.account.menu}
            className="flex h-8 items-center gap-1.5 rounded-lg pl-1.5 pr-2 outline-none transition hover:bg-deep-violet/[0.06] focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:hover:bg-deep-violet/[0.1]"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-violet-light to-magenta text-[10px] font-semibold text-white">
              {initials}
            </span>
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={`h-3 w-3 text-ink/40 transition-transform ${profileOpen ? "rotate-180" : ""}`} aria-hidden>
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>
          {profileOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-deep-violet/[0.08] bg-white shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
              <div className="border-b border-deep-violet/[0.06] px-3 py-2.5">
                <p className="truncate text-[13px] font-medium text-ink dark:text-fog">{displayName}</p>
                <p className="truncate text-[11px] text-ink/40 dark:text-fog/40">{user?.email ?? ""}</p>
              </div>
              <div className="py-1">
                <ProfileMenuItem label={t.account.myProfile} href="/dashboard/profile" />
                <ProfileMenuItem label={t.header.settings} href="/dashboard/settings" />
              </div>
              <div className="border-t border-deep-violet/[0.06] py-1">
                <button
                  onClick={() => { setProfileOpen(false); logout(); }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-coral transition hover:bg-deep-violet/[0.04]"
                >
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
                    <path d="M6 8H2M4 6l4-4M4 14l4 4M10 8h4" />
                  </svg>
                  {t.account.signOut}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {pilotOpen && (
        <AutoPilotDialog
          channels={pilotChannels}
          current={pilot}
          saving={pilotSaving}
          error={pilotError}
          onConfirm={applyPilot}
          onClose={() => {
            if (!pilotSaving) setPilotOpen(false);
          }}
        />
      )}
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

function ProfileMenuItem({ label, href }: { label: string; href: string }) {
  return (
    <Link
      href={href}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-[12px] text-ink/60 transition hover:bg-deep-violet/[0.04] hover:text-ink focus-visible:bg-deep-violet/[0.04] focus-visible:outline-none dark:text-fog/60 dark:hover:text-fog"
    >
      {label}
    </Link>
  );
}
