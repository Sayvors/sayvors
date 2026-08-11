import type { StepProps } from "@/lib/agent-wizard-data";

export default function StepSave({ data }: StepProps) {
  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div className="text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-green-400 to-emerald-500 text-white shadow-lg shadow-green-400/20">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <path d="M12 2l1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2z" />
          </svg>
        </div>
        <h2 className="mt-4 text-[18px] font-bold text-ink dark:text-fog">Ready to save?</h2>
        <p className="mt-1.5 text-[13px] text-ink/45 dark:text-fog/45">Review your agent&apos;s configuration, then hit save.</p>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-ink/[0.06] bg-fog/50 p-4 dark:bg-ink/50 dark:border-fog/[0.06]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Name</span>
            <span className="text-[13px] font-semibold text-ink dark:text-fog">{data.name || "Unnamed Agent"}</span>
          </div>
        </div>

        <div className="rounded-xl border border-ink/[0.06] bg-fog/50 p-4 dark:bg-ink/50 dark:border-fog/[0.06]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Persona</span>
            <span className="text-[13px] font-semibold text-ink dark:text-fog">{data.persona}</span>
          </div>
        </div>

        <div className="rounded-xl border border-ink/[0.06] bg-fog/50 p-4 dark:bg-ink/50 dark:border-fog/[0.06]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Creativity</span>
            <span className="text-[13px] font-semibold text-ink dark:text-fog">{data.creativity}%</span>
          </div>
        </div>

        <div className="rounded-xl border border-ink/[0.06] bg-fog/50 p-4 dark:bg-ink/50 dark:border-fog/[0.06]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Training</span>
            <span className="text-[13px] font-semibold text-ink dark:text-fog">{data.trainingMode === "zero-shot" ? "Zero-shot" : `Few-shot (${data.examples.length} examples)`}</span>
          </div>
        </div>

        {data.coreInstructions && (
          <div className="rounded-xl border border-ink/[0.06] bg-fog/50 p-4 dark:bg-ink/50 dark:border-fog/[0.06]">
            <span className="block text-[11px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30 mb-2">Instructions</span>
            <p className="text-[12px] leading-relaxed text-ink/60 dark:text-fog/60 line-clamp-3">{data.coreInstructions}</p>
          </div>
        )}
      </div>
    </div>
  );
}
