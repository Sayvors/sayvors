"use client";

import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "@/components/ThemeProvider";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { LOCALES } from "@/lib/i18n/locales";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api-rag";
import AutoPilotDialog from "@/components/dashboard/AutoPilotDialog";
import NotificationsBell from "@/components/dashboard/NotificationsBell";
import SearchPalette from "@/components/dashboard/SearchPalette";
import { useTour } from "@/components/tour/TourProvider";
import { toggleChat, useChatOpen } from "@/lib/chat-store";
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
  const chatOpen = useChatOpen();
  const profileRef = useRef<HTMLDivElement>(null);
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
  // Same gate as the sidebar: owners and roles carrying team.view/manage.
  const [teamPermitted, setTeamPermitted] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const ctx = await apiFetch("/api/v1/team/context");
        setTeamPermitted(
          !!(ctx.is_owner || (ctx.permissions || []).some((p: string) => ["team.manage", "team.view"].includes(p))),
        );
      } catch {
        /* not permitted / not signed in — button stays hidden */
      }
    })();
  }, []);

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
    }
    function handleKeydown(e: KeyboardEvent) {
      if (e.key === "Escape") setProfileOpen(false);
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

  /* The sidebar becomes a drawer on phones, so the crumb is the only
     persistent "where am I" cue. Labels come from the nav dictionary instead
     of a second hand-written list, so they stay translated. */
  const navLabels = t.nav as Record<string, string>;
  const crumbs: [string, string][] = [
    ["/dashboard/notifications", t.header.notifications],
    ["/dashboard/posts-media", navLabels.postsMedia],
    ["/dashboard/analytics", navLabels.analytics],
    ["/dashboard/locations", navLabels.locations],
    ["/dashboard/locations?tab=services", navLabels.services],
    ["/dashboard/customers", navLabels.customers],
    ["/dashboard/reviews", navLabels.reviews],
    ["/dashboard/databank", navLabels.databank],
    ["/dashboard/outbox", navLabels.outbox],
    ["/dashboard/insights", navLabels.insights],
    ["/dashboard/growth", navLabels.growth],
    ["/dashboard/benchmark", navLabels.benchmark],
    ["/dashboard/issues", navLabels.issues],
    ["/dashboard/verification", navLabels.verification],
    ["/dashboard/usage", navLabels.usage],
    ["/dashboard/billing", navLabels.billing],
    ["/dashboard/automations", navLabels.automations],
    ["/dashboard/settings", navLabels.settings],
    ["/dashboard/profile", navLabels.profile],
    ["/dashboard/team", t.header.team],
    ["/dashboard/channels", navLabels.channels],
    ["/dashboard/inbox", navLabels.inbox],
    ["/dashboard/connect", navLabels.connect],
    ["/dashboard", navLabels.dashboard],
  ];
  const currentCrumb =
    crumbs.find(([href]) => pathname === href || pathname.startsWith(`${href}/`))?.[1] ??
    navLabels.dashboard;
  const atRoot = currentCrumb === navLabels.dashboard;

  return (
    <header className="mx-2 mt-2 flex h-14 shrink-0 items-center gap-2 rounded-[20px] border border-ink/[0.06] bg-white px-3 shadow-[0_18px_44px_-34px_rgba(26,18,48,0.45)] sm:px-5 dark:border-white/[0.08] dark:bg-[#1d1636] dark:shadow-none">
      {/* Mobile hamburger — fixed to the header so it stays visible on scroll. */}
      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent("open-nav-drawer"))}
        aria-label="Open menu"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-ink/[0.08] bg-white text-ink shadow-sm transition hover:bg-fog focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:border-fog/[0.08] dark:bg-ink dark:text-fog md:hidden"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>
      {/* Where am I. */}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 ps-11 md:ps-0">
        {!atRoot && (
          <>
            <Link
              href="/dashboard"
              className="hidden shrink-0 rounded-[2px] text-[12px] text-ink/45 outline-none transition hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/40 sm:inline dark:text-fog/45 dark:hover:text-deep-violet"
            >
              {navLabels.dashboard}
            </Link>
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="hidden h-3 w-3 shrink-0 text-ink/25 sm:block rtl:-scale-x-100 dark:text-fog/25"
              aria-hidden
            >
              <path d="M6 3l5 5-5 5" />
            </svg>
          </>
        )}
        <span
          aria-current="page"
          className="truncate text-[13px] font-medium text-ink dark:text-fog"
        >
          {currentCrumb}
        </span>
      </nav>

      {/* Search — desktop only; the phone row is navigation-only and the
          palette shortcut doesn't exist there. */}
      <button
        onClick={() => setSearchOpen(true)}
        aria-label={t.header.searchLabel}
        title={`${t.header.searchLabel} (⌘K)`}
        className="ms-2 hidden h-9 w-52 shrink-0 items-center gap-2 rounded-[2px] bg-deep-violet/[0.04] px-3 text-[13px] text-ink/40 outline-none transition hover:bg-deep-violet/[0.07] hover:text-ink/60 focus-visible:ring-2 focus-visible:ring-deep-violet/40 md:flex lg:ms-4 lg:w-64 dark:bg-fog/[0.05] dark:text-fog/40 dark:hover:bg-fog/[0.08] dark:hover:text-fog/60"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          className="h-4 w-4 shrink-0"
          aria-hidden
        >
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-4-4" />
        </svg>
        <span className="flex-1 truncate text-start">{t.header.search}</span>
        <kbd className="shrink-0 rounded-[2px] border border-deep-violet/[0.08] bg-white px-1.5 py-0.5 text-[9.5px] font-medium tabular-nums text-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog/40">
          ⌘K
        </kbd>
      </button>

      <div className="ms-auto flex shrink-0 items-center gap-1 sm:gap-1.5">
        <NotificationsBell />

        {/* Ask Sayvors — secondary by design; the only solid button in the
            bar is Connect. */}
        <button
          onClick={toggleChat}
          aria-expanded={chatOpen}
          aria-label={t.header.ask}
          title={t.header.ask}
          className={`flex h-10 items-center gap-1.5 rounded-[2px] px-2.5 text-[13px] outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:translate-y-px md:h-9 ${
            chatOpen
              ? "bg-deep-violet/[0.09] font-semibold text-deep-violet dark:bg-fog/[0.08] dark:text-violet-soft"
              : "font-medium text-ink/60 hover:bg-deep-violet/[0.05] hover:text-ink dark:text-fog/60 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
          }`}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-[18px] w-[18px]"
            aria-hidden
          >
            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" />
            <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" />
          </svg>
          <span className="hidden lg:inline">{t.header.ask}</span>
        </button>

        <Link
          href="/dashboard/channels"
          aria-label={t.header.connect}
          title={t.header.connect}
          className="hidden h-9 shrink-0 items-center gap-1.5 rounded-[2px] bg-deep-violet px-3.5 text-[13px] font-semibold text-white shadow-sm shadow-deep-violet/20 transition hover:bg-deep-violet/90 active:translate-y-px md:flex"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-3.5 w-3.5" aria-hidden>
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
          <span>{t.header.connect}</span>
        </Link>

        <span aria-hidden className="mx-1 hidden h-5 w-px bg-deep-violet/[0.08] sm:block dark:bg-fog/[0.1]" />

        <div className="relative shrink-0" ref={profileRef}>
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            aria-label={t.account.menu}
            aria-expanded={profileOpen}
            title={t.account.menu}
            className="flex h-10 items-center gap-2 rounded-[2px] ps-1 pe-1.5 outline-none transition hover:bg-deep-violet/[0.05] focus-visible:ring-2 focus-visible:ring-deep-violet/40 md:h-9 dark:hover:bg-fog/[0.06]"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-[2px] bg-deep-violet text-[10px] font-semibold tracking-wide text-white">
              {initials}
            </span>
            <span className="hidden max-w-[124px] truncate text-[12.5px] font-medium text-ink/70 xl:block dark:text-fog/70">
              {displayName}
            </span>
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`h-3 w-3 text-ink/35 transition-transform dark:text-fog/35 ${profileOpen ? "rotate-180" : ""}`}
              aria-hidden
            >
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>

          {profileOpen && (
            <div className="absolute end-0 top-full z-50 mt-2 max-h-[80vh] w-[282px] overflow-y-auto rounded-[2px] border border-deep-violet/[0.1] bg-white shadow-xl dark:border-fog/[0.12] dark:bg-[#1d1636]">
              {/* Identity opens the profile page; a separate "My profile" row
                  would repeat the same destination. */}
              <Link
                href="/dashboard/profile"
                onClick={closeMenu}
                className="flex items-center gap-2.5 border-b border-deep-violet/[0.06] px-3 py-3 outline-none transition hover:bg-deep-violet/[0.04] focus-visible:bg-deep-violet/[0.04] dark:border-fog/[0.07] dark:hover:bg-fog/[0.05]"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[2px] bg-deep-violet text-[11px] font-semibold text-white">
                  {initials}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink dark:text-fog">{displayName}</span>
                  <span className="block truncate text-[11px] text-ink/45 dark:text-fog/45">{user?.email ?? ""}</span>
                </span>
                <svg
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-3.5 w-3.5 shrink-0 text-ink/25 rtl:-scale-x-100 dark:text-fog/25"
                  aria-hidden
                >
                  <path d="M6 3l5 5-5 5" />
                </svg>
              </Link>

              {/* Auto Pilot */}
              <div className="border-b border-deep-violet/[0.06] py-1 dark:border-fog/[0.07]">
                <button
                  onClick={() => {
                    setProfileOpen(false);
                    setPilotError(null);
                    setPilotOpen(true);
                  }}
                  title={`Auto Pilot — ${t.pilot.title}`}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-start text-[13px] outline-none transition hover:bg-deep-violet/[0.04] focus-visible:bg-deep-violet/[0.04] dark:hover:bg-fog/[0.05]"
                >
                  <span
                    aria-hidden
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      pilot === "on" ? "bg-emerald-500" : pilot === "none" ? "bg-ink/20 dark:bg-fog/20" : "bg-amber-500"
                    }`}
                  />
                  <span className="flex-1 text-ink/65 dark:text-fog/65">{t.pilot.label}</span>
                  <span
                    className={`rounded-[2px] px-1.5 py-0.5 text-[9.5px] font-semibold ${
                      pilot === "on"
                        ? "bg-emerald/10 text-emerald-600"
                        : pilot === "none"
                          ? "bg-ink/[0.05] text-ink/35 dark:bg-fog/[0.06] dark:text-fog/35"
                          : "bg-amber/10 text-amber-600"
                    }`}
                  >
                    {pilotLabel}
                  </span>
                </button>
              </div>

              {/* Workspace */}
              <div className="border-b border-deep-violet/[0.06] py-1 dark:border-fog/[0.07]">
                <p className="px-3 pb-1 pt-1.5 text-[10.5px] font-semibold text-ink/35 dark:text-fog/35">
                  {t.account.workspace}
                </p>
                {teamPermitted && (
                  <MenuItem
                    href="/dashboard/team"
                    label={t.header.team}
                    onNavigate={closeMenu}
                    icon={<TeamIcon />}
                  />
                )}
                <MenuItem
                  href="/dashboard/settings"
                  label={t.account.settings}
                  onNavigate={closeMenu}
                  icon={<GearIcon />}
                />
              </div>

              {/* Preferences */}
              <div className="border-b border-deep-violet/[0.06] py-1 dark:border-fog/[0.07]">
                <p className="px-3 pb-1 pt-1.5 text-[10.5px] font-semibold text-ink/35 dark:text-fog/35">
                  {t.account.preferences}
                </p>
                <button
                  onClick={toggle}
                  aria-label={theme === "light" ? t.header.switchToDark : t.header.switchToLight}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-start text-[13px] text-ink/65 outline-none transition hover:bg-deep-violet/[0.04] focus-visible:bg-deep-violet/[0.04] dark:text-fog/65 dark:hover:bg-fog/[0.05]"
                >
                  <span className="text-ink/35 dark:text-fog/35">
                    {theme === "light" ? <MoonIcon /> : <SunIcon />}
                  </span>
                  <span className="flex-1 truncate">
                    {theme === "light" ? t.header.switchToDark : t.header.switchToLight}
                  </span>
                </button>

                <div className="px-3 pb-1.5 pt-1">
                  <p className="mb-1 text-[10.5px] font-medium text-ink/35 dark:text-fog/35">
                    {t.account.language}
                  </p>
                  <div className="grid grid-cols-2 gap-0.5 rounded-[2px] bg-deep-violet/[0.05] p-0.5 dark:bg-fog/[0.06]">
                    {LOCALES.filter((l) => l.code === "en" || l.code === "ar").map((l) => {
                      const active = locale === l.code;
                      return (
                        <button
                          key={l.code}
                          onClick={() => setLocale(l.code)}
                          aria-pressed={active}
                          className={`rounded-[2px] px-2 py-1 text-[11.5px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                            active
                              ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-violet-soft"
                              : "text-ink/50 hover:text-ink dark:text-fog/50 dark:hover:text-fog"
                          }`}
                        >
                          {l.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Help — one tour entry, not a "?" button plus a compass
                  button plus a menu row. */}
              <div className="border-b border-deep-violet/[0.06] py-1 dark:border-fog/[0.07]">
                <p className="px-3 pb-1 pt-1.5 text-[10.5px] font-semibold text-ink/35 dark:text-fog/35">
                  {t.account.help}
                </p>
                <button
                  onClick={() => {
                    setProfileOpen(false);
                    startTour();
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-start text-[13px] text-ink/65 outline-none transition hover:bg-deep-violet/[0.04] focus-visible:bg-deep-violet/[0.04] dark:text-fog/65 dark:hover:bg-fog/[0.05]"
                >
                  <span className="text-ink/35 dark:text-fog/35">
                    <CompassIcon />
                  </span>
                  <span className="flex-1 truncate">{t.account.takeTour}</span>
                </button>
              </div>

              <div className="py-1">
                <button
                  onClick={() => {
                    setProfileOpen(false);
                    logout();
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-start text-[13px] text-coral outline-none transition hover:bg-coral/[0.06] focus-visible:bg-coral/[0.06] dark:hover:bg-coral/[0.1]"
                >
                  <SignOutIcon />
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

      {searchOpen && <SearchPalette onClose={() => setSearchOpen(false)} />}
    </header>
  );
}

function MenuItem({
  label,
  href,
  icon,
  onNavigate,
}: {
  label: string;
  href: string;
  icon: ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className="group flex w-full items-center gap-2.5 px-3 py-2 text-[13px] text-ink/65 outline-none transition hover:bg-deep-violet/[0.04] hover:text-ink focus-visible:bg-deep-violet/[0.04] dark:text-fog/65 dark:hover:bg-fog/[0.05] dark:hover:text-fog"
    >
      <span className="text-ink/35 transition group-hover:text-deep-violet dark:text-fog/35 dark:group-hover:text-violet-soft">
        {icon}
      </span>
      <span className="flex-1 truncate">{label}</span>
    </Link>
  );
}

function TeamIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function CompassIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" />
      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function SignOutIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <path d="M9 4H5a2 2 0 00-2 2v12a2 2 0 002 2h4" />
      <path d="M16 8l4 4-4 4M20 12H9" />
    </svg>
  );
}
