import type { AiVisibilityClaim, AiVisibilitySource } from "@/lib/api-ai-visibility";
import { safeHref } from "@/lib/safe-url";

type Copy = {
  claimLedger: string;
  supported: string;
  contradicted: string;
  unsupported: string;
  evidence: string;
};

const STYLE = {
  supported: "border-[var(--ai-ok)] text-[var(--ai-ok)]",
  contradicted: "border-[var(--ai-danger)] text-[var(--ai-danger)]",
  unsupported: "border-[var(--ai-warn)] text-[var(--ai-warn)]",
};

export default function ClaimLedger({
  claims,
  sources,
  copy,
}: {
  claims: AiVisibilityClaim[];
  sources: AiVisibilitySource[];
  copy: Copy;
}) {
  const byLabel = new Map(sources.map((source) => [source.label, source]));
  return (
    <section aria-label={copy.claimLedger} className="divide-y divide-[var(--ai-line)] border-y border-[var(--ai-line)]">
      {claims.map((claim, index) => (
        <article
          key={`${claim.claim}-${index}`}
          className="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto]"
        >
          <div className="min-w-0">
            <h4 className="text-[13px] font-bold leading-5 text-[var(--ai-ink)]">
              {claim.claim}
            </h4>
            <blockquote className="mt-2 border-s-2 border-[var(--ai-signal)] ps-3 text-[12px] leading-5 text-[var(--ai-ink-2)]">
              {claim.quote}
            </blockquote>
          </div>
          <div className="flex flex-wrap items-start gap-2 sm:justify-end">
            <span
              className={`rounded-full border px-2.5 py-1 text-[9px] font-bold uppercase tracking-wide ${STYLE[claim.status]}`}
            >
              {copy[claim.status]}
            </span>
            {claim.source_ids.map((id) => {
              const source = byLabel.get(id);
              const href = source ? safeHref(source.url) : null;
              return href ? (
                <a
                  key={id}
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-8 items-center rounded-md border border-[var(--ai-line)] px-2 font-mono text-[10px] font-bold text-[var(--ai-accent)] hover:bg-[var(--ai-sunken)]"
                >
                  {id} · {source?.title ?? copy.evidence}
                </a>
              ) : null;
            })}
          </div>
        </article>
      ))}
    </section>
  );
}
