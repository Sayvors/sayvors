"use client";

import { useState } from "react";

interface AdsTabProps {
  channelSlug: string;
  channelName: string;
}

const campaignsData = [
  { id: "1", name: "Summer Sale 2024", type: "promotional", status: "active", sent: 1247, delivered: 1198, opened: 845, clicked: 312, conversion: 25, budget: 2400, spent: 1820, createdAt: "2 days ago", targetAudience: "All Contacts", message: "Get 30% off on all Pro plans this summer!" },
  { id: "2", name: "Product Launch", type: "announcement", status: "completed", sent: 3200, delivered: 3102, opened: 2145, clicked: 876, conversion: 27, budget: 5000, spent: 4850, createdAt: "1 week ago", targetAudience: "Leads Only", message: "Introducing our new AI-powered features!" },
  { id: "3", name: "Re-engagement", type: "re-engagement", status: "paused", sent: 890, delivered: 845, opened: 520, clicked: 180, conversion: 21, budget: 1500, spent: 980, createdAt: "3 days ago", targetAudience: "Cold Leads", message: "We miss you! Come back and see what's new." },
  { id: "4", name: "Holiday Promotions", type: "promotional", status: "draft", sent: 0, delivered: 0, opened: 0, clicked: 0, conversion: 0, budget: 3000, spent: 0, createdAt: "Just now", targetAudience: "All Contacts", message: "Special holiday offers just for you!" },
];

const statusColors: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  completed: "bg-sky-100 text-sky-600",
  paused: "bg-amber-100 text-amber-700",
  draft: "bg-ink/10 text-ink/50",
};

const typeColors: Record<string, string> = {
  promotional: "bg-coral/10 text-coral",
  announcement: "bg-sky-100 text-sky-600",
  "follow-up": "bg-amber-100 text-amber-700",
  "re-engagement": "bg-deep-violet/10 text-deep-violet",
};

export default function AdsTab({ channelSlug, channelName }: AdsTabProps) {
  const [selectedCampaign, setSelectedCampaign] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newType, setNewType] = useState("promotional");
  const [newAudience, setNewAudience] = useState("all");
  const campaign = selectedCampaign ? campaignsData.find((c) => c.id === selectedCampaign) : null;

  if (showNewForm) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="p-4 sm:p-6">
          <div className="mx-auto max-w-2xl space-y-6">
            <button
              onClick={() => setShowNewForm(false)}
              className="flex items-center gap-1.5 text-[12px] font-semibold text-ink/50 transition hover:text-deep-violet"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back to Campaigns
            </button>

            <h2 className="text-[15px] font-bold text-ink">New Campaign</h2>

            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5 space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Campaign Name</label>
                <input
                  type="text"
                  placeholder="e.g., Summer Sale 2024"
                  className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                />
              </div>

              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Type</label>
                <div className="flex gap-2">
                  {["promotional", "announcement", "follow-up", "re-engagement"].map((type) => (
                    <button
                      key={type}
                      onClick={() => setNewType(type)}
                      className={`rounded-lg px-3 py-1.5 text-[11px] font-semibold transition ${
                        newType === type
                          ? "bg-deep-violet text-white"
                          : "bg-ink/[0.04] text-ink/60 hover:bg-ink/[0.08]"
                      }`}
                    >
                      {type.charAt(0).toUpperCase() + type.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Target Audience</label>
                <div className="space-y-2">
                  {[
                    { id: "all", label: "All Contacts", desc: "Everyone on this channel" },
                    { id: "leads", label: "Leads Only", desc: "Potential customers" },
                    { id: "hot", label: "Hot Leads", desc: "High-intent prospects" },
                  ].map((option) => (
                    <label
                      key={option.id}
                      className={`flex items-center gap-3 rounded-xl border-2 p-3 cursor-pointer transition ${
                        newAudience === option.id
                          ? "border-deep-violet bg-deep-violet/[0.04]"
                          : "border-white hover:bg-ink/[0.02]"
                      }`}
                    >
                      <input
                        type="radio"
                        name="audience"
                        value={option.id}
                        checked={newAudience === option.id}
                        onChange={(e) => setNewAudience(e.target.value)}
                        className="h-4 w-4 accent-deep-violet"
                      />
                      <div>
                        <p className="text-[13px] font-semibold text-ink">{option.label}</p>
                        <p className="text-[11px] text-ink/50">{option.desc}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Budget ($)</label>
                <input
                  type="number"
                  placeholder="0.00"
                  className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                />
              </div>

              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Message</label>
                <textarea
                  rows={4}
                  placeholder="Write your campaign message..."
                  className="w-full rounded-xl border-2 border-white bg-white px-4 py-3 text-[13px] text-ink outline-none transition placeholder:text-ink/35 focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                />
                <p className="mt-1 text-[10px] text-ink/35">Supports {"{name}"}, {"{company}"}</p>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setShowNewForm(false)}
                className="flex-1 rounded-xl border-2 border-ink/10 px-4 py-2.5 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]"
              >
                Save as Draft
              </button>
              <button className="flex-1 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90">
                Launch Campaign
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (campaign) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="p-4 sm:p-6">
          <div className="mx-auto max-w-2xl space-y-6">
            <button
              onClick={() => setSelectedCampaign(null)}
              className="flex items-center gap-1.5 text-[12px] font-semibold text-ink/50 transition hover:text-deep-violet"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back to Campaigns
            </button>

            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-[18px] font-bold text-ink">{campaign.name}</h2>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${statusColors[campaign.status]}`}>
                    {campaign.status.toUpperCase()}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${typeColors[campaign.type]}`}>
                    {campaign.type}
                  </span>
                </div>
                <p className="text-[12px] text-ink/50 mt-0.5">Created {campaign.createdAt} &middot; Target: {campaign.targetAudience}</p>
              </div>
              <div className="flex gap-2">
                {campaign.status === "draft" && (
                  <button className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white">Launch</button>
                )}
                {campaign.status === "active" && (
                  <button className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/60">Pause</button>
                )}
                {campaign.status === "paused" && (
                  <button className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white">Resume</button>
                )}
              </div>
            </div>

            {/* Message preview */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[10px] text-ink/40 mb-2">Message</p>
              <p className="text-[13px] text-ink/70">{campaign.message}</p>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-xl border-2 border-white bg-white/80 p-3 text-center">
                <p className="text-[20px] font-bold text-ink">{campaign.sent.toLocaleString()}</p>
                <p className="text-[10px] text-ink/40">Sent</p>
              </div>
              <div className="rounded-xl border-2 border-white bg-white/80 p-3 text-center">
                <p className="text-[20px] font-bold text-ink">{campaign.delivered.toLocaleString()}</p>
                <p className="text-[10px] text-ink/40">Delivered</p>
              </div>
              <div className="rounded-xl border-2 border-white bg-white/80 p-3 text-center">
                <p className="text-[20px] font-bold text-ink">{campaign.opened.toLocaleString()}</p>
                <p className="text-[10px] text-ink/40">Opened</p>
              </div>
              <div className="rounded-xl border-2 border-white bg-white/80 p-3 text-center">
                <p className="text-[20px] font-bold text-emerald-600">{campaign.conversion}%</p>
                <p className="text-[10px] text-ink/40">Conversion</p>
              </div>
            </div>

            {/* Budget */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[11px] text-ink/50">Budget Progress</p>
                <p className="text-[12px] font-semibold text-ink">${campaign.spent.toLocaleString()} / ${campaign.budget.toLocaleString()}</p>
              </div>
              <div className="h-2 rounded-full bg-ink/10 overflow-hidden">
                <div
                  className="h-full rounded-full bg-deep-violet"
                  style={{ width: `${(campaign.spent / campaign.budget) * 100}%` }}
                />
              </div>
            </div>

            {/* Performance breakdown */}
            <div className="rounded-xl border-2 border-white bg-white/80 p-4">
              <p className="text-[11px] text-ink/50 mb-3">Performance Breakdown</p>
              <div className="space-y-3">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-ink/60">Delivery Rate</span>
                    <span className="text-[11px] font-semibold text-ink">{campaign.sent > 0 ? ((campaign.delivered / campaign.sent) * 100).toFixed(1) : 0}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-ink/10 overflow-hidden">
                    <div className="h-full rounded-full bg-emerald-400" style={{ width: `${campaign.sent > 0 ? (campaign.delivered / campaign.sent) * 100 : 0}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-ink/60">Open Rate</span>
                    <span className="text-[11px] font-semibold text-ink">{campaign.delivered > 0 ? ((campaign.opened / campaign.delivered) * 100).toFixed(1) : 0}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-ink/10 overflow-hidden">
                    <div className="h-full rounded-full bg-sky-400" style={{ width: `${campaign.delivered > 0 ? (campaign.opened / campaign.delivered) * 100 : 0}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-ink/60">Click Rate</span>
                    <span className="text-[11px] font-semibold text-ink">{campaign.opened > 0 ? ((campaign.clicked / campaign.opened) * 100).toFixed(1) : 0}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-ink/10 overflow-hidden">
                    <div className="h-full rounded-full bg-deep-violet" style={{ width: `${campaign.opened > 0 ? (campaign.clicked / campaign.opened) * 100 : 0}%` }} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[15px] font-bold text-ink">Ads & Campaigns</h2>
            <p className="text-[13px] text-ink/60">Manage campaigns for {channelName}</p>
          </div>
          <button
            onClick={() => setShowNewForm(true)}
            className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
          >
            + New Campaign
          </button>
        </div>

        <div className="space-y-3">
          {campaignsData.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedCampaign(c.id)}
              className="w-full rounded-xl border-2 border-white bg-white/80 p-4 text-left transition hover:bg-white"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-[14px] font-bold text-ink">{c.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${statusColors[c.status]}`}>
                      {c.status.toUpperCase()}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${typeColors[c.type]}`}>
                      {c.type}
                    </span>
                  </div>
                  <p className="text-[11px] text-ink/50 mt-0.5">Target: {c.targetAudience} &middot; Created {c.createdAt}</p>
                </div>
                <div className="text-right">
                  <p className="text-[12px] font-semibold text-ink">${c.spent.toLocaleString()} / ${c.budget.toLocaleString()}</p>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-4 gap-2">
                <div className="text-center">
                  <p className="text-[14px] font-bold text-ink">{c.sent.toLocaleString()}</p>
                  <p className="text-[9px] text-ink/40">Sent</p>
                </div>
                <div className="text-center">
                  <p className="text-[14px] font-bold text-ink">{c.opened.toLocaleString()}</p>
                  <p className="text-[9px] text-ink/40">Opened</p>
                </div>
                <div className="text-center">
                  <p className="text-[14px] font-bold text-ink">{c.clicked.toLocaleString()}</p>
                  <p className="text-[9px] text-ink/40">Clicked</p>
                </div>
                <div className="text-center">
                  <p className="text-[14px] font-bold text-emerald-600">{c.conversion}%</p>
                  <p className="text-[9px] text-ink/40">Conv.</p>
                </div>
              </div>

              <div className="mt-3 h-1.5 rounded-full bg-ink/10 overflow-hidden">
                <div
                  className="h-full rounded-full bg-deep-violet"
                  style={{ width: `${c.budget > 0 ? (c.spent / c.budget) * 100 : 0}%` }}
                />
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
