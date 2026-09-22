"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "@/components/ThemeProvider";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { LOCALES } from "@/lib/i18n/locales";
import { useAuth } from "@/lib/auth-context";
import AutoPilotDialog from "@/components/dashboard/AutoPilotDialog";
import NotificationsBell from "@/components/dashboard/NotificationsBell";
import SearchPalette from "@/components/dashboard/SearchPalette";
import { useTour } from "@/components/tour/TourProvider";
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
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const helpRef = useRef<HTMLDivElement>(null);
  const { user, logout } = useAuth();
  const { startTour } = useTour();

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
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false);
      if (helpRef.current && !helpRef.current.contains(e.target as Node)) setHelpOpen(false);
    }
    function handleKeydown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setProfileOpen(false);
        setHelpOpen(false);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKeydown);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKeydown);
    };
  }, []);

  const closeMenu = useCallback(() => setProfileOpen(false), []);

  const pilotLabel =
    pilot === "on" ? t.pilot.on : pilot === "off" ? t.pilot.off : pilot === "mixed" ? t.pilot.mixed : t.pilot.none;

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-deep-violet/[0.06] bg-white px-4 dark:bg-ink dark:border-deep-violet/[0.06]">
      {/* Search */}
      <button
        onClick={() => setSearchOpen(true)}
        aria-label={t.header.searchLabel}
        title={`${t.header.searchLabel} (⌘K)`}
        className="flex h-8 items-center gap-2 rounded-lg border border-deep-violet/[0.08] bg-deep-violet/[0.03] px-2.5 text-[12px] text-ink/40 outline-none transition hover:border-deep-violet/25 hover:text-ink/60 focus-visible:ring-2 focus-visible:ring-deep-violet/30 sm:w-56 dark:text-fog/40 dark:hover:text-fog/60"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5 shrink-0" aria-hidden>
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span className="hidden flex-1 truncate text-left sm:block">{t.header.search}</span>
        <kbd className="hidden shrink-0 rounded border border-deep-violet/[0.1] bg-white px-1 py-0.5 text-[9px] font-medium text-deep-violet/40 sm:block dark:bg-ink dark:text-deep-violet/50">
          ⌘K
        </kbd>
      </button>

      <div className="flex items-center gap-2">
      <NotificationsBell />
      {/* Help — guided tour */}
      <div className="relative" ref={helpRef}>
        <button
          onClick={() => setHelpOpen(!helpOpen)}
          aria-label="Help"
          aria-expanded={helpOpen}
          title="Help — take the guided tour"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-deep-violet/[0.08] text-[13px] font-bold text-ink/50 outline-none transition hover:border-deep-violet/25 hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:border-fog/[0.1] dark:text-fog/50 dark:hover:text-deep-violet"
        >
          ?
        </button>
        {helpOpen && (
          <div className="absolute right-0 top-full z-50 mt-1 w-52 overflow-hidden rounded-lg border border-deep-violet/[0.08] bg-white shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
            <button
              onClick={() => {
                setHelpOpen(false);
                startTour();
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-[12.5px] text-ink/70 outline-none transition hover:bg-deep-violet/[0.04] hover:text-ink dark:text-fog/70 dark:hover:bg-deep-violet/[0.08] dark:hover:text-fog"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-3.5 w-3.5 text-deep-violet" aria-hidden>
                <circle cx="10" cy="10" r="8" />
                <path d="M10 14.5v.01M7.5 7.3A2.5 2.5 0 0112.5 8c0 1.7-2.5 2-2.5 3.5" strokeLinecap="round" />
              </svg>
              Start tour
            </button>
          </div>
        )}
      </div>

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
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={`h-3 w-3 text-ink/40 transition-transform dark:text-fog/40 ${profileOpen ? "rotate-180" : ""}`} aria-hidden>
            <path d="M4 6l4 4 4-4" />
          </svg>
        </button>
        {profileOpen && (
          <div className="absolute right-0 top-full z-50 mt-1 max-h-[80vh] w-60 overflow-y-auto rounded-lg border border-deep-violet/[0.08] bg-white shadow-lg dark:border-deep-violet/[0.12] dark:bg-ink">
            <div className="border-b border-deep-violet/[0.06] px-3 py-2.5">
              <p className="truncate text-[13px] font-medium text-ink dark:text-fog">{displayName}</p>
              <p className="truncate text-[11px] text-ink/40 dark:text-fog/40">{user?.email ?? ""}</p>
            </div>

            {/* Auto Pilot */}
            <div className="py-1">
              <button
                onClick={() => {
                  setProfileOpen(false);
                  setPilotError(null);
                  setPilotOpen(true);
                }}
                title={`Auto Pilot — ${t.pilot.title}`}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] transition hover:bg-deep-violet/[0.04]"
              >
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    pilot === "on" ? "bg-emerald-500" : pilot === "none" ? "bg-ink/20 dark:bg-fog/20" : "bg-amber-500"
                  }`}
                />
                <span className="flex-1 text-ink/60 dark:text-fog/60">{t.pilot.label}</span>
                <span
                  className={`rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
                    pilot === "on"
                      ? "bg-emerald/10 text-emerald-600"
                      : pilot === "none"
                        ? "bg-ink/[0.05] text-ink/35 dark:text-fog/35"
                        : "bg-amber/10 text-amber-600"
                  }`}
                >
                  {pilotLabel}
                </span>
              </button>
            </div>

            {/* Create */}
            <div className="border-t border-deep-violet/[0.06] py-1">
              <p className="px-3 pb-0.5 pt-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink/35 dark:text-fog/35">
                {t.header.createNew}
              </p>
              <MenuLink label={t.header.newDatabank} href="/dashboard/databank/new" onNavigate={closeMenu} />
              <MenuLink label={t.header.newChannel} href="/dashboard/channels" onNavigate={closeMenu} />
            </div>

            {/* Appearance + language */}
            <div className="border-t border-deep-violet/[0.06] py-1">
              <button
                onClick={toggle}
                aria-label={theme === "light" ? t.header.switchToDark : t.header.switchToLight}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-ink/60 transition hover:bg-deep-violet/[0.04] hover:text-ink dark:text-fog/60 dark:hover:text-fog"
              >
                {theme === "light" ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
                    <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
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
                {theme === "light" ? t.header.switchToDark : t.header.switchToLight}
              </button>
              {LOCALES.filter((l) => l.code === "en").map((l) => (
                <button
                  key={l.code}
                  onClick={() => setLocale(l.code)}
                  aria-current={locale === l.code ? "true" : undefined}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] transition hover:bg-deep-violet/[0.04] ${
                    locale === l.code ? "font-medium text-deep-violet" : "text-ink/60 dark:text-fog/60"
                  }`}
                >
                  <span className="text-[14px]" aria-hidden>{l.flag}</span>
                  {l.label}
                  {locale === l.code && (
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="ml-auto h-3 w-3" aria-hidden>
                      <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </button>
              ))}
              {LOCALES.filter((l) => l.code !== "en").map((l) => (
                <div
                  key={l.code}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-[12px] text-ink/35 dark:text-fog/35"
                  title="Coming soon"
                >
                  <span className="text-[14px] opacity-50" aria-hidden>{l.flag}</span>
                  <span className="flex-1">{l.label}</span>
                  <span className="rounded-full bg-ink/[0.06] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">
                    Soon
                  </span>
                </div>
              ))}
            </div>

            {/* Account */}
            <div className="border-t border-deep-violet/[0.06] py-1">
              <MenuLink label={t.account.myProfile} href="/dashboard/profile" onNavigate={closeMenu} />
              <MenuLink label={t.header.settings} href="/dashboard/settings" onNavigate={closeMenu} />
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
      </div>

      {searchOpen && <SearchPalette onClose={() => setSearchOpen(false)} />}
    </header>
  );
}

function MenuLink({ label, href, onNavigate }: { label: string; href: string; onNavigate?: () => void }) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-[12px] text-ink/60 transition hover:bg-deep-violet/[0.04] hover:text-ink focus-visible:bg-deep-violet/[0.04] focus-visible:outline-none dark:text-fog/60 dark:hover:text-fog"
    >
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3 text-ink/30 dark:text-fog/30" aria-hidden>
        <path d="M8 3v10M3 8h10" strokeLinecap="round" />
      </svg>
      {label}
    </Link>
  );
}
