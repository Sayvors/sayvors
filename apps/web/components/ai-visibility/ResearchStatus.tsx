import type { Dict } from "@/lib/i18n/en";

type Copy = Dict["aiVisibility"];

export default function ResearchStatus({
  status,
  phase,
  version,
  completed,
  total,
  error,
  copy,
}: {
  status: string;
  phase: string | null;
  version: number;
  completed: number;
  total: number;
  error: string | null;
  copy: Copy;
}) {
  const active = status === "generating" || status === "running";
  if (!active && status !== "failed" && status !== "partial") return null;
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const label =
    phase === "adaptive"
      ? copy.backgroundAdaptive
      : status === "generating"
        ? copy.backgroundPreparing
        : copy.backgroundRunning;
  return (
    <section
      role="status"
      aria-live="polite"
      className="rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-surface)] p-4 shadow-[var(--ai-shadow-panel)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span
            className={`mt-1 h-2.5 w-2.5 rounded-full ${
              active ? "animate-pulse bg-[var(--ai-signal)]" : "bg-[var(--ai-danger)]"
            }`}
            aria-hidden="true"
          />
          <div>
            <p className="text-[13px] font-bold text-[var(--ai-ink)]">
              {active ? copy.backgroundTitle : status === "partial" ? copy.researchPartial : copy.researchFailed}
            </p>
            <p className="mt-1 max-w-2xl text-[12px] leading-5 text-[var(--ai-ink-2)]">
              {active ? copy.backgroundBody : error || (status === "partial" ? copy.researchPartial : copy.researchFailed)}
            </p>
          </div>
        </div>
        <span className="rounded-full bg-[var(--ai-sunken)] px-3 py-1 font-mono text-[10px] font-bold text-[var(--ai-muted)]">
          {copy.version} {version}
        </span>
      </div>
      {active && (
        <div className="mt-4">
          <div className="flex items-center justify-between gap-3 text-[10px] font-semibold text-[var(--ai-muted)]">
            <span>{label}</span>
            <span>{completed}/{total} {copy.questionsProgress}</span>
          </div>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--ai-sunken)]"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-label={label}
          >
            <div
              className="h-full rounded-full bg-[var(--ai-signal)] transition-[width] duration-500"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
