"use client";

import { useEffect, useState } from "react";
import type { Dict } from "@/lib/i18n/en";

const STAGE_PERCENT: Record<string, number> = {
  queued: 5,
  searching: 25,
  fetching: 55,
  reading: 70,
  validating: 82,
  writing: 92,
  completed: 100,
  insufficient_evidence: 100,
};

export default function ResearchProgress({
  status,
  completed,
  total,
  elapsedSeconds,
  createdAt,
  copy,
}: {
  status: string;
  completed?: number;
  total?: number;
  elapsedSeconds?: number;
  createdAt?: string;
  copy: Dict["aiVisibility"];
}) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!createdAt) return;
    const update = () => setNow(Date.now());
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [createdAt]);
  const startedAt = createdAt ? new Date(createdAt).getTime() : null;
  const measuredElapsed = now !== null && startedAt !== null && Number.isFinite(startedAt)
    ? Math.max(0, Math.floor((now - startedAt) / 1000))
    : elapsedSeconds;
  const measured = typeof completed === "number" && typeof total === "number" && total > 0;
  const percent = measured
    ? Math.min(100, Math.max(0, Math.round((completed / total) * 100)))
    : Math.min(100, Math.max(0, STAGE_PERCENT[status] ?? 0));
  const step =
    status === "completed" || status === "insufficient_evidence"
      ? copy.ready
      : ["reading", "validating", "writing"].includes(status)
        ? copy.checking
        : status === "failed" || status === "ambiguous"
          ? copy.stopped
          : copy.scanning;

  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-semibold text-[var(--ai-ink-2)]">
        <span>{step}</span>
        <span aria-hidden="true" className="font-mono text-[10px] text-[var(--ai-muted)]">
          {typeof measuredElapsed === "number" ? `${measuredElapsed}s` : ""}
        </span>
      </div>
      <progress
        className="h-2 w-full overflow-hidden rounded-full [&::-webkit-progress-bar]:bg-[var(--ai-sunken)] [&::-webkit-progress-value]:bg-[var(--ai-signal)] [&::-moz-progress-bar]:bg-[var(--ai-signal)]"
        value={percent}
        max={100}
        aria-label={copy.progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${step}, ${percent}%`}
      >
        {percent}%
      </progress>
    </div>
  );
}
