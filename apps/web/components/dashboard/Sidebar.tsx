"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n/I18nProvider";

interface NavItem {
  key: string;
  icon: React.ReactNode;
  href: string;
  /** Legacy paths that should also highlight this item. */
  aliases?: string[];
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { key: "dashboard", icon: <LayoutIcon />, href: "/dashboard" },
      {
        key: "analytics",
        icon: <ChartIcon />,
        href: "/dashboard/analytics",
        aliases: ["/dashboard/insights", "/dashboard/growth", "/dashboard/benchmark"],
      },
    ],
  },
  {
    label: "Google Business",
    items: [
      { key: "locations", icon: <LocationIcon />, href: "/dashboard/locations" },
      { key: "services", icon: <WrenchIcon />, href: "/dashboard/services" },
      { key: "media", icon: <PhotoIcon />, href: "/dashboard/media" },
      { key: "posts", icon: <MegaphoneIcon />, href: "/dashboard/posts" },
      { key: "reviews", icon: <StarIcon />, href: "/dashboard/reviews" },
      { key: "issues", icon: <ChecklistIcon />, href: "/dashboard/issues" },
      { key: "verification", icon: <ShieldCheckIcon />, href: "/dashboard/verification" },
    ],
  },
  {
    label: "Tools",
    items: [
      { key: "databank", icon: <DatabaseIcon />, href: "/dashboard/databank" },
      { key: "connect", icon: <LinkIcon />, href: "/dashboard/channels" },
      { key: "outbox", icon: <OutboxIcon />, href: "/dashboard/outbox" },
      { key: "usage", icon: <ChartIcon />, href: "/dashboard/usage" },
      { key: "billing", icon: <CardIcon />, href: "/dashboard/billing" },
    ],
  },
];

function isActive(pathname: string, item: NavItem) {
  const { href } = item;
  if (href === "/dashboard") return pathname === "/dashboard";
  if (pathname === href || pathname.startsWith(`${href}/`)) return true;
  return (item.aliases ?? []).some(
    (alias) => pathname === alias || pathname.startsWith(`${alias}/`)
  );
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Small screens get the nav as an overlay drawer, not a column. A 220px
  // inline sidebar is 56% of a 390px phone, permanently, before any content.
  const [isMobile, setIsMobile] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const apply = () => {
      setIsMobile(mq.matches);
      // Leaving the mobile breakpoint should not strand a half-open drawer,
      // and entering it should not leave the inline toggle in a stale state.
      if (!mq.matches) setDrawerOpen(false);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  // While the drawer is open it covers the page, so the page behind it must
  // not scroll away underneath.
  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { t } = useI18n();
  const menuRef = useRef<HTMLDivElement>(null);

  const displayName =
    user && (user.first_name || user.last_name)
      ? `${user.first_name} ${user.last_name}`.trim()
      : t.account.fallbackName;

  const initials = user
    ? `${user.first_name?.[0] ?? ""}${user.last_name?.[0] ?? ""}`.toUpperCase() || "U"
    : "U";

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    // Following a link inside the drawer should reveal the page, not leave the
    // nav covering it.
    setDrawerOpen(false);
  }, [pathname]);

  // "Rail" means the icon-only 56px strip. Only the inline desktop sidebar can
  // be a rail — the mobile drawer is always full width, so gating label
  // visibility on `collapsed` alone would render it icon-only for no reason.
  const rail = collapsed && !isMobile;

  return (
    <>
      {/* Hamburger — mobile only, fixed so it does not shift page content. */}
      <button
        onClick={() => setDrawerOpen(true)}
        aria-label={t.nav.openMenu}
        aria-expanded={drawerOpen}
        aria-controls="dashboard-sidebar"
        className={`fixed left-3 top-3 z-40 flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-[#1e1547] text-white shadow-lg transition hover:bg-[#251b55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-light md:hidden ${
          drawerOpen ? "pointer-events-none opacity-0" : "opacity-100"
        }`}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>

      {/* Scrim — tap anywhere to dismiss, as a drawer is expected to do. */}
      {drawerOpen && (
        <button
          onClick={() => setDrawerOpen(false)}
          aria-label={t.nav.closeMenu}
          tabIndex={-1}
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
        />
      )}

      <aside
        id="dashboard-sidebar"
        aria-hidden={isMobile && !drawerOpen ? true : undefined}
        className={`flex h-screen flex-col border-r border-white/[0.08] transition-all duration-200 ${
          isMobile
            ? `fixed inset-y-0 left-0 z-50 w-[248px] shadow-2xl ${
                drawerOpen ? "translate-x-0" : "-translate-x-full"
              }`
            : collapsed
              ? "w-[56px]"
              : "w-[220px]"
        }`}
        style={{ background: "linear-gradient(180deg, #1e1547 0%, #151030 100%)" }}
      >
      {/* Logo */}
      <div className="flex h-11 items-center gap-2 border-b border-white/[0.08] px-3">
        <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-5 w-auto" />
        {/* The drawer is always wide, so the wordmark shows even when the
            inline rail is collapsed. */}
        {(!collapsed || isMobile) && (
          <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={110} height={18} className="h-4 w-auto brightness-0 invert" />
        )}
        <button
          onClick={() => setDrawerOpen(false)}
          aria-label={t.nav.closeMenu}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-white/40 outline-none transition hover:bg-white/[0.08] hover:text-white/70 focus-visible:ring-2 focus-visible:ring-violet-light/60 md:hidden"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-3 pb-4" aria-label={t.nav.mainNavigation}>
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi}>
            {group.label && !rail && (
              <p className="mb-1 px-2.5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/25">
                {group.label}
              </p>
            )}
            {group.label && rail && gi > 0 && (
              <div className="mx-2 my-2 border-t border-white/[0.06]" />
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const label = (t.nav as Record<string, string>)[item.key] ?? item.key;
                const active = isActive(pathname, item);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    data-tour={`nav-${item.key}`}
                    aria-current={active ? "page" : undefined}
                    title={rail ? label : undefined}
                    className={`group relative flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-violet-light/60 ${
                      active
                        ? "bg-white/[0.1] text-white"
                        : "text-white/50 hover:bg-white/[0.08] hover:text-white"
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-violet-light to-magenta transition-opacity ${
                        active ? "opacity-100" : "opacity-0"
                      }`}
                    />
                    <span
                      className={`h-4 w-4 shrink-0 transition-colors ${
                        active ? "text-white" : "text-white/30 group-hover:text-white/60"
                      }`}
                    >
                      {item.icon}
                    </span>
                    {!rail && <span className="flex-1 truncate">{label}</span>}
                  </Link>
                );
              })}
            </div>
            {gi < NAV_GROUPS.length - 1 && (
              <div className="mx-2 my-2 border-t border-white/[0.06]" />
            )}
          </div>
        ))}
      </nav>

      {/* Account + collapse */}
      <div ref={menuRef} className="relative border-t border-white/[0.08]">
        {menuOpen && (
          <div
            className={`absolute bottom-full z-50 mb-2 overflow-hidden rounded-lg border border-white/10 bg-[#221b4d] shadow-xl ${
              rail ? "left-12 w-48" : "left-2 right-2"
            }`}
          >
            <div className="border-b border-white/[0.08] px-3 py-2.5">
              <p className="truncate text-[13px] font-medium text-white">
                {displayName}
              </p>
              <p className="truncate text-[11px] text-white/40">{user?.email ?? ""}</p>
            </div>
            <div className="py-1">
              <SidebarMenuLink href="/dashboard/profile" label={t.account.myProfile} />
              <SidebarMenuLink href="/dashboard/settings" label={t.account.settings} />
            </div>
            <div className="border-t border-white/[0.08] py-1">
              <button
                onClick={() => logout()}
                className="flex w-full items-center px-3 py-2 text-[12px] text-coral transition hover:bg-white/[0.06]"
              >
                {t.account.signOut}
              </button>
            </div>
          </div>
        )}
        <div className={`flex items-center gap-1 p-2 ${collapsed && !isMobile ? "flex-col" : ""}`}>
          <button
            onClick={() => (isMobile ? setDrawerOpen(false) : setMenuOpen(!menuOpen))}
            aria-label={isMobile ? t.nav.closeMenu : t.account.menu}
            aria-expanded={isMobile ? drawerOpen : menuOpen}
            title={!isMobile && collapsed ? displayName : undefined}
            className={`flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1.5 outline-none transition hover:bg-white/[0.08] focus-visible:ring-2 focus-visible:ring-violet-light/60 ${
              collapsed ? "justify-center" : ""
            }`}
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-light to-magenta text-[10px] font-semibold text-white">
              {initials}
            </span>
            {!collapsed && (
              <span className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[12px] font-medium text-white">
                  {displayName}
                </span>
                <span className="block truncate text-[10px] text-white/40">
                  {user?.email ?? ""}
                </span>
              </span>
            )}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? t.nav.expand : t.nav.collapse}
            title={collapsed ? t.nav.expand : t.nav.collapse}
            /* The drawer is already the compact form on a phone — a collapse
               toggle there would collapse what is off-screen twice over. */
            className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md text-white/25 outline-none transition hover:bg-white/[0.08] hover:text-white/50 focus-visible:ring-2 focus-visible:ring-violet-light/60 md:flex"
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className={`h-3.5 w-3.5 transition-transform ${collapsed ? "rotate-180" : ""}`}
            >
              <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </aside>
    </>
  );
}

function SidebarMenuLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex w-full items-center px-3 py-2 text-[12px] text-white/60 transition hover:bg-white/[0.06] hover:text-white"
    >
      {label}
    </Link>
  );
}

/* ── Icons ─────────────────────────────────────── */

function LayoutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function LocationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function WrenchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
    </svg>
  );
}

function PhotoIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="M21 15l-5-5L5 21" />
    </svg>
  );
}

function MegaphoneIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11l18-5v12L3 13v-2z" />
      <path d="M11.6 16.8a3 3 0 11-5.8-1.6" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}

function ChecklistIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M3.5 6l1.2 1.2L7 4.9" />
      <path d="M3.5 12l1.2 1.2L7 10.9" />
      <path d="M3.5 18l1.2 1.2L7 16.9" />
    </svg>
  );
}

function ShieldCheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 20V10" /><path d="M12 20V4" /><path d="M6 20v-6" />
    </svg>
  );
}

function DatabaseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

function LinkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
    </svg>
  );
}

function OutboxIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6" />
      <path d="M12 3v12" />
      <path d="M8 7l4-4 4 4" />
    </svg>
  );
}

function CardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </svg>
  );
}
