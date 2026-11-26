import type { Dict } from "@/lib/i18n/en";

type Copy = Dict["aiVisibility"];

type EvidenceCard = {
  key: string;
  value: number;
  label: string;
  caption: string;
};

function num(source: Record<string, unknown>, key: string): number | null {
  const raw = source[key];
  if (raw === null || raw === undefined) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

/**
 * Owner-first evidence summary. Search candidates are deliberately not shown
 * here: a search engine returning ten generic pages is not the same as ten
 * websites mentioning the business. Only actual evidence counts toward the
 * big numbers and the chart.
 */
export default function ResearchFacts({
  coverage,
  copy,
}: {
  coverage: Record<string, unknown>;
  copy: Copy;
}) {
  const metrics =
    coverage.metrics && typeof coverage.metrics === "object"
      ? (coverage.metrics as Record<string, unknown>)
      : {};
  const independent = num(coverage, "third_party_source_count");
  const owned = num(coverage, "owned_source_count");
  const profiles = num(metrics, "platforms_found");
  const verified = num(coverage, "validated_claim_count");

  const cards: EvidenceCard[] = [];
  if (independent !== null) {
    cards.push({
      key: "independent",
      value: independent,
      label: copy.facts.independentMentions,
      caption: copy.facts.independentMentionsCaption,
    });
  }
  if (owned !== null) {
    cards.push({
      key: "owned",
      value: owned,
      label: copy.facts.ownedPages,
      caption: copy.facts.ownedPagesCaption,
    });
  }
  if (profiles !== null) {
    cards.push({
      key: "profiles",
      value: profiles,
      label: copy.facts.publicProfiles,
      caption: copy.facts.publicProfilesCaption,
    });
  }
  if (verified !== null) {
    cards.push({
      key: "verified",
      value: verified,
      label: copy.facts.verifiedFacts,
      caption: copy.facts.verifiedFactsCaption,
    });
  }

  if (cards.length === 0) return null;
  const chartRows = cards.filter((card) => card.key !== "verified");
  const chartMax = Math.max(1, ...chartRows.map((card) => card.value));
  const note =
    independent === 0
      ? copy.facts.noIndependentNote
      : independent !== null
        ? copy.facts.independentNote(independent)
        : copy.facts.noEvidenceNote;

  return (
    <section aria-label={copy.facts.title} className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <p className="ai-eyebrow">{copy.facts.title}</p>
        <p className="max-w-xl text-[11px] leading-5 text-[var(--ai-muted)]">{note}</p>
      </div>
      <div className="overflow-hidden rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-line)] shadow-[var(--ai-shadow-panel)]">
        <dl className="grid grid-cols-2 gap-px sm:grid-cols-4">
          {cards.map((card) => (
            <div key={card.key} className="bg-[var(--ai-surface)] px-4 py-5">
              <dt className="text-[11px] font-semibold leading-4 text-[var(--ai-muted)]">
                {card.label}
              </dt>
              <dd
                className={`mt-2 font-mono text-[34px] font-bold leading-none tracking-tight ${
                  card.value === 0 ? "text-[var(--ai-muted)]" : "text-[var(--ai-ink)]"
                }`}
              >
                {card.value.toLocaleString()}
              </dd>
              <p className="mt-2 text-[11px] leading-4 text-[var(--ai-muted)]">
                {card.caption}
              </p>
            </div>
          ))}
        </dl>
      </div>
      {chartRows.length > 0 && (
        <div className="border-t border-[var(--ai-line)] pt-3">
          <p className="text-[11px] font-bold text-[var(--ai-ink-2)]">
            {copy.facts.chartTitle}
          </p>
          <ul className="mt-3 space-y-2.5" aria-label={copy.facts.chartTitle}>
            {chartRows.map((row) => (
              <li key={row.key}>
                <div className="flex items-center justify-between gap-3 text-[10px]">
                  <span className="text-[var(--ai-muted)]">{row.label}</span>
                  <span className="font-mono font-bold text-[var(--ai-ink-2)]">
                    {row.value.toLocaleString()}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--ai-sunken)]">
                  <div
                    className="h-full rounded-full bg-[var(--ai-accent)]"
                    style={{ width: `${(row.value / chartMax) * 100}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
