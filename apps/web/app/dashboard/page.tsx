"use client";

import { useState } from "react";

const periodTabs = ["24h", "7d", "30d", "90d"];

const kpis = [
  { label: "Total messages", value: "12,847", change: "+18.2%", up: true, icon: MessageIcon },
  { label: "Conversations", value: "1,243", change: "+9.1%", up: true, icon: ChatIcon },
  { label: "Response time", value: "1.8m", change: "-22%", up: true, icon: ClockIcon },
  { label: "Resolution rate", value: "94.2%", change: "+3.4%", up: true, icon: CheckIcon },
];

const channelPerformance = [
  { name: "Instagram", messages: 3420, growth: "+24%", color: "bg-gradient-to-r from-pink-500 to-purple-500" },
  { name: "WhatsApp", messages: 2890, growth: "+12%", color: "bg-gradient-to-r from-green-400 to-emerald-500" },
  { name: "X / Twitter", messages: 2100, growth: "+8%", color: "bg-gradient-to-r from-sky-400 to-blue-500" },
  { name: "Telegram", messages: 1650, growth: "+15%", color: "bg-gradient-to-r from-blue-400 to-indigo-500" },
  { name: "Facebook", messages: 1420, growth: "+5%", color: "bg-gradient-to-r from-blue-500 to-blue-600" },
  { name: "LinkedIn", messages: 1367, growth: "+31%", color: "bg-gradient-to-r from-blue-600 to-blue-700" },
];

const recentActivity = [
  { time: "2m", text: "New conversation started on Instagram", type: "info" },
  { time: "5m", text: "Campaign \"Spring Sale\" sent to 2,400 contacts", type: "success" },
  { time: "12m", text: "LLM summary generated for support ticket #4821", type: "info" },
  { time: "18m", text: "STT transcription completed (3m 24s audio)", type: "info" },
  { time: "25m", text: "TTS audio generated for voice message", type: "info" },
  { time: "1h", text: "Weekly report ready for download", type: "success" },
];

const topContacts = [
  { name: "Sarah Chen", platform: "Instagram", messages: 89, avatar: "SC", color: "from-deep-violet to-magenta" },
  { name: "Marcus Rivera", platform: "WhatsApp", messages: 67, avatar: "MR", color: "from-magenta to-coral" },
  { name: "Elena Kowalski", platform: "X", messages: 54, avatar: "EK", color: "from-amber-400 to-orange-400" },
  { name: "James Okafor", platform: "Telegram", messages: 41, avatar: "JO", color: "from-sky-400 to-blue-500" },
];

function MiniChart({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const h = 32;
  const w = 80;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-8 w-20">
      <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={points} className={color} />
    </svg>
  );
}

export default function DashboardPage() {
  const [period, setPeriod] = useState("7d");

  return (
    <div className="space-y-5">
      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((k) => (
          <div key={k.label} className="flex items-center gap-3 rounded-xl border border-ink/[0.06] bg-white p-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-deep-violet/[0.06]">
              <k.icon className="h-5 w-5 text-deep-violet" />
            </div>
            <div>
              <p className="text-[11px] font-medium text-ink/40">{k.label}</p>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[18px] font-bold text-ink">{k.value}</span>
                <span className="text-[11px] font-semibold text-emerald-600">{k.change}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Channel performance — 2 cols */}
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-ink">Channel Performance</h3>
            <div className="flex gap-1">
              {periodTabs.map((t) => (
                <button
                  key={t}
                  onClick={() => setPeriod(t)}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                    period === t ? "bg-deep-violet/10 text-deep-violet" : "text-ink/35 hover:text-ink/60"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-3">
            {channelPerformance.map((ch) => {
              const max = channelPerformance[0].messages;
              const pct = (ch.messages / max) * 100;
              return (
                <div key={ch.name} className="flex items-center gap-3">
                  <span className="w-24 shrink-0 text-[12px] font-medium text-ink/60">{ch.name}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink/[0.04]">
                    <div className={`h-full rounded-full ${ch.color}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="w-16 shrink-0 text-right text-[12px] font-semibold text-ink">{ch.messages.toLocaleString()}</span>
                  <span className="w-12 shrink-0 text-right text-[11px] font-medium text-emerald-600">{ch.growth}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Activity feed */}
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4">
          <h3 className="mb-3 text-[13px] font-semibold text-ink">Recent Activity</h3>
          <div className="space-y-3">
            {recentActivity.map((a, i) => (
              <div key={i} className="flex items-start gap-2.5">
                <div className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${a.type === "success" ? "bg-emerald-500" : "bg-deep-violet"}`} />
                <div>
                  <p className="text-[12px] text-ink/60">{a.text}</p>
                  <p className="text-[10px] text-ink/30">{a.time} ago</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Usage chart placeholder */}
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 lg:col-span-2">
          <h3 className="mb-3 text-[13px] font-semibold text-ink">Message Volume</h3>
          <div className="flex items-end gap-1.5" style={{ height: 120 }}>
            {[35, 52, 48, 65, 72, 68, 80, 95, 88, 76, 82, 90, 98, 85].map((h, i) => (
              <div key={i} className="flex-1 rounded-t bg-gradient-to-t from-deep-violet/20 to-deep-violet/5 transition-all hover:from-deep-violet/30 hover:to-deep-violet/10" style={{ height: `${h}%` }} />
            ))}
          </div>
          <div className="mt-2 flex justify-between text-[9px] text-ink/25">
            <span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span>
          </div>
        </div>

        {/* Top contacts */}
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4">
          <h3 className="mb-3 text-[13px] font-semibold text-ink">Top Contacts</h3>
          <div className="space-y-2.5">
            {topContacts.map((c) => (
              <div key={c.name} className="flex items-center gap-2.5">
                <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${c.color} text-[10px] font-semibold text-white`}>
                  {c.avatar}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-medium text-ink">{c.name}</p>
                  <p className="text-[10px] text-ink/35">{c.platform}</p>
                </div>
                <span className="text-[12px] font-semibold text-ink">{c.messages}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* AI Usage */}
      <div className="rounded-xl border border-ink/[0.06] bg-white p-4">
        <h3 className="mb-3 text-[13px] font-semibold text-ink">AI Usage Today</h3>
        <div className="grid grid-cols-3 gap-4">
          <div className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-xl bg-deep-violet/[0.06]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-deep-violet">
                <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" strokeLinecap="round" />
                <path d="M19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-[18px] font-bold text-ink">47</p>
            <p className="text-[11px] text-ink/40">TTS generated</p>
          </div>
          <div className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-xl bg-magenta/[0.06]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-magenta">
                <path d="M3 18v-6a9 9 0 0118 0v6" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-[18px] font-bold text-ink">31</p>
            <p className="text-[11px] text-ink/40">STT transcribed</p>
          </div>
          <div className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-xl bg-coral/[0.06]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-coral">
                <path d="M12 2l2.09 6.26L20.18 10l-6.09 1.74L12 18l-2.09-6.26L3.82 10l6.09-1.74z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-[18px] font-bold text-ink">156</p>
            <p className="text-[11px] text-ink/40">LLM queries</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
      <polyline points="22,6 12,13 2,6" />
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

function ClockIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}
