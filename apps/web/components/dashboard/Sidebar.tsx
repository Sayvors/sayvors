"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";

interface NavGroup {
  label: string;
  icon: React.ReactNode;
  color: string;
  items: { label: string; href: string }[];
}

const navGroups: NavGroup[] = [
  {
    label: "AI Agents",
    icon: <BotIcon />,
    color: "from-deep-violet to-magenta",
    items: [
      { label: "My Agents", href: "/dashboard/agents" },
      { label: "Create Agent", href: "/dashboard/agents/create" },
    ],
  },
  {
    label: "AI Tools",
    icon: <SparklesIcon />,
    color: "from-magenta to-coral",
    items: [
      { label: "Speech to Text", href: "/dashboard/stt" },
      { label: "Text to Speech", href: "/dashboard/tts" },
      { label: "Chat with Docs", href: "/dashboard/docs" },
    ],
  },
];

const bottomNav = [
  { label: "Dashboard", icon: <LayoutIcon />, href: "/dashboard" },
  { label: "Conversations", icon: <ChatIcon />, href: "/dashboard/conversations", badge: 3 },
  { label: "Contacts", icon: <UsersIcon />, href: "/dashboard/contacts" },
  { label: "Channels", icon: <GlobeIcon />, href: "/dashboard/channels" },
  { label: "Databank", icon: <DatabaseIcon />, href: "/dashboard/databank" },
  { label: "Settings", icon: <SettingsIcon />, href: "/dashboard/settings" },
];

function GroupHeader({
  group,
  expanded,
  onToggle,
  collapsed,
}: {
  group: NavGroup;
  expanded: string | null;
  onToggle: (label: string) => void;
  collapsed: boolean;
}) {
  const isOpen = expanded === group.label;

  if (collapsed) {
    return (
      <div className="relative group/tooltip">
        <button
          className="flex h-8 w-full items-center justify-center rounded-lg text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/40 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60"
          title={group.label}
        >
          <span className={`flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br ${group.color} text-white`}>
            {group.icon}
          </span>
        </button>
        <div className="absolute left-full top-1/2 z-50 ml-2 hidden -translate-y-1/2 whitespace-nowrap rounded-lg border border-ink/[0.08] bg-white px-2.5 py-1.5 text-[11px] font-medium text-ink shadow-lg group-hover/tooltip:block dark:border-fog/[0.08] dark:bg-ink dark:text-fog">
          {group.label}
        </div>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => onToggle(group.label)}
        className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 transition ${
          isOpen ? "bg-ink/[0.04] dark:bg-fog/[0.04]" : "hover:bg-ink/[0.03] dark:hover:bg-fog/[0.03]"
        }`}
      >
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-gradient-to-br ${group.color} text-white`}>
          {group.icon}
        </span>
        <span className="flex-1 text-[13px] font-semibold text-ink dark:text-fog">{group.label}</span>
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className={`h-3 w-3 text-ink/25 transition-transform ${isOpen ? "rotate-90" : ""} dark:text-fog/25`}
        >
          <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {isOpen && (
        <div className="ml-4 mt-0.5 space-y-0.5 border-l border-ink/[0.06] pl-3 dark:border-fog/[0.06]">
          {group.items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-2 rounded-md px-2.5 py-[6px] text-[12px] font-medium text-ink/50 transition hover:bg-ink/[0.04] hover:text-ink dark:text-fog/50 dark:hover:bg-fog/[0.04] dark:hover:text-fog"
            >
              <span className="h-1 w-1 shrink-0 rounded-full bg-ink/20 dark:bg-fog/20" />
              {item.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState<string | null>("AI Agents");

  const toggleGroup = (label: string) => {
    setExpanded((prev) => (prev === label ? null : label));
  };

  return (
    <aside
      className={`relative flex h-screen flex-col border-r border-ink/[0.06] bg-white transition-all duration-200 dark:bg-ink dark:border-fog/[0.06] ${
        collapsed ? "w-[56px]" : "w-[220px]"
      }`}
    >
      {/* Logo */}
      <div className="flex h-11 items-center gap-2 border-b border-ink/[0.06] px-3 dark:border-fog/[0.06]">
        <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-5 w-auto" />
        {!collapsed && (
          <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={110} height={18} className="h-4 w-auto" />
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-3">
        {/* Bottom nav first */}
        <div className="space-y-0.5 mb-3">
          {bottomNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-ink/50 transition hover:bg-ink/[0.04] hover:text-ink dark:text-fog/50 dark:hover:bg-fog/[0.04] dark:hover:text-fog"
            >
              <span className="h-4 w-4 shrink-0 text-ink/30 dark:text-fog/30">{item.icon}</span>
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
          ))}
        </div>

        {/* Divider */}
        <div className="mx-2.5 mb-2 h-px bg-ink/[0.06] dark:bg-fog/[0.06]" />

        {/* AI System groups */}
        {!collapsed && (
          <p className="mx-2.5 mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink/25 dark:text-fog/25">
            AI Systems
          </p>
        )}
        <div className="space-y-1">
          {navGroups.map((group) => (
            <GroupHeader
              key={group.label}
              group={group}
              expanded={expanded}
              onToggle={toggleGroup}
              collapsed={collapsed}
            />
          ))}
        </div>

        {/* Shared templates */}
        {!collapsed && (
          <>
            <div className="mx-2.5 my-3 h-px bg-ink/[0.06] dark:bg-fog/[0.06]" />
            <p className="mx-2.5 mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink/25 dark:text-fog/25">
              Templates
            </p>
            <Link
              href="/dashboard/templates"
              className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-ink/50 transition hover:bg-ink/[0.04] hover:text-ink dark:text-fog/50 dark:hover:bg-fog/[0.04] dark:hover:text-fog"
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-ink/30 dark:text-fog/30">
                  <rect x="3" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="14" width="7" height="7" rx="1" />
                  <rect x="3" y="14" width="7" height="7" rx="1" />
                </svg>
              </span>
              Agent Templates
            </Link>
            <Link
              href="/dashboard/templates/shared"
              className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-ink/50 transition hover:bg-ink/[0.04] hover:text-ink dark:text-fog/50 dark:hover:bg-fog/[0.04] dark:hover:text-fog"
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-ink/30 dark:text-fog/30">
                  <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
                </svg>
              </span>
              Shared Templates
            </Link>
          </>
        )}
      </nav>

      {/* Collapse */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex h-9 items-center justify-center border-t border-ink/[0.06] text-ink/25 transition hover:text-ink/50 dark:border-fog/[0.06] dark:text-fog/25 dark:hover:text-fog/50"
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

function BotIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4M8 11v4M16 11v4" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2" />
      <path d="M12 19v4M8 23h8" />
    </svg>
  );
}

function VolumeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07" />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  );
}

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

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function UsersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <circle cx="12" cy="12" r="10" />
      <line x1="2" y1="12" x2="22" y2="12" />
      <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
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

function SparklesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <path d="M12 2l1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2z" />
      <path d="M19 14l1 3.5L23.5 18.5 19 19.5l-1 3.5-1-3.5-4.5-1 4.5-1 1-3.5z" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  );
}
