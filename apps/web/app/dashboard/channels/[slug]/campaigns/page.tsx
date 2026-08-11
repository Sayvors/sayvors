"use client";

import { use } from "react";
import Link from "next/link";
import { ChannelLogo } from "@/components/dashboard/ChannelLogos";

const campaigns = [
  { id: "1", name: "Summer Sale 2024", status: "active", sent: 1247, delivered: 1198, opened: 845, clicked: 312, conversion: "25%", budget: "$2,400", spent: "$1,820" },
  { id: "2", name: "Product Launch", status: "completed", sent: 3200, delivered: 3102, opened: 2145, clicked: 876, conversion: "27%", budget: "$5,000", spent: "$4,850" },
  { id: "3", name: "Re-engagement Campaign", status: "paused", sent: 890, delivered: 845, opened: 520, clicked: 180, conversion: "21%", budget: "$1,500", spent: "$980" },
  { id: "4", name: "Holiday Promotions", status: "draft", sent: 0, delivered: 0, opened: 0, clicked: 0, conversion: "0%", budget: "$3,000", spent: "$0" },
];

const statusColors: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  completed: "bg-sky-100 text-sky-600",
  paused: "bg-amber-100 text-amber-700",
  draft: "bg-ink/10 text-ink/50",
};

export default function CampaignsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      {/* Header */}
      <div className="border-b border-deep-violet/10 bg-white px-4 sm:px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ChannelLogo channel={slug} className="h-8 w-8" />
            <div>
              <h1 className="text-[18px] sm:text-[20px] font-bold text-ink">Campaigns</h1>
              <p className="text-[12px] text-ink/60">Manage promotional campaigns for this channel</p>
            </div>
          </div>
          <Link
            href={`/dashboard/channels/${slug}/campaigns/new`}
            className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
          >
            + New Campaign
          </Link>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {campaigns.map((campaign) => (
            <div
              key={campaign.id}
              className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5 transition hover:bg-white"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-[14px] font-bold text-ink">{campaign.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${statusColors[campaign.status]}`}>
                      {campaign.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-4 text-[11px] text-ink/50">
                    <span>Budget: {campaign.budget}</span>
                    <span>Spent: {campaign.spent}</span>
                  </div>
                </div>
                <div className="flex gap-2">
                  {campaign.status === "draft" && (
                    <button className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white">
                      Launch
                    </button>
                  )}
                  {campaign.status === "active" && (
                    <button className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/60">
                      Pause
                    </button>
                  )}
                  {campaign.status === "paused" && (
                    <button className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white">
                      Resume
                    </button>
                  )}
                </div>
              </div>

              {/* Stats */}
              <div className="mt-4 grid grid-cols-4 gap-3">
                <div className="text-center">
                  <p className="text-[16px] font-bold text-ink">{campaign.sent.toLocaleString()}</p>
                  <p className="text-[10px] text-ink/40">Sent</p>
                </div>
                <div className="text-center">
                  <p className="text-[16px] font-bold text-ink">{campaign.delivered.toLocaleString()}</p>
                  <p className="text-[10px] text-ink/40">Delivered</p>
                </div>
                <div className="text-center">
                  <p className="text-[16px] font-bold text-ink">{campaign.opened.toLocaleString()}</p>
                  <p className="text-[10px] text-ink/40">Opened</p>
                </div>
                <div className="text-center">
                  <p className="text-[16px] font-bold text-emerald-600">{campaign.conversion}</p>
                  <p className="text-[10px] text-ink/40">Conversion</p>
                </div>
              </div>

              {/* Progress bar */}
              <div className="mt-3 h-1.5 rounded-full bg-ink/10 overflow-hidden">
                <div
                  className="h-full rounded-full bg-deep-violet"
                  style={{ width: `${(parseFloat(campaign.spent.replace("$", "").replace(",", "")) / parseFloat(campaign.budget.replace("$", "").replace(",", ""))) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
