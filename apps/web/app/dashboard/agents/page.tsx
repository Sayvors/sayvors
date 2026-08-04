"use client";

import { useState } from "react";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";

type Tab = "agents" | "logs" | "analytics";
type StatusFilter = "all" | "active" | "paused" | "draft";
type Period = "day" | "week" | "month" | "year";

const agents = [
  { id: 1, name: "Support Bot", model: "GPT-4o", status: "active", channels: ["WhatsApp", "Web Widget"], conversations: 1240, conversion: "12%", lastActive: "2 min ago" },
  { id: 2, name: "Sales Assistant", model: "Gemini 2.5 Flash", status: "active", channels: ["Instagram", "Facebook"], conversations: 890, conversion: "8%", lastActive: "15 min ago" },
  { id: 3, name: "Lead Qualifier", model: "Grok-3", status: "paused", channels: ["X"], conversations: 456, conversion: "15%", lastActive: "3 days ago" },
  { id: 4, name: "FAQ Bot", model: "DeepSeek Chat", status: "active", channels: ["Web Widget", "WhatsApp"], conversations: 2100, conversion: "22%", lastActive: "5 min ago" },
  { id: 5, name: "Cart Recovery", model: "GPT-4o Mini", status: "draft", channels: [], conversations: 0, conversion: "—", lastActive: "Never" },
  { id: 6, name: "Appointment Scheduler", model: "Kimi K2", status: "active", channels: ["WhatsApp"], conversations: 320, conversion: "18%", lastActive: "1 hour ago" },
  { id: 7, name: "Feedback Collector", model: "Gemini 2.0 Flash", status: "active", channels: ["Instagram"], conversations: 780, conversion: "9%", lastActive: "30 min ago" },
  { id: 8, name: "Upsell Bot", model: "Llama 3.1", status: "paused", channels: ["Facebook"], conversations: 150, conversion: "5%", lastActive: "1 week ago" },
];

const logs = [
  { timestamp: "2026-08-04 14:32:01", agent: "Support Bot", channel: "WhatsApp", preview: "Thanks for reaching out! I can help with...", status: "success", duration: "1.2s" },
  { timestamp: "2026-08-04 14:28:45", agent: "Sales Assistant", channel: "Instagram", preview: "Here's the pricing information you asked...", status: "success", duration: "0.8s" },
  { timestamp: "2026-08-04 14:25:12", agent: "FAQ Bot", channel: "Web Widget", preview: "Our return policy allows returns within 30...", status: "success", duration: "1.5s" },
  { timestamp: "2026-08-04 14:20:33", agent: "Support Bot", channel: "WhatsApp", preview: "Error: timeout connecting to model...", status: "error", duration: "30.0s" },
  { timestamp: "2026-08-04 14:15:08", agent: "Feedback Collector", channel: "Instagram", preview: "We'd love to hear your feedback! Could...", status: "success", duration: "0.9s" },
  { timestamp: "2026-08-04 14:10:51", agent: "Appointment Scheduler", channel: "WhatsApp", preview: "Let me check available slots for next...", status: "success", duration: "2.1s" },
  { timestamp: "2026-08-04 14:05:22", agent: "Sales Assistant", channel: "Facebook", preview: "I'd recommend our Pro plan based on...", status: "success", duration: "1.1s" },
  { timestamp: "2026-08-04 14:00:05", agent: "FAQ Bot", channel: "Web Widget", preview: "Error: rate limit exceeded", status: "error", duration: "0.3s" },
];

function PeriodFilter({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const opts: Period[] = ["day", "week", "month", "year"];
  return (
    <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03]">
      {opts.map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          className={`rounded-md px-2 py-1 text-[11px] font-medium capitalize transition ${
            value === p ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
          }`}
        >
          {p}
        </button>
      ))}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">{label}</p>
      <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{value}</p>
      {sub && <p className="text-[11px] text-ink/30 dark:text-fog/30">{sub}</p>}
    </div>
  );
}

function AgentIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4M8 11v4M16 11v4" />
    </svg>
  );
}

export default function AgentsPage() {
  const [tab, setTab] = useState<Tab>("agents");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [period, setPeriod] = useState<Period>("week");

  const filteredAgents = statusFilter === "all" ? agents : agents.filter((a) => a.status === statusFilter);

  const tabs: { id: Tab; label: string }[] = [
    { id: "agents", label: "Agents" },
    { id: "logs", label: "Logs" },
    { id: "analytics", label: "Analytics" },
  ];

  const statusOpts: StatusFilter[] = ["all", "active", "paused", "draft"];

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <Breadcrumbs items={[{ label: "Agents" }]} />
          <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">My Agents</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Manage, monitor, and deploy your AI agents.</p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/dashboard/agents/customizations"
            className="text-[12px] font-medium text-deep-violet transition hover:text-deep-violet/80"
          >
            Manage Customizations
          </Link>
          <Link
            href="/dashboard/agents/create"
            className="flex items-center gap-1.5 rounded-lg bg-deep-violet px-3 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
              <path d="M8 3v10M3 8h10" strokeLinecap="round" />
            </svg>
            Create Agent
          </Link>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03]">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition ${
              tab === t.id ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Agents Tab */}
      {tab === "agents" && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Total Agents" value="8" />
            <StatCard label="Active" value="5" />
            <StatCard label="Total Conversations" value="5,936" />
            <StatCard label="Avg Conversion" value="13.6%" />
          </div>

          {/* Filters */}
          <div className="flex items-center justify-between">
            <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03]">
              {statusOpts.map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium capitalize transition ${
                    statusFilter === s ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            <PeriodFilter value={period} onChange={setPeriod} />
          </div>

          {/* Table */}
          <div className="rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-ink/[0.04] dark:border-fog/[0.04]">
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Name</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Status</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Channels</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Conversations</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Conversion</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Last Active</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAgents.map((a) => (
                    <tr key={a.id} className="border-b border-ink/[0.02] last:border-0 dark:border-fog/[0.02]">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-deep-violet/[0.06] text-deep-violet">
                            <AgentIcon />
                          </div>
                          <div>
                            <p className="text-[12px] font-medium text-ink dark:text-fog">{a.name}</p>
                            <p className="text-[10px] text-ink/30 dark:text-fog/30">{a.model}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          a.status === "active" ? "bg-emerald-50 text-emerald-600" :
                          a.status === "paused" ? "bg-amber-50 text-amber-600" :
                          "bg-ink/[0.04] text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40"
                        }`}>
                          <span className={`h-1 w-1 rounded-full ${
                            a.status === "active" ? "bg-emerald-500" :
                            a.status === "paused" ? "bg-amber-500" :
                            "bg-ink/30 dark:bg-fog/30"
                          }`} />
                          {a.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {a.channels.length === 0 ? (
                            <span className="text-[10px] text-ink/25 dark:text-fog/25">—</span>
                          ) : (
                            a.channels.map((ch) => (
                              <span key={ch} className="rounded bg-ink/[0.04] px-1.5 py-0.5 text-[9px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                                {ch}
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[12px] text-ink/60 dark:text-fog/60">{a.conversations.toLocaleString()}</td>
                      <td className="px-4 py-3 text-[12px] font-medium text-ink dark:text-fog">{a.conversion}</td>
                      <td className="px-4 py-3 text-[11px] text-ink/40 dark:text-fog/40">{a.lastActive}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button className="rounded p-1 text-ink/30 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/30 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60" title="Edit">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                              <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </button>
                          <button className="rounded p-1 text-ink/30 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/30 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60" title={a.status === "paused" ? "Run" : "Pause"}>
                            {a.status === "paused" ? (
                              <svg viewBox="0 0 16 16" fill="currentColor" className="h-3.5 w-3.5">
                                <path d="M4 2l10 6-10 6V2z" />
                              </svg>
                            ) : (
                              <svg viewBox="0 0 16 16" fill="currentColor" className="h-3.5 w-3.5">
                                <rect x="3" y="2" width="3.5" height="12" rx="1" />
                                <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
                              </svg>
                            )}
                          </button>
                          <button className="rounded p-1 text-ink/30 transition hover:bg-coral/10 hover:text-coral dark:text-fog/30" title="Delete">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                              <path d="M2 4h12M5.33 4V2.67a1.33 1.33 0 011.34-1.34h2.66a1.33 1.33 0 011.34 1.34V4m2 0v9.33a1.33 1.33 0 01-1.34 1.34H4.67a1.33 1.33 0 01-1.34-1.34V4h9.34z" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </button>
                          <button className="rounded p-1 text-ink/30 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/30 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60" title="Duplicate">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                              <rect x="5" y="5" width="9" height="9" rx="1.5" />
                              <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" strokeLinecap="round" />
                            </svg>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Logs Tab */}
      {tab === "logs" && (
        <div className="rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-ink/[0.04] dark:border-fog/[0.04]">
                  <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Timestamp</th>
                  <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Agent</th>
                  <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Channel</th>
                  <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Message Preview</th>
                  <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Status</th>
                  <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Duration</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l, i) => (
                  <tr key={i} className="border-b border-ink/[0.02] last:border-0 dark:border-fog/[0.02]">
                    <td className="px-4 py-2.5 text-[11px] font-mono text-ink/40 dark:text-fog/40">{l.timestamp}</td>
                    <td className="px-4 py-2.5 text-[12px] font-medium text-ink dark:text-fog">{l.agent}</td>
                    <td className="px-4 py-2.5">
                      <span className="rounded bg-ink/[0.04] px-1.5 py-0.5 text-[9px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">{l.channel}</span>
                    </td>
                    <td className="max-w-[240px] truncate px-4 py-2.5 text-[11px] text-ink/50 dark:text-fog/50">{l.preview}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        l.status === "success" ? "bg-emerald-50 text-emerald-600" : "bg-coral/10 text-coral"
                      }`}>
                        <span className={`h-1 w-1 rounded-full ${l.status === "success" ? "bg-emerald-500" : "bg-coral"}`} />
                        {l.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[11px] text-ink/40 dark:text-fog/40">{l.duration}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Analytics Tab */}
      {tab === "analytics" && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Total Conversations" value="5,936" sub="+12% this period" />
            <StatCard label="Active Agents" value="5" sub="of 8 total" />
            <StatCard label="Avg Response Time" value="1.3s" sub="-0.2s improvement" />
            <StatCard label="Conversion Rate" value="13.6%" sub="+2.1% this period" />
          </div>
          <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="mb-3 text-[13px] font-semibold text-ink dark:text-fog">Conversation Volumes</h3>
            <div className="flex items-end gap-1" style={{ height: 160 }}>
              {[35, 52, 28, 65, 78, 42, 88, 55, 70, 45, 82, 60].map((h, i) => (
                <div key={i} className="flex flex-1 flex-col items-center gap-1">
                  <div className="w-full rounded-t bg-gradient-to-t from-deep-violet/25 to-deep-violet/5 transition-all hover:from-deep-violet/40 hover:to-deep-violet/10" style={{ height: `${h}%` }} />
                  <span className="text-[9px] text-ink/25 dark:text-fog/25">{["J","F","M","A","M","J","J","A","S","O","N","D"][i]}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-ink/[0.04] dark:border-fog/[0.04] pt-3">
              <div>
                <p className="text-[18px] font-bold text-ink dark:text-fog">5,936</p>
                <p className="text-[10px] text-ink/35 dark:text-fog/35">total conversations</p>
              </div>
              <span className="text-[11px] font-semibold text-emerald-600">+12%</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
