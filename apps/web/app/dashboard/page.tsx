"use client";

import { useState } from "react";
import Link from "next/link";
import { ChannelLogo } from "@/components/dashboard/ChannelLogos";

type Period = "today" | "week" | "month";

const channels = [
  { slug: "whatsapp", name: "WhatsApp", conversations: 342, responseTime: "12s", health: 98, trend: "+12%", active: true },
  { slug: "instagram", name: "Instagram", conversations: 218, responseTime: "8s", health: 95, trend: "+8%", active: true },
  { slug: "telegram", name: "Telegram", conversations: 156, responseTime: "5s", health: 99, trend: "+15%", active: true },
  { slug: "x", name: "X / Twitter", conversations: 89, responseTime: "18s", health: 92, trend: "-3%", active: true },
  { slug: "facebook", name: "Facebook", conversations: 0, responseTime: "-", health: 0, trend: "-", active: false },
  { slug: "linkedin", name: "LinkedIn", conversations: 0, responseTime: "-", health: 0, trend: "-", active: false },
];

const liveActivity = [
  { id: "1", type: "message", channel: "whatsapp", user: "Sarah Chen", action: "Replied to pricing inquiry", time: "Just now", sentiment: "positive" },
  { id: "2", type: "lead", channel: "instagram", user: "Marcus Rivera", action: "New lead captured", time: "2m ago", sentiment: "hot" },
  { id: "3", type: "call", channel: "telegram", user: "Elena Kowalski", action: "Outbound call completed", time: "5m ago", sentiment: "positive" },
  { id: "4", type: "message", channel: "whatsapp", user: "James Okafor", action: "Sent invoice", time: "8m ago", sentiment: "neutral" },
  { id: "5", type: "lead", channel: "x", user: "Aisha Patel", action: "Score updated to 85", time: "12m ago", sentiment: "hot" },
  { id: "6", type: "campaign", channel: "instagram", user: "Summer Sale", action: "Campaign sent to 1,247 contacts", time: "1h ago", sentiment: "positive" },
  { id: "7", type: "message", channel: "telegram", user: "David Kim", action: "Resolved support ticket", time: "1h ago", sentiment: "positive" },
  { id: "8", type: "call", channel: "whatsapp", user: "Olivia Thompson", action: "Missed call follow-up", time: "2h ago", sentiment: "negative" },
];

const topLeads = [
  { name: "Omar Benali", source: "WhatsApp", value: "$4,100", score: 95, status: "hot" },
  { name: "David Kim", source: "Instagram", value: "$2,400", score: 92, status: "hot" },
  { name: "Sarah Chen", source: "WhatsApp", value: "$1,800", score: 88, status: "hot" },
  { name: "Marcus Rivera", source: "Instagram", value: "$1,200", score: 85, status: "hot" },
];

const aiMetrics = {
  messagesHandled: 1847,
  avgResponseTime: "8s",
  resolutionRate: "94%",
  satisfaction: "4.8",
  activeNow: 3,
  totalAgents: 5,
};

const weeklyData = [
  { day: "Mon", conversations: 145, leads: 12, conversions: 3 },
  { day: "Tue", conversations: 178, leads: 18, conversions: 5 },
  { day: "Wed", conversations: 156, leads: 14, conversions: 4 },
  { day: "Thu", conversations: 203, leads: 22, conversions: 7 },
  { day: "Fri", conversations: 189, leads: 19, conversions: 6 },
  { day: "Sat", conversations: 124, leads: 8, conversions: 2 },
  { day: "Sun", conversations: 98, leads: 6, conversions: 1 },
];

const sentimentColors: Record<string, string> = {
  positive: "bg-emerald-100 text-emerald-700",
  neutral: "bg-ink/10 text-ink/60",
  negative: "bg-coral/10 text-coral",
  hot: "bg-coral/10 text-coral",
};

const activityIcons: Record<string, React.ReactNode> = {
  message: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  ),
  lead: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
    </svg>
  ),
  call: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
    </svg>
  ),
  campaign: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  ),
};

export default function DashboardPage() {
  const [period, setPeriod] = useState<Period>("week");

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };

  const maxConversations = Math.max(...weeklyData.map((d) => d.conversations));

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-5 bg-[#f3f0ff]">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-[20px] sm:text-[22px] font-bold text-ink">{greeting()}, Syed</h1>
          <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">Here&apos;s what&apos;s happening across your channels today.</p>
        </div>
        <div className="flex gap-0.5 rounded-xl bg-deep-violet/[0.06] p-0.5">
          {(["today", "week", "month"] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`rounded-lg px-3 py-1.5 text-[11px] font-semibold capitalize transition ${
                period === p ? "bg-deep-violet text-white shadow-sm" : "text-ink/50 hover:text-ink/70"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          label="Total Conversations"
          value="1,243"
          change="+9.1%"
          icon={<ChatIcon />}
          color="deep-violet"
        />
        <KpiCard
          label="Leads Captured"
          value="247"
          change="+18.2%"
          icon={<LeadsIcon />}
          color="coral"
        />
        <KpiCard
          label="AI Resolution Rate"
          value="94%"
          change="+2.1%"
          icon={<BotIcon />}
          color="emerald"
        />
        <KpiCard
          label="Pipeline Value"
          value="$18.4K"
          change="+22%"
          icon={<RevenueIcon />}
          color="amber"
        />
      </div>

      {/* Live Count Strip */}
      <div className="rounded-2xl border-2 border-deep-violet/20 bg-gradient-to-r from-deep-violet/5 via-white/80 to-magenta/5 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-deep-violet/10">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
          </span>
          <span className="text-[12px] font-bold text-ink">Live Now</span>
          <span className="text-[10px] text-ink/40">&middot; Real-time activity across all channels</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 divide-x divide-deep-violet/10">
          <LiveCounter label="Active Chats" value={47} icon={<ChatIcon />} color="text-deep-violet" bg="bg-deep-violet/10" />
          <LiveCounter label="Agents Online" value={5} icon={<BotIcon />} color="text-emerald-600" bg="bg-emerald-100" pulse />
          <LiveCounter label="Queued Messages" value={12} icon={<QueueIcon />} color="text-amber-600" bg="bg-amber-100" />
          <LiveCounter label="Leads Today" value={18} icon={<LeadsIcon />} color="text-coral" bg="bg-coral/10" />
          <LiveCounter label="Calls Active" value={3} icon={<CallIcon />} color="text-sky-600" bg="bg-sky-100" pulse />
          <LiveCounter label="Campaigns Running" value={2} icon={<CampaignIcon />} color="text-magenta" bg="bg-magenta/10" pulse />
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Channel Performance */}
        <div className="lg:col-span-2 rounded-2xl border-2 border-white bg-white/80 backdrop-blur-sm">
          <div className="flex items-center justify-between border-b border-deep-violet/[0.06] px-4 py-3">
            <h3 className="text-[13px] font-semibold text-ink">Channel Performance</h3>
            <Link href="/dashboard/channels" className="text-[11px] font-semibold text-deep-violet hover:text-deep-violet/80">
              View All
            </Link>
          </div>
          <div className="p-4">
            <div className="space-y-3">
              {channels.filter(c => c.active).map((ch) => (
                <Link
                  key={ch.slug}
                  href={`/dashboard/channels/${ch.slug}`}
                  className="flex items-center gap-3 rounded-xl p-3 transition hover:bg-ink/[0.02]"
                >
                  <ChannelLogo channel={ch.slug} className="h-8 w-8" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-ink">{ch.name}</span>
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-ink/50">
                      <span>{ch.conversations} conversations</span>
                      <span>&middot;</span>
                      <span>{ch.responseTime} avg response</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="flex items-center gap-1.5">
                      <div className="h-1.5 w-16 rounded-full bg-ink/10 overflow-hidden">
                        <div className="h-full rounded-full bg-emerald-400" style={{ width: `${ch.health}%` }} />
                      </div>
                      <span className="text-[11px] font-semibold text-ink/60">{ch.health}%</span>
                    </div>
                    <span className={`text-[10px] font-semibold ${ch.trend.startsWith("+") ? "text-emerald-600" : "text-coral"}`}>
                      {ch.trend}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </div>

        {/* AI Agent Status */}
        <div className="rounded-2xl border-2 border-white bg-white/80 backdrop-blur-sm">
          <div className="flex items-center justify-between border-b border-deep-violet/[0.06] px-4 py-3">
            <h3 className="text-[13px] font-semibold text-ink">AI Agent Status</h3>
            <span className="flex items-center gap-1.5 text-[10px] font-semibold text-emerald-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              {aiMetrics.activeNow} Active
            </span>
          </div>
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-deep-violet/[0.04] p-3 text-center">
                <p className="text-[20px] font-bold text-ink">{aiMetrics.messagesHandled.toLocaleString()}</p>
                <p className="text-[10px] text-ink/45">Messages Today</p>
              </div>
              <div className="rounded-xl bg-deep-violet/[0.04] p-3 text-center">
                <p className="text-[20px] font-bold text-ink">{aiMetrics.avgResponseTime}</p>
                <p className="text-[10px] text-ink/45">Avg Response</p>
              </div>
              <div className="rounded-xl bg-emerald-100 p-3 text-center">
                <p className="text-[20px] font-bold text-emerald-700">{aiMetrics.resolutionRate}</p>
                <p className="text-[10px] text-emerald-600/80">Resolution</p>
              </div>
              <div className="rounded-xl bg-amber-100 p-3 text-center">
                <p className="text-[20px] font-bold text-amber-700">{aiMetrics.satisfaction}</p>
                <p className="text-[10px] text-amber-600/80">Satisfaction</p>
              </div>
            </div>

            <div className="border-t border-deep-violet/[0.06] pt-3">
              <p className="text-[11px] font-semibold text-ink/50 mb-2">Active Agents</p>
              <div className="space-y-2">
                {["Support Bot", "Sales Assistant", "Lead Qualifier"].map((agent, i) => (
                  <div key={agent} className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    <span className="text-[12px] text-ink/70">{agent}</span>
                    <span className="ml-auto text-[10px] text-ink/40">{[42, 28, 15][i]} active</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Weekly Trend */}
        <div className="lg:col-span-2 rounded-2xl border-2 border-white bg-white/80 backdrop-blur-sm">
          <div className="flex items-center justify-between border-b border-deep-violet/[0.06] px-4 py-3">
            <h3 className="text-[13px] font-semibold text-ink">Weekly Overview</h3>
            <div className="flex items-center gap-3 text-[10px]">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-deep-violet" /> Conversations</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-coral" /> Leads</span>
            </div>
          </div>
          <div className="p-4">
            <div className="flex items-end gap-2" style={{ height: 160 }}>
              {weeklyData.map((d, i) => (
                <div key={i} className="flex flex-1 flex-col items-center gap-1">
                  <div className="w-full flex gap-0.5 items-end" style={{ height: 140 }}>
                    <div
                      className="flex-1 rounded-t bg-deep-violet/60 transition-all hover:bg-deep-violet/80"
                      style={{ height: `${(d.conversations / maxConversations) * 100}%` }}
                    />
                    <div
                      className="flex-1 rounded-t bg-coral/60 transition-all hover:bg-coral/80"
                      style={{ height: `${(d.leads / maxConversations) * 100}%` }}
                    />
                  </div>
                  <span className="text-[9px] text-ink/35">{d.day}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-deep-violet/[0.06] pt-3">
              <div>
                <p className="text-[16px] font-bold text-ink">1,243</p>
                <p className="text-[10px] text-ink/45">total conversations</p>
              </div>
              <div className="text-right">
                <p className="text-[16px] font-bold text-ink">99</p>
                <p className="text-[10px] text-ink/45">leads captured</p>
              </div>
            </div>
          </div>
        </div>

        {/* Top Leads */}
        <div className="rounded-2xl border-2 border-white bg-white/80 backdrop-blur-sm">
          <div className="flex items-center justify-between border-b border-deep-violet/[0.06] px-4 py-3">
            <h3 className="text-[13px] font-semibold text-ink">Top Leads</h3>
            <span className="text-[10px] font-semibold text-deep-violet">View All</span>
          </div>
          <div className="p-4 space-y-2">
            {topLeads.map((lead, i) => (
              <div key={i} className="flex items-center gap-3 rounded-xl p-2 transition hover:bg-ink/[0.02]">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[11px] font-bold text-white">
                  {lead.name.split(" ").map(n => n[0]).join("")}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-semibold text-ink">{lead.name}</p>
                  <p className="text-[10px] text-ink/45">{lead.source}</p>
                </div>
                <div className="text-right">
                  <p className="text-[12px] font-bold text-ink">{lead.value}</p>
                  <div className="flex items-center gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-coral" />
                    <span className="text-[9px] text-ink/40">{lead.score}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Live Activity */}
      <div className="rounded-2xl border-2 border-white bg-white/80 backdrop-blur-sm">
        <div className="flex items-center justify-between border-b border-deep-violet/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <h3 className="text-[13px] font-semibold text-ink">Live Activity</h3>
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
          </div>
          <span className="text-[10px] text-ink/40">Auto-updating</span>
        </div>
        <div className="p-4">
          <div className="space-y-0">
            {liveActivity.map((activity) => (
              <div key={activity.id} className="flex items-start gap-3 border-b border-ink/[0.04] py-3 last:border-0">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-deep-violet/10 text-deep-violet">
                  {activityIcons[activity.type]}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-semibold text-ink">{activity.user}</span>
                    <ChannelLogo channel={activity.channel} className="h-3.5 w-3.5" />
                  </div>
                  <p className="text-[11px] text-ink/55">{activity.action}</p>
                </div>
                <div className="text-right shrink-0">
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${sentimentColors[activity.sentiment]}`}>
                    {activity.sentiment}
                  </span>
                  <p className="mt-1 text-[10px] text-ink/35">{activity.time}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── KPI Card ──────────────────────────────────── */
function KpiCard({ label, value, change, icon, color }: { label: string; value: string; change: string; icon: React.ReactNode; color: string }) {
  const positive = change.startsWith("+");
  const colorMap: Record<string, string> = {
    "deep-violet": "bg-deep-violet/10 text-deep-violet",
    coral: "bg-coral/10 text-coral",
    emerald: "bg-emerald-100 text-emerald-600",
    amber: "bg-amber-100 text-amber-600",
  };

  return (
    <div className="flex items-center gap-3 rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm">
      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${colorMap[color]}`}>
        {icon}
      </div>
      <div>
        <p className="text-[10px] sm:text-[11px] font-semibold text-ink/55">{label}</p>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[18px] sm:text-[20px] font-bold text-ink">{value}</span>
          <span className={`text-[10px] sm:text-[11px] font-bold ${positive ? "text-emerald-600" : "text-coral"}`}>{change}</span>
        </div>
      </div>
    </div>
  );
}

/* ── Icons ─────────────────────────────────────── */
function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function LeadsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function BotIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4M8 11v4M16 11v4" />
    </svg>
  );
}

function RevenueIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <line x1="12" y1="1" x2="12" y2="23" />
      <path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
    </svg>
  );
}

function QueueIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <rect x="2" y="7" width="20" height="4" rx="1" />
      <rect x="4" y="13" width="16" height="4" rx="1" />
      <rect x="6" y="19" width="12" height="4" rx="1" />
    </svg>
  );
}

function CallIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
    </svg>
  );
}

function CampaignIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  );
}

/* ── Live Counter ──────────────────────────────── */
function LiveCounter({
  label,
  value,
  icon,
  color,
  bg,
  pulse = false,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
  bg: string;
  pulse?: boolean;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${bg} ${color}`}>
        {icon}
      </div>
      <div>
        <div className="flex items-center gap-1.5">
          <span className="text-[18px] font-bold text-ink">{value}</span>
          {pulse && (
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
          )}
        </div>
        <p className="text-[10px] text-ink/45">{label}</p>
      </div>
    </div>
  );
}
