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
  supported: "bg-emerald-100 text-emerald-800",
  contradicted: "bg-red-100 text-red-800",
  unsupported: "bg-amber-100 text-amber-800",
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
  const byId = new Map(sources.map((source) => [source.id, source]));
  return (
    <section aria-label={copy.claimLedger} className="space-y-2">
      {claims.map((claim, index) => (
        <article
          key={`${claim.claim}-${index}`}
          className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-[12px] font-bold text-[var(--ui-ink)]">
              {claim.claim}
            </h4>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STYLE[claim.status]}`}
            >
              {copy[claim.status]}
            </span>
          </div>
          <blockquote className="mt-2 border-s-2 border-[var(--ui-line)] ps-3 text-[12px] text-[var(--ui-ink-2)]">
            {claim.quote}
          </blockquote>
          <div className="mt-2 flex flex-wrap gap-2">
            {claim.source_ids.map((id) => {
              const source = byId.get(id);
              const href = source ? safeHref(source.url) : null;
              return href ? (
                <a
                  key={id}
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] font-bold text-[var(--ui-ink)] underline"
                >
                  {copy.evidence} · {source?.title ?? id}
                </a>
              ) : null;
            })}
          </div>
        </article>
      ))}
    </section>
  );
}
