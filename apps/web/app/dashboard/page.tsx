"use client";

import { useState } from "react";

const tabs = ["All", "Unread", "Starred", "Mentions"];

const messages = [
  {
    id: 1,
    sender: "Sarah Chen",
    avatar: "SC",
    color: "from-deep-violet to-magenta",
    subject: "Q4 campaign performance report",
    preview: "Hey team, the numbers are in for Q4. Overall engagement is up 34% across all channels. The Instagram campaign outperformed...",
    time: "2m ago",
    channel: "Instagram",
    unread: true,
    starred: false,
  },
  {
    id: 2,
    sender: "Marcus Rivera",
    avatar: "MR",
    color: "from-magenta to-coral",
    subject: "Customer support escalation #4821",
    preview: "Premium client reporting issues with the billing portal. They've been charged twice for their annual subscription. Need immediate...",
    time: "15m ago",
    channel: "Support",
    unread: true,
    starred: true,
  },
  {
    id: 3,
    sender: "AI Assistant",
    avatar: "AI",
    color: "from-emerald-500 to-teal-400",
    subject: "Weekly summary ready",
    preview: "Your weekly communication summary is ready. 142 messages processed, 23 conversations resolved, average response time improved by 12%...",
    time: "1h ago",
    channel: "System",
    unread: false,
    starred: false,
  },
  {
    id: 4,
    sender: "Elena Kowalski",
    avatar: "EK",
    color: "from-amber-400 to-orange-400",
    subject: "Re: Product launch timeline",
    preview: "I've updated the Gantt chart with the revised dates. The social media rollout should start 2 weeks before the official launch. I've also...",
    time: "3h ago",
    channel: "X / Twitter",
    unread: false,
    starred: true,
  },
  {
    id: 5,
    sender: "James Okafor",
    avatar: "JO",
    color: "from-blue-500 to-indigo-500",
    subject: "New integration partner",
    preview: "The partnership with TechFlow is confirmed. They want to integrate their CRM with our platform. I've scheduled a kickoff call for...",
    time: "5h ago",
    channel: "Email",
    unread: false,
    starred: false,
  },
  {
    id: 6,
    sender: "Aisha Patel",
    avatar: "AP",
    color: "from-coral to-pink-400",
    subject: "Brand guidelines update",
    preview: "Attached are the updated brand guidelines. Key changes: new color palette for dark mode, updated typography scale, and revised logo usage...",
    time: "8h ago",
    channel: "Facebook",
    unread: false,
    starred: false,
  },
  {
    id: 7,
    sender: "Telegram Bot",
    avatar: "TB",
    color: "from-sky-400 to-blue-500",
    subject: "Alert: Server response time spike",
    preview: "Monitoring alert: API response time has increased to 850ms (threshold: 500ms). This may affect customer-facing applications. Auto-scaling...",
    time: "12h ago",
    channel: "Telegram",
    unread: true,
    starred: false,
  },
];

const stats = [
  { label: "Messages today", value: "142", change: "+12%", up: true },
  { label: "Active conversations", value: "23", change: "+5%", up: true },
  { label: "Avg response time", value: "2.4m", change: "-18%", up: true },
  { label: "Channels connected", value: "6", change: "", up: true },
];

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("All");
  const [selected, setSelected] = useState<number[]>([]);

  const toggleSelect = (id: number) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  return (
    <div className="mx-auto max-w-5xl">
      {/* Stats row */}
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-ink/[0.06] bg-white p-4">
            <p className="text-[12px] font-medium text-ink/40">{s.label}</p>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-[22px] font-bold text-ink">{s.value}</span>
              {s.change && (
                <span className={`text-[12px] font-semibold ${s.up ? "text-emerald-600" : "text-coral"}`}>
                  {s.change}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Inbox card */}
      <div className="overflow-hidden rounded-xl border border-ink/[0.06] bg-white">
        {/* Tabs + toolbar */}
        <div className="flex items-center gap-1 border-b border-ink/[0.06] px-4">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={`relative px-3 py-3 text-[13px] font-medium transition ${
                activeTab === t
                  ? "text-deep-violet"
                  : "text-ink/45 hover:text-ink/70"
              }`}
            >
              {t}
              {activeTab === t && (
                <span className="absolute bottom-0 left-3 right-3 h-[2px] rounded-full bg-deep-violet" />
              )}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            {selected.length > 0 && (
              <span className="mr-2 text-[12px] text-ink/40">{selected.length} selected</span>
            )}
            <button className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium text-ink/45 transition hover:bg-ink/[0.04] hover:text-ink/70">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M2 4h12M2 8h12M2 12h12" strokeLinecap="round" />
              </svg>
              Filter
            </button>
          </div>
        </div>

        {/* Messages */}
        <div>
          {messages.map((m) => (
            <div
              key={m.id}
              className={`group flex items-start gap-3 border-b border-ink/[0.04] px-4 py-3 transition hover:bg-fog/60 ${
                m.unread ? "bg-deep-violet/[0.02]" : ""
              }`}
            >
              {/* Checkbox */}
              <input
                type="checkbox"
                checked={selected.includes(m.id)}
                onChange={() => toggleSelect(m.id)}
                className="mt-1 h-4 w-4 rounded border-ink/20 accent-deep-violet"
              />

              {/* Star */}
              <button className="mt-0.5 shrink-0">
                <svg viewBox="0 0 24 24" className={`h-4 w-4 ${m.starred ? "fill-amber-400 text-amber-400" : "fill-none text-ink/20 group-hover:text-ink/30"}`} stroke="currentColor" strokeWidth="1.5">
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>

              {/* Avatar */}
              <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${m.color} text-[12px] font-semibold text-white`}>
                {m.avatar}
              </div>

              {/* Content */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={`text-[13px] ${m.unread ? "font-semibold text-ink" : "font-medium text-ink/70"}`}>
                    {m.sender}
                  </span>
                  <span className="rounded bg-ink/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-ink/35">
                    {m.channel}
                  </span>
                </div>
                <p className={`mt-0.5 truncate text-[13px] ${m.unread ? "font-medium text-ink/80" : "text-ink/50"}`}>
                  {m.subject}
                </p>
                <p className="mt-0.5 truncate text-[12px] text-ink/35">
                  {m.preview}
                </p>
              </div>

              {/* Time */}
              <span className="shrink-0 text-[11px] text-ink/30">{m.time}</span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-ink/[0.06] px-4 py-2.5">
          <span className="text-[12px] text-ink/35">Showing 7 of 142 messages</span>
          <div className="flex items-center gap-1">
            <button className="flex h-7 items-center justify-center rounded px-2 text-[12px] text-ink/35 transition hover:bg-ink/[0.04] hover:text-ink/60" disabled>
              Previous
            </button>
            <button className="flex h-7 items-center justify-center rounded bg-deep-violet/10 px-2 text-[12px] font-medium text-deep-violet">
              1
            </button>
            <button className="flex h-7 items-center justify-center rounded px-2 text-[12px] text-ink/45 transition hover:bg-ink/[0.04]">
              2
            </button>
            <button className="flex h-7 items-center justify-center rounded px-2 text-[12px] text-ink/45 transition hover:bg-ink/[0.04]">
              3
            </button>
            <button className="flex h-7 items-center justify-center rounded px-2 text-[12px] text-ink/45 transition hover:bg-ink/[0.04]">
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
