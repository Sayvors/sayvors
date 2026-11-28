"use client";

import type { Dict } from "@/lib/i18n/en";
import type { AiVisibilityRunDetail } from "@/lib/api-ai-visibility";
import { safeHref } from "@/lib/safe-url";

function sourceDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export default function EvidenceDrawer({
  detail,
  copy,
}: {
  detail: AiVisibilityRunDetail;
  copy: Dict["aiVisibility"];
}) {
  const sources = new Map(detail.sources.map((source) => [source.label, source]));
  const competitors = detail.competitor_mentions ?? [];
  const statusLabel = (status: string) =>
    status === "supported"
      ? copy.supported
      : status === "contradicted"
        ? copy.contradicted
        : copy.unsupported;

  return (
    <details className="rounded-[var(--ai-radius-control)] border border-[var(--ai-line)] bg-[var(--ai-surface)]">
      <summary className="cursor-pointer list-none px-4 py-3 text-[12px] font-bold text-[var(--ai-ink)] marker:content-none">
        {copy.evidenceSummary(detail.claims.length, detail.sources.length)}
      </summary>
      <div className="border-t border-[var(--ai-line)] px-4 py-4">
        {detail.claims.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-start text-[11px] leading-5">
              <thead>
                <tr className="border-b border-[var(--ai-line)] text-[10px] uppercase tracking-wide text-[var(--ai-muted)]">
                  <th scope="col" className="px-2 py-2 text-start font-bold">{copy.claim}</th>
                  <th scope="col" className="px-2 py-2 text-start font-bold">{copy.status}</th>
                  <th scope="col" className="px-2 py-2 text-start font-bold">{copy.sources}</th>
                  <th scope="col" className="px-2 py-2 text-start font-bold">{copy.quote}</th>
                </tr>
              </thead>
              <tbody>
                {detail.claims.map((claim, index) => (
                  <tr
                    key={`${claim.claim}-${index}`}
                    data-evidence-row
                    className="border-b border-[var(--ai-line)] align-top last:border-0"
                  >
                    <td className="px-2 py-3 font-semibold text-[var(--ai-ink)]">{claim.claim}</td>
                    <td className="px-2 py-3 text-[var(--ai-ink-2)]">{statusLabel(claim.status)}</td>
                    <td className="px-2 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {claim.source_ids.map((label) => {
                          const source = sources.get(label);
                          const href = source ? safeHref(source.url) : null;
                          return href ? (
                            <a
                              key={label}
                              href={href}
                              target="_blank"
                              rel="noreferrer"
                              className="rounded-full border border-[var(--ai-line)] px-2 py-0.5 font-mono text-[10px] font-bold text-[var(--ai-accent)] underline"
                            >
                              {label}
                            </a>
                          ) : (
                            <span key={label} className="font-mono text-[10px] font-bold text-[var(--ai-muted)]">{label}</span>
                          );
                        })}
                      </div>
                    </td>
                    <td className="px-2 py-3 text-[var(--ai-ink-2)]">{claim.quote}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[12px] text-[var(--ai-muted)]">{copy.noEvidence}</p>
        )}

        {detail.sources.length > 0 && (
          <div className="mt-4 border-t border-[var(--ai-line)] pt-3">
            <p className="ai-eyebrow mb-2">{copy.sources}</p>
            <ul className="space-y-2">
              {detail.sources.map((source) => {
                const href = safeHref(source.url);
                const domain = sourceDomain(source.url);
                return (
                  <li key={source.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[11px] leading-5">
                    <span className="font-mono font-bold text-[var(--ai-signal)]">{source.label}</span>
                    {domain && <span className="font-mono text-[10px] text-[var(--ai-muted)]">{domain}</span>}
                    {href ? (
                      <a href={href} target="_blank" rel="noreferrer" aria-label={`${source.label} · ${source.title ?? source.url}`} className="font-bold text-[var(--ai-accent)] underline">
                        {source.title ?? source.url}
                      </a>
                    ) : (
                      <span className="text-[var(--ai-ink-2)]">{source.title ?? source.url}</span>
                    )}
                    {source.fetch_error ? <span className="text-[var(--ai-danger)]">· {source.fetch_error}</span> : null}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {competitors.length > 0 && (
          <div className="mt-4 border-t border-[var(--ai-line)] pt-3">
            <p className="ai-eyebrow mb-2">{copy.competitors}</p>
            <ul className="space-y-2">
              {competitors.map((row, index) => (
                <li key={`${row.name}-${index}`} className="text-[11px] leading-5 text-[var(--ai-ink-2)]">
                  <strong className="text-[var(--ai-ink)]">{row.name}:</strong> {row.quote}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
