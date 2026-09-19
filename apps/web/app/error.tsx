"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-coral/10 text-coral">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
      </div>
      <div className="text-center">
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Something went wrong</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">
          {error.message || "An unexpected error occurred."}
        </p>
      </div>
      <button
        onClick={reset}
        className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
      >
        Try again
      </button>
    </div>
  );
}
