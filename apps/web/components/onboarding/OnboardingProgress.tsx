"use client";

import Link from "next/link";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  stepLabels: string[];
}

export default function OnboardingProgress({ currentStep, totalSteps, stepLabels }: OnboardingProgressProps) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: totalSteps }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div
            className={`flex h-8 w-8 items-center justify-center rounded-full text-[12px] font-bold transition-all ${
              i < currentStep
                ? "bg-deep-violet text-white"
                : i === currentStep
                ? "bg-deep-violet/20 text-deep-violet ring-2 ring-deep-violet"
                : "bg-ink/[0.06] text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40"
            }`}
          >
            {i < currentStep ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : (
              i + 1
            )}
          </div>
          {i < totalSteps - 1 && (
            <div className={`h-0.5 w-8 rounded-full transition-all ${i < currentStep ? "bg-deep-violet" : "bg-ink/[0.06] dark:bg-fog/[0.06]"}`} />
          )}
        </div>
      ))}
      <span className="ml-2 text-[12px] text-ink/40 dark:text-fog/40">
        {stepLabels[currentStep]}
      </span>
    </div>
  );
}
