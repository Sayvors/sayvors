"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ChannelLogo } from "@/components/dashboard/ChannelLogos";

export default function NewCampaignPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [campaignName, setCampaignName] = useState("");
  const [campaignType, setCampaignType] = useState("promotional");
  const [targetAudience, setTargetAudience] = useState("all");
  const [budget, setBudget] = useState("");
  const [message, setMessage] = useState("");

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      {/* Header */}
      <div className="border-b border-deep-violet/10 bg-white px-4 sm:px-6 py-4">
        <div className="flex items-center gap-3">
          <ChannelLogo channel={slug} className="h-8 w-8" />
          <div>
            <h1 className="text-[18px] sm:text-[20px] font-bold text-ink">Create Campaign</h1>
            <p className="text-[12px] text-ink/60">Set up a new promotional campaign</p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-2xl space-y-6">
          {/* Campaign Name */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Campaign Details</h2>
            <p className="mb-4 text-[13px] text-ink/60">Basic information about your campaign.</p>
            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5 space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Campaign Name</label>
                <input
                  type="text"
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  placeholder="e.g., Summer Sale 2024"
                  className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Campaign Type</label>
                <div className="flex gap-2">
                  {["promotional", "announcement", "follow-up", "re-engagement"].map((type) => (
                    <button
                      key={type}
                      onClick={() => setCampaignType(type)}
                      className={`rounded-lg px-3 py-1.5 text-[11px] font-semibold transition ${
                        campaignType === type
                          ? "bg-deep-violet text-white"
                          : "bg-ink/[0.04] text-ink/60 hover:bg-ink/[0.08]"
                      }`}
                    >
                      {type.charAt(0).toUpperCase() + type.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* Target Audience */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Target Audience</h2>
            <p className="mb-4 text-[13px] text-ink/60">Who should receive this campaign.</p>
            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5 space-y-3">
              {[
                { id: "all", label: "All Contacts", desc: "Everyone on this channel" },
                { id: "leads", label: "Leads Only", desc: "Potential customers" },
                { id: "hot", label: "Hot Leads", desc: "High-intent prospects" },
                { id: "custom", label: "Custom Segment", desc: "Filter by tags or criteria" },
              ].map((option) => (
                <label
                  key={option.id}
                  className={`flex items-center gap-3 rounded-xl border-2 p-3 cursor-pointer transition ${
                    targetAudience === option.id
                      ? "border-deep-violet bg-deep-violet/[0.04]"
                      : "border-white hover:bg-ink/[0.02]"
                  }`}
                >
                  <input
                    type="radio"
                    name="audience"
                    value={option.id}
                    checked={targetAudience === option.id}
                    onChange={(e) => setTargetAudience(e.target.value)}
                    className="h-4 w-4 accent-deep-violet"
                  />
                  <div>
                    <p className="text-[13px] font-semibold text-ink">{option.label}</p>
                    <p className="text-[11px] text-ink/50">{option.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </section>

          {/* Budget */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Budget</h2>
            <p className="mb-4 text-[13px] text-ink/60">Set your spending limit.</p>
            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5">
              <div className="flex items-center gap-3">
                <span className="text-[18px] font-bold text-ink/40">$</span>
                <input
                  type="number"
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  placeholder="0.00"
                  className="flex-1 rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[18px] font-bold text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                />
              </div>
              <p className="mt-2 text-[11px] text-ink/40">Recommended: $500 - $5,000 based on audience size</p>
            </div>
          </section>

          {/* Message */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Message</h2>
            <p className="mb-4 text-[13px] text-ink/60">The content to send to your audience.</p>
            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5">
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={6}
                placeholder="Write your campaign message here..."
                className="w-full rounded-xl border-2 border-white bg-white px-4 py-3 text-[13px] text-ink outline-none transition placeholder:text-ink/35 focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
              />
              <div className="mt-2 flex items-center justify-between">
                <p className="text-[11px] text-ink/40">Supports variables like {"{name}"}, {"{company}"}</p>
                <p className="text-[11px] text-ink/40">{message.length}/1000</p>
              </div>
            </div>
          </section>

          {/* Schedule */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Schedule</h2>
            <p className="mb-4 text-[13px] text-ink/60">When to send the campaign.</p>
            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5">
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="schedule" defaultChecked className="h-4 w-4 accent-deep-violet" />
                  <span className="text-[13px] font-semibold text-ink">Send Now</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="schedule" className="h-4 w-4 accent-deep-violet" />
                  <span className="text-[13px] font-semibold text-ink">Schedule Later</span>
                </label>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-deep-violet/10 bg-white px-4 sm:px-6 py-3 sm:py-4">
        <Link
          href={`/dashboard/channels/${slug}/campaigns`}
          className="rounded-xl border-2 border-ink/10 px-4 sm:px-5 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] hover:text-ink"
        >
          Back
        </Link>
        <div className="flex gap-2">
          <button className="rounded-xl border-2 border-ink/10 px-5 sm:px-6 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]">
            Save as Draft
          </button>
          <button className="rounded-xl bg-deep-violet px-5 sm:px-6 py-2 sm:py-2.5 text-[12px] sm:text-[13px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 hover:shadow-lg active:scale-[0.98]">
            Launch Campaign
          </button>
        </div>
      </div>
    </div>
  );
}
