"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import Breadcrumbs from "@/components/Breadcrumbs";
import WizardStepper from "@/components/agents/WizardStepper";
import WizardTips from "@/components/agents/wizard/WizardTips";
import StepIdentity from "@/components/agents/wizard/StepIdentity";
import StepInstructions from "@/components/agents/wizard/StepInstructions";
import StepKnowledge from "@/components/agents/wizard/StepKnowledge";
import StepSave from "@/components/agents/wizard/StepSave";
import { defaultWizardData, WIZARD_STEPS, type WizardData } from "@/lib/agent-wizard-data";

export default function CreateAgentPage() {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<WizardData>(defaultWizardData);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");

  // Auto-save draft
  useEffect(() => {
    const timer = setTimeout(() => {
      if (data.name || data.coreInstructions) {
        localStorage.setItem("sayvors_agent_draft", JSON.stringify(data));
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [data]);

  // Load draft on mount
  useEffect(() => {
    const draft = localStorage.getItem("sayvors_agent_draft");
    if (draft) {
      try {
        setData(JSON.parse(draft));
      } catch {}
    }
  }, []);

  // Keyboard shortcut: Ctrl+S / Cmd+S to save
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSaveDraft();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [data]);

  const update = useCallback(<K extends keyof WizardData>(key: K, value: WizardData[K]) => {
    setData((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleSaveDraft = () => {
    setSaveStatus("saving");
    localStorage.setItem("sayvors_agent_draft", JSON.stringify(data));
    setTimeout(() => {
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    }, 500);
  };

  const handleSaveAgent = () => {
    const agents = JSON.parse(localStorage.getItem("sayvors_agents") || "[]");
    agents.push({ ...data, id: crypto.randomUUID(), createdAt: new Date().toISOString(), status: "active" });
    localStorage.setItem("sayvors_agents", JSON.stringify(agents));
    localStorage.removeItem("sayvors_agent_draft");
    window.location.href = "/dashboard/agents";
  };

  const markCompleteAndNext = () => {
    setCompletedSteps((prev) => [...prev, step]);
    if (step < WIZARD_STEPS.length - 1) setStep(step + 1);
  };

  const goBack = () => {
    if (step > 0) setStep(step - 1);
  };

  const goToStep = (s: number) => setStep(s);

  const isLastStep = step === WIZARD_STEPS.length - 1;
  const canProceed = step === 0 ? data.name.trim().length > 0 : true;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-ink/[0.04] px-6 py-3 dark:border-fog/[0.04]">
        <div>
          <Breadcrumbs items={[{ label: "Agents", href: "/dashboard/agents" }, { label: "Create Agent" }]} />
          <h1 className="mt-1 text-[18px] font-bold text-ink dark:text-fog">Create Agent</h1>
        </div>
        <div className="flex items-center gap-3">
          {saveStatus === "saved" && (
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-emerald-600">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Saved
            </span>
          )}
          {saveStatus === "saving" && (
            <span className="text-[11px] text-ink/40 dark:text-fog/40">Saving...</span>
          )}
          <button
            onClick={handleSaveDraft}
            className="flex items-center gap-1.5 rounded-lg border border-ink/[0.08] px-3 py-1.5 text-[12px] font-medium text-ink/60 transition hover:bg-ink/[0.04] dark:border-fog/[0.08] dark:text-fog/60 dark:hover:bg-fog/[0.04]"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
              <path d="M13 1H3a1 1 0 00-1 1v12a1 1 0 001 1h10a1 1 0 001-1V4l-3-3z" strokeLinecap="round" />
              <path d="M11 1v3H5V1M5 9h6M5 12h4" strokeLinecap="round" />
            </svg>
            Save Draft
          </button>
          <Link
            href="/dashboard/agents"
            className="rounded-lg border border-ink/[0.08] px-3 py-1.5 text-[12px] font-medium text-ink/40 transition hover:text-ink/60 dark:border-fog/[0.08] dark:text-fog/40 dark:hover:text-fog/60"
          >
            Exit
          </Link>
        </div>
      </div>

      {/* Progress */}
      <div className="border-b border-ink/[0.04] px-6 py-4 dark:border-fog/[0.04]">
        <WizardStepper steps={WIZARD_STEPS} current={step} completedSteps={completedSteps} />
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          {step === 0 && <StepIdentity data={data} update={update} />}
          {step === 1 && <StepInstructions data={data} update={update} />}
          {step === 2 && <StepKnowledge data={data} update={update} />}
          {step === 3 && <StepSave data={data} update={update} />}
        </div>
        <WizardTips step={step} steps={WIZARD_STEPS} />
      </div>

      {/* Bottom navigation */}
      <div className="flex items-center justify-between border-t border-ink/[0.04] px-6 py-3 dark:border-fog/[0.04]">
        <div>
          {step > 0 ? (
            <button onClick={goBack} className="flex items-center gap-1.5 rounded-lg border border-ink/[0.08] px-4 py-2 text-[12px] font-medium text-ink/60 transition hover:bg-ink/[0.04] dark:border-fog/[0.08] dark:text-fog/60 dark:hover:bg-fog/[0.04]">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back
            </button>
          ) : (
            <div />
          )}
        </div>

        <div className="flex items-center gap-2">
          {!WIZARD_STEPS[step].required && (
            <button onClick={markCompleteAndNext} className="rounded-lg px-4 py-2 text-[12px] font-medium text-ink/40 transition hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60">
              Skip
            </button>
          )}

          {!isLastStep ? (
            <button
              onClick={markCompleteAndNext}
              disabled={!canProceed}
              className="flex items-center gap-1.5 rounded-lg bg-deep-violet px-5 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            >
              Continue
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M6 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ) : (
            <button
              onClick={handleSaveAgent}
              disabled={!data.name.trim()}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-deep-violet to-magenta px-5 py-2 text-[12px] font-semibold text-white transition hover:shadow-md hover:shadow-deep-violet/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Save Agent
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
