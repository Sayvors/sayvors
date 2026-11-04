"use client";

import { safeHref } from "@/lib/safe-url";

/**
 * The provenance footer every fact card carries.
 *
 * A number without a source is indistinguishable from an invented score. This
 * line names where the number came from and, when we hold a real identifier,
 * links to the place the tenant can check it. The link is deliberately quiet
 * (10px, underlined on hover) so it does not compete with the fact itself.
 */
export function FactSource({
  source,
  detail,
  note,
  href,
  linkLabel = "Verify at source",
  className = "",
}: {
  source: string;
  /** The window or refresh time, e.g. "last 30 days" or "synced 5m ago". */
  detail?: string | null;
  /** A caveat worth keeping beside the source, e.g. "not a national average". */
  note?: string | null;
  href?: string | null;
  linkLabel?: string;
  className?: string;
}) {
  const url = href ? safeHref(href) : null;
  const external = url ? /^https?:\/\//i.test(url) : false;

  return (
    <p
      className={`mt-3 flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-[10px] leading-relaxed text-[var(--ui-ink-2)] ${className}`}
    >
      <span>
        <span className="font-semibold">Source:</span> {source}
      </span>
      {detail && (
        <>
          <span aria-hidden>·</span>
          <span>{detail}</span>
        </>
      )}
      {note && (
        <>
          <span aria-hidden>·</span>
          <span>{note}</span>
        </>
      )}
      {url && (
        <>
          <span aria-hidden>·</span>
          <a
            href={url}
            target={external ? "_blank" : undefined}
            rel={external ? "noopener noreferrer" : undefined}
            className="inline-flex items-center gap-0.5 font-bold text-[var(--ui-ink)] underline decoration-[var(--ui-line-strong)] underline-offset-2 outline-none transition hover:decoration-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {linkLabel}
            {external && <span aria-hidden>↗</span>}
            {external && <span className="sr-only"> (opens in a new tab)</span>}
          </a>
        </>
      )}
    </p>
  );
}
