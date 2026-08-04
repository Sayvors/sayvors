"use client";

import { useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import WizardStepper from "@/components/agents/WizardStepper";
import PresetPicker from "@/components/agents/PresetPicker";
import WidgetPreview from "@/components/agents/WidgetPreview";

type WizardData = {
  name: string;
  model: string;
  template: string;
  coreInstructions: string;
  creativity: number;
  knowledgePreset: string;
  appearancePreset: string;
  ticketsPreset: string;
  webhooksPreset: string;
  integrationsPreset: string;
  deployChannels: string[];
};

const defaultData: WizardData = {
  name: "",
  model: "",
  template: "blank",
  coreInstructions: "",
  creativity: 50,
  knowledgePreset: "",
  appearancePreset: "",
  ticketsPreset: "",
  webhooksPreset: "",
  integrationsPreset: "",
  deployChannels: [],
};

const stepLabels = ["Basics", "Knowledge", "Appearance", "Tickets", "Webhooks", "Deploy", "Review"];

const modelGroups = [
  { label: "OpenAI", models: ["GPT-4o", "GPT-4o Mini", "GPT-4 Turbo", "o3-mini", "o4-mini"] },
  { label: "Grok", models: ["Grok-2", "Grok-2 Mini", "Grok-3", "Grok-3 Mini"] },
  { label: "Gemini", models: ["Gemini 2.5 Pro", "Gemini 2.5 Flash", "Gemini 2.0 Flash"] },
  { label: "Kimi", models: ["Kimi K2", "Moonshot v1 128k", "Moonshot v1 32k", "Moonshot v1 8k"] },
  { label: "DeepSeek", models: ["DeepSeek Chat", "DeepSeek Reasoner"] },
  { label: "Ollama", models: ["Llama 3.1", "Mistral", "Qwen3"] },
];

const templates = [
  { id: "blank", name: "Blank", desc: "Start from scratch with full control", icon: "📄" },
  { id: "welcome", name: "Welcome Series", desc: "Onboard new users with a warm greeting", icon: "👋" },
  { id: "cart-recovery", name: "Cart Recovery", desc: "Re-engage shoppers who left items behind", icon: "🛒" },
  { id: "lead-nurture", name: "Lead Nurture", desc: "Guide prospects through the funnel", icon: "🌱" },
  { id: "support", name: "Support", desc: "Handle common questions and tickets", icon: "🎧" },
];

const knowledgePresets = [
  { id: "kp1", name: "Product Knowledge" },
  { id: "kp2", name: "FAQ Collection" },
  { id: "kp3", name: "Company Policies" },
];

const appearancePresets = [
  { id: "ap1", name: "Default Widget" },
  { id: "ap2", name: "Minimal Left" },
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

const channelOptions = [
  { id: "website", name: "Website Widget", desc: "Embed on your website", icon: <WebsiteIcon /> },
  { id: "whatsapp", name: "WhatsApp Business", desc: "Connect via WhatsApp API", icon: <WhatsAppIcon /> },
  { id: "instagram", name: "Instagram", desc: "DM automation", icon: <InstagramIcon /> },
  { id: "facebook", name: "Facebook", desc: "Messenger integration", icon: <FacebookIcon /> },
  { id: "x", name: "X / Twitter", desc: "DM and mention replies", icon: <XIcon /> },
];

export default function CreateAgentPage() {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<WizardData>(defaultData);

  const update = <K extends keyof WizardData>(key: K, value: WizardData[K]) => {
    setData((prev) => ({ ...prev, [key]: value }));
  };

  const toggleChannel = (id: string) => {
    setData((prev) => ({
      ...prev,
      deployChannels: prev.deployChannels.includes(id)
        ? prev.deployChannels.filter((c) => c !== id)
        : [...prev.deployChannels, id],
    }));
  };

  const selectedTemplate = templates.find((t) => t.id === data.template);

  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Agents", href: "/dashboard/agents" }, { label: "Create Agent" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Create Agent</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Set up a new AI agent in 7 steps.</p>
      </div>

      <WizardStepper steps={stepLabels} current={step} />

      {/* Step content */}
      <div className="min-h-[400px] rounded-xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">

        {/* Step 1: Basics */}
        {step === 0 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Basics</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Agent Name</label>
                <input
                  type="text"
                  value={data.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="e.g. Support Bot"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Model</label>
                <select
                  value={data.model}
                  onChange={(e) => update("model", e.target.value)}
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                >
                  <option value="">Select a model...</option>
                  {modelGroups.map((g) => (
                    <optgroup key={g.label} label={g.label}>
                      {g.models.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-2">Template</label>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => { update("template", t.id); if (t.id !== "blank") { update("coreInstructions", t.id === "welcome" ? "You are a friendly onboarding assistant. Welcome new users warmly, explain key features, and offer to help them get started." : t.id === "cart-recovery" ? "You are a cart recovery assistant. Reach out to users who abandoned their cart. Be friendly, offer help, and incentivize completing the purchase." : t.id === "lead-nurture" ? "You are a lead nurturing assistant. Guide prospects through the sales funnel. Qualify leads, answer questions, and schedule demos." : "You are a customer support assistant. Answer common questions, troubleshoot issues, and create tickets when needed. Be helpful and concise."); } }}
                    className={`flex flex-col items-center gap-1.5 rounded-xl border p-3 text-center transition ${
                      data.template === t.id ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] hover:border-ink/[0.1] dark:border-fog/[0.06] dark:hover:border-fog/[0.1]"
                    }`}
                  >
                    <span className="text-[20px]">{t.icon}</span>
                    <span className="text-[11px] font-medium text-ink dark:text-fog">{t.name}</span>
                    <span className="text-[9px] text-ink/30 dark:text-fog/30">{t.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">
                Core Instructions {data.template !== "blank" && <span className="text-ink/30 dark:text-fog/30">(from {selectedTemplate?.name} template)</span>}
              </label>
              <textarea
                value={data.coreInstructions}
                onChange={(e) => update("coreInstructions", e.target.value)}
                rows={5}
                placeholder="Describe what this agent should do, its personality, and any rules it should follow..."
                className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
              />
            </div>

            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">
                Creativity: {data.creativity}% <span className="text-ink/30 dark:text-fog/30">({data.creativity <= 20 ? "Precise" : data.creativity <= 40 ? "Balanced" : data.creativity <= 60 ? "Moderate" : data.creativity <= 80 ? "Creative" : "Very Creative"})</span>
              </label>
              <input
                type="range"
                min={0}
                max={100}
                value={data.creativity}
                onChange={(e) => update("creativity", Number(e.target.value))}
                className="w-full accent-deep-violet"
              />
              <div className="flex justify-between text-[9px] text-ink/25 dark:text-fog/25">
                <span>Precise (0)</span>
                <span>Creative (100)</span>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Knowledge */}
        {step === 1 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Knowledge</h2>
            <PresetPicker
              label="Knowledge Preset"
              presets={knowledgePresets}
              selected={data.knowledgePreset}
              onSelect={(id) => update("knowledgePreset", id)}
              onCreateNew={() => setShowNewKnowledge(true)}
            >
              <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure sources, FAQ pairs, URLs, and databank category.</p>
              </div>
            </PresetPicker>
            <div className="flex items-center gap-2 rounded-lg bg-ink/[0.03] p-3 dark:bg-fog/[0.03]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4 text-deep-violet">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4M12 8h.01" />
              </svg>
              <p className="text-[11px] text-ink/50 dark:text-fog/50">
                Need more control? <a href="/dashboard/agents/customizations" className="font-medium text-deep-violet hover:text-deep-violet/80">Create a full knowledge preset</a>
              </p>
            </div>
          </div>
        )}

        {/* Step 3: Appearance */}
        {step === 2 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Appearance</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <PresetPicker
                  label="Appearance Preset"
                  presets={appearancePresets}
                  selected={data.appearancePreset}
                  onSelect={(id) => update("appearancePreset", id)}
                  onCreateNew={() => setShowNewAppearance(true)}
                >
                  <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                    <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Font</label>
                        <select className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog">
                          <option>Inter</option><option>Roboto</option><option>Open Sans</option><option>System</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Color</label>
                        <input type="color" defaultValue="#3D1D6E" className="h-7 w-full rounded border-0" />
                      </div>
                    </div>
                    <div>
                      <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Welcome Text</label>
                      <input type="text" placeholder="Hi! How can I help you today?" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                    </div>
                  </div>
                </PresetPicker>
              </div>
              <WidgetPreview
                position="bottom-right"
                primaryColor="#3D1D6E"
                font="Inter"
                launcherIcon="chat"
                welcomeText="Hi! How can I help you today?"
              />
            </div>
            <div className="flex items-center gap-2 rounded-lg bg-ink/[0.03] p-3 dark:bg-fog/[0.03]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4 text-deep-violet">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4M12 8h.01" />
              </svg>
              <p className="text-[11px] text-ink/50 dark:text-fog/50">
                Need more control? <a href="/dashboard/agents/customizations" className="font-medium text-deep-violet hover:text-deep-violet/80">Create a full appearance preset</a>
              </p>
            </div>
          </div>
        )}

        {/* Step 4: Tickets */}
        {step === 3 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Tickets</h2>
            <PresetPicker
              label="Tickets Preset"
              presets={ticketPresets}
              selected={data.ticketsPreset}
              onSelect={(id) => update("ticketsPreset", id)}
              onCreateNew={() => setShowNewTickets(true)}
            >
              <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure which fields to collect from users.</p>
              </div>
            </PresetPicker>
            <div className="flex items-center gap-2 rounded-lg bg-ink/[0.03] p-3 dark:bg-fog/[0.03]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4 text-deep-violet">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4M12 8h.01" />
              </svg>
              <p className="text-[11px] text-ink/50 dark:text-fog/50">
                Need more control? <a href="/dashboard/agents/customizations" className="font-medium text-deep-violet hover:text-deep-violet/80">Create a full tickets preset</a>
              </p>
            </div>
          </div>
        )}

        {/* Step 5: Webhooks & Integrations */}
        {step === 4 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Webhooks & Integrations</h2>
            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <PresetPicker
                  label="Webhooks Preset"
                  presets={webhookPresets}
                  selected={data.webhooksPreset}
                  onSelect={(id) => update("webhooksPreset", id)}
                  onCreateNew={() => setShowNewWebhooks(true)}
                >
                  <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                    <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                    <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure webhook events and URL.</p>
                  </div>
                </PresetPicker>
              </div>
              <div>
                <PresetPicker
                  label="Integrations Preset"
                  presets={integrationPresets}
                  selected={data.integrationsPreset}
                  onSelect={(id) => update("integrationsPreset", id)}
                  onCreateNew={() => setShowNewIntegrations(true)}
                >
                  <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                    <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                    <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure integrations like MCP, Google Calendar, etc.</p>
                  </div>
                </PresetPicker>
              </div>
            </div>
          </div>
        )}

        {/* Step 6: Deployment */}
        {step === 5 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Deployment Channels</h2>
            <p className="text-[12px] text-ink/45 dark:text-fog/45">Select where this agent should be available.</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {channelOptions.map((ch) => {
                const selected = data.deployChannels.includes(ch.id);
                return (
                  <button
                    key={ch.id}
                    onClick={() => toggleChannel(ch.id)}
                    className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${
                      selected ? "border-deep-violet/30 bg-deep-violet/[0.04]" : "border-ink/[0.06] hover:border-ink/[0.1] dark:border-fog/[0.06] dark:hover:border-fog/[0.1]"
                    }`}
                  >
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                      selected ? "bg-deep-violet/[0.1] text-deep-violet" : "bg-ink/[0.04] text-ink/30 dark:bg-fog/[0.04] dark:text-fog/30"
                    }`}>
                      {ch.icon}
                    </div>
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
          </div>
        )}

        {/* Step 7: Review */}
        {step === 6 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Review & Deploy</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <ReviewCard title="Basics">
                <ReviewRow label="Name" value={data.name || "—"} />
                <ReviewRow label="Model" value={data.model || "—"} />
                <ReviewRow label="Template" value={selectedTemplate?.name || "—"} />
                <ReviewRow label="Creativity" value={`${data.creativity}%`} />
              </ReviewCard>
              <ReviewCard title="Knowledge">
                <ReviewRow label="Preset" value={knowledgePresets.find((p) => p.id === data.knowledgePreset)?.name || "—"} />
              </ReviewCard>
              <ReviewCard title="Appearance">
                <ReviewRow label="Preset" value={appearancePresets.find((p) => p.id === data.appearancePreset)?.name || "—"} />
              </ReviewCard>
              <ReviewCard title="Tickets">
                <ReviewRow label="Preset" value={ticketPresets.find((p) => p.id === data.ticketsPreset)?.name || "—"} />
              </ReviewCard>
              <ReviewCard title="Webhooks">
                <ReviewRow label="Preset" value={webhookPresets.find((p) => p.id === data.webhooksPreset)?.name || "—"} />
              </ReviewCard>
              <ReviewCard title="Integrations">
                <ReviewRow label="Preset" value={integrationPresets.find((p) => p.id === data.integrationsPreset)?.name || "—"} />
              </ReviewCard>
              <ReviewCard title="Channels" className="sm:col-span-2">
                <div className="flex flex-wrap gap-1.5">
                  {data.deployChannels.length === 0 ? (
                    <span className="text-[11px] text-ink/30 dark:text-fog/30">No channels selected</span>
                  ) : (
                    data.deployChannels.map((ch) => (
                      <span key={ch} className="rounded-full bg-deep-violet/[0.06] px-2 py-0.5 text-[10px] font-medium text-deep-violet capitalize">{ch}</span>
                    ))
                  )}
                </div>
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
            <button className="text-[12px] font-medium text-ink/30 transition hover:text-ink/50 dark:text-fog/30 dark:hover:text-fog/50">
              Save as Draft
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button className="text-[12px] font-medium text-ink/40 transition hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60">
            Save as Draft
          </button>
          {step < 6 ? (
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

function WebsiteIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5"><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" /></svg>;
}

function WhatsAppIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5"><path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" /></svg>;
}

function InstagramIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5"><rect x="2" y="2" width="20" height="20" rx="5" /><circle cx="12" cy="12" r="5" /><circle cx="17.5" cy="6.5" r="1.5" fill="currentColor" /></svg>;
}

function FacebookIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5"><path d="M18 2h-3a5 5 0 00-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 011-1h3z" /></svg>;
}

function XIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5"><path d="M4 4l6.5 8L4 20h2l5.5-6.8L16 20h4l-6.8-8.5L20 4h-2l-5.2 6.4L8 4H4z" /></svg>;
}
