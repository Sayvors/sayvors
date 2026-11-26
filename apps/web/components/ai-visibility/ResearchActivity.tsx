import type { Dict } from "@/lib/i18n/en";
import Typewriter from "@/components/Typewriter";

type Copy = Dict["aiVisibility"] & {
  activityTitle: string;
  activitySearch: string;
  activityFound: string;
  activityRead: string;
  activityFacts: string;
  activityClaims: string;
  activityWrite: string;
  activityDone: string;
  activityFailed: string;
  activityNoEvidence: string;
  activityNow: string;
};

const ORDER: Record<string, number> = {
  queued: 0,
  searching: 0,
  fetching: 1,
  reading: 2,
  validating: 4,
  writing: 5,
  completed: 6,
  insufficient_evidence: 6,
  ambiguous: 6,
  failed: 6,
};

export default function ResearchActivity({
  status,
  coverage,
  copy,
}: {
  status: string;
  coverage: Record<string, unknown>;
  copy: Copy;
}) {
  const search =
    coverage.search && typeof coverage.search === "object"
      ? (coverage.search as Record<string, unknown>)
      : {};
  const query = String(search.query ?? "").split(" | ")[0];
  const current = ORDER[status] ?? 0;
  const terminal = status === "completed" || status === "insufficient_evidence";
  const failed = status === "failed" || status === "ambiguous";
  const steps = [
    [copy.activitySearch, query || "Bing public web"],
    [copy.activityFound, String(search.result_count ?? 0)],
    [copy.activityRead, String(search.fetched_count ?? coverage.source_count ?? 0)],
    [copy.activityFacts, copy.activityNow],
    [copy.activityClaims, copy.activityNow],
    [copy.activityWrite, copy.activityNow],
    [
      failed
        ? copy.activityFailed
        : status === "insufficient_evidence"
          ? copy.activityNoEvidence
          : copy.activityDone,
      "",
    ],
  ] as const;
  const thinking = [
    copy.activitySearch,
    `${copy.activityFound}: ${search.result_count ?? 0}`,
    `${copy.activityRead}: ${search.fetched_count ?? coverage.source_count ?? 0}`,
    copy.activityFacts,
    copy.activityClaims,
    copy.activityWrite,
  ];

  return (
    <section aria-label={copy.activityTitle} className="space-y-1">
      <p className="ai-eyebrow">{copy.activityTitle}</p>
      {!terminal && !failed && (
        <div
          role="status"
          aria-live="polite"
          className="mt-2 flex items-center rounded-[var(--ai-radius-control)] bg-[var(--ai-sunken)] px-3 py-2 text-[12px] text-[var(--ai-muted)]"
        >
          <Typewriter
            phrases={thinking}
            label={copy.activityTitle}
            holdMs={1600}
          />
        </div>
      )}
      <ol className="mt-2 divide-y divide-[var(--ai-line)] border-y border-[var(--ai-line)]">
        {steps.map(([label, detail], index) => {
          const done = index < current || (index === current && terminal);
          const active = index === current && !terminal && !failed;
          return (
            <li
              key={label}
              className={`flex items-center gap-3 py-2 text-[11px] ${
                done || active
                  ? "text-[var(--ai-ink-2)]"
                  : "text-[var(--ai-muted)] opacity-55"
              }`}
            >
              <span className="w-4 font-mono text-[10px]">
                {done ? "✓" : active ? "→" : "·"}
              </span>
              <span className="min-w-0 flex-1">
                {label}
                {detail && detail !== copy.activityNow ? (
                  <span className="ms-2 font-mono text-[10px] text-[var(--ai-muted)]">
                    {detail}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
