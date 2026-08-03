"use client";

import Link from "next/link";
import { useState } from "react";

const navItems = [
  { label: "Dashboard", icon: LayoutIcon, href: "/dashboard" },
  { label: "Conversations", icon: ChatIcon, href: "/dashboard/conversations", badge: 3 },
  { label: "Contacts", icon: UsersIcon, href: "/dashboard/contacts" },
  { label: "Channels", icon: GlobeIcon, href: "/dashboard/channels" },
  { label: "Campaigns", icon: MegaphoneIcon, href: "/dashboard/campaigns" },
];

const aiItems = [
  { label: "TTS", icon: MicIcon, href: "/dashboard/tts" },
  { label: "STT", icon: HeadphonesIcon, href: "/dashboard/stt" },
  { label: "LLM", icon: SparklesIcon, href: "/dashboard/llm" },
];

const bottomItems = [
  { label: "Settings", icon: SettingsIcon, href: "/dashboard/settings" },
];

function NavItem({ item, collapsed }: { item: typeof navItems[0]; collapsed: boolean }) {
  return (
    <Link
      href={item.href}
      className="group flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-ink/50 transition hover:bg-ink/[0.04] hover:text-ink"
    >
      <item.icon className="h-4 w-4 shrink-0 text-ink/30 group-hover:text-deep-violet" />
      {!collapsed && (
        <>
          <span className="flex-1">{item.label}</span>
          {"badge" in item && item.badge && (
            <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-coral px-1 text-[10px] font-semibold text-white">
              {item.badge}
            </span>
          )}
        </>
      )}
    </Link>
  );
}

function SectionLabel({ children, collapsed }: { children: React.ReactNode; collapsed: boolean }) {
  if (collapsed) return <div className="mx-2.5 my-1.5 h-px bg-ink/[0.06]" />;
  return (
    <p className="mx-2.5 mb-0.5 mt-3 text-[10px] font-semibold uppercase tracking-wider text-ink/25">
      {children}
    </p>
  );
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`relative flex h-screen flex-col border-r border-ink/[0.06] bg-white transition-all duration-200 ${
        collapsed ? "w-[56px]" : "w-[200px]"
      }`}
    >
      {/* Logo */}
      <div className="flex h-11 items-center gap-2 border-b border-ink/[0.06] px-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-deep-violet to-magenta">
          <span className="text-[11px] font-bold text-white">S</span>
        </div>
        {!collapsed && <span className="text-[14px] font-semibold text-ink">Sayvors</span>}
      </div>

      {/* Quick action */}
      <div className="px-2 pt-3">
        <button
          className={`flex h-8 items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-deep-violet to-magenta text-[12px] font-semibold text-white shadow-sm shadow-deep-violet/20 transition hover:shadow-md active:scale-[0.98] ${
            collapsed ? "w-8" : "w-full px-3"
          }`}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
          {!collapsed && "New"}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-2">
        <div className="space-y-0.5">
          {navItems.map((item) => (
            <NavItem key={item.href} item={item} collapsed={collapsed} />
          ))}
        </div>

        <SectionLabel collapsed={collapsed}>AI</SectionLabel>
        <div className="space-y-0.5">
          {aiItems.map((item) => (
            <NavItem key={item.href} item={item} collapsed={collapsed} />
          ))}
        </div>

        <SectionLabel collapsed={collapsed}>More</SectionLabel>
        <div className="space-y-0.5">
          {bottomItems.map((item) => (
            <NavItem key={item.href} item={item} collapsed={collapsed} />
          ))}
        </div>
      </nav>

      {/* Collapse */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex h-9 items-center justify-center border-t border-ink/[0.06] text-ink/25 transition hover:text-ink/50"
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

/* ── Icons (small, consistent) ────────────────── */

function LayoutIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function ChatIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function UsersIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function GlobeIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <circle cx="12" cy="12" r="10" />
      <line x1="2" y1="12" x2="22" y2="12" />
      <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
    </svg>
  );
}

function MegaphoneIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M3 11l18-5v12L3 13v-2z" />
      <path d="M11.6 16.8a3 3 0 11-5.8-1.6" />
    </svg>
  );
}

function MicIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8" />
    </svg>
  );
}

function HeadphonesIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M3 18v-6a9 9 0 0118 0v6" />
      <path d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3z" />
    </svg>
  );
}

function SparklesIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12 2l2.09 6.26L20.18 10l-6.09 1.74L12 18l-2.09-6.26L3.82 10l6.09-1.74z" />
    </svg>
  );
}

function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  );
}
