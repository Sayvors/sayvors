"use client";

export default function WizardStepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="flex items-center">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={i} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold transition ${
                  done
                    ? "bg-deep-violet text-white"
                    : active
                      ? "border-2 border-deep-violet text-deep-violet"
                      : "border border-ink/10 text-ink/30 dark:border-fog/10 dark:text-fog/30"
                }`}
              >
                {done ? (
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                    <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={`mt-1.5 text-[10px] font-medium whitespace-nowrap ${
                  active ? "text-deep-violet" : done ? "text-ink/50 dark:text-fog/50" : "text-ink/25 dark:text-fog/25"
                }`}
              >
                {label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div
                className={`mx-1 mb-5 h-px w-6 ${i < current ? "bg-deep-violet" : "bg-ink/10 dark:bg-fog/10"}`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
