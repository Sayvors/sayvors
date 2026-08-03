"use client";

import Link from "next/link";
import { useState } from "react";

const navItems = [
  { label: "Inbox", icon: InboxIcon, href: "/dashboard", badge: 12 },
  { label: "Conversations", icon: ChatIcon, href: "/dashboard/conversations", badge: 3 },
  { label: "Contacts", icon: UsersIcon, href: "/dashboard/contacts" },
  { label: "Channels", icon: GlobeIcon, href: "/dashboard/channels" },
];

const aiItems = [
  { label: "TTS Studio", icon: MicIcon, href: "/dashboard/tts" },
  { label: "STT Transcribe", icon: HeadphonesIcon, href: "/dashboard/stt" },
  { label: "LLM Chat", icon: SparklesIcon, href: "/dashboard/llm" },
];

const bottomItems = [
  { label: "Settings", icon: SettingsIcon, href: "/dashboard/settings" },
  { label: "Billing", icon: CreditCardIcon, href: "/dashboard/billing" },
];

function NavItem({ item, collapsed }: { item: typeof navItems[0]; collapsed: boolean }) {
  return (
    <Link
      href={item.href}
      className="group flex items-center gap-3 rounded-lg px-3 py-2.5 text-[14px] font-medium text-ink/60 transition hover:bg-ink/[0.04] hover:text-ink"
    >
      <item.icon className="h-[18px] w-[18px] shrink-0 text-ink/40 group-hover:text-deep-violet" />
      {!collapsed && (
        <>
          <span className="flex-1">{item.label}</span>
          {"badge" in item && item.badge && (
            <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-coral px-1.5 text-[11px] font-semibold text-white">
              {item.badge}
            </span>
          )}
        </>
      )}
    </Link>
  );
}

function SectionLabel({ children, collapsed }: { children: React.ReactNode; collapsed: boolean }) {
  if (collapsed) return <div className="mx-3 my-2 h-px bg-ink/[0.06]" />;
  return (
    <p className="mx-3 mb-1 mt-5 text-[11px] font-semibold uppercase tracking-wider text-ink/30">
      {children}
    </p>
  );
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`relative flex h-screen flex-col border-r border-ink/[0.06] bg-white transition-all duration-200 ${
        collapsed ? "w-[68px]" : "w-[240px]"
      }`}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2.5 border-b border-ink/[0.06] px-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-deep-violet to-magenta">
          <span className="text-[13px] font-bold text-white">S</span>
        </div>
        {!collapsed && <span className="text-[15px] font-semibold text-ink">Sayvors</span>}
      </div>

      {/* Compose button */}
      <div className="px-3 pt-4">
        <button
          className={`flex h-10 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-deep-violet to-magenta text-[13px] font-semibold text-white shadow-md shadow-deep-violet/20 transition hover:shadow-lg hover:shadow-deep-violet/30 active:scale-[0.98] ${
            collapsed ? "w-10" : "w-full px-4"
          }`}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
            <path d="M12 2.5H4a1.5 1.5 0 00-1.5 1.5v8A1.5 1.5 0 004 13.5h8a1.5 1.5 0 001.5-1.5V4A1.5 1.5 0 0012 2.5zM5.5 5.5h5M5.5 8h3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {!collapsed && "New Message"}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-3">
        <div className="space-y-0.5">
          {navItems.map((item) => (
            <NavItem key={item.href} item={item} collapsed={collapsed} />
          ))}
        </div>

        <SectionLabel collapsed={collapsed}>AI Tools</SectionLabel>
        <div className="space-y-0.5">
          {aiItems.map((item) => (
            <NavItem key={item.href} item={item} collapsed={collapsed} />
          ))}
        </div>

        <SectionLabel collapsed={collapsed}>Account</SectionLabel>
        <div className="space-y-0.5">
          {bottomItems.map((item) => (
            <NavItem key={item.href} item={item} collapsed={collapsed} />
          ))}
        </div>
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex h-10 items-center justify-center border-t border-ink/[0.06] text-ink/30 transition hover:text-ink/60"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className={`h-4 w-4 transition-transform ${collapsed ? "rotate-180" : ""}`}
        >
          <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </aside>
  );
}

/* ── Icons ──────────────────────────────────────── */

function InboxIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" />
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
      <path d="M5 3l1 3M18 17l1 3" />
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

function CreditCardIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
    </svg>
  );
}
