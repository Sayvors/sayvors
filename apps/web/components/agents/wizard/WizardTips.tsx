import type { StepDef } from "@/lib/agent-wizard-data";

const tipsByStep: Record<number, string[]> = {
  0: [
    "Choose a descriptive name so you can identify this agent easily.",
    "Pick a persona that matches your use case — it pre-fills instructions.",
  ],
  1: [
    "Be specific about tone, rules, and what the agent should do.",
    "Few-shot examples help the agent learn exact response patterns.",
  ],
  2: [
    "More knowledge = better answers. Upload FAQs, docs, or policies.",
    "You can skip this step and add knowledge later.",
  ],
  3: [
    "Match the widget to your brand colors and font.",
    "The welcome message sets the first impression.",
  ],
  4: [
    "Review everything before deploying. You can always edit later.",
    "Deploying to a channel activates the agent for that channel's conversations.",
  ],
};

export default function WizardTips({ step, steps }: { step: number; steps: StepDef[] }) {
  const tips = tipsByStep[step] || [];

  return (
    <div className="hidden w-64 shrink-0 border-l border-ink/[0.04] bg-fog/30 p-4 dark:border-fog/[0.04] dark:bg-ink/30 lg:block">
      <div className="space-y-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/25 dark:text-fog/25">Current Step</p>
          <p className="mt-1 text-[13px] font-medium text-ink dark:text-fog">{steps[step].label}</p>
          <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">{steps[step].description}</p>
        </div>

        <div className="h-px bg-ink/[0.06] dark:bg-fog/[0.06]" />

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/25 dark:text-fog/25">Tips</p>
          <ul className="mt-2 space-y-2">
            {tips.map((tip, i) => (
              <li key={i} className="text-[11px] text-ink/45 dark:text-fog/45">{tip}</li>
            ))}
          </ul>
        </div>

        <div className="h-px bg-ink/[0.06] dark:bg-fog/[0.06]" />

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/25 dark:text-fog/25">Keyboard Shortcuts</p>
          <div className="mt-2 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-ink/30 dark:text-fog/30">Save draft</span>
              <kbd className="rounded border border-ink/[0.08] bg-white px-1 py-0.5 text-[9px] font-medium text-ink/30 dark:border-fog/[0.08] dark:bg-ink dark:text-fog/30">Ctrl+S</kbd>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
