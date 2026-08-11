"use client";

import { use } from "react";
import Link from "next/link";
import { ChannelLogo } from "@/components/dashboard/ChannelLogos";

const leads = [
  { id: "1", name: "Sarah Chen", email: "sarah@example.com", interest: "Pro Plan", score: 92, status: "hot", lastInteraction: "2m ago", source: "Inbound message" },
  { id: "2", name: "Marcus Rivera", email: "marcus@corp.io", interest: "Enterprise", score: 85, status: "hot", lastInteraction: "18m ago", source: "Outbound call" },
  { id: "3", name: "Elena Kowalski", email: "elena@startup.co", interest: "Starter Plan", score: 68, status: "warm", lastInteraction: "1h ago", source: "Inbound message" },
  { id: "4", name: "James Okafor", email: "james@agency.com", interest: "Pro Plan", score: 78, status: "warm", lastInteraction: "2h ago", source: "Outbound call" },
  { id: "5", name: "Aisha Patel", email: "aisha@tech.dev", interest: "Enterprise", score: 45, status: "cold", lastInteraction: "3h ago", source: "Inbound message" },
  { id: "6", name: "Olivia Thompson", email: "olivia@brand.com", interest: "Starter Plan", score: 55, status: "cold", lastInteraction: "5h ago", source: "Inbound message" },
];

const statusColors: Record<string, string> = {
  hot: "bg-coral/10 text-coral",
  warm: "bg-amber-100 text-amber-700",
  cold: "bg-sky-100 text-sky-600",
};

export default function LeadsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      {/* Header */}
      <div className="border-b border-deep-violet/10 bg-white px-4 sm:px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ChannelLogo channel={slug} className="h-8 w-8" />
            <div>
              <h1 className="text-[18px] sm:text-[20px] font-bold text-ink">Leads</h1>
              <p className="text-[12px] text-ink/60">Potential customers from this channel</p>
            </div>
          </div>
          <div className="flex gap-2">
            <span className="rounded-full bg-coral/10 px-2.5 py-1 text-[11px] font-bold text-coral">2 Hot</span>
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold text-amber-700">2 Warm</span>
            <span className="rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-bold text-sky-600">2 Cold</span>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-3xl space-y-2">
          {leads.map((lead) => (
            <Link
              key={lead.id}
              href={`/dashboard/channels/${slug}/leads/${lead.id}`}
              className="flex items-center gap-3 rounded-xl border-2 border-white bg-white/80 p-3 sm:p-4 transition hover:bg-white"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[14px] font-bold text-white">
                {lead.name.split(" ").map(n => n[0]).join("")}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold text-ink">{lead.name}</span>
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${statusColors[lead.status]}`}>
                    {lead.status.toUpperCase()}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-ink/50">
                  <span>{lead.email}</span>
                  <span>&middot;</span>
                  <span>{lead.interest}</span>
                </div>
              </div>

              <div className="text-right shrink-0">
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 w-12 rounded-full bg-ink/10 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        lead.score >= 80 ? "bg-coral" : lead.score >= 60 ? "bg-amber-400" : "bg-sky-400"
                      }`}
                      style={{ width: `${lead.score}%` }}
                    />
                  </div>
                  <span className="text-[11px] font-semibold text-ink/60">{lead.score}</span>
                </div>
                <span className="text-[10px] text-ink/35">{lead.lastInteraction}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-deep-violet/10 bg-white px-4 sm:px-6 py-3 sm:py-4">
        <Link
          href={`/dashboard/channels/${slug}`}
          className="rounded-xl border-2 border-ink/10 px-4 sm:px-5 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] hover:text-ink"
        >
          Back
        </Link>
        <button className="rounded-xl bg-deep-violet px-5 sm:px-6 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 hover:shadow-lg active:scale-[0.98]">
          Export Leads
        </button>
      </div>
    </div>
  );
}
