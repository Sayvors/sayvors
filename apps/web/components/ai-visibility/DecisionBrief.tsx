import type { ReactNode } from "react";
import type { AiVisibilityRunDetail } from "@/lib/api-ai-visibility";
import { safeHref } from "@/lib/safe-url";
import ClaimLedger from "./ClaimLedger";
import FixNextActions from "./FixNextActions";

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
};

function Answer({
  text,
  sources,
}: {
  text: string;
  sources: AiVisibilityRunDetail["sources"];
}) {
  const byLabel = new Map(
    sources.map((source) => [`S${source.position + 1}`, source]),
  );
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-[13px] leading-6 text-[var(--ui-ink)]">
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
            className="font-bold text-[var(--ui-ink)] underline"
          >
            {label}
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
  const outcomes: Array<[string, boolean | null]> = [
    [copy.mentioned, detail.mentioned],
    [copy.cited, detail.cited],
    [copy.recommended, detail.recommended],
    [copy.incorrect, detail.incorrect],
  ];
  return (
    <div className="space-y-5">
      <p className="rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[11px] text-[var(--ui-ink-2)]">
        {copy.disclosure}
      </p>
      <section>
        <h3 className="text-[14px] font-bold">{copy.answer}</h3>
        {detail.answer_text && (
          <Answer text={detail.answer_text} sources={detail.sources} />
        )}
      </section>
      <section className="flex flex-wrap gap-2" aria-label={copy.answer}>
        {outcomes.map(([label, value]) => {
          const danger = label === copy.incorrect && value;
          return (
            <span
              key={label}
              className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                value
                  ? danger
                    ? "bg-red-100 text-red-800"
                    : "bg-emerald-100 text-emerald-800"
                  : "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]"
              }`}
            >
              {label}: {value ? "✓" : "—"}
            </span>
          );
        })}
      </section>
      <section>
        <h3 className="mb-2 text-[14px] font-bold">{copy.claimLedger}</h3>
        <ClaimLedger
          claims={detail.claims}
          sources={detail.sources}
          copy={copy}
        />
      </section>
      {detail.competitor_mentions.length > 0 && (
        <section>
          <h3 className="mb-2 text-[14px] font-bold">{copy.competitors}</h3>
          {detail.competitor_mentions.map((row, index) => (
            <p key={index} className="text-[12px] text-[var(--ui-ink-2)]">
              {row.name}: {row.quote}
            </p>
          ))}
        </section>
      )}
      <section>
        <h3 className="mb-2 text-[14px] font-bold">{copy.fixNext}</h3>
        {detail.actions.length > 0 ? (
          <FixNextActions actions={detail.actions} />
        ) : (
          <p className="text-[12px] text-[var(--ui-ink-2)]">{copy.noActions}</p>
        )}
      </section>
      <section>
        <h3 className="mb-2 text-[14px] font-bold">{copy.sources}</h3>
        {detail.sources.map((source) => {
          const href = safeHref(source.url);
          return (
            <p
              key={source.id}
              className="text-[11px] text-[var(--ui-ink-2)]"
            >
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="font-bold text-[var(--ui-ink)] underline"
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
