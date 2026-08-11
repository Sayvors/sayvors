"use client";

export type ProcessingStep = "sending" | "chunking" | "vectorizing" | "storing" | "finalizing" | "done";

export interface ProcessingJob {
  id: string;
  filename: string;
  currentStep: ProcessingStep;
  progress: number;
}

interface ProcessingPanelProps {
  jobs: ProcessingJob[];
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
}

const STEPS: { id: ProcessingStep; label: string }[] = [
  { id: "sending", label: "Sending" },
  { id: "chunking", label: "Chunking" },
  { id: "vectorizing", label: "Vectorizing" },
  { id: "storing", label: "Storing" },
  { id: "finalizing", label: "Finalizing" },
  { id: "done", label: "Done" },
];

const STEP_COLORS: Record<ProcessingStep, string> = {
  sending: "bg-sky-400",
  chunking: "bg-amber-400",
  vectorizing: "bg-deep-violet",
  storing: "bg-emerald-500",
  finalizing: "bg-emerald-500",
  done: "bg-emerald-500",
};

export default function ProcessingPanel({ jobs, isOpen, onToggle, onClose }: ProcessingPanelProps) {
  if (jobs.length === 0) return null;

  const activeJobs = jobs.filter((j) => j.currentStep !== "done");
  const totalActive = activeJobs.length;

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {/* Collapsed pill */}
      {!isOpen && (
        <button
          onClick={onToggle}
          className="flex items-center gap-2 rounded-full bg-deep-violet px-4 py-2.5 text-[12px] font-semibold text-white shadow-lg transition hover:bg-deep-violet/90"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-white" />
          </span>
          <span>{totalActive} job{totalActive !== 1 ? "s" : ""}</span>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}

      {/* Expanded panel */}
      {isOpen && (
        <div className="w-80 rounded-2xl border border-ink/[0.08] bg-white shadow-2xl dark:border-fog/[0.08] dark:bg-ink overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-ink/[0.06] px-4 py-3 dark:border-fog/[0.06]">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-deep-violet opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-deep-violet" />
              </span>
              <span className="text-[13px] font-semibold text-ink dark:text-fog">Jobs</span>
              <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[10px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                {jobs.length}
              </span>
            </div>
            <button
              onClick={onClose}
              className="rounded-md p-1 text-ink/30 transition hover:text-ink/60 dark:text-fog/30 dark:hover:text-fog/60"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>

          {/* Jobs list */}
          <div className="max-h-80 overflow-y-auto">
            {jobs.map((job) => {
              const currentStepIndex = STEPS.findIndex((s) => s.id === job.currentStep);

              return (
                <div key={job.id} className="border-b border-ink/[0.04] px-4 py-3 dark:border-fog/[0.04] last:border-b-0">
                  {/* Filename + progress */}
                  <div className="flex items-start justify-between mb-2">
                    <p className="text-[12px] font-medium text-ink dark:text-fog truncate pr-2">{job.filename}</p>
                    <span className="text-[11px] font-bold text-deep-violet shrink-0">{Math.round(job.progress)}%</span>
                  </div>

                  {/* Steps */}
                  <div className="space-y-1.5">
                    {STEPS.map((step, i) => {
                      const isCompleted = i < currentStepIndex;
                      const isCurrent = step.id === job.currentStep;

                      return (
                        <div key={step.id} className="flex items-center gap-2">
                          <div className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                            isCompleted ? "bg-emerald-500 text-white" :
                            isCurrent ? "bg-deep-violet text-white" :
                            "bg-ink/[0.06] text-ink/30 dark:bg-fog/[0.06] dark:text-fog/30"
                          }`}>
                            {isCompleted ? (
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="h-2.5 w-2.5">
                                <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            ) : (
                              <span className="text-[8px] font-bold">{i + 1}</span>
                            )}
                          </div>
                          <span className={`text-[10px] font-medium ${
                            isCompleted ? "text-emerald-600 dark:text-emerald-400" :
                            isCurrent ? "text-ink dark:text-fog" :
                            "text-ink/30 dark:text-fog/30"
                          }`}>
                            {step.label}
                          </span>
                          {isCurrent && (
                            <span className="ml-auto relative flex h-1.5 w-1.5">
                              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-deep-violet opacity-75" />
                              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-deep-violet" />
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Progress bar */}
                  <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                    <div
                      className="h-full rounded-full bg-deep-violet transition-all duration-500"
                      style={{ width: `${job.progress}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
