import type { Dict } from "@/lib/i18n/en";

type Copy = Dict["aiVisibility"];

type StatCard = {
  key: string;
  value: string;
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
 * The measurable output of one research run: how much of the public web was
 * actually looked at, not an engagement score. Every number comes from the
 * run's stored evidence metrics; a run predating these counters shows no
 * rail rather than an invented one.
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
      : null;
  if (!metrics) return null;

  const platforms = Array.isArray(coverage.platforms)
    ? coverage.platforms.length
    : null;
  const cards: StatCard[] = [];
  const push = (
    key: string,
    value: number | null,
    label: string,
    caption: string,
  ) => {
    if (value !== null) cards.push({ key, value: value.toLocaleString(), label, caption });
  };

  push(
    "candidates_found",
    num(metrics, "candidates_found"),
    copy.facts.pagesFound,
    copy.facts.pagesFoundCaption,
  );
  push(
    "pages_read",
    num(metrics, "pages_read"),
    copy.facts.pagesRead,
    (num(metrics, "pages_failed") ?? 0) > 0
      ? `${copy.facts.pagesReadFailed} ${num(metrics, "pages_failed")}`
      : copy.facts.pagesReadCaption,
  );
  push(
    "links_found",
    num(metrics, "links_found"),
    copy.facts.linksFound,
    copy.facts.linksFoundCaption,
  );
  push(
    "words_read",
    num(metrics, "words_read"),
    copy.facts.wordsRead,
    copy.facts.wordsReadCaption,
  );
  push(
    "domains_found",
    num(metrics, "domains_found"),
    copy.facts.domainsFound,
    copy.facts.domainsFoundCaption,
  );
  push(
    "brand_mentions",
    num(metrics, "brand_mentions"),
    copy.facts.mentionsFound,
    copy.facts.mentionsFoundCaption,
  );
  push(
    "claims_verified",
    num(coverage, "validated_claim_count"),
    copy.facts.claimsVerified,
    copy.facts.claimsVerifiedCaption,
  );
  if (platforms !== null && platforms > 0) {
    cards.push({
      key: "platforms",
      value: platforms.toLocaleString(),
      label: copy.facts.platformsChecked,
      caption: `${copy.facts.platformsFound} ${num(metrics, "platforms_found") ?? 0}`,
    });
  }

  if (cards.length === 0) return null;
  return (
    <section aria-label={copy.facts.title} className="space-y-2">
      <p className="ai-eyebrow">{copy.facts.title}</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cards.map((card) => (
          <div
            key={card.key}
            className="rounded-[calc(var(--ai-radius-panel)*0.7)] border border-[var(--ai-line)] bg-[var(--ai-surface)] p-3 shadow-[var(--ai-shadow-panel)]"
          >
            <dt className="text-[10px] font-bold tracking-wide text-[var(--ai-muted)] uppercase">
              {card.label}
            </dt>
            <dd className="mt-1 font-mono text-[26px] leading-8 font-bold text-[var(--ai-ink)]">
              {card.value}
            </dd>
            <p className="mt-1 text-[10px] leading-4 text-[var(--ai-muted)]">
              {card.caption}
            </p>
          </div>
        ))}
      </dl>
    </section>
  );
}
