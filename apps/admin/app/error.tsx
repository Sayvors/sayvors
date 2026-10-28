"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md space-y-3 text-center">
        <h1 className="text-[18px] font-bold">Something went wrong</h1>
        <p className="text-[13px] text-ink/60">
          An unexpected error occurred. It has been reported.
        </p>
        <button
          onClick={() => reset()}
          className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
