"use client";

import { useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import WizardStepper from "@/components/agents/WizardStepper";

type WizardData = {
  agentId: string;
  model: string;
  channels: string[];
  widgetPreset: string;
  responseHours: "24/7" | "business";
  businessStart: string;
  businessEnd: string;
  handoffThreshold: number;
  greetingEnabled: boolean;
  greetingMessage: string;
};

const defaultData: WizardData = {
  agentId: "",
  model: "",
  channels: [],
  widgetPreset: "",
  responseHours: "24/7",
  businessStart: "09:00",
  businessEnd: "17:00",
  handoffThreshold: 3,
  greetingEnabled: true,
  greetingMessage: "Hi! How can I help you today?",
};

const stepLabels = ["Pick Agent", "Pick Model", "Channels & Widget", "Rules", "Review"];

const agents = [
  { id: "hr-agent", name: "HR Agent", category: "HR", description: "Handles employee inquiries, policies, onboarding" },
  { id: "tech-support-agent", name: "Tech Support Agent", category: "Tech", description: "Troubleshoots technical issues, routes tickets" },
  { id: "sales-agent", name: "Sales Agent", category: "Sales", description: "Qualifies leads, answers product questions, demos" },
  { id: "support-agent", name: "Support Agent", category: "Support", description: "Handles customer questions, creates tickets" },
  { id: "lead-qualifier", name: "Lead Qualifier", category: "Lead Qualifier", description: "Qualifies inbound leads, collects info, routes to sales" },
  { id: "concierge", name: "Concierge Agent", category: "Concierge", description: "Warm onboarding, guides new users" },
  { id: "faq-bot", name: "FAQ Bot", category: "Support", description: "Answers frequently asked questions from knowledge base" },
  { id: "cart-recovery-agent", name: "Cart Recovery Agent", category: "Sales", description: "Re-engages shoppers who abandoned carts" },
];

const modelGroups = [
  { provider: "OpenAI", models: ["GPT-4o", "GPT-4o Mini", "GPT-4 Turbo", "o3-mini", "o4-mini"] },
  { provider: "Grok", models: ["Grok-2", "Grok-2 Mini", "Grok-3", "Grok-3 Mini"] },
  { provider: "Gemini", models: ["2.5 Pro", "2.5 Flash", "2.0 Flash"] },
  { provider: "Kimi", models: ["Kimi K2", "Moonshot v1 128k", "Moonshot v1 32k", "Moonshot v1 8k"] },
  { provider: "DeepSeek", models: ["Chat", "Reasoner"] },
  { provider: "Ollama", models: ["Llama 3.1", "Mistral", "Qwen3"] },
];

const channelOptions = [
  { id: "website", name: "Website Widget", desc: "Embed on your website", icon: "🌐" },
  { id: "whatsapp", name: "WhatsApp Business", desc: "Connect via WhatsApp API", icon: "💬" },
  { id: "instagram", name: "Instagram", desc: "DM automation", icon: "📸" },
  { id: "facebook", name: "Facebook", desc: "Messenger integration", icon: "👤" },
  { id: "x", name: "X / Twitter", desc: "DM and mention replies", icon: "✖" },
];

const widgetPresets = [
  { id: "ap1", name: "Default Widget" },
  { id: "ap2", name: "Minimal Left" },
];

export default function CreateAutomationPage() {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<WizardData>(defaultData);

  const update = <K extends keyof WizardData>(key: K, value: WizardData[K]) => {
    setData((prev) => ({ ...prev, [key]: value }));
  };

  const toggleChannel = (id: string) => {
    setData((prev) => ({
      ...prev,
      channels: prev.channels.includes(id)
        ? prev.channels.filter((c) => c !== id)
        : [...prev.channels, id],
    }));
  };

  const selectedAgent = agents.find((a) => a.id === data.agentId);

  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Automations", href: "/dashboard/automations" }, { label: "Create Automation" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Create Automation</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Deploy an agent with a model across channels.</p>
      </div>

      <WizardStepper steps={stepLabels} current={step} />

      {/* Step content */}
      <div className="min-h-[400px] rounded-xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">

        {/* Step 1: Pick Agent */}
        {step === 0 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Pick Agent</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {agents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => update("agentId", agent.id)}
                  className={`rounded-xl border p-4 text-left transition ${
                    data.agentId === agent.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] hover:border-ink/[0.1] dark:border-fog/[0.06] dark:hover:border-fog/[0.1]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[13px] font-semibold text-ink dark:text-fog">{agent.name}</span>
                    <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[9px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                      {agent.category}
                    </span>
                  </div>
                  <p className="text-[11px] text-ink/45 dark:text-fog/45 line-clamp-2">{agent.description}</p>
                </button>
              ))}
            </div>
            {selectedAgent && (
              <div className="rounded-xl border border-deep-violet/20 bg-deep-violet/[0.04] p-4">
                <p className="text-[12px] font-medium text-deep-violet">Selected: {selectedAgent.name}</p>
                <p className="text-[11px] text-ink/45 dark:text-fog/45">{selectedAgent.description}</p>
              </div>
            )}
          </div>
        )}

        {/* Step 2: Pick Model */}
        {step === 1 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Pick Model</h2>
            <p className="text-[12px] text-ink/45 dark:text-fog/45">Choose the AI model for this automation.</p>

            {modelGroups.map((group) => (
              <div key={group.provider}>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">{group.provider}</p>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {group.models.map((model) => (
                    <button
                      key={model}
                      onClick={() => update("model", model)}
                      className={`flex items-center justify-between rounded-xl border p-3 text-left transition ${
                        data.model === model ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] hover:border-ink/[0.1] dark:border-fog/[0.06] dark:hover:border-fog/[0.1]"
                      }`}
                    >
                      <div>
                        <p className="text-[12px] font-medium text-ink dark:text-fog">{model}</p>
                        <p className="text-[10px] text-ink/30 dark:text-fog/30">{group.provider}</p>
                      </div>
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-semibold text-emerald-600">Instant</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}

            <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-deep-violet/[0.06] text-deep-violet">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div>
                  <p className="text-[12px] font-medium text-ink dark:text-fog">Privacy</p>
                  <p className="text-[11px] text-ink/45 dark:text-fog/45">All models run on private infrastructure. Your data stays yours.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Channels & Widget */}
        {step === 2 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Channels & Widget</h2>
            <p className="text-[12px] text-ink/45 dark:text-fog/45">Select where this automation will be active.</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {channelOptions.map((ch) => {
                const selected = data.channels.includes(ch.id);
                return (
                  <button
                    key={ch.id}
                    onClick={() => toggleChannel(ch.id)}
                    className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${
                      selected ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] hover:border-ink/[0.1] dark:border-fog/[0.06] dark:hover:border-fog/[0.1]"
                    }`}
                  >
                    <span className="text-[20px]">{ch.icon}</span>
                    <div className="flex-1">
                      <p className="text-[12px] font-medium text-ink dark:text-fog">{ch.name}</p>
                      <p className="text-[10px] text-ink/30 dark:text-fog/30">{ch.desc}</p>
                    </div>
                    <div className={`flex h-5 w-5 items-center justify-center rounded border ${
                      selected ? "border-deep-violet bg-deep-violet" : "border-ink/20 dark:border-fog/20"
                    }`}>
                      {selected && (
                        <svg viewBox="0 0 16 16" fill="none" stroke="white" strokeWidth="2" className="h-3 w-3">
                          <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {data.channels.includes("website") && (
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-2">Widget Preset</label>
                <div className="grid grid-cols-2 gap-2">
                  {widgetPresets.map((wp) => (
                    <button
                      key={wp.id}
                      onClick={() => update("widgetPreset", wp.id)}
                      className={`rounded-xl border p-3 text-center transition ${
                        data.widgetPreset === wp.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] hover:border-ink/[0.1] dark:border-fog/[0.06] dark:hover:border-fog/[0.1]"
                      }`}
                    >
                      <span className="text-[12px] font-medium text-ink dark:text-fog">{wp.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Step 4: Rules & Triggers */}
        {step === 3 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Rules & Triggers</h2>

            {/* Response Hours */}
            <div className="space-y-3">
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Response Hours</label>
              <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03] w-fit">
                <button
                  onClick={() => update("responseHours", "24/7")}
                  className={`rounded-md px-4 py-2 text-[12px] font-medium transition ${
                    data.responseHours === "24/7" ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
                  }`}
                >
                  24/7
                </button>
                <button
                  onClick={() => update("responseHours", "business")}
                  className={`rounded-md px-4 py-2 text-[12px] font-medium transition ${
                    data.responseHours === "business" ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
                  }`}
                >
                  Business hours only
                </button>
              </div>
              {data.responseHours === "business" && (
                <div className="flex items-center gap-3">
                  <div>
                    <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Start</label>
                    <input
                      type="time"
                      value={data.businessStart}
                      onChange={(e) => update("businessStart", e.target.value)}
                      className="rounded-lg border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                    />
                  </div>
                  <span className="text-ink/25 dark:text-fog/25">to</span>
                  <div>
                    <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">End</label>
                    <input
                      type="time"
                      value={data.businessEnd}
                      onChange={(e) => update("businessEnd", e.target.value)}
                      className="rounded-lg border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Human Handoff Threshold */}
            <div className="space-y-2">
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">
                Human Handoff Threshold: {data.handoffThreshold} failed attempts
              </label>
              <input
                type="range"
                min={1}
                max={10}
                value={data.handoffThreshold}
                onChange={(e) => update("handoffThreshold", Number(e.target.value))}
                className="w-full accent-deep-violet"
              />
              <div className="flex justify-between text-[9px] text-ink/25 dark:text-fog/25">
                <span>1 attempt</span>
                <span>10 attempts</span>
              </div>
            </div>

            {/* Greeting Message */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Greeting Message</label>
                <button
                  onClick={() => update("greetingEnabled", !data.greetingEnabled)}
                  className={`relative h-5 w-9 rounded-full transition ${
                    data.greetingEnabled ? "bg-deep-violet" : "bg-ink/20 dark:bg-fog/20"
                  }`}
                >
                  <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                    data.greetingEnabled ? "translate-x-4" : "translate-x-0.5"
                  }`} />
                </button>
              </div>
              {data.greetingEnabled && (
                <input
                  type="text"
                  value={data.greetingMessage}
                  onChange={(e) => update("greetingMessage", e.target.value)}
                  placeholder="Hi! How can I help you today?"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              )}
            </div>
          </div>
        )}

        {/* Step 5: Review & Activate */}
        {step === 4 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Review & Activate</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <ReviewCard title="Agent">
                <ReviewRow label="Agent" value={selectedAgent?.name || "—"} />
                <ReviewRow label="Category" value={selectedAgent?.category || "—"} />
              </ReviewCard>
              <ReviewCard title="Model">
                <ReviewRow label="Model" value={data.model || "—"} />
              </ReviewCard>
              <ReviewCard title="Channels">
                <div className="flex flex-wrap gap-1.5">
                  {data.channels.length === 0 ? (
                    <span className="text-[11px] text-ink/30 dark:text-fog/30">No channels selected</span>
                  ) : (
                    data.channels.map((ch) => (
                      <span key={ch} className="rounded-full bg-deep-violet/[0.06] px-2 py-0.5 text-[10px] font-medium text-deep-violet capitalize">{ch}</span>
                    ))
                  )}
                </div>
              </ReviewCard>
              <ReviewCard title="Rules">
                <ReviewRow label="Response Hours" value={data.responseHours === "24/7" ? "24/7" : `${data.businessStart} - ${data.businessEnd}`} />
                <ReviewRow label="Handoff After" value={`${data.handoffThreshold} attempts`} />
                <ReviewRow label="Greeting" value={data.greetingEnabled ? "Enabled" : "Disabled"} />
              </ReviewCard>
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <div>
          {step > 0 ? (
            <button onClick={() => setStep(step - 1)} className="rounded-lg border border-ink/[0.06] px-4 py-2 text-[12px] font-medium text-ink/60 transition hover:border-ink/[0.1] hover:text-ink dark:border-fog/[0.06] dark:text-fog/60 dark:hover:border-fog/[0.1] dark:hover:text-fog">
              Previous
            </button>
          ) : (
            <div />
          )}
        </div>
        <div className="flex items-center gap-2">
          <button className="text-[12px] font-medium text-ink/40 transition hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60">
            Save as Draft
          </button>
          {step < 4 ? (
            <button onClick={() => setStep(step + 1)} className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">
              Next
            </button>
          ) : (
            <button className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">
              Deploy & Activate
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ReviewCard({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06] ${className}`}>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">{title}</p>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-ink/40 dark:text-fog/40">{label}</span>
      <span className="text-[11px] font-medium text-ink dark:text-fog">{value}</span>
    </div>
  );
}
