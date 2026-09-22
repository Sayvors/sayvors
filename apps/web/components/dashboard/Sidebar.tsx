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
  }, [pathname]);

  return (
    <aside
      className={`relative flex h-screen flex-col border-r border-white/[0.08] transition-all duration-200 ${
        collapsed ? "w-[56px]" : "w-[220px]"
      }`}
      style={{ background: "linear-gradient(180deg, #1e1547 0%, #151030 100%)" }}
    >
      {/* Logo */}
      <div className="flex h-11 items-center gap-2 border-b border-white/[0.08] px-3">
        <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-5 w-auto" />
        {!collapsed && (
          <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={110} height={18} className="h-4 w-auto brightness-0 invert" />
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-3 pb-4" aria-label={t.nav.mainNavigation}>
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi}>
            {group.label && !collapsed && (
              <p className="mb-1 px-2.5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/25">
                {group.label}
              </p>
            )}
            {group.label && collapsed && gi > 0 && (
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
                    title={collapsed ? label : undefined}
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
                    {!collapsed && <span className="flex-1 truncate">{label}</span>}
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
              collapsed ? "left-12 w-48" : "left-2 right-2"
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
        <div className={`flex items-center gap-1 p-2 ${collapsed ? "flex-col" : ""}`}>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label={t.account.menu}
            aria-expanded={menuOpen}
            title={collapsed ? displayName : undefined}
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
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-white/25 outline-none transition hover:bg-white/[0.08] hover:text-white/50 focus-visible:ring-2 focus-visible:ring-violet-light/60"
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
