"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import { useState } from "react";

type Period = "day" | "week" | "month" | "year";

const periods: { label: string; value: Period }[] = [
  { label: "Day", value: "day" },
  { label: "Week", value: "week" },
  { label: "Month", value: "month" },
  { label: "Year", value: "year" },
];

const automations = [
  { id: 1, name: "Welcome series", status: "active", triggers: 1240, conversion: "12%", created: "2026-01-15", lastRun: "2 min ago", steps: 4 },
  { id: 2, name: "Cart recovery", status: "active", triggers: 890, conversion: "8%", created: "2026-02-01", lastRun: "15 min ago", steps: 3 },
  { id: 3, name: "Lead nurture", status: "paused", triggers: 456, conversion: "15%", created: "2026-01-20", lastRun: "3 days ago", steps: 6 },
  { id: 4, name: "Post-purchase follow-up", status: "active", triggers: 2100, conversion: "22%", created: "2025-12-10", lastRun: "5 min ago", steps: 5 },
  { id: 5, name: "Re-engagement campaign", status: "draft", triggers: 0, conversion: "—", created: "2026-03-28", lastRun: "Never", steps: 2 },
  { id: 6, name: "Appointment reminder", status: "active", triggers: 320, conversion: "18%", created: "2026-02-14", lastRun: "1 hour ago", steps: 3 },
  { id: 7, name: "Feedback request", status: "active", triggers: 780, conversion: "9%", created: "2026-01-05", lastRun: "30 min ago", steps: 2 },
  { id: 8, name: "Upsell offer", status: "paused", triggers: 150, conversion: "5%", created: "2026-03-01", lastRun: "1 week ago", steps: 4 },
];

const stats = [
  { label: "Total Automations", value: "8", change: "+2 this month", up: true },
  { label: "Active", value: "5", change: "62.5% of total", up: true },
  { label: "Total Triggers", value: "5,936", change: "+12.3% vs last period", up: true },
  { label: "Avg Conversion", value: "13.6%", change: "+2.1% vs last period", up: true },
];

export default function AutomationsPage() {
  const [period, setPeriod] = useState<Period>("week");
  const [filter, setFilter] = useState<"all" | "active" | "paused" | "draft">("all");

  const filtered = automations.filter((a) => filter === "all" || a.status === filter);

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <Breadcrumbs items={[{ label: "Automations" }]} />
          <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Automation Overview</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Monitor and manage your automation workflows.</p>
        </div>
        <button className="flex h-9 items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-deep-violet to-magenta px-4 text-[13px] font-semibold text-white transition hover:shadow-md active:scale-[0.98]">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Create Automation
        </button>
      </div>

      {/* Stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <p className="text-[11px] font-medium uppercase tracking-wider text-ink/35 dark:text-fog/35">{s.label}</p>
            <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{s.value}</p>
            <p className={`mt-0.5 text-[11px] font-medium ${s.up ? "text-emerald-600" : "text-coral"}`}>{s.change}</p>
          </div>
        ))}
      </div>

      {/* Filters + Period */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 rounded-lg border border-ink/[0.06] bg-white p-0.5 dark:border-fog/[0.06] dark:bg-ink">
          {(["all", "active", "paused", "draft"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition ${
                filter === f
                  ? "bg-deep-violet text-white shadow-sm"
                  : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex gap-1 rounded-lg border border-ink/[0.06] bg-white p-0.5 dark:border-fog/[0.06] dark:bg-ink">
          {periods.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition ${
                period === p.value
                  ? "bg-ink text-white dark:bg-fog dark:text-ink"
                  : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-ink/[0.04] dark:border-fog/[0.04]">
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Name</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Status</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Triggers</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Conversion</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Steps</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Last Run</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Created</th>
                <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id} className="border-b border-ink/[0.02] last:border-0 dark:border-fog/[0.02] transition hover:bg-ink/[0.02] dark:hover:bg-fog/[0.02]">
                  <td className="px-4 py-3">
                    <p className="text-[13px] font-medium text-ink dark:text-fog">{a.name}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      a.status === "active" ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20" :
                      a.status === "paused" ? "bg-amber-50 text-amber-600 dark:bg-amber-900/20" :
                      "bg-ink/[0.04] text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40"
                    }`}>
                      <span className={`h-1 w-1 rounded-full ${
                        a.status === "active" ? "bg-emerald-500" :
                        a.status === "paused" ? "bg-amber-500" :
                        "bg-ink/40 dark:bg-fog/40"
                      }`} />
                      {a.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[12px] text-ink/60 dark:text-fog/60">{a.triggers.toLocaleString()}</td>
                  <td className="px-4 py-3 text-[12px] font-medium text-ink dark:text-fog">{a.conversion}</td>
                  <td className="px-4 py-3 text-[12px] text-ink/60 dark:text-fog/60">{a.steps}</td>
                  <td className="px-4 py-3 text-[12px] text-ink/40 dark:text-fog/40">{a.lastRun}</td>
                  <td className="px-4 py-3 text-[12px] text-ink/40 dark:text-fog/40">{a.created}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button className="flex h-7 items-center justify-center rounded-md px-2 text-[11px] text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/40 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60">
                        Edit
                      </button>
                      <button className="flex h-7 items-center justify-center rounded-md px-2 text-[11px] text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/40 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60">
                        {a.status === "active" ? "Pause" : "Run"}
                      </button>
                      <button className="flex h-7 items-center justify-center rounded-md px-2 text-[11px] text-coral/60 transition hover:bg-coral/5 hover:text-coral">
                        Delete
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
