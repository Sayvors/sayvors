"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AdminSearch } from "@/components/AdminSearch";
import { SearchIcon } from "@/components/SearchIcon";
import { adminLogout, checkAdminSession } from "@/lib/admin-api";
import AdminBell from "@/components/AdminBell";
import { FLAT_NAV, SECTIONS, type NavItem } from "@/lib/admin-nav";
import { useTheme } from "../theme";

const SIDEBAR_KEY = "sayvors-admin-sidebar";

function pageContext(pathname: string): { section: string; title: string } {
  const match = FLAT_NAV.filter(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  ).sort((a, b) => b.href.length - a.href.length)[0];
  if (!match) return { section: "Console", title: "Admin" };
  if (pathname === match.href) {
    return { section: match.section, title: match.label };
  }
  return {
    section: match.section,
    title: `${match.label.replace(/s$/, "")} detail`,
  };
}

function ThemeToggle({ toggle }: { toggle: () => void }) {
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle color theme"
      title="Toggle color theme"
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] text-ink/55 transition-colors duration-150 hover:border-[var(--ui-line-strong)] hover:text-ink"
    >
      {/* Both icons are rendered; the pre-hydration .dark class picks one, so
       * the icon is right on first paint without a theme-state mismatch. */}
      <svg aria-hidden viewBox="0 0 24 24" fill="none" className="h-4 w-4 dark:hidden">
        <path
          d="M20.2 14.1A8.4 8.4 0 0 1 9.9 3.8 8.4 8.4 0 1 0 20.2 14.1z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
      <svg aria-hidden viewBox="0 0 24 24" fill="none" className="hidden h-4 w-4 dark:block">
        <circle cx="12" cy="12" r="4.2" stroke="currentColor" strokeWidth="1.6" />
        <path
          d="M12 2.8v2.2M12 19v2.2M2.8 12h2.2M19 12h2.2M5.5 5.5l1.6 1.6M16.9 16.9l1.6 1.6M18.5 5.5l-1.6 1.6M7.1 16.9l-1.6 1.6"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}

function NavIcon({ name, active }: { name: NavItem["icon"]; active: boolean }) {
  const cls = `h-[16px] w-[16px] shrink-0 ${active ? "text-[var(--ui-ink)]" : "text-ink/45 group-hover:text-ink/75"}`;
  switch (name) {
    case "overview":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
          <rect x="13" y="3.5" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
          <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
          <rect x="13" y="13" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      );
    case "tenants":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <circle cx="9" cy="8.2" r="3.2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M3.2 18.2a5.2 5.2 0 0 1 11.6 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="17.2" cy="9.2" r="2.4" stroke="currentColor" strokeWidth="1.4" />
          <path d="M14.8 15.8a3.8 3.8 0 0 1 5.6 1.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      );
    case "usage":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <path d="M4 18V9" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M9.2 18V13.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M14.4 18V6.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M19.6 18V10.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
      );
    case "logs":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="3.5" y="4.2" width="17" height="15.6" rx="2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M7.5 9h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M7.5 12.2h8.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M7.5 15.4h5.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="17.2" cy="9" r="1" fill="currentColor" />
        </svg>
      );
    case "llms":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <path d="M12 3.2l1.6 4 4.2.4-3.1 2.7.9 4.1L12 12.1 8.4 14.4l.9-4.1L6.2 7.6l4.2-.4L12 3.2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M5 14.5l.9 1.9 2 .4-1.5 1.3.4 2-1.8-1.1-1.8 1.1.4-2L2.1 16.8l2-.4.9-1.9z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
      );
    case "voice":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="9" y="3" width="6" height="11.5" rx="3" stroke="currentColor" strokeWidth="1.6" />
          <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" stroke="currentColor" strokeWidth="1.6" />
          <path d="M12 18v3" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      );
    case "embeddings":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <circle cx="6" cy="6.5" r="2.2" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="18" cy="6.5" r="2.2" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="12" cy="17.5" r="2.2" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M7.7 7.8l2.8 7.5M16.3 7.8l-2.8 7.5M8.2 6.5h7.6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      );
    case "billing":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="3.5" y="6" width="17" height="12" rx="2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M3.5 10h17" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="7.5" cy="14" r="1.2" fill="currentColor" />
          <path d="M11 14h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
    case "jobs":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="3.5" y="4" width="17" height="4" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
          <rect x="3.5" y="10" width="17" height="4" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
          <rect x="3.5" y="16" width="17" height="4" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="7" cy="6" r="0.9" fill="currentColor" />
          <circle cx="7" cy="12" r="0.9" fill="currentColor" />
          <circle cx="7" cy="18" r="0.9" fill="currentColor" />
        </svg>
      );
    case "special":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <path
            d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8L12 3.6z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "search":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <circle cx="10.7" cy="10.7" r="6.2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M15.2 15.2L20.5 20.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
      );
    case "backups":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <ellipse cx="12" cy="5.5" rx="7.5" ry="2.8" stroke="currentColor" strokeWidth="1.5" />
          <path d="M4.5 5.5v6c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8v-6" stroke="currentColor" strokeWidth="1.5" />
          <path d="M4.5 11.5v6c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8v-6" stroke="currentColor" strokeWidth="1.5" />
          <path d="M12 9.5v8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          <path d="M9.2 15.2L12 18l2.8-2.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    default:
      return null;
  }
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { toggle } = useTheme();
  const [ready, setReady] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
      /* private mode */
    }
    return false;
  });
  const [navOpen, setNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    checkAdminSession().then((ok) => {
      if (!ok) router.replace("/login");
      else setReady(true);
    });
  }, [router]);

  // Global command-palette shortcut. The palette handles Escape and focus.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The nav is taller than the viewport on shorter screens. Bring the active
  // destination into view so the sidebar always answers "where am I?".
  useEffect(() => {
    if (!ready) return;
    document
      .querySelector<HTMLElement>('nav[aria-label="Primary"] [aria-current="page"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [pathname, collapsed, ready]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  if (!ready) return null;

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  const nav = (
    <nav className="flex-1 px-3 pb-6 pt-3" aria-label="Primary">
      <div className="space-y-5">
        {SECTIONS.map((section) => (
          <div key={section.title}>
            {collapsed ? (
              <div
                aria-hidden
                className="mx-auto mb-2 h-px w-6 bg-[var(--ui-line)]"
              />
            ) : (
              <p className="mb-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">
                {section.title}
              </p>
            )}
            <ul className="space-y-1">
              {section.items.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      title={collapsed ? item.label : undefined}
                      className={`group relative flex scroll-mb-6 scroll-mt-24 items-center gap-3 rounded-[2px] px-2.5 py-2.5 text-[13px] transition-colors duration-150 ${
                        active
                          ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
                          : "text-ink/55 hover:bg-ink/[0.04] hover:text-ink"
                      } ${collapsed ? "justify-center px-0" : ""}`}
                    >
                      {/* The active marker is a rail, not a fill. */}
                      <span
                        aria-hidden
                        className={`absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 bg-[var(--ui-ink)] transition-opacity duration-150 ${
                          active ? "opacity-100" : "opacity-0"
                        }`}
                      />
                      <NavIcon name={item.icon} active={active} />
                      {!collapsed && (
                        <span className="min-w-0 flex-1">
                          <span className={`block text-[13px] font-semibold leading-none ${active ? "text-[var(--ui-ink)]" : "text-ink/80 group-hover:text-ink"}`}>
                            {item.label}
                          </span>
                          <span className={`mt-1 block truncate text-[11px] leading-none ${active ? "text-ink/55" : "text-ink/40 group-hover:text-ink/60"}`}>
                            {item.desc}
                          </span>
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );

  const context = pageContext(pathname);

  const header = (
    <header className="sticky top-0 z-20 hidden items-center justify-between gap-6 border-b border-[var(--ui-line)] bg-[var(--ui-surface-solid)] px-5 py-3 lg:flex">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-ink/40">
            {context.section}
          </span>
          <span aria-hidden className="h-3 w-px bg-[var(--ui-line)]" />
          <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-ink/30">
            Admin console
          </span>
        </div>
        <p className="mt-1 truncate text-[16px] font-semibold tracking-tight text-[var(--ui-ink)]">
          {context.title}
        </p>
      </div>

      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        aria-label="Search admin console"
        aria-keyshortcuts="Control+K Meta+K"
        className="hidden min-w-0 max-w-[340px] flex-1 items-center gap-2 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-left text-[12px] text-ink/35 transition hover:border-[var(--ui-line-strong)] hover:text-ink/60 lg:flex"
      >
        <SearchIcon className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">Search tenants, models, jobs…</span>
        <kbd className="ml-auto shrink-0 rounded-[2px] border border-[var(--ui-line)] px-1.5 py-0.5 text-[9px] font-semibold text-ink/30">
          Ctrl K
        </kbd>
      </button>

      <div className="flex shrink-0 items-center gap-2">
        <AdminBell />
        <ThemeToggle toggle={toggle} />
        <span aria-hidden className="h-6 w-px bg-[var(--ui-line)]" />
        <div className="flex items-center gap-2.5 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5">
          <div className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-deep-violet text-[10px] font-bold text-white">
            AD
            <span
              aria-hidden
              className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-[var(--ui-surface)] bg-emerald-500"
            />
          </div>
          <div className="min-w-0">
            <p className="truncate text-[11.5px] font-semibold leading-none text-[var(--ui-ink)]">
              Administrator
            </p>
            <p className="mt-1 truncate text-[10px] leading-none text-ink/45">
              Admin account
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            adminLogout().finally(() => router.replace("/login"));
          }}
          aria-label="Sign out"
          title="Sign out"
          className="flex h-9 items-center justify-center gap-2 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 text-[11.5px] font-semibold text-ink/60 transition-colors duration-150 hover:border-[var(--ui-ink)] hover:text-ink"
        >
          <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" className="opacity-60">
            <path d="M15.2 18.2L9 12l6.2-6.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M9 12H21" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            <path d="M3 5.2a2 2 0 0 1 2-2h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <path d="M3 18.8a2 2 0 0 0 2 2h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="hidden xl:inline">Sign out</span>
        </button>
      </div>
    </header>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--ui-page)]">
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-[2px] focus:bg-[var(--ui-ink)] focus:px-3 focus:py-2 focus:text-[12px] focus:font-semibold focus:text-[var(--ui-on-ink)]"
      >
        Skip to content
      </a>
      {/* Sidebar: a drawer under lg, a flat rail on desktop. */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex flex-col border-r border-[var(--ui-line)] bg-[var(--ui-surface)] transition-[width,transform] duration-200 ease-out lg:static lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "lg:w-16" : "w-60"}`}
      >
        {/* Everything scrolls in here; the aside itself must not clip, or the
            collapse toggle straddling its right edge gets cut off. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain [scrollbar-width:thin]">
        {/* Brand + console identity */}
        <div className={`sticky top-0 z-10 border-b border-[var(--ui-line)] bg-[var(--ui-surface-solid)] px-4 pb-3 pt-4 ${collapsed ? "lg:px-0" : ""}`}>
          <div className={`flex items-center gap-3 ${collapsed ? "lg:justify-center" : ""}`}>
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[3px] border border-[var(--ui-line)] bg-white">
              <Image
                src="/Sayvors_Icon.png"
                alt="Sayvors"
                width={28}
                height={28}
                className="h-7 w-7 object-contain"
                unoptimized
              />
            </div>
            {!collapsed && (
              <div className="min-w-0">
                <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-ink/40">
                  Control plane
                </p>
                <p className="mt-0.5 text-[15px] font-semibold leading-none tracking-tight text-[var(--ui-ink)]">
                  Sayvors
                </p>
              </div>
            )}
          </div>
          {!collapsed && (
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-[var(--ui-line)] pt-2.5">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink/40">
                Admin console
              </span>
              <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-ink/50">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Secure session
              </span>
            </div>
          )}
        </div>

        {nav}
        </div>

        {/* Collapse toggle: a small circular arrow straddling the sidebar's
            right edge line. Desktop only. */}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="absolute -right-3 top-[24px] z-50 hidden h-6 w-6 items-center justify-center rounded-full border border-[var(--ui-line-strong)] bg-[var(--ui-surface-solid)] text-[var(--ui-ink)] transition-colors duration-150 hover:bg-[var(--ui-sunken)] lg:flex"
        >
          <svg aria-hidden viewBox="0 0 24 24" fill="none" className={`h-3 w-3 transition-transform duration-200 ${collapsed ? "rotate-180" : ""}`}>
            <path d="M14.5 6.5L9 12l5.5 5.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </aside>

      {/* Mobile scrim */}
      {navOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-30 bg-ink/30 lg:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Desktop header (hidden on mobile) */}
        {header}
        {/* Mobile top bar */}
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-[var(--ui-line)] bg-[var(--ui-surface-solid)] px-4 py-3 lg:hidden">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={navOpen}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[2px] border border-[var(--ui-line-strong)] text-ink/60"
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" className="h-4 w-4">
              <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
          <div className="min-w-0 flex-1">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-ink/40">
              {context.section}
            </p>
            <p className="truncate text-[13px] font-semibold tracking-tight text-[var(--ui-ink)]">
              {context.title}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            aria-label="Search admin console"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[2px] border border-[var(--ui-line)] text-ink/55 transition hover:border-[var(--ui-line-strong)] hover:text-ink"
          >
            <SearchIcon className="h-4 w-4" />
          </button>
          <AdminBell />
          <ThemeToggle toggle={toggle} />
        </header>

        <main
          id="admin-main"
          className="min-w-0 flex-1 overflow-y-auto overscroll-contain bg-[var(--ui-page)] p-4 sm:p-6"
        >
          {children}
        </main>
      </div>

      {searchOpen ? (
        <AdminSearch onClose={() => setSearchOpen(false)} />
      ) : null}
    </div>
  );
}
