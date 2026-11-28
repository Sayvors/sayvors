"use client";

import { useCallback, useState } from "react";
import Modal from "@/components/dashboard/media/Modal";
import type { AiVisibilityRunDetail } from "@/lib/api-ai-visibility";
import type { Dict } from "@/lib/i18n/en";
import { Answer } from "./DecisionBrief";
import EvidenceDrawer from "./EvidenceDrawer";
import FixNextActions from "./FixNextActions";
import ResearchProvenance from "./ResearchProvenance";

const ANSWER_PREVIEW_CHARS = 600;

export default function ResearchBrief({
  detail,
  copy,
}: {
  detail: AiVisibilityRunDetail;
  copy: Dict["aiVisibility"];
}) {
  const [fullAnswerOpen, setFullAnswerOpen] = useState(false);
  const closeAnswer = useCallback(() => setFullAnswerOpen(false), []);
  const answer = detail.answer_text ?? "";
  const hasLongAnswer = answer.length > ANSWER_PREVIEW_CHARS;
  const verdict = detail.incorrect
    ? copy.incorrectProof
    : detail.recommended
      ? copy.strongProof
      : detail.cited || detail.mentioned
        ? copy.limitedProof
        : copy.noProof;
  const outcomes: Array<[string, boolean | null]> = [
    [copy.mentioned, detail.mentioned],
    [copy.cited, detail.cited],
    [copy.recommended, detail.recommended],
    [copy.incorrect, detail.incorrect],
  ];

  return (
    <article className="space-y-5">
      <header className="rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-surface)] p-5 shadow-[var(--ai-shadow-panel)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="ai-eyebrow">{copy.decisionBrief}</p>
            <h2 className="mt-1 text-[22px] font-bold leading-tight tracking-[-0.02em] text-[var(--ai-ink)]">{verdict}</h2>
          </div>
          <span className="rounded-full bg-[var(--ai-sunken)] px-3 py-1 font-mono text-[10px] font-bold text-[var(--ai-muted)]">
            {copy.evidenceSummary(detail.claims.length, detail.sources.length)}
          </span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2" aria-label={copy.answer}>
          {outcomes.map(([label, value]) => (
            <span
              key={label}
              className={`rounded-full border px-3 py-1.5 text-[10px] font-bold ${
                value
                  ? label === copy.incorrect
                    ? "border-[var(--ai-danger)] text-[var(--ai-danger)]"
                    : "border-[var(--ai-ok)] text-[var(--ai-ok)]"
                  : "border-[var(--ai-line)] text-[var(--ai-muted)]"
              }`}
            >
              {label}: {value ? "✓" : "—"}
            </span>
          ))}
        </div>
      </header>

      <section className="rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-surface)] p-5">
        <h3 className="ai-eyebrow">{copy.answer}</h3>
        {detail.answer_text ? (
          <Answer text={hasLongAnswer ? `${answer.slice(0, ANSWER_PREVIEW_CHARS)}…` : answer} sources={detail.sources} />
        ) : (
          <p className="mt-2 text-[13px] text-[var(--ai-muted)]">{copy.noEvidence}</p>
        )}
        {hasLongAnswer && (
          <button
            type="button"
            onClick={() => setFullAnswerOpen(true)}
            className="mt-3 min-h-11 rounded-[var(--ai-radius-control)] border border-[var(--ai-line)] px-3 py-2 text-[12px] font-bold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ai-accent)]"
          >
            {copy.readFullAnswer}
          </button>
        )}
      </section>

      <Modal open={fullAnswerOpen} onClose={closeAnswer} title={copy.fullAnswer} closeLabel={copy.close}>
        <Answer text={answer} sources={detail.sources} />
      </Modal>

      <section className="rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-surface)] p-5">
        <h3 className="ai-eyebrow mb-3">{copy.fixNext}</h3>
        {detail.actions.length > 0 ? (
          <FixNextActions actions={detail.actions.slice(0, 3)} label={copy.fixNext} />
        ) : (
          <p className="text-[12px] text-[var(--ai-muted)]">{copy.noActions}</p>
        )}
      </section>

      <EvidenceDrawer detail={detail} copy={copy} />
      <ResearchProvenance coverage={detail.evidence_coverage} sources={detail.sources} copy={copy} />
    </article>
  );
}
