"use client";

import { useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import WizardStepper from "@/components/agents/WizardStepper";
import PresetPicker from "@/components/agents/PresetPicker";
import WidgetPreview from "@/components/agents/WidgetPreview";

type WizardData = {
  name: string;
  description: string;
  persona: string;
  template: string;
  coreInstructions: string;
  creativity: number;
  trainingMode: "zero-shot" | "few-shot";
  examples: { message: string; reply: string; tag: string }[];
  knowledgePreset: string;
  appearancePreset: string;
  ticketsPreset: string;
  webhooksPreset: string;
  integrationsPreset: string;
};

const defaultData: WizardData = {
  name: "",
  description: "",
  persona: "Customer Support",
  template: "blank",
  coreInstructions: "",
  creativity: 50,
  trainingMode: "zero-shot",
  examples: [],
  knowledgePreset: "",
  appearancePreset: "",
  ticketsPreset: "",
  webhooksPreset: "",
  integrationsPreset: "",
};

  const stepLabels = ["Basics", "Training", "Knowledge", "Appearance", "Tickets", "Webhooks", "Review"];

const personas = ["Customer Support", "Sales Assistant", "HR Rep", "Tech Support", "Concierge", "Custom"];

const templates = [
  { id: "blank", name: "Blank", desc: "Start from scratch", icon: "📄" },
  { id: "sales-agent", name: "Sales Agent", desc: "Qualify leads and close deals", icon: "💰" },
  { id: "lead-qualifier", name: "Lead Qualifier", desc: "Collect info from inbound leads", icon: "🎯" },
  { id: "hr-agent", name: "HR Agent", desc: "Handle employee inquiries", icon: "👥" },
  { id: "tech-support", name: "Tech Support", desc: "Troubleshoot technical issues", icon: "🔧" },
  { id: "concierge", name: "Concierge", desc: "Warm onboarding for new users", icon: "🤝" },
];

const personaInstructions: Record<string, string> = {
  "Customer Support": "You are a helpful customer support agent. Answer questions clearly, troubleshoot issues, and escalate when needed. Be empathetic and concise.",
  "Sales Assistant": "You are a sales assistant. Qualify leads, answer product questions, and guide prospects toward a purchase. Be persuasive but not pushy.",
  "HR Rep": "You are an HR representative. Help employees with policies, benefits, onboarding, and general workplace questions. Be professional and supportive.",
  "Tech Support": "You are a technical support specialist. Troubleshoot issues step by step, ask clarifying questions, and provide clear solutions.",
  "Concierge": "You are a friendly concierge. Welcome users warmly, guide them through features, and help them get started. Be warm and inviting.",
  Custom: "",
};

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

export default function CreateAgentPage() {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<WizardData>(defaultData);

  const handleSaveDraft = () => {
    const drafts = JSON.parse(localStorage.getItem("sayvors_agent_drafts") || "[]");
    drafts.push({ ...data, savedAt: new Date().toISOString() });
    localStorage.setItem("sayvors_agent_drafts", JSON.stringify(drafts));
    alert("Draft saved!");
  };

  const handleSaveAgent = () => {
    const agents = JSON.parse(localStorage.getItem("sayvors_agents") || "[]");
    agents.push({ ...data, id: crypto.randomUUID(), createdAt: new Date().toISOString() });
    localStorage.setItem("sayvors_agents", JSON.stringify(agents));
    alert("Agent saved!");
    window.location.href = "/dashboard/agents";
  };

  const update = <K extends keyof WizardData>(key: K, value: WizardData[K]) => {
    setData((prev) => ({ ...prev, [key]: value }));
  };

  const addExample = () => {
    setData((prev) => ({
      ...prev,
      examples: [...prev.examples, { message: "", reply: "", tag: "" }],
    }));
  };

  const removeExample = (index: number) => {
    setData((prev) => ({
      ...prev,
      examples: prev.examples.filter((_, i) => i !== index),
    }));
  };

  const updateExample = (index: number, field: "message" | "reply" | "tag", value: string) => {
    setData((prev) => ({
      ...prev,
      examples: prev.examples.map((ex, i) => (i === index ? { ...ex, [field]: value } : ex)),
    }));
  };

  const selectedTemplate = templates.find((t) => t.id === data.template);

  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Agents", href: "/dashboard/agents" }, { label: "Create Agent" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Create Agent</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Set up a new AI agent in 7 steps. No model selection here — that happens in the automation flow.</p>
      </div>

      <WizardStepper steps={stepLabels} current={step} />

      {/* Step content */}
      <div className="min-h-[400px] rounded-xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">

        {/* Step 1: Identity & Purpose (Basics) */}
        {step === 0 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Identity & Purpose</h2>
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
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Description</label>
                <input
                  type="text"
                  value={data.description}
                  onChange={(e) => update("description", e.target.value)}
                  placeholder="Short tagline for this agent"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Persona</label>
              <select
                value={data.persona}
                onChange={(e) => {
                  const p = e.target.value;
                  update("persona", p);
                  if (p !== "Custom" && personaInstructions[p]) {
                    update("coreInstructions", personaInstructions[p]);
                  }
                }}
                className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
              >
                {personas.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>

            {/* Quick Templates */}
            <div>
              <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-2">Quick Templates</label>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      update("template", t.id);
                      if (t.id !== "blank" && personaInstructions[t.id]) {
                        update("coreInstructions", personaInstructions[t.id]);
                      }
                    }}
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
              <div className="flex items-center justify-between mb-1">
                <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">
                  Core Instructions {data.template !== "blank" && <span className="text-ink/30 dark:text-fog/30">(from {selectedTemplate?.name} template)</span>}
                </label>
                <button className="flex items-center gap-1 text-[11px] font-medium text-deep-violet transition hover:text-deep-violet/80">
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                    <path d="M8 2l1.5 4.5L14 8l-4.5 1.5L8 14l-1.5-4.5L2 8l4.5-1.5L8 2z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Enhance with AI
                </button>
              </div>
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

        {/* Step 2: Training Mode */}
        {step === 1 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Training Mode</h2>

            {/* Toggle */}
            <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03] w-fit">
              <button
                onClick={() => update("trainingMode", "zero-shot")}
                className={`rounded-md px-4 py-2 text-[12px] font-medium transition ${
                  data.trainingMode === "zero-shot" ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
                }`}
              >
                Zero-shot
              </button>
              <button
                onClick={() => update("trainingMode", "few-shot")}
                className={`rounded-md px-4 py-2 text-[12px] font-medium transition ${
                  data.trainingMode === "few-shot" ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
                }`}
              >
                Few-shot
              </button>
            </div>

            {/* Zero-shot summary */}
            {data.trainingMode === "zero-shot" && (
              <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-deep-violet/[0.06] text-deep-violet">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                      <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
                      <circle cx="12" cy="12" r="10" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-[13px] font-medium text-ink dark:text-fog">Zero-shot mode</p>
                    <p className="mt-1 text-[11px] text-ink/45 dark:text-fog/45">
                      Your agent will follow the core instructions above. No example conversations needed — the agent infers behavior from the instructions alone.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Few-shot examples editor */}
            {data.trainingMode === "few-shot" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[12px] text-ink/50 dark:text-fog/50">{data.examples.length} examples</span>
                  <div className="flex gap-2">
                    <button className="rounded-lg border border-ink/[0.06] px-2.5 py-1.5 text-[11px] font-medium text-ink/50 transition hover:border-ink/[0.1] hover:text-ink dark:border-fog/[0.06] dark:text-fog/50 dark:hover:border-fog/[0.1] dark:hover:text-fog">
                      Import from conversations
                    </button>
                    <button onClick={addExample} className="flex items-center gap-1 rounded-lg bg-deep-violet px-2.5 py-1.5 text-[11px] font-semibold text-white transition hover:bg-deep-violet/90">
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                        <path d="M8 3v10M3 8h10" strokeLinecap="round" />
                      </svg>
                      Add example
                    </button>
                  </div>
                </div>

                {data.examples.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-ink/[0.1] p-8 text-center dark:border-fog/[0.1]">
                    <p className="text-[13px] text-ink/40 dark:text-fog/40">No examples yet. Add example Q&A pairs to train your agent.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {data.examples.map((ex, i) => (
                      <div key={i} className="rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[11px] font-medium text-ink/40 dark:text-fog/40">Example {i + 1}</span>
                          <button onClick={() => removeExample(i)} className="rounded p-1 text-ink/25 transition hover:bg-coral/10 hover:text-coral dark:text-fog/25">
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
                            </svg>
                          </button>
                        </div>
                        <div className="grid gap-2 sm:grid-cols-3">
                          <div>
                            <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Customer message</label>
                            <input
                              type="text"
                              value={ex.message}
                              onChange={(e) => updateExample(i, "message", e.target.value)}
                              placeholder="e.g. What's your pricing?"
                              className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Agent reply</label>
                            <input
                              type="text"
                              value={ex.reply}
                              onChange={(e) => updateExample(i, "reply", e.target.value)}
                              placeholder="e.g. We offer 3 plans..."
                              className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] text-ink/40 dark:text-fog/40 mb-1">Tag / Intent (optional)</label>
                            <input
                              type="text"
                              value={ex.tag}
                              onChange={(e) => updateExample(i, "tag", e.target.value)}
                              placeholder="e.g. pricing"
                              className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Step 3: Knowledge */}
        {step === 2 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Knowledge</h2>
            <PresetPicker
              label="Knowledge Preset"
              presets={knowledgePresets}
              selected={data.knowledgePreset}
              onSelect={(id) => update("knowledgePreset", id)}
              onCreateNew={() => {}}
            >
              <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure sources, FAQ pairs, URLs, and databank category.</p>
              </div>
            </PresetPicker>
          </div>
        )}

        {/* Step 4: Appearance */}
        {step === 3 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Appearance</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <PresetPicker
                  label="Appearance Preset"
                  presets={appearancePresets}
                  selected={data.appearancePreset}
                  onSelect={(id) => update("appearancePreset", id)}
                  onCreateNew={() => {}}
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
          </div>
        )}

        {/* Step 5: Tickets */}
        {step === 4 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Tickets</h2>
            <PresetPicker
              label="Tickets Preset"
              presets={ticketPresets}
              selected={data.ticketsPreset}
              onSelect={(id) => update("ticketsPreset", id)}
              onCreateNew={() => {}}
            >
              <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure which fields to collect from users.</p>
              </div>
            </PresetPicker>
          </div>
        )}

        {/* Step 6: Webhooks & Integrations */}
        {step === 5 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Webhooks & Integrations</h2>
            <div className="grid gap-5 lg:grid-cols-2">
              <PresetPicker
                label="Webhooks Preset"
                presets={webhookPresets}
                selected={data.webhooksPreset}
                onSelect={(id) => update("webhooksPreset", id)}
                onCreateNew={() => {}}
              >
                <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                  <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                  <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure webhook events and URL.</p>
                </div>
              </PresetPicker>
              <PresetPicker
                label="Integrations Preset"
                presets={integrationPresets}
                selected={data.integrationsPreset}
                onSelect={(id) => update("integrationsPreset", id)}
                onCreateNew={() => {}}
              >
                <div className="space-y-3 rounded-lg border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                  <input type="text" placeholder="Preset Name" className="w-full rounded border border-ink/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog" />
                  <p className="text-[10px] text-ink/30 dark:text-fog/30">Configure integrations like MCP, Google Calendar, etc.</p>
                </div>
              </PresetPicker>
            </div>
          </div>
        )}

        {/* Step 7: Review */}
        {step === 6 && (
          <div className="space-y-5">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Review</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <ReviewCard title="Identity">
                <ReviewRow label="Name" value={data.name || "—"} />
                <ReviewRow label="Description" value={data.description || "—"} />
                <ReviewRow label="Persona" value={data.persona} />
                <ReviewRow label="Template" value={selectedTemplate?.name || "—"} />
                <ReviewRow label="Creativity" value={`${data.creativity}%`} />
              </ReviewCard>
              <ReviewCard title="Training">
                <ReviewRow label="Mode" value={data.trainingMode === "zero-shot" ? "Zero-shot" : "Few-shot"} />
                <ReviewRow label="Examples" value={String(data.examples.length)} />
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
            </div>
            <div className="rounded-xl border border-deep-violet/20 bg-deep-violet/[0.04] p-4">
              <p className="text-[12px] text-ink/60 dark:text-fog/60">
                Model selection happens in the <span className="font-semibold text-deep-violet">Automation</span> flow, not here. Your agent is ready — deploy it with a model and channel in Automations.
              </p>
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
            <button onClick={handleSaveDraft} className="text-[12px] font-medium text-ink/30 transition hover:text-ink/50 dark:text-fog/30 dark:hover:text-fog/50">
              Save as Draft
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleSaveDraft} className="text-[12px] font-medium text-ink/40 transition hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60">
            Save as Draft
          </button>
          {step < 6 ? (
            <button onClick={() => setStep(step + 1)} className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">
              Next
            </button>
          ) : (
            <button onClick={handleSaveAgent} className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90">
              Save Agent
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
