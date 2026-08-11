"use client";

import { useState } from "react";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";

type Tab = "browse" | "my-agents";
type Category = "All" | "HR" | "Tech" | "Sales" | "Support" | "Lead Qualifier" | "Concierge";

const categories: Category[] = ["All", "HR", "Tech", "Sales", "Support", "Lead Qualifier", "Concierge"];

const systemAgents = [
  { id: "hr-agent", name: "HR Agent", description: "Handles employee inquiries, policies, onboarding", category: "HR", templateCount: 8, gradient: "from-violet-500 to-purple-600" },
  { id: "tech-support-agent", name: "Tech Support Agent", description: "Troubleshoots technical issues, routes tickets", category: "Tech", templateCount: 12, gradient: "from-blue-500 to-indigo-600" },
  { id: "sales-agent", name: "Sales Agent", description: "Qualifies leads, answers product questions, demos", category: "Sales", templateCount: 15, gradient: "from-emerald-500 to-teal-600" },
  { id: "support-agent", name: "Support Agent", description: "Handles customer questions, creates tickets", category: "Support", templateCount: 10, gradient: "from-orange-500 to-red-500" },
  { id: "lead-qualifier", name: "Lead Qualifier", description: "Qualifies inbound leads, collects info, routes to sales", category: "Lead Qualifier", templateCount: 6, gradient: "from-pink-500 to-rose-500" },
  { id: "concierge", name: "Concierge Agent", description: "Warm onboarding, guides new users", category: "Concierge", templateCount: 9, gradient: "from-amber-400 to-orange-500" },
  { id: "faq-bot", name: "FAQ Bot", description: "Answers frequently asked questions from knowledge base", category: "Support", templateCount: 7, gradient: "from-cyan-500 to-blue-500" },
  { id: "cart-recovery-agent", name: "Cart Recovery Agent", description: "Re-engages shoppers who abandoned carts", category: "Sales", templateCount: 5, gradient: "from-fuchsia-500 to-pink-500" },
];

const myAgents = [
  { id: 1, name: "Support Bot", model: "GPT-4o", status: "active", conversations: 1240, lastActive: "2 min ago" },
  { id: 2, name: "Sales Assistant", model: "Gemini 2.5 Flash", status: "active", conversations: 890, lastActive: "15 min ago" },
  { id: 3, name: "Lead Qualifier", model: "Grok-3", status: "paused", conversations: 456, lastActive: "3 days ago" },
  { id: 4, name: "FAQ Bot", model: "DeepSeek Chat", status: "active", conversations: 2100, lastActive: "5 min ago" },
];

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">{label}</p>
      <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{value}</p>
    </div>
  );
}

export default function AgentsPage() {
  const [tab, setTab] = useState<Tab>("browse");
  const [category, setCategory] = useState<Category>("All");

  const filteredAgents = category === "All" ? systemAgents : systemAgents.filter((a) => a.category === category);

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <Breadcrumbs items={[{ label: "Agents" }]} />
          <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Agents Library</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Browse system agents or manage your custom agents.</p>
        </div>
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

      {/* Tabs */}
      <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03]">
        {(["browse", "my-agents"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition ${
              tab === t ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
            }`}
          >
            {t === "browse" ? "Browse" : "My Agents"}
          </button>
        ))}
      </div>

      {/* Browse Tab */}
      {tab === "browse" && (
        <>
          {/* Category Filter */}
          <div className="flex flex-wrap gap-1.5">
            {categories.map((c) => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`rounded-full px-3 py-1.5 text-[11px] font-medium transition ${
                  category === c
                    ? "bg-deep-violet text-white"
                    : "border border-ink/[0.06] text-ink/50 hover:border-ink/[0.1] hover:text-ink dark:border-fog/[0.06] dark:text-fog/50 dark:hover:border-fog/[0.1] dark:hover:text-fog"
                }`}
              >
                {c}
              </button>
            ))}
          </div>

          {/* System Agent Cards */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredAgents.map((agent) => (
              <div key={agent.id} className="group rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-ink/[0.1] hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink dark:hover:border-fog/[0.1]">
                <div className="flex items-start justify-between">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br ${agent.gradient} text-white`}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
                      <rect x="3" y="11" width="18" height="10" rx="2" />
                      <circle cx="12" cy="5" r="2" />
                      <path d="M12 7v4M8 11v4M16 11v4" />
                    </svg>
                  </div>
                  <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[9px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                    {agent.category}
                  </span>
                </div>
                <h3 className="mt-3 text-[13px] font-semibold text-ink dark:text-fog">{agent.name}</h3>
                <p className="mt-1 text-[11px] text-ink/45 dark:text-fog/45 line-clamp-2">{agent.description}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[10px] text-ink/30 dark:text-fog/30">{agent.templateCount} templates</span>
                  <Link
                    href={`/dashboard/agents/create?from=${agent.id}`}
                    className="rounded-lg border border-ink/[0.06] px-2.5 py-1 text-[10px] font-medium text-deep-violet transition hover:bg-deep-violet/[0.04] dark:border-fog/[0.06]"
                  >
                    Use this agent
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* My Agents Tab */}
      {tab === "my-agents" && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Total Agents" value={String(myAgents.length)} />
            <StatCard label="Active" value={String(myAgents.filter((a) => a.status === "active").length)} />
          </div>

          {/* Table */}
          <div className="rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-ink/[0.04] dark:border-fog/[0.04]">
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Name</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Model</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Status</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Conversations</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Last Active</th>
                    <th className="px-4 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ink/35 dark:text-fog/35">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {myAgents.map((a) => (
                    <tr key={a.id} className="border-b border-ink/[0.02] last:border-0 dark:border-fog/[0.02]">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-deep-violet/[0.06] text-deep-violet">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                              <rect x="3" y="11" width="18" height="10" rx="2" />
                              <circle cx="12" cy="5" r="2" />
                              <path d="M12 7v4M8 11v4M16 11v4" />
                            </svg>
                          </div>
                          <span className="text-[12px] font-medium text-ink dark:text-fog">{a.name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[11px] text-ink/40 dark:text-fog/40">{a.model}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          a.status === "active" ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"
                        }`}>
                          <span className={`h-1 w-1 rounded-full ${a.status === "active" ? "bg-emerald-500" : "bg-amber-500"}`} />
                          {a.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[12px] text-ink/60 dark:text-fog/60">{a.conversations.toLocaleString()}</td>
                      <td className="px-4 py-3 text-[11px] text-ink/40 dark:text-fog/40">{a.lastActive}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button className="rounded p-1 text-ink/30 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/30 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60" title="Edit">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                              <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </button>
                          <button className="rounded p-1 text-ink/30 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/30 dark:hover:bg-fog/[0.04] dark:hover:text-fog/60" title="Duplicate">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                              <rect x="5" y="5" width="9" height="9" rx="1.5" />
                              <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" strokeLinecap="round" />
                            </svg>
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
        </>
      )}
    </div>
  );
}
