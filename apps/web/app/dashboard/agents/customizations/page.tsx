"use client";

import { useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";

type Tab = "appearance" | "knowledge" | "tickets" | "webhooks" | "integrations";

const appearancePresets = [
  { id: "ap1", name: "Default Widget", position: "bottom-right" },
  { id: "ap2", name: "Minimal Left", position: "bottom-left" },
];

const knowledgePresets = [
  { id: "kp1", name: "Product Knowledge" },
  { id: "kp2", name: "FAQ Collection" },
];

const ticketPresets = [
  { id: "tp1", name: "Standard Support" },
  { id: "tp2", name: "Sales Inquiry" },
];

const webhookPresets = [
  { id: "wp1", name: "Slack Notifications" },
  { id: "wp2", name: "CRM Sync" },
];

const integrationPresets = [
  { id: "ip1", name: "Google Calendar Setup" },
  { id: "ip2", name: "Calendly Integration" },
];

const tabs: { id: Tab; label: string }[] = [
  { id: "appearance", label: "Appearance" },
  { id: "knowledge", label: "Knowledge" },
  { id: "tickets", label: "Tickets" },
  { id: "webhooks", label: "Webhooks" },
  { id: "integrations", label: "Integrations" },
];

const launcherIcons = [
  { id: "chat", label: "Chat Bubble" },
  { id: "question", label: "Question Mark" },
  { id: "headphones", label: "Headphones" },
];

const fontOptions = ["Inter", "Roboto", "Open Sans", "System"];

const positions = ["bottom-right", "bottom-left", "top-right", "top-left"] as const;

const channels = ["Files", "FAQs", "URLs", "Search"] as const;
const databankCategories = ["Knowledge Base", "Product Catalog", "FAQs", "Policies", "Templates", "Training Data"];
const ticketFields = ["Email", "Name", "Phone", "Company", "Subject", "Message"] as const;
const webhookEvents = ["message_received", "ticket_created", "conversation_ended", "agent_error"] as const;

export default function CustomizationsPage() {
  const [tab, setTab] = useState<Tab>("appearance");
  const [editingPreset, setEditingPreset] = useState<string | null>(null);

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Agents", href: "/dashboard/agents" }, { label: "Customizations" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Customization Library</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Create and manage reusable presets for your agents.</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03]">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition ${
              tab === t.id ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Appearance */}
      {tab === "appearance" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Saved Presets</p>
            {appearancePresets.map((p) => (
              <button
                key={p.id}
                onClick={() => setEditingPreset(p.id)}
                className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${
                  editingPreset === p.id
                    ? "border-deep-violet/30 bg-deep-violet/[0.04]"
                    : "border-ink/[0.06] bg-white hover:border-ink/[0.1] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-fog/[0.1]"
                }`}
              >
                <div>
                  <p className="text-[12px] font-medium text-ink dark:text-fog">{p.name}</p>
                  <p className="text-[10px] text-ink/30 dark:text-fog/30">{p.position}</p>
                </div>
                <div className="flex gap-1">
                  <span className="rounded p-1 text-ink/20 hover:text-ink/50 dark:text-fog/20">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                      <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                  <span className="rounded p-1 text-ink/20 hover:text-coral dark:text-fog/20">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                      <path d="M2 4h12M5.33 4V2.67a1.33 1.33 0 011.34-1.34h2.66a1.33 1.33 0 011.34 1.34V4m2 0v9.33a1.33 1.33 0 01-1.34 1.34H4.67a1.33 1.33 0 01-1.34-1.34V4h9.34z" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                </div>
              </button>
            ))}
            <button className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-ink/[0.1] py-2.5 text-[12px] font-medium text-ink/30 transition hover:border-deep-violet/30 hover:text-deep-violet dark:border-fog/[0.1] dark:text-fog/30 dark:hover:border-deep-violet/30 dark:hover:text-deep-violet">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                <path d="M8 3v10M3 8h10" strokeLinecap="round" />
              </svg>
              New Preset
            </button>
          </div>

          <div className="lg:col-span-2 space-y-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Edit Preset</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Preset Name</label>
                <input type="text" defaultValue="Default Widget" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Chat Welcome Text</label>
                <input type="text" defaultValue="Hi! How can I help you today?" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Logo</label>
                <div className="flex items-center gap-3">
                  <div className="flex h-14 w-14 items-center justify-center rounded-lg border border-dashed border-ink/[0.1] text-ink/20 dark:border-fog/[0.1] dark:text-fog/20">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
                      <rect x="3" y="3" width="18" height="18" rx="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" />
                      <path d="M21 15l-5-5L5 21" />
                    </svg>
                  </div>
                  <button className="text-[11px] font-medium text-deep-violet transition hover:text-deep-violet/80">Upload</button>
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Avatar</label>
                <div className="flex items-center gap-3">
                  <div className="flex h-14 w-14 items-center justify-center rounded-full border border-dashed border-ink/[0.1] text-ink/20 dark:border-fog/[0.1] dark:text-fog/20">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
                      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                  </div>
                  <button className="text-[11px] font-medium text-deep-violet transition hover:text-deep-violet/80">Upload</button>
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Launcher Icon</label>
                <div className="flex gap-2">
                  {launcherIcons.map((icon) => (
                    <button key={icon.id} className={`flex h-10 w-10 items-center justify-center rounded-lg border transition ${
                      icon.id === "chat" ? "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet" : "border-ink/[0.06] text-ink/30 hover:border-ink/[0.1] dark:border-fog/[0.06] dark:text-fog/30 dark:hover:border-fog/[0.1]"
                    }`}>
                      {icon.id === "chat" && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /></svg>}
                      {icon.id === "question" && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4"><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" /></svg>}
                      {icon.id === "headphones" && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4"><path d="M3 18v-6a9 9 0 0118 0v6" /></svg>}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Font Family</label>
                <select className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog">
                  {fontOptions.map((f) => <option key={f}>{f}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Widget Position</label>
                <div className="grid grid-cols-2 gap-1.5 p-2">
                  {positions.map((pos) => (
                    <button key={pos} className={`flex h-8 items-center justify-center rounded border text-[9px] transition ${
                      pos === "bottom-right" ? "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet" : "border-ink/[0.08] text-ink/25 hover:border-ink/[0.15] dark:border-fog/[0.08] dark:text-fog/25 dark:hover:border-fog/[0.15]"
                    }`}>
                      {pos.replace("-", " ")}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Primary Color</label>
                <div className="flex items-center gap-2">
                  <input type="color" defaultValue="#3D1D6E" className="h-9 w-9 cursor-pointer rounded-lg border-0 p-0" />
                  <input type="text" defaultValue="#3D1D6E" className="flex-1 rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[12px] font-mono text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Reviews</label>
                <button className="flex items-center gap-2">
                  <div className="relative h-5 w-9 rounded-full bg-deep-violet">
                    <div className="absolute right-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" />
                  </div>
                  <span className="text-[12px] text-ink/60 dark:text-fog/60">Enabled</span>
                </button>
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <button className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {/* Knowledge */}
      {tab === "knowledge" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Saved Presets</p>
            {knowledgePresets.map((p) => (
              <button
                key={p.id}
                onClick={() => setEditingPreset(p.id)}
                className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${
                  editingPreset === p.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] bg-white hover:border-ink/[0.1] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-fog/[0.1]"
                }`}
              >
                <p className="text-[12px] font-medium text-ink dark:text-fog">{p.name}</p>
                <div className="flex gap-1">
                  <span className="rounded p-1 text-ink/20 hover:text-ink/50 dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                  <span className="rounded p-1 text-ink/20 hover:text-coral dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M2 4h12M5.33 4V2.67a1.33 1.33 0 011.34-1.34h2.66a1.33 1.33 0 011.34 1.34V4m2 0v9.33a1.33 1.33 0 01-1.34 1.34H4.67a1.33 1.33 0 01-1.34-1.34V4h9.34z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                </div>
              </button>
            ))}
          </div>
          <div className="lg:col-span-2 space-y-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Knowledge Sources</h3>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Preset Name</label>
              <input type="text" defaultValue="Product Knowledge" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
            </div>
            <div className="space-y-3">
              {channels.map((ch) => (
                <div key={ch} className="rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-medium text-ink dark:text-fog">{ch}</span>
                    <button className="flex items-center gap-2">
                      <div className={`relative h-4 w-7 rounded-full ${ch === "FAQs" ? "bg-deep-violet" : "bg-ink/10 dark:bg-fog/10"}`}>
                        <div className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition ${ch === "FAQs" ? "right-0.5" : "left-0.5"}`} />
                      </div>
                    </button>
                  </div>
                  {ch === "Files" && (
                    <div className="mt-2 flex items-center justify-center rounded-lg border border-dashed border-ink/[0.1] py-4 dark:border-fog/[0.1]">
                      <p className="text-[11px] text-ink/25 dark:text-fog/25">Drag & drop files here</p>
                    </div>
                  )}
                  {ch === "FAQs" && (
                    <div className="mt-2 space-y-2">
                      <div className="flex gap-2">
                        <input placeholder="Question" className="flex-1 rounded border border-ink/[0.06] bg-white px-2 py-1 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                        <input placeholder="Answer" className="flex-1 rounded border border-ink/[0.06] bg-white px-2 py-1 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                        <button className="rounded bg-deep-violet/[0.06] px-2 text-[10px] font-medium text-deep-violet">Add</button>
                      </div>
                    </div>
                  )}
                  {ch === "URLs" && (
                    <textarea placeholder="Enter URLs, one per line" rows={2} className="mt-2 w-full rounded border border-ink/[0.06] bg-white px-2 py-1 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                  )}
                  {ch === "Search" && (
                    <p className="mt-1 text-[10px] text-ink/30 dark:text-fog/30">Enable web search as a knowledge source</p>
                  )}
                </div>
              ))}
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Databank Category</label>
              <select className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog">
                {databankCategories.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div className="flex justify-end pt-2">
              <button className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {/* Tickets */}
      {tab === "tickets" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Saved Presets</p>
            {ticketPresets.map((p) => (
              <button
                key={p.id}
                onClick={() => setEditingPreset(p.id)}
                className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${
                  editingPreset === p.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] bg-white hover:border-ink/[0.1] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-fog/[0.1]"
                }`}
              >
                <p className="text-[12px] font-medium text-ink dark:text-fog">{p.name}</p>
                <div className="flex gap-1">
                  <span className="rounded p-1 text-ink/20 hover:text-ink/50 dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                  <span className="rounded p-1 text-ink/20 hover:text-coral dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M2 4h12M5.33 4V2.67a1.33 1.33 0 011.34-1.34h2.66a1.33 1.33 0 011.34 1.34V4m2 0v9.33a1.33 1.33 0 01-1.34 1.34H4.67a1.33 1.33 0 01-1.34-1.34V4h9.34z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                </div>
              </button>
            ))}
          </div>
          <div className="lg:col-span-2 space-y-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Ticket Form Settings</h3>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Preset Name</label>
              <input type="text" defaultValue="Standard Support" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
            </div>
            <div className="flex items-center justify-between rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
              <span className="text-[12px] font-medium text-ink dark:text-fog">Enable ticket collection</span>
              <button className="flex items-center gap-2">
                <div className="relative h-5 w-9 rounded-full bg-deep-violet">
                  <div className="absolute right-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" />
                </div>
              </button>
            </div>
            <div className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Fields</p>
              {ticketFields.map((f) => (
                <label key={f} className="flex items-center gap-3 rounded-lg border border-ink/[0.04] p-2.5 dark:border-fog/[0.04]">
                  <input type="checkbox" defaultChecked={f !== "Company"} className="h-3.5 w-3.5 rounded border-ink/20 accent-deep-violet" />
                  <span className="text-[12px] text-ink dark:text-fog">{f}</span>
                </label>
              ))}
            </div>
            <div className="flex justify-end pt-2">
              <button className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {/* Webhooks */}
      {tab === "webhooks" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Saved Presets</p>
            {webhookPresets.map((p) => (
              <button
                key={p.id}
                onClick={() => setEditingPreset(p.id)}
                className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${
                  editingPreset === p.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] bg-white hover:border-ink/[0.1] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-fog/[0.1]"
                }`}
              >
                <p className="text-[12px] font-medium text-ink dark:text-fog">{p.name}</p>
                <div className="flex gap-1">
                  <span className="rounded p-1 text-ink/20 hover:text-ink/50 dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                  <span className="rounded p-1 text-ink/20 hover:text-coral dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M2 4h12M5.33 4V2.67a1.33 1.33 0 011.34-1.34h2.66a1.33 1.33 0 011.34 1.34V4m2 0v9.33a1.33 1.33 0 01-1.34 1.34H4.67a1.33 1.33 0 01-1.34-1.34V4h9.34z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                </div>
              </button>
            ))}
          </div>
          <div className="lg:col-span-2 space-y-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Webhook Settings</h3>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Preset Name</label>
              <input type="text" defaultValue="Slack Notifications" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
            </div>
            <div className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Events</p>
              {webhookEvents.map((ev) => (
                <label key={ev} className="flex items-center gap-3 rounded-lg border border-ink/[0.04] p-2.5 dark:border-fog/[0.04]">
                  <input type="checkbox" defaultChecked className="h-3.5 w-3.5 rounded border-ink/20 accent-deep-violet" />
                  <span className="text-[12px] font-mono text-ink dark:text-fog">{ev}</span>
                </label>
              ))}
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Webhook URL</label>
              <input type="url" placeholder="https://hooks.example.com/webhook" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Secret</label>
              <input type="password" placeholder="whsec_..." className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25" />
            </div>
            <div className="flex justify-end pt-2">
              <button className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {/* Integrations */}
      {tab === "integrations" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Saved Presets</p>
            {integrationPresets.map((p) => (
              <button
                key={p.id}
                onClick={() => setEditingPreset(p.id)}
                className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${
                  editingPreset === p.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] bg-white hover:border-ink/[0.1] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-fog/[0.1]"
                }`}
              >
                <p className="text-[12px] font-medium text-ink dark:text-fog">{p.name}</p>
                <div className="flex gap-1">
                  <span className="rounded p-1 text-ink/20 hover:text-ink/50 dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                  <span className="rounded p-1 text-ink/20 hover:text-coral dark:text-fog/20"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3"><path d="M2 4h12M5.33 4V2.67a1.33 1.33 0 011.34-1.34h2.66a1.33 1.33 0 011.34 1.34V4m2 0v9.33a1.33 1.33 0 01-1.34 1.34H4.67a1.33 1.33 0 01-1.34-1.34V4h9.34z" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                </div>
              </button>
            ))}
          </div>
          <div className="lg:col-span-2 space-y-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Integration Settings</h3>
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Preset Name</label>
              <input type="text" defaultValue="Google Calendar Setup" className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
            </div>
            <div className="space-y-3">
              {/* MCP Server */}
              <div className="rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-deep-violet/[0.06] text-deep-violet">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4"><rect x="2" y="2" width="20" height="20" rx="2" /><path d="M7 12h10M12 7v10" /></svg>
                    </div>
                    <span className="text-[12px] font-medium text-ink dark:text-fog">MCP Server</span>
                  </div>
                  <button className="flex items-center gap-2">
                    <div className="relative h-5 w-9 rounded-full bg-ink/10 dark:bg-fog/10">
                      <div className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" />
                    </div>
                  </button>
                </div>
                <input type="url" placeholder="MCP server URL" className="mt-2 w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
              </div>
              {/* Google Calendar */}
              <div className="rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink/[0.04] dark:bg-fog/[0.04]">
                      <span className="text-[14px]">📅</span>
                    </div>
                    <span className="text-[12px] font-medium text-ink dark:text-fog">Google Calendar</span>
                  </div>
                  <button className="flex items-center gap-2">
                    <div className="relative h-5 w-9 rounded-full bg-deep-violet">
                      <div className="absolute right-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" />
                    </div>
                  </button>
                </div>
                <button className="mt-2 w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[11px] font-medium text-ink/60 transition hover:border-deep-violet/30 dark:border-fog/[0.06] dark:bg-ink dark:text-fog/60">Reconnect OAuth</button>
              </div>
              {/* Calendly */}
              <div className="rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink/[0.04] dark:bg-fog/[0.04]">
                      <span className="text-[14px]">📆</span>
                    </div>
                    <span className="text-[12px] font-medium text-ink dark:text-fog">Calendly</span>
                  </div>
                  <button className="flex items-center gap-2">
                    <div className="relative h-5 w-9 rounded-full bg-ink/10 dark:bg-fog/10">
                      <div className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" />
                    </div>
                  </button>
                </div>
                <input type="text" placeholder="Calendly API key" className="mt-2 w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
              </div>
              {/* Cal.com */}
              <div className="rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink/[0.04] dark:bg-fog/[0.04]">
                      <span className="text-[14px]">🗓️</span>
                    </div>
                    <span className="text-[12px] font-medium text-ink dark:text-fog">Cal.com</span>
                  </div>
                  <button className="flex items-center gap-2">
                    <div className="relative h-5 w-9 rounded-full bg-ink/10 dark:bg-fog/10">
                      <div className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" />
                    </div>
                  </button>
                </div>
                <input type="text" placeholder="Cal.com API key" className="mt-2 w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <button className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">Save Changes</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
