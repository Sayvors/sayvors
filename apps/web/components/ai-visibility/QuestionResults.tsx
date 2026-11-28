import type { AiVisibilityGeneratedQuestion } from "@/lib/api-ai-visibility";
import type { Dict } from "@/lib/i18n/en";

type Copy = Dict["aiVisibility"];

function intentLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export default function QuestionResults({
  questions,
  selectedRunId,
  onSelect,
  copy,
  hint,
}: {
  questions: AiVisibilityGeneratedQuestion[];
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  copy: Copy;
  hint?: string;
}) {
  if (questions.length === 0) return null;
  return (
    <section aria-label={copy.questionsTitle} className="space-y-3">
      <div>
        <p className="ai-eyebrow">{copy.questionsTitle}</p>
        <p className="mt-1 text-[11px] text-[var(--ai-muted)]">{hint ?? copy.questionsHint}</p>
      </div>
      <ul className="space-y-2">
        {questions.map((question) => {
          const selected = question.run_id != null && question.run_id === selectedRunId;
          const stage =
            copy.stages[question.status as keyof typeof copy.stages] ?? question.status;
          const canOpen = Boolean(question.run_id);
          return (
            <li key={`${question.query_set_id}:${question.id}`}>
              <button
                type="button"
                disabled={!canOpen}
                onClick={() => question.run_id && onSelect(question.run_id)}
                aria-pressed={selected}
                className={`w-full rounded-[var(--ai-radius-control)] border px-4 py-3 text-start transition-colors focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ai-accent)] ${
                  selected
                    ? "border-[var(--ai-accent)] bg-[var(--ai-sunken)]"
                    : "border-[var(--ai-line)] bg-[var(--ai-surface)] hover:bg-[var(--ai-sunken)]"
                } ${canOpen ? "" : "cursor-default opacity-70"}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <p className="min-w-0 flex-1 text-[13px] font-semibold leading-6 text-[var(--ai-ink)]">
                    {question.question_text}
                  </p>
                  <span className="rounded-full bg-[var(--ai-sunken)] px-2.5 py-1 font-mono text-[9px] font-bold uppercase text-[var(--ai-muted)]">
                    {question.language} · {question.research_priority}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--ai-muted)]">
                  {question.channel_label && (
                    <>
                      <span className="font-semibold text-[var(--ai-ink-2)]">{question.channel_label}</span>
                      <span aria-hidden="true">·</span>
                    </>
                  )}
                  <span>{intentLabel(question.customer_intent)}</span>
                  <span aria-hidden="true">·</span>
                  <span>{stage}</span>
                  {question.mentioned != null && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>
                        {copy.mentioned}: {question.mentioned ? "✓" : "—"} · {copy.cited}:{" "}
                        {question.cited ? "✓" : "—"}
                      </span>
                    </>
                  )}
                  {canOpen && <span className="font-bold text-[var(--ai-accent)]">{copy.openBrief} ↗</span>}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
