"use client";

import { ChannelLogo } from "../ChannelLogos";

interface AnalyticsTabProps {
  channelSlug: string;
  channelName: string;
}

const stats = [
  { label: "Total Chats", value: "1,284", change: "+12.5%", up: true },
  { label: "Leads Generated", value: "342", change: "+8.3%", up: true },
  { label: "Tokens Used", value: "2.4M", change: "+15.2%", up: true },
  { label: "Avg Response Time", value: "1.2s", change: "-18%", up: true },
];

const weeklyData = [
  { day: "Mon", chats: 45, leads: 12 },
  { day: "Tue", chats: 62, leads: 18 },
  { day: "Wed", chats: 38, leads: 9 },
  { day: "Thu", chats: 75, leads: 22 },
  { day: "Fri", chats: 88, leads: 28 },
  { day: "Sat", chats: 52, leads: 15 },
  { day: "Sun", chats: 35, leads: 8 },
];

const recentActivity = [
  { time: "2m ago", event: "New lead captured", type: "lead" },
  { time: "15m ago", event: "Conversation resolved", type: "resolved" },
  { time: "32m ago", event: "Agent responded to inquiry", type: "agent" },
  { time: "1h ago", event: "New follower acquired", type: "lead" },
  { time: "2h ago", event: "Campaign click-through", type: "campaign" },
];

export default function AnalyticsTab({ channelSlug, channelName }: AnalyticsTabProps) {
  const maxChats = Math.max(...weeklyData.map((d) => d.chats));

  return (
    <div className="p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-[16px] font-bold text-ink">{channelName} Analytics</h2>
        <p className="mt-0.5 text-[13px] text-ink/60">Overview of your channel performance.</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="rounded-2xl border-2 border-white bg-white/80 p-4">
            <p className="text-[11px] font-semibold text-ink/50">{s.label}</p>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-[22px] font-bold text-ink">{s.value}</span>
              <span className={`text-[11px] font-bold ${s.up ? "text-emerald-600" : "text-coral"}`}>{s.change}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Chart + Activity */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Bar chart */}
        <div className="lg:col-span-2 rounded-2xl border-2 border-white bg-white/80 p-4 sm:p-5">
          <h3 className="mb-4 text-[13px] font-bold text-ink">Weekly Conversations</h3>
          <div className="flex items-end gap-2" style={{ height: 160 }}>
            {weeklyData.map((d) => (
              <div key={d.day} className="flex flex-1 flex-col items-center gap-1.5">
                <div className="w-full rounded-t-lg bg-gradient-to-t from-deep-violet/30 to-deep-violet/5 transition-all hover:from-deep-violet/50 hover:to-deep-violet/10" style={{ height: `${(d.chats / maxChats) * 100}%` }} />
                <span className="text-[10px] font-semibold text-ink/40">{d.day}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Recent activity */}
        <div className="rounded-2xl border-2 border-white bg-white/80 p-4 sm:p-5">
          <h3 className="mb-3 text-[13px] font-bold text-ink">Recent Activity</h3>
          <div className="space-y-3">
            {recentActivity.map((a, i) => (
              <div key={i} className="flex items-start gap-3">
                <div className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
                  a.type === "lead" ? "bg-emerald-500" :
                  a.type === "resolved" ? "bg-deep-violet" :
                  a.type === "agent" ? "bg-sky-500" :
                  "bg-amber-500"
                }`} />
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-medium text-ink">{a.event}</p>
                  <p className="text-[10px] text-ink/40">{a.time}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Token usage breakdown */}
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4 sm:p-5">
        <h3 className="mb-3 text-[13px] font-bold text-ink">Token Usage</h3>
        <div className="space-y-2.5">
          {[
            { name: "Input Tokens", used: 1.2, total: 5, color: "bg-deep-violet" },
            { name: "Output Tokens", used: 0.8, total: 5, color: "bg-magenta" },
            { name: "Cached Tokens", used: 0.4, total: 5, color: "bg-sky-500" },
          ].map((t) => (
            <div key={t.name} className="flex items-center gap-3">
              <span className="w-28 text-[11px] font-semibold text-ink/55">{t.name}</span>
              <div className="flex-1 h-2 overflow-hidden rounded-full bg-ink/[0.06]">
                <div className={`h-full rounded-full ${t.color}`} style={{ width: `${(t.used / t.total) * 100}%` }} />
              </div>
              <span className="w-12 text-right text-[11px] font-bold text-ink">{t.used}M</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
