"use client";

interface Step {
  label: string;
  description: string;
  required: boolean;
  recommended?: boolean;
}

interface WizardStepperProps {
  steps: Step[];
  current: number;
  completedSteps: number[];
}

export default function WizardStepper({ steps, current, completedSteps }: WizardStepperProps) {
  const progress = ((current) / (steps.length - 1)) * 100;

  return (
    <div className="space-y-4">
      {/* Progress bar */}
      <div className="relative">
        <div className="h-1 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-deep-violet to-magenta transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="absolute -top-1 left-0 h-3 w-3 rounded-full border-2 border-deep-violet bg-white transition-all duration-500 dark:bg-ink" style={{ left: `calc(${progress}% - 6px)` }} />
      </div>

      {/* Step labels */}
      <div className="flex items-start justify-between">
        {steps.map((step, i) => {
          const isDone = completedSteps.includes(i);
          const isCurrent = i === current;
          const isFuture = i > current;

          return (
            <div key={i} className="flex flex-1 flex-col items-center text-center">
              {/* Step indicator */}
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-semibold transition-all duration-200 ${
                  isDone
                    ? "bg-deep-violet text-white shadow-sm shadow-deep-violet/20"
                    : isCurrent
                      ? "border-2 border-deep-violet bg-deep-violet/5 text-deep-violet shadow-sm shadow-deep-violet/10"
                      : "border border-ink/10 text-ink/30 dark:border-fog/10 dark:text-fog/30"
                }`}
              >
                {isDone ? (
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5">
                    <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  i + 1
                )}
              </div>

              {/* Label */}
              <span
                className={`mt-2 text-[11px] font-medium leading-tight ${
                  isCurrent ? "text-deep-violet" : isDone ? "text-ink/60 dark:text-fog/60" : "text-ink/30 dark:text-fog/30"
                }`}
              >
                {step.label}
              </span>

              {/* Badge */}
              <div className="mt-1">
                {step.required && !isDone && (
                  <span className="inline-flex items-center rounded-full bg-coral/10 px-1.5 py-0.5 text-[8px] font-semibold text-coral">
                    Required
                  </span>
                )}
                {step.recommended && !isDone && !step.required && (
                  <span className="inline-flex items-center rounded-full bg-amber-400/10 px-1.5 py-0.5 text-[8px] font-semibold text-amber-600">
                    Recommended
                  </span>
                )}
                {!step.required && !step.recommended && !isDone && (
                  <span className="inline-flex items-center rounded-full bg-ink/[0.04] px-1.5 py-0.5 text-[8px] font-medium text-ink/30 dark:bg-fog/[0.04] dark:text-fog/30">
                    Optional
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
