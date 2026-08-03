"use client";

import { useState } from "react";

type Period = "day" | "week" | "month" | "year";

function PeriodFilter({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const opts: Period[] = ["day", "week", "month", "year"];
  return (
    <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5">
      {opts.map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          className={`rounded-md px-2 py-1 text-[11px] font-medium capitalize transition ${
            value === p ? "bg-white text-deep-violet shadow-sm" : "text-ink/40 hover:text-ink/60"
          }`}
        >
          {p}
        </button>
      ))}
    </div>
  );
}

function PanelCard({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-ink/[0.06] bg-white ${className}`}>
      <div className="flex items-center justify-between border-b border-ink/[0.04] px-4 py-3">
        <h3 className="text-[13px] font-semibold text-ink">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

/* ── Dummy data ────────────────────────────────── */

const automations = [
  { name: "Welcome series", status: "active", triggers: 1240, conversion: "12%" },
  { name: "Cart recovery", status: "active", triggers: 890, conversion: "8%" },
  { name: "Support follow-up", status: "paused", triggers: 456, conversion: "15%" },
  { name: "Lead nurture", status: "active", triggers: 2100, conversion: "6%" },
  { name: "Re-engagement", status: "active", triggers: 670, conversion: "9%" },
];

const conversations = [
  { name: "Sarah Chen", platform: "Instagram", lastMsg: "Thanks for the quick response!", time: "2m", unread: false },
  { name: "Marcus Rivera", platform: "WhatsApp", lastMsg: "Can you send me the invoice?", time: "8m", unread: true },
  { name: "Elena Kowalski", platform: "X", lastMsg: "The campaign looks great!", time: "15m", unread: false },
  { name: "James Okafor", platform: "Telegram", lastMsg: "When is the next meeting?", time: "32m", unread: true },
  { name: "Aisha Patel", platform: "Facebook", lastMsg: "I'll review the proposal today", time: "1h", unread: false },
];

const leads = [
  { name: "David Kim", source: "Instagram", value: "$2,400", score: 92, status: "hot" },
  { name: "Fatima Al-Hassan", source: "LinkedIn", value: "$1,800", score: 85, status: "hot" },
  { name: "Lucas Silva", source: "X", value: "$950", score: 68, status: "warm" },
  { name: "Priya Sharma", source: "Website", value: "$3,200", score: 78, status: "warm" },
  { name: "Omar Benali", source: "WhatsApp", value: "$4,100", score: 95, status: "hot" },
];

const ratings = [
  { stars: 5, count: 847, pct: 68 },
  { stars: 4, count: 234, pct: 19 },
  { stars: 3, count: 98, pct: 8 },
  { stars: 2, count: 45, pct: 4 },
  { stars: 1, count: 16, pct: 1 },
];

const tickets = [
  { id: "#4821", subject: "Billing issue", status: "open", priority: "high", created: "10m ago" },
  { id: "#4820", subject: "Feature request", status: "pending", priority: "medium", created: "1h ago" },
  { id: "#4819", subject: "Integration help", status: "resolved", priority: "low", created: "3h ago" },
  { id: "#4818", subject: "Account access", status: "resolved", priority: "high", created: "5h ago" },
];

/* ── Page ───────────────────────────────────────── */

export default function DashboardPage() {
  const [period, setPeriod] = useState<Period>("week");

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };

  return (
    <div className="space-y-5">
      {/* Welcome */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-bold text-ink">{greeting()}, Syed 👋</h1>
          <p className="mt-0.5 text-[13px] text-ink/45">Here's what's happening across your channels today.</p>
        </div>
        <PeriodFilter value={period} onChange={setPeriod} />
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Total Leads" value="2,847" change="+18.2%" icon={<LeadsIcon />} />
        <KpiCard label="Conversations" value="1,243" change="+9.1%" icon={<ChatIcon />} />
        <KpiCard label="User Ratings" value="4.7" change="+0.3" icon={<StarIcon />} />
        <KpiCard label="Open Tickets" value="24" change="-12%" icon={<TicketIcon />} />
      </div>

      {/* Main grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Automation overview — 2 cols */}
        <PanelCard title="Automation Overview" className="lg:col-span-2">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-ink/[0.04]">
                  <th className="pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink/35">Name</th>
                  <th className="pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink/35">Status</th>
                  <th className="pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink/35">Triggers</th>
                  <th className="pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink/35">Conversion</th>
                </tr>
              </thead>
              <tbody>
                {automations.map((a) => (
                  <tr key={a.name} className="border-b border-ink/[0.02] last:border-0">
                    <td className="py-2.5 text-[12px] font-medium text-ink">{a.name}</td>
                    <td className="py-2.5">
                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        a.status === "active" ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"
                      }`}>
                        <span className={`h-1 w-1 rounded-full ${a.status === "active" ? "bg-emerald-500" : "bg-amber-500"}`} />
                        {a.status}
                      </span>
                    </td>
                    <td className="py-2.5 text-[12px] text-ink/60">{a.triggers.toLocaleString()}</td>
                    <td className="py-2.5 text-[12px] font-medium text-ink">{a.conversion}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </PanelCard>

        {/* Conversation volumes */}
        <PanelCard title="Conversation Volumes">
          <div className="flex items-end gap-1" style={{ height: 140 }}>
            {[45, 62, 38, 75, 88, 52, 95].map((h, i) => (
              <div key={i} className="flex flex-1 flex-col items-center gap-1">
                <div className="w-full rounded-t bg-gradient-to-t from-deep-violet/25 to-deep-violet/5 transition-all hover:from-deep-violet/40 hover:to-deep-violet/10" style={{ height: `${h}%` }} />
                <span className="text-[9px] text-ink/25">{["M","T","W","T","F","S","S"][i]}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-ink/[0.04] pt-3">
            <div>
              <p className="text-[18px] font-bold text-ink">1,243</p>
              <p className="text-[10px] text-ink/35">total this week</p>
            </div>
            <span className="text-[11px] font-semibold text-emerald-600">+9.1%</span>
          </div>
        </PanelCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent conversations */}
        <PanelCard title="Recent Conversations" className="lg:col-span-2">
          <div className="space-y-0">
            {conversations.map((c, i) => (
              <div key={i} className={`flex items-center gap-3 border-b border-ink/[0.03] py-2.5 last:border-0 ${c.unread ? "" : ""}`}>
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-deep-violet/[0.06] text-[11px] font-semibold text-deep-violet">
                  {c.name.split(" ").map((n) => n[0]).join("")}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-[12px] ${c.unread ? "font-semibold text-ink" : "font-medium text-ink/70"}`}>{c.name}</span>
                    <span className="rounded bg-ink/[0.04] px-1.5 py-0.5 text-[9px] font-medium text-ink/30">{c.platform}</span>
                  </div>
                  <p className="truncate text-[11px] text-ink/40">{c.lastMsg}</p>
                </div>
                <span className="shrink-0 text-[10px] text-ink/25">{c.time}</span>
              </div>
            ))}
          </div>
        </PanelCard>

        {/* User ratings */}
        <PanelCard title="User Ratings">
          <div className="text-center">
            <p className="text-[32px] font-bold text-ink">4.7</p>
            <div className="mx-auto flex items-center justify-center gap-0.5">
              {[1, 2, 3, 4, 5].map((s) => (
                <svg key={s} viewBox="0 0 24 24" className={`h-4 w-4 ${s <= 4 ? "fill-amber-400 text-amber-400" : "fill-amber-400/40 text-amber-400/40"}`}>
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
                </svg>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-ink/35">Based on 1,240 reviews</p>
          </div>
          <div className="mt-4 space-y-1.5">
            {ratings.map((r) => (
              <div key={r.stars} className="flex items-center gap-2">
                <span className="w-3 text-right text-[10px] text-ink/40">{r.stars}</span>
                <svg viewBox="0 0 24 24" className="h-3 w-3 fill-amber-400 text-amber-400">
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
                </svg>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink/[0.04]">
                  <div className="h-full rounded-full bg-amber-400" style={{ width: `${r.pct}%` }} />
                </div>
                <span className="w-8 text-right text-[10px] text-ink/30">{r.count}</span>
              </div>
            ))}
          </div>
        </PanelCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Tickets */}
        <PanelCard title="Tickets & Leads Created" className="lg:col-span-2">
          <div className="mb-3 grid grid-cols-3 gap-2">
            <div className="rounded-lg bg-emerald-50 px-3 py-2 text-center">
              <p className="text-[16px] font-bold text-emerald-700">18</p>
              <p className="text-[10px] text-emerald-600/70">Resolved</p>
            </div>
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-center">
              <p className="text-[16px] font-bold text-amber-700">4</p>
              <p className="text-[10px] text-amber-600/70">Pending</p>
            </div>
            <div className="rounded-lg bg-coral/10 px-3 py-2 text-center">
              <p className="text-[16px] font-bold text-coral">2</p>
              <p className="text-[10px] text-coral/70">Open</p>
            </div>
          </div>
          <div className="space-y-0">
            {tickets.map((t) => (
              <div key={t.id} className="flex items-center gap-3 border-b border-ink/[0.03] py-2 last:border-0">
                <span className="text-[11px] font-mono text-ink/30">{t.id}</span>
                <span className="min-w-0 flex-1 truncate text-[12px] text-ink/70">{t.subject}</span>
                <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${
                  t.status === "open" ? "bg-coral/10 text-coral" :
                  t.status === "pending" ? "bg-amber-50 text-amber-600" :
                  "bg-emerald-50 text-emerald-600"
                }`}>{t.status}</span>
                <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${
                  t.priority === "high" ? "bg-coral/10 text-coral" :
                  t.priority === "medium" ? "bg-amber-50 text-amber-600" :
                  "bg-ink/[0.04] text-ink/40"
                }`}>{t.priority}</span>
                <span className="shrink-0 text-[10px] text-ink/25">{t.created}</span>
              </div>
            ))}
          </div>
        </PanelCard>

        {/* Recent leads */}
        <PanelCard title="Recent Leads">
          <div className="space-y-0">
            {leads.map((l, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-ink/[0.03] py-2.5 last:border-0">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-deep-violet/[0.06] text-[11px] font-semibold text-deep-violet">
                  {l.name.split(" ").map((n) => n[0]).join("")}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-medium text-ink">{l.name}</p>
                  <p className="text-[10px] text-ink/35">{l.source}</p>
                </div>
                <div className="text-right">
                  <p className="text-[12px] font-semibold text-ink">{l.value}</p>
                  <div className="flex items-center gap-1">
                    <span className={`h-1.5 w-1.5 rounded-full ${l.score >= 80 ? "bg-emerald-500" : l.score >= 60 ? "bg-amber-400" : "bg-coral"}`} />
                    <span className="text-[9px] text-ink/30">{l.score}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      </div>
    </div>
  );
}

/* ── KPI card ──────────────────────────────────── */

function KpiCard({ label, value, change, icon }: { label: string; value: string; change: string; icon: React.ReactNode }) {
  const up = change.startsWith("+") || change.startsWith("-");
  const positive = change.startsWith("+") || (change.startsWith("-") && label.includes("Ticket"));
  return (
    <div className="flex items-center gap-3 rounded-xl border border-ink/[0.06] bg-white p-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-deep-violet/[0.06] text-deep-violet">
        {icon}
      </div>
      <div>
        <p className="text-[11px] font-medium text-ink/40">{label}</p>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[18px] font-bold text-ink">{value}</span>
          <span className={`text-[11px] font-semibold ${positive ? "text-emerald-600" : "text-coral"}`}>{change}</span>
        </div>
      </div>
    </div>
  );
}

/* ── Icons ─────────────────────────────────────── */

function LeadsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
    </svg>
  );
}

function TicketIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}
