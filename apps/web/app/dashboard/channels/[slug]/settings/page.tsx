"use client";

import { useState, useRef, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";
import { channels, agents } from "@/lib/channel-data";
import { ChannelLogo } from "@/components/dashboard/ChannelLogos";

function Dropdown({
  label,
  value,
  options,
  onSelect,
  renderOption,
  renderSelected,
}: {
  label: string;
  value: string;
  options: Record<string, unknown>[];
  onSelect: (id: string) => void;
  renderOption: (opt: Record<string, unknown>) => React.ReactNode;
  renderSelected: (opt: Record<string, unknown>) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.id === value);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <label className="mb-2 block text-[13px] font-semibold text-ink">{label}</label>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 rounded-xl border-2 border-white bg-white/80 px-4 py-3 text-left transition hover:border-deep-violet/20 hover:bg-white"
      >
        {selected && renderSelected(selected)}
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className={`ml-auto h-4 w-4 text-ink/30 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-50 mt-2 overflow-hidden rounded-xl border-2 border-white bg-white shadow-xl">
          <div className="max-h-64 overflow-y-auto py-1">
            {options.map((opt, i) => (
              <button
                key={(opt.id as string) || i}
                onClick={() => { onSelect(opt.id as string); setOpen(false); }}
                className={`flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-deep-violet/[0.04] ${opt.id === value ? "bg-deep-violet/[0.06]" : ""}`}
              >
                {renderOption(opt)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Toggle({
  label,
  desc,
  checked,
  onChange,
}: {
  label: string;
  desc: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5">
      <div>
        <span className="text-[14px] font-semibold text-ink">{label}</span>
        <p className="mt-0.5 text-[12px] text-ink/60">{desc}</p>
      </div>
      <button
        onClick={onChange}
        className={`relative h-7 w-12 shrink-0 rounded-full transition ${checked ? "bg-deep-violet" : "bg-ink/15"}`}
      >
        <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow-md transition-transform ${checked ? "translate-x-[22px]" : "translate-x-0.5"}`} />
      </button>
    </div>
  );
}

export default function ChannelSettingsPage() {
  const params = useParams();
  const slug = params.slug as string;
  const channel = channels.find((c) => c.slug === slug);

  const [selectedAgent, setSelectedAgent] = useState<string>(channel?.connected ? "support-bot" : "");
  const [autoReply, setAutoReply] = useState(true);
  const [workingHours, setWorkingHours] = useState(true);
  const [workingStart, setWorkingStart] = useState("09:00");
  const [workingEnd, setWorkingEnd] = useState("17:00");
  const [offlineMsg, setOfflineMsg] = useState("We're currently offline. Leave a message and we'll get back to you!");
  const [typingIndicator, setTypingIndicator] = useState(true);

  if (!channel) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="text-center">
          <p className="text-[14px] text-ink/60">Channel not found.</p>
          <Link href="/dashboard/channels" className="mt-2 text-[12px] text-deep-violet hover:underline">
            Back to channels
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      {/* Header */}
      <div className="border-b border-deep-violet/10 bg-white px-4 sm:px-6 py-4">
        <Breadcrumbs
          items={[
            { label: "Channels", href: "/dashboard/channels" },
            { label: channel.name, href: `/dashboard/channels/${slug}` },
            { label: "Settings" },
          ]}
        />
        <div className="mt-3 flex items-center gap-3 sm:gap-4">
          <div className="flex h-11 w-11 sm:h-12 sm:w-12 items-center justify-center rounded-2xl bg-gradient-to-br shadow-md overflow-hidden" style={{ background: `linear-gradient(135deg, ${channel.color.includes("pink") ? "#E1306C" : channel.color.includes("green") ? "#25D366" : channel.color.includes("blue") ? "#1877F2" : channel.color.includes("sky") ? "#000000" : channel.color.includes("indigo") ? "#2AABEE" : "#0A66C2"}, ${channel.color.includes("pink") ? "#F77737" : channel.color.includes("green") ? "#128C7E" : channel.color.includes("blue") ? "#4267B2" : channel.color.includes("sky") ? "#000000" : channel.color.includes("indigo") ? "#229ED9" : "#0A66C2"})` }}>
            <ChannelLogo channel={slug} className="h-7 w-7 sm:h-8 sm:w-8" />
          </div>
          <div>
            <h1 className="text-[18px] sm:text-[20px] font-bold text-ink">{channel.name} Settings</h1>
            <p className="text-[12px] sm:text-[13px] text-ink/60">
              {channel.connected ? "Connected" : "Not connected"} &middot; Configure this channel
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-2xl space-y-6">

          {/* ── Agent Selection ── */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Agent</h2>
            <p className="mb-4 text-[13px] text-ink/60">Choose which AI agent handles conversations on this channel.</p>
            <Dropdown
              label="Assigned Agent"
              value={selectedAgent}
              options={[{ id: "", name: "No Agent", status: "none" }, ...agents]}
              onSelect={setSelectedAgent}
              renderOption={(opt) => (
                <>
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-deep-violet/10">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-deep-violet">
                      <rect x="3" y="11" width="18" height="10" rx="2" />
                      <circle cx="12" cy="5" r="2" />
                      <path d="M12 7v4M8 11v4M16 11v4" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-[13px] font-semibold text-ink">{String(opt.name || "No Agent")}</span>
                    {!opt.id && <p className="text-[11px] text-ink/50">Manual mode — you reply yourself</p>}
                  </div>
                  {opt.id && "status" in opt && typeof opt.status === "string" && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${opt.status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                      {opt.status}
                    </span>
                  )}
                </>
              )}
              renderSelected={(opt) => (
                <>
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-deep-violet/10">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-deep-violet">
                      <rect x="3" y="11" width="18" height="10" rx="2" />
                      <circle cx="12" cy="5" r="2" />
                      <path d="M12 7v4M8 11v4M16 11v4" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-[13px] font-semibold text-ink">{String(opt.name || "No Agent")}</span>
                  </div>
                </>
              )}
            />
          </section>

          {/* ── Divider ── */}
          <div className="border-t border-deep-violet/10" />

          {/* ── Divider ── */}
          <div className="border-t border-deep-violet/10" />

          {/* ── General Settings ── */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">General</h2>
            <p className="mb-4 text-[13px] text-ink/60">Configure how this channel operates.</p>
            <div className="space-y-3">
              <Toggle label="Auto-Reply" desc="Automatically respond to incoming messages" checked={autoReply} onChange={() => setAutoReply(!autoReply)} />
              <Toggle label="Typing Indicator" desc='Show "typing..." while the agent processes' checked={typingIndicator} onChange={() => setTypingIndicator(!typingIndicator)} />
              <Toggle label="Working Hours" desc="Only respond during business hours" checked={workingHours} onChange={() => setWorkingHours(!workingHours)} />
            </div>
          </section>

          {/* ── Working Hours (conditional) ── */}
          {workingHours && (
            <>
              <div className="border-t border-deep-violet/10" />
              <section>
                <h2 className="mb-1 text-[15px] font-bold text-ink">Business Hours</h2>
                <p className="mb-4 text-[13px] text-ink/60">Set when the agent is available.</p>
                <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-4">
                    <div className="flex-1 w-full sm:w-auto">
                      <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">Start</label>
                      <input
                        type="time"
                        value={workingStart}
                        onChange={(e) => setWorkingStart(e.target.value)}
                        className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                      />
                    </div>
                    <span className="mt-5 hidden sm:block text-ink/25">&rarr;</span>
                    <span className="mt-1 sm:mt-5 text-ink/25 sm:hidden">&darr;</span>
                    <div className="flex-1 w-full sm:w-auto">
                      <label className="mb-1.5 block text-[11px] font-semibold text-ink/50">End</label>
                      <input
                        type="time"
                        value={workingEnd}
                        onChange={(e) => setWorkingEnd(e.target.value)}
                        className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                      />
                    </div>
                  </div>
                  <div className="mt-4">
                    <label className="mb-2 block text-[12px] font-semibold text-ink">Offline Message</label>
                    <textarea
                      value={offlineMsg}
                      onChange={(e) => setOfflineMsg(e.target.value)}
                      rows={3}
                      placeholder="Message shown outside working hours..."
                      className="w-full rounded-xl border-2 border-white bg-white px-4 py-3 text-[13px] text-ink outline-none transition placeholder:text-ink/35 focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
                    />
                  </div>
                </div>
              </section>
            </>
          )}

          {/* ── Divider ── */}
          <div className="border-t border-deep-violet/10" />

          {/* ── Connection Status ── */}
          <section>
            <h2 className="mb-1 text-[15px] font-bold text-ink">Connection</h2>
            <p className="mb-4 text-[13px] text-ink/60">Channel connection status.</p>
            <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`h-3 w-3 rounded-full ${channel.connected ? "bg-emerald-500" : "bg-ink/20"}`} />
                  <div>
                    <span className={`text-[14px] font-semibold ${channel.connected ? "text-emerald-600" : "text-ink/50"}`}>
                      {channel.connected ? "Connected" : "Disconnected"}
                    </span>
                    <p className="text-[11px] text-ink/45">
                      {channel.connected ? "All systems operational" : "Connect this channel to start"}
                    </p>
                  </div>
                </div>
                {!channel.connected && (
                  <button className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]">
                    Connect
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* Spacer for footer */}
          <div className="h-4" />
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
          Save Changes
        </button>
      </div>
    </div>
  );
}
