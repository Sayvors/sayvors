"use client";

import { useCallback, useState, type ReactNode } from "react";
import Modal from "@/components/dashboard/media/Modal";
import type { AiVisibilityRunDetail } from "@/lib/api-ai-visibility";
import { safeHref } from "@/lib/safe-url";
import ClaimLedger from "./ClaimLedger";
import FixNextActions from "./FixNextActions";
import ResearchProvenance from "./ResearchProvenance";

const ANSWER_PREVIEW_CHARS = 600;

type Copy = {
  disclosure: string;
  answer: string;
  claimLedger: string;
  supported: string;
  contradicted: string;
  unsupported: string;
  evidence: string;
  competitors: string;
  fixNext: string;
  sources: string;
  mentioned: string;
  cited: string;
  recommended: string;
  incorrect: string;
  noActions: string;
  readFullAnswer: string;
  fullAnswer: string;
  close: string;
  howSearched: string;
  searchProvider: string;
  searchQuery: string;
  searchResults: string;
  sourcesFetched: string;
  thirdPartySources: string;
  ownedSources: string;
  socialNotChecked: string;
  publishingChecklist: string;
  publishingHint: string;
};

function Answer({
  text,
  sources,
}: {
  text: string;
  sources: AiVisibilityRunDetail["sources"];
}) {
  const byLabel = new Map(
    sources.map((source) => [source.label, source]),
  );
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-[14px] leading-7 text-[var(--ai-ink)]">
      {parts.map((part, index): ReactNode => {
        const label = part.match(/^\[(S\d+)\]$/)?.[1];
        const source = label ? byLabel.get(label) : undefined;
        const href = source ? safeHref(source.url) : null;
        return href ? (
          <a
            key={index}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="font-bold text-[var(--ai-accent)] underline"
          >
            [{label}]
          </a>
        ) : (
          part
        );
      })}
    </p>
  );
}

export default function DecisionBrief({
  detail,
  copy,
}: {
  detail: AiVisibilityRunDetail;
  copy: Copy;
}) {
  const [fullAnswerOpen, setFullAnswerOpen] = useState(false);
  const closeAnswer = useCallback(() => setFullAnswerOpen(false), []);
  const answer = detail.answer_text ?? "";
  const hasLongAnswer = answer.length > ANSWER_PREVIEW_CHARS;
  const outcomes: Array<[string, boolean | null]> = [
    [copy.mentioned, detail.mentioned],
    [copy.cited, detail.cited],
    [copy.recommended, detail.recommended],
    [copy.incorrect, detail.incorrect],
  ];
  return (
    <div className="space-y-7">
      <p className="border-s-4 border-[var(--ai-signal)] bg-[var(--ai-sunken)] px-4 py-3 text-[11px] leading-5 text-[var(--ai-ink-2)]">
        {copy.disclosure}
      </p>
      <section>
        <h3 className="ai-eyebrow">{copy.answer}</h3>
        {detail.answer_text && (
          <Answer
            text={
              hasLongAnswer
                ? `${answer.slice(0, ANSWER_PREVIEW_CHARS)}…`
                : answer
            }
            sources={detail.sources}
          />
        )}
        {hasLongAnswer && (
          <button
            type="button"
            onClick={() => setFullAnswerOpen(true)}
            className="mt-2 min-h-11 rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[12px] font-bold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
          >
            {copy.readFullAnswer}
          </button>
        )}
      </section>
      <Modal
        open={fullAnswerOpen}
        onClose={closeAnswer}
        title={copy.fullAnswer}
        closeLabel={copy.close}
      >
        <Answer text={answer} sources={detail.sources} />
      </Modal>
      <section className="flex flex-wrap gap-2" aria-label={copy.answer}>
        {outcomes.map(([label, value]) => {
          const danger = label === copy.incorrect && value;
          return (
            <span
              key={label}
              className={`rounded-full border px-3 py-1.5 text-[10px] font-bold ${
                value
                  ? danger
                    ? "border-[var(--ai-danger)] text-[var(--ai-danger)]"
                    : "border-[var(--ai-ok)] text-[var(--ai-ok)]"
                  : "border-[var(--ai-line)] text-[var(--ai-muted)]"
              }`}
            >
              {label}: {value ? "✓" : "—"}
            </span>
          );
        })}
      </section>
      <ResearchProvenance
        coverage={detail.evidence_coverage}
        sources={detail.sources}
        copy={copy}
      />
      <section>
        <h3 className="ai-eyebrow mb-3">{copy.claimLedger}</h3>
        <ClaimLedger
          claims={detail.claims}
          sources={detail.sources}
          copy={copy}
        />
      </section>
      {detail.competitor_mentions.length > 0 && (
        <section>
          <h3 className="ai-eyebrow mb-3">{copy.competitors}</h3>
          {detail.competitor_mentions.map((row, index) => (
            <p key={index} className="text-[12px] text-[var(--ui-ink-2)]">
              {row.name}: {row.quote}
            </p>
          ))}
        </section>
      )}
      <section>
        <h3 className="ai-eyebrow mb-3">{copy.fixNext}</h3>
        {detail.actions.length > 0 ? (
          <FixNextActions actions={detail.actions} label={copy.fixNext} />
        ) : (
          <p className="text-[12px] leading-5 text-[var(--ai-ink-2)]">{copy.noActions}</p>
        )}
      </section>
      <section>
        <h3 className="ai-eyebrow mb-3">{copy.sources}</h3>
        {detail.sources.map((source) => {
          const href = safeHref(source.url);
          return (
            <p
              key={source.id}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-[var(--ai-line)] py-2 text-[11px] leading-5 text-[var(--ai-ink-2)] last:border-0"
            >
              <span className="font-mono text-[10px] font-bold text-[var(--ai-signal)]">
                {source.label}
              </span>
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="font-bold text-[var(--ai-accent)] underline"
                >
                  {source.title ?? source.url}
                </a>
              ) : (
                source.title ?? source.url
              )}
              {source.fetch_error ? ` · ${source.fetch_error}` : ""}
            </p>
          );
        })}
      </section>
    </div>
  );
}
