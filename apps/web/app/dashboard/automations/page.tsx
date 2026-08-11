"use client";

import { useState } from "react";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";

type Period = "day" | "week" | "month" | "year";

const automations = [
  { id: 1, name: "WhatsApp Support", agent: "Support Bot", model: "GPT-4o", channels: ["WhatsApp"], status: "active", conversations: 1240, lastRun: "2 min ago" },
  { id: 2, name: "Instagram Sales", agent: "Sales Agent", model: "Gemini 2.5 Flash", channels: ["Instagram"], status: "active", conversations: 890, lastRun: "15 min ago" },
  { id: 3, name: "Website Widget", agent: "Concierge", model: "Grok-3", channels: ["Web Widget", "WhatsApp"], status: "active", conversations: 456, lastRun: "1 hour ago" },
  { id: 4, name: "Facebook Lead Gen", agent: "Lead Qualifier", model: "DeepSeek Chat", channels: ["Facebook"], status: "paused", conversations: 320, lastRun: "3 days ago" },
  { id: 5, name: "X Auto-Reply", agent: "FAQ Bot", model: "GPT-4o Mini", channels: ["X"], status: "draft", conversations: 0, lastRun: "Never" },
];

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">{label}</p>
      <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{value}</p>
      {sub && <p className="text-[11px] text-ink/30 dark:text-fog/30">{sub}</p>}
    </div>
  );
}

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

export default function AutomationsPage() {
  const [period, setPeriod] = useState<Period>("week");

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <Breadcrumbs items={[{ label: "Automations" }]} />
          <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Automations</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Deploy agents with models across channels.</p>
        </div>
        <Link
          href="/dashboard/automations/create"
          className="flex items-center gap-1.5 rounded-lg bg-deep-violet px-3 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
          Create Automation
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Total Automations" value={String(automations.length)} />
        <StatCard label="Active" value={String(automations.filter((a) => a.status === "active").length)} />
        <StatCard label="Total Conversations" value={automations.reduce((sum, a) => sum + a.conversations, 0).toLocaleString()} />
        <StatCard label="Avg Conversion" value="14.2%" />
      </div>

      {/* Period filter */}
      <div className="flex items-center justify-between">
        <div />
        <PeriodFilter value={period} onChange={setPeriod} />
      </div>

      {/* Table */}
      <div className="rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-ink/[0.04] dark:border-fog/[0.04]">
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Name</th>
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Agent</th>
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Model</th>
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Channels</th>
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Status</th>
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Last Run</th>
                <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Actions</th>
              </tr>
            </thead>
            <tbody>
              {automations.map((a) => (
                <tr key={a.id} className="border-b border-ink/[0.02] last:border-0 dark:border-fog/[0.02]">
                  <td className="px-4 py-3">
                    <span className="text-[12px] font-medium text-ink dark:text-fog">{a.name}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-deep-violet/[0.06] px-2 py-0.5 text-[10px] font-medium text-deep-violet">{a.agent}</span>
                  </td>
                  <td className="px-4 py-3 text-[11px] text-ink/40 dark:text-fog/40">{a.model}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {a.channels.map((ch) => (
                        <span key={ch} className="rounded bg-ink/[0.04] px-1.5 py-0.5 text-[9px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                          {ch}
                        </span>
                      ))}
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
                  <td className="px-4 py-3 text-[11px] text-ink/40 dark:text-fog/40">{a.lastRun}</td>
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
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
