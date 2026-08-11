"use client";

import { use } from "react";
import Link from "next/link";
import { ChannelLogo } from "@/components/dashboard/ChannelLogos";

const leadsData: Record<string, { name: string; email: string; phone: string; interest: string; score: number; status: string; source: string; joinedDate: string; lastSeen: string; tags: string[]; notes: string[]; conversations: { id: string; date: string; summary: string; sentiment: string }[] }> = {
  "1": {
    name: "Sarah Chen",
    email: "sarah@example.com",
    phone: "+1 (555) 123-4567",
    interest: "Pro Plan",
    score: 92,
    status: "hot",
    source: "Inbound message",
    joinedDate: "2 days ago",
    lastSeen: "2 minutes ago",
    tags: ["enterprise", "high-intent", "referral"],
    notes: [
      "Interested in API access and team features",
      "Currently using competitor product",
      "Budget approved for Q3 purchase",
    ],
    conversations: [
      { id: "1", date: "2m ago", summary: "Asked about Pro plan pricing and API limits", sentiment: "Positive" },
      { id: "2", date: "1h ago", summary: "Initial inquiry about enterprise features", sentiment: "Interested" },
    ],
  },
  "2": {
    name: "Marcus Rivera",
    email: "marcus@corp.io",
    phone: "+1 (555) 234-5678",
    interest: "Enterprise",
    score: 85,
    status: "hot",
    source: "Outbound call",
    joinedDate: "5 days ago",
    lastSeen: "18 minutes ago",
    tags: ["enterprise", "decision-maker"],
    notes: [
      "CTO at mid-size company",
      "Looking for custom integration",
      "Decision expected by end of month",
    ],
    conversations: [
      { id: "1", date: "18m ago", summary: "Follow-up call about deployment options", sentiment: "Positive" },
    ],
  },
  "3": {
    name: "Elena Kowalski",
    email: "elena@startup.co",
    phone: "+48 123 456 789",
    interest: "Starter Plan",
    score: 68,
    status: "warm",
    source: "Inbound message",
    joinedDate: "1 week ago",
    lastSeen: "1 hour ago",
    tags: ["startup", "small-team"],
    notes: [
      "Runs a 5-person startup",
      "Price sensitive but needs automation",
    ],
    conversations: [
      { id: "1", date: "1h ago", summary: "Asked about Starter plan limitations", sentiment: "Neutral" },
    ],
  },
};

const statusColors: Record<string, string> = {
  hot: "bg-coral/10 text-coral",
  warm: "bg-amber-100 text-amber-700",
  cold: "bg-sky-100 text-sky-600",
};

export default function LeadDetailPage({ params }: { params: Promise<{ slug: string; leadId: string }> }) {
  const { slug, leadId } = use(params);
  const lead = leadsData[leadId] || leadsData["1"];

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      {/* Header */}
      <div className="border-b border-deep-violet/10 bg-white px-4 sm:px-6 py-4">
        <div className="flex items-center gap-3 sm:gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-[18px] font-bold text-white shadow-md">
            {lead.name.split(" ").map(n => n[0]).join("")}
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-[18px] sm:text-[20px] font-bold text-ink">{lead.name}</h1>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${statusColors[lead.status]}`}>
                {lead.status.toUpperCase()}
              </span>
            </div>
            <p className="text-[12px] text-ink/60">{lead.email} &middot; {lead.phone}</p>
          </div>
          <div className="flex gap-2">
            <button className="rounded-xl border-2 border-ink/10 px-4 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]">
              Edit
            </button>
            <button className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90">
              Convert to Customer
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-3xl space-y-6">
          {/* Score & Info */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[11px] text-ink/50 mb-1">Lead Score</p>
              <div className="flex items-center gap-3">
                <span className="text-[28px] font-bold text-ink">{lead.score}</span>
                <div className="flex-1 h-2 rounded-full bg-ink/10 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      lead.score >= 80 ? "bg-coral" : lead.score >= 60 ? "bg-amber-400" : "bg-sky-400"
                    }`}
                    style={{ width: `${lead.score}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="rounded-xl border-2 border-white bg-white/80 p-4 space-y-2">
              <div className="flex justify-between">
                <span className="text-[11px] text-ink/50">Source</span>
                <span className="text-[12px] font-semibold text-ink">{lead.source}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[11px] text-ink/50">Interest</span>
                <span className="text-[12px] font-semibold text-ink">{lead.interest}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[11px] text-ink/50">Last Seen</span>
                <span className="text-[12px] font-semibold text-ink">{lead.lastSeen}</span>
              </div>
            </div>
          </div>

          {/* Tags */}
          <div className="rounded-xl border-2 border-white bg-white/80 p-4">
            <p className="text-[11px] text-ink/50 mb-2">Tags</p>
            <div className="flex flex-wrap gap-1.5">
              {lead.tags.map((tag) => (
                <span key={tag} className="rounded-lg bg-deep-violet/10 px-2.5 py-1 text-[10px] font-semibold text-deep-violet/70">
                  {tag}
                </span>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div className="rounded-xl border-2 border-white bg-white/80 p-4">
            <p className="text-[11px] text-ink/50 mb-2">Notes</p>
            <div className="space-y-2">
              {lead.notes.map((note, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet/40" />
                  <span className="text-[12px] text-ink/70">{note}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Conversation History */}
          <div className="rounded-xl border-2 border-white bg-white/80 p-4">
            <p className="text-[11px] text-ink/50 mb-3">Recent Conversations</p>
            <div className="space-y-2">
              {lead.conversations.map((conv) => (
                <div key={conv.id} className="flex items-start gap-3 rounded-lg bg-ink/[0.02] p-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-deep-violet/10">
                    <ChannelLogo channel={slug} className="h-4 w-4" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] font-semibold text-ink">{conv.summary}</span>
                      <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-bold text-emerald-700">
                        {conv.sentiment}
                      </span>
                    </div>
                    <span className="text-[10px] text-ink/35">{conv.date}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-deep-violet/10 bg-white px-4 sm:px-6 py-3 sm:py-4">
        <Link
          href={`/dashboard/channels/${slug}/leads`}
          className="rounded-xl border-2 border-ink/10 px-4 sm:px-5 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] hover:text-ink"
        >
          Back to Leads
        </Link>
        <button className="rounded-xl bg-deep-violet px-5 sm:px-6 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 hover:shadow-lg active:scale-[0.98]">
          Send Message
        </button>
      </div>
    </div>
  );
}
