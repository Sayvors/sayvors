"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const bottomNav = [
  { label: "Dashboard", icon: <LayoutIcon />, href: "/dashboard" },
  { label: "Analytics", icon: <ChartIcon />, href: "/dashboard/analytics" },
  { label: "Insights", icon: <InsightsIcon />, href: "/dashboard/insights" },
  { label: "Growth", icon: <GrowthIcon />, href: "/dashboard/growth" },
  { label: "Databank", icon: <DatabaseIcon />, href: "/dashboard/databank" },
  { label: "Connect", icon: <LinkIcon />, href: "/dashboard/channels" },
  { label: "Auto-Reply", icon: <AutoReplyIcon />, href: "/dashboard/automations" },
];

function isActive(pathname: string, href: string) {
  if (href === "/dashboard") return pathname === "/dashboard";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

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
      <nav className="flex-1 overflow-y-auto px-2 pt-3" aria-label="Main navigation">
        <div className="space-y-0.5">
          {bottomNav.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                title={collapsed ? item.label : undefined}
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
                {!collapsed && <span className="flex-1">{item.label}</span>}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Collapse */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="flex h-9 items-center justify-center border-t border-white/[0.08] text-white/25 outline-none transition hover:text-white/50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-light/60"
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
    </aside>
  );
}

/* ── Icons ─────────────────────────────────────── */

function LayoutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M18 20V10" />
      <path d="M12 20V4" />
      <path d="M6 20v-6" />
    </svg>
  );
}

function InsightsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <circle cx="11" cy="11" r="8" />
      <path d="M21 21l-4.35-4.35" />
      <path d="M11 8v3l2 2" />
    </svg>
  );
}

function GrowthIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M23 6l-9.5 9.5-5-5L1 18" />
      <path d="M17 6h6v6" />
    </svg>
  );
}

function DatabaseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

function LinkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
    </svg>
  );
}

function AutoReplyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      <path d="M8 10h8M8 14h4" />
    </svg>
  );
}
