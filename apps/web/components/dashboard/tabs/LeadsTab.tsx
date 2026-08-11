"use client";

import { useState } from "react";
import { ChannelLogo } from "../ChannelLogos";

interface LeadsTabProps {
  channelSlug: string;
  channelName: string;
}

const leadsData = [
  { id: "1", name: "Sarah Chen", email: "sarah@example.com", phone: "+1 (555) 123-4567", interest: "Pro Plan", score: 92, status: "hot", lastInteraction: "2m ago", source: "Inbound message", tags: ["enterprise", "high-intent", "referral"], notes: ["Interested in API access", "Budget approved for Q3"], conversations: [{ date: "2m ago", summary: "Asked about Pro plan pricing", sentiment: "Positive" }] },
  { id: "2", name: "Marcus Rivera", email: "marcus@corp.io", phone: "+1 (555) 234-5678", interest: "Enterprise", score: 85, status: "hot", lastInteraction: "18m ago", source: "Outbound call", tags: ["enterprise", "decision-maker"], notes: ["CTO at mid-size company", "Decision expected by end of month"], conversations: [{ date: "18m ago", summary: "Follow-up call about deployment", sentiment: "Positive" }] },
  { id: "3", name: "Elena Kowalski", email: "elena@startup.co", phone: "+48 123 456 789", interest: "Starter Plan", score: 68, status: "warm", lastInteraction: "1h ago", source: "Inbound message", tags: ["startup", "small-team"], notes: ["Runs a 5-person startup", "Price sensitive"], conversations: [{ date: "1h ago", summary: "Asked about Starter plan limitations", sentiment: "Neutral" }] },
  { id: "4", name: "James Okafor", email: "james@agency.com", phone: "+1 (555) 345-6789", interest: "Pro Plan", score: 78, status: "warm", lastInteraction: "2h ago", source: "Outbound call", tags: ["agency", "growth"], notes: ["Marketing agency", "Needs team features"], conversations: [{ date: "2h ago", summary: "Discussed team collaboration features", sentiment: "Interested" }] },
  { id: "5", name: "Aisha Patel", email: "aisha@tech.dev", phone: "+91 98765 43210", interest: "Enterprise", score: 45, status: "cold", lastInteraction: "3h ago", source: "Inbound message", tags: ["tech", "exploring"], notes: ["Just exploring options", "No timeline"], conversations: [{ date: "3h ago", summary: "Initial inquiry about features", sentiment: "Neutral" }] },
  { id: "6", name: "Olivia Thompson", email: "olivia@brand.com", phone: "+44 7890 123456", interest: "Starter Plan", score: 55, status: "cold", lastInteraction: "5h ago", source: "Inbound message", tags: ["brand", "small-team"], notes: ["Small brand account", "Budget constraints"], conversations: [{ date: "5h ago", summary: "Asked about pricing options", sentiment: "Neutral" }] },
];

const statusColors: Record<string, string> = {
  hot: "bg-coral/10 text-coral",
  warm: "bg-amber-100 text-amber-700",
  cold: "bg-sky-100 text-sky-600",
};

export default function LeadsTab({ channelSlug, channelName }: LeadsTabProps) {
  const [selectedLead, setSelectedLead] = useState<string | null>(null);
  const lead = selectedLead ? leadsData.find((l) => l.id === selectedLead) : null;

  if (lead) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="p-4 sm:p-6">
          <div className="mx-auto max-w-2xl space-y-6">
            {/* Back button */}
            <button
              onClick={() => setSelectedLead(null)}
              className="flex items-center gap-1.5 text-[12px] font-semibold text-ink/50 transition hover:text-deep-violet"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back to Leads
            </button>

            {/* Lead header */}
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-[20px] font-bold text-white shadow-md">
                {lead.name.split(" ").map(n => n[0]).join("")}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="text-[18px] font-bold text-ink">{lead.name}</h2>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${statusColors[lead.status]}`}>
                    {lead.status.toUpperCase()}
                  </span>
                </div>
                <p className="text-[12px] text-ink/50">{lead.email} &middot; {lead.phone}</p>
              </div>
            </div>

            {/* Score */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[11px] text-ink/50 mb-1">Lead Score</p>
              <div className="flex items-center gap-3">
                <span className="text-[28px] font-bold text-ink">{lead.score}</span>
                <div className="flex-1 h-2 rounded-full bg-ink/10 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${lead.score >= 80 ? "bg-coral" : lead.score >= 60 ? "bg-amber-400" : "bg-sky-400"}`}
                    style={{ width: `${lead.score}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Info grid */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border-2 border-white bg-white/80 p-3">
                <p className="text-[10px] text-ink/40">Source</p>
                <p className="text-[12px] font-semibold text-ink">{lead.source}</p>
              </div>
              <div className="rounded-xl border-2 border-white bg-white/80 p-3">
                <p className="text-[10px] text-ink/40">Interest</p>
                <p className="text-[12px] font-semibold text-ink">{lead.interest}</p>
              </div>
            </div>

            {/* Tags */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[10px] text-ink/40 mb-2">Tags</p>
              <div className="flex flex-wrap gap-1.5">
                {lead.tags.map((tag) => (
                  <span key={tag} className="rounded-lg bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet/70">
                    {tag}
                  </span>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[10px] text-ink/40 mb-2">Notes</p>
              <div className="space-y-1.5">
                {lead.notes.map((note, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet/40" />
                    <span className="text-[12px] text-ink/70">{note}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Conversation */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[10px] text-ink/40 mb-2">Recent Conversation</p>
              <div className="flex items-start gap-3 rounded-lg bg-ink/[0.02] p-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-deep-violet/10">
                  <ChannelLogo channel={channelSlug} className="h-3.5 w-3.5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-semibold text-ink">{lead.conversations[0].summary}</span>
                    <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-bold text-emerald-700">
                      {lead.conversations[0].sentiment}
                    </span>
                  </div>
                  <span className="text-[10px] text-ink/35">{lead.conversations[0].date}</span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-2">
              <button className="flex-1 rounded-xl border-2 border-ink/10 px-4 py-2.5 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]">
                Edit Lead
              </button>
              <button className="flex-1 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90">
                Convert to Customer
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-[15px] font-bold text-ink">Leads</h2>
              <p className="text-[13px] text-ink/60">Potential customers from {channelName}</p>
            </div>
            <div className="flex gap-2">
              <span className="rounded-full bg-coral/10 px-2.5 py-1 text-[11px] font-bold text-coral">2 Hot</span>
              <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold text-amber-700">2 Warm</span>
              <span className="rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-bold text-sky-600">2 Cold</span>
            </div>
          </div>

          <div className="space-y-2">
            {leadsData.map((l) => (
              <button
                key={l.id}
                onClick={() => setSelectedLead(l.id)}
                className="flex w-full items-center gap-3 rounded-xl border-2 border-white bg-white/80 p-3 sm:p-4 text-left transition hover:bg-white"
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[14px] font-bold text-white">
                  {l.name.split(" ").map(n => n[0]).join("")}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-ink">{l.name}</span>
                    <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${statusColors[l.status]}`}>
                      {l.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-ink/50">
                    <span>{l.interest}</span>
                    <span>&middot;</span>
                    <span>{l.source}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 w-12 rounded-full bg-ink/10 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${l.score >= 80 ? "bg-coral" : l.score >= 60 ? "bg-amber-400" : "bg-sky-400"}`}
                        style={{ width: `${l.score}%` }}
                      />
                    </div>
                    <span className="text-[11px] font-semibold text-ink/60">{l.score}</span>
                  </div>
                  <span className="text-[10px] text-ink/35">{l.lastInteraction}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-1 text-[15px] font-bold text-ink">Lead Summary</h2>
          <p className="mb-4 text-[13px] text-ink/60">Conversion metrics for this channel.</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Total Leads", value: "247", change: "+18%" },
              { label: "Converted", value: "42", change: "+8%" },
              { label: "Avg Score", value: "72", change: "+5" },
              { label: "Pipeline Value", value: "$18.4K", change: "+22%" },
            ].map((stat) => (
              <div key={stat.label} className="rounded-xl border-2 border-white bg-white/80 p-3">
                <p className="text-[11px] text-ink/50">{stat.label}</p>
                <p className="text-[18px] font-bold text-ink">{stat.value}</p>
                <p className="text-[10px] font-semibold text-emerald-600">{stat.change}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
