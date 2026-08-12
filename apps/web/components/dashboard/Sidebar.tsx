"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { ChannelLogo } from "./ChannelLogos";

interface NavGroup {
  label: string;
  icon: React.ReactNode;
  iconSrc?: string;
  color: string;
  items: { label: string; href: string }[];
}

const navGroups: NavGroup[] = [
  {
    label: "AI Agents",
    icon: <BotIcon />,
    iconSrc: "/agents.png",
    color: "from-deep-violet to-magenta",
    items: [
      { label: "Agents Library", href: "/dashboard/agents" },
      { label: "Create Agent", href: "/dashboard/agents/create" },
    ],
  },
  {
    label: "AI Tools",
    icon: <SparklesIcon />,
    iconSrc: "/aitools.png",
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
  { label: "Contacts", icon: <UsersIcon />, href: "/dashboard/contacts" },
  { label: "Databank", icon: <DatabaseIcon />, href: "/dashboard/databank" },
  { label: "Video Studio", icon: <VideoStudioIcon />, href: "/dashboard/video-studio" },
  { label: "Settings", icon: <SettingsIcon />, href: "/dashboard/settings" },
];

const channelList = [
  { name: "Instagram", slug: "instagram", connected: true, agentActive: false },
  { name: "X / Twitter", slug: "x", connected: true, agentActive: false },
  { name: "Telegram", slug: "telegram", connected: true, agentActive: true },
  { name: "Facebook", slug: "facebook", connected: false, agentActive: false },
  { name: "WhatsApp", slug: "whatsapp", connected: true, agentActive: false },
  { name: "LinkedIn", slug: "linkedin", connected: false, agentActive: false },
  { name: "TikTok", slug: "tiktok", connected: false, agentActive: false },
];

const channelsGroup: NavGroup = {
  label: "Channels",
  icon: <ChannelsIcon />,
  iconSrc: "/channels.png",
  color: "from-sky-400 to-blue-500",
  items: channelList.map((ch) => ({ label: ch.name, href: `/dashboard/channels/${ch.slug}` })),
};

const channelsWithHref = channelList.map((ch) => ({ ...ch, href: `/dashboard/channels/${ch.slug}` }));

function GroupHeader({
  group,
  expanded,
  onToggle,
  collapsed,
  channelList,
}: {
  group: NavGroup;
  expanded: string | null;
  onToggle: (label: string) => void;
  collapsed: boolean;
  channelList?: { name: string; slug: string; connected: boolean; agentActive: boolean; href: string }[];
}) {
  const isOpen = expanded === group.label;

  const iconContent = group.iconSrc ? (
    <Image src={group.iconSrc} alt="" width={20} height={20} className="h-5 w-5 rounded-md object-cover" />
  ) : (
    group.icon
  );

  if (collapsed) {
    return (
      <div className="relative group/tooltip">
        <button
          className="flex h-8 w-full items-center justify-center rounded-lg text-white/40 transition hover:bg-white/[0.08] hover:text-white/60"
          title={group.label}
        >
          <span className={`flex h-6 w-6 items-center justify-center rounded-md ${group.iconSrc ? "" : `bg-gradient-to-br ${group.color} text-white`}`}>
            {iconContent}
          </span>
        </button>
        <div className="absolute left-full top-1/2 z-50 ml-2 hidden -translate-y-1/2 whitespace-nowrap rounded-lg border border-white/[0.08] bg-[#1e1547] px-2.5 py-1.5 text-[11px] font-medium text-white shadow-lg group-hover/tooltip:block">
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
          isOpen ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"
        }`}
      >
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${group.iconSrc ? "" : `bg-gradient-to-br ${group.color} text-white`}`}>
            {iconContent}
          </span>
        <span className="flex-1 text-[13px] font-semibold text-white/90">{group.label}</span>
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className={`h-3 w-3 text-white/25 transition-transform ${isOpen ? "rotate-90" : ""}`}
        >
          <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {isOpen && (
        <div className="ml-4 mt-0.5 space-y-0.5 border-l border-white/[0.1] pl-3">
          {channelList ? (
            channelList.map((ch) => (
              <Link
                key={ch.slug}
                href={ch.href}
                className="flex items-center gap-2 rounded-md px-2.5 py-[6px] text-[12px] font-medium text-white/40 transition hover:bg-white/[0.08] hover:text-white/80"
              >
                <ChannelLogo channel={ch.slug} className="h-3.5 w-3.5 shrink-0" />
                <span className="flex-1">{ch.name}</span>
                <ChannelStatusDot connected={ch.connected} agentActive={ch.agentActive} />
              </Link>
            ))
          ) : (
            group.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-2 rounded-md px-2.5 py-[6px] text-[12px] font-medium text-white/40 transition hover:bg-white/[0.08] hover:text-white/80"
              >
                <span className="h-1 w-1 shrink-0 rounded-full bg-white/20" />
                {item.label}
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function ChannelStatusDot({ connected, agentActive }: { connected: boolean; agentActive: boolean }) {
  if (agentActive) {
    return (
      <span className="relative flex h-2 w-2 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
    );
  }
  if (connected) {
    return <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />;
  }
  return <span className="h-2 w-2 shrink-0 rounded-full bg-coral" />;
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState<string | null>("AI Agents");

  const toggleGroup = (label: string) => {
    setExpanded((prev) => (prev === label ? null : label));
  };

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
      <nav className="flex-1 overflow-y-auto px-2 pt-3">
        {/* Bottom nav first */}
        <div className="space-y-0.5 mb-3">
          {bottomNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-white/50 transition hover:bg-white/[0.08] hover:text-white"
            >
              <span className="h-4 w-4 shrink-0 text-white/30">{item.icon}</span>
              {!collapsed && <span className="flex-1">{item.label}</span>}
            </Link>
          ))}
        </div>

        {/* Divider */}
        <div className="mx-2.5 mb-2 h-px bg-white/[0.08]" />

        {/* Channels dropdown */}
        <GroupHeader
          group={channelsGroup}
          expanded={expanded}
          onToggle={toggleGroup}
          collapsed={collapsed}
          channelList={channelsWithHref}
        />

        {/* Divider */}
        <div className="mx-2.5 mb-2 h-px bg-white/[0.08]" />

        {/* AI System groups */}
        {!collapsed && (
          <p className="mx-2.5 mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/25">
            AI Agents & Tools
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
            <div className="mx-2.5 my-3 h-px bg-white/[0.08]" />
            <p className="mx-2.5 mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/25">
              Templates
            </p>
            <Link
              href="/dashboard/templates"
              className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-white/50 transition hover:bg-white/[0.08] hover:text-white"
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-white/30">
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
              className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] font-medium text-white/50 transition hover:bg-white/[0.08] hover:text-white"
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-white/30">
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
        className="flex h-9 items-center justify-center border-t border-white/[0.08] text-white/25 transition hover:text-white/50"
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

function UsersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
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

function ZapIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}

function WidgetIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <circle cx="12" cy="12" r="3" />
      <circle cx="12" cy="12" r="1" fill="currentColor" />
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

function ChannelsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  );
}

function VideoStudioIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <polygon points="23 7 16 12 23 17 23 7" />
      <rect x="1" y="5" width="15" height="14" rx="2" />
    </svg>
  );
}
