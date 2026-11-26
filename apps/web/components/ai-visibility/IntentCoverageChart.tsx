import type { AiVisibilityGeneratedQuestion } from "@/lib/api-ai-visibility";
import type { Dict } from "@/lib/i18n/en";

type Copy = Dict["aiVisibility"];

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function IntentCoverageChart({
  questions,
  copy,
}: {
  questions: AiVisibilityGeneratedQuestion[];
  copy: Copy;
}) {
  if (questions.length === 0) return null;
  const groups = new Map<string, { total: number; done: number }>();
  for (const question of questions) {
    const row = groups.get(question.customer_intent) ?? { total: 0, done: 0 };
    row.total += 1;
    if (question.status === "completed" || question.status === "insufficient_evidence") {
      row.done += 1;
    }
    groups.set(question.customer_intent, row);
  }
  const rows = [...groups.entries()].sort((a, b) => b[1].total - a[1].total);
  return (
    <section
      aria-label={copy.intentCoverage}
      className="rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-surface)] p-4 shadow-[var(--ai-shadow-panel)]"
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="ai-eyebrow">{copy.intentCoverage}</p>
          <p className="mt-1 text-[11px] text-[var(--ai-muted)]">
            {copy.intentCoverageCaption}
          </p>
        </div>
      </div>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {rows.map(([intent, counts]) => {
          const percent = counts.total > 0 ? Math.round((counts.done / counts.total) * 100) : 0;
          return (
            <li key={intent}>
              <div className="flex items-center justify-between gap-3 text-[11px]">
                <span className="font-semibold text-[var(--ai-ink-2)]">{humanize(intent)}</span>
                <span className="font-mono text-[10px] font-bold text-[var(--ai-muted)]">
                  {counts.done}/{counts.total}
                </span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--ai-sunken)]">
                <div
                  className="h-full rounded-full bg-[var(--ai-accent)]"
                  style={{ width: `${percent}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
