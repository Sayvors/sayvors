import type { Dict } from "@/lib/i18n/en";

type Copy = Dict["aiVisibility"];

type StatCard = {
  key: string;
  raw: number;
  value: string;
  label: string;
  caption: string;
  primary: boolean;
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
    primary: boolean,
  ) => {
    if (value !== null) {
      cards.push({
        key,
        raw: value,
        value: value.toLocaleString(),
        label,
        caption,
        primary,
      });
    }
  };

  push(
    "candidates_found",
    num(metrics, "candidates_found"),
    copy.facts.pagesFound,
    copy.facts.pagesFoundCaption,
    true,
  );
  push(
    "domains_found",
    num(metrics, "domains_found"),
    copy.facts.domainsFound,
    copy.facts.domainsFoundCaption,
    true,
  );
  push(
    "brand_mentions",
    num(metrics, "brand_mentions"),
    copy.facts.mentionsFound,
    copy.facts.mentionsFoundCaption,
    true,
  );
  if (platforms !== null && platforms > 0) {
    const found = num(metrics, "platforms_found") ?? 0;
    cards.push({
      key: "platforms",
      raw: platforms,
      value: platforms.toLocaleString(),
      label: copy.facts.platformsChecked,
      caption: `${copy.facts.platformsFound} ${found}`,
      primary: true,
    });
  }
  push(
    "pages_read",
    num(metrics, "pages_read"),
    copy.facts.pagesRead,
    (num(metrics, "pages_failed") ?? 0) > 0
      ? `${copy.facts.pagesReadFailed} ${num(metrics, "pages_failed")}`
      : copy.facts.pagesReadCaption,
    false,
  );
  push(
    "links_found",
    num(metrics, "links_found"),
    copy.facts.linksFound,
    copy.facts.linksFoundCaption,
    false,
  );
  push(
    "words_read",
    num(metrics, "words_read"),
    copy.facts.wordsRead,
    copy.facts.wordsReadCaption,
    false,
  );
  push(
    "claims_verified",
    num(coverage, "validated_claim_count"),
    copy.facts.claimsVerified,
    copy.facts.claimsVerifiedCaption,
    false,
  );

  if (cards.length === 0) return null;
  const primary = cards.filter((card) => card.primary);
  const secondary = cards.filter((card) => !card.primary);
  const chartKeys = new Set([
    "candidates_found",
    "pages_read",
    "domains_found",
    "brand_mentions",
    "platforms",
  ]);
  const chartRows = cards.filter((card) => chartKeys.has(card.key));
  const chartMax = Math.max(1, ...chartRows.map((card) => card.raw));
  const showChart = chartRows.some((card) => card.raw > 0);

  return (
    <section aria-label={copy.facts.title} className="space-y-3">
      <p className="ai-eyebrow">{copy.facts.title}</p>
      <div className="overflow-hidden rounded-[var(--ai-radius-panel)] border border-[var(--ai-line)] bg-[var(--ai-line)] shadow-[var(--ai-shadow-panel)]">
        <dl className="grid grid-cols-2 gap-px sm:grid-cols-4">
          {primary.map((card) => {
            const muted = card.raw === 0;
            return (
              <div key={card.key} className="bg-[var(--ai-surface)] px-4 py-5">
                <dt className="text-[11px] font-semibold leading-4 text-[var(--ai-muted)]">
                  {card.label}
                </dt>
                <dd
                  className={`mt-2 font-mono text-[34px] font-bold leading-none tracking-tight ${
                    muted ? "text-[var(--ai-muted)]" : "text-[var(--ai-ink)]"
                  }`}
                >
                  {card.value}
                </dd>
                <p className="mt-2 text-[11px] leading-4 text-[var(--ai-muted)]">
                  {card.caption}
                </p>
              </div>
            );
          })}
        </dl>
        {secondary.length > 0 && (
          <dl className="grid grid-cols-2 gap-px border-t border-[var(--ai-line)] sm:grid-cols-4">
            {secondary.map((card) => {
              const muted = card.raw === 0;
              return (
                <div key={card.key} className="bg-[var(--ai-sunken)] px-4 py-3">
                  <dt className="text-[10px] font-bold uppercase tracking-wide text-[var(--ai-muted)]">
                    {card.label}
                  </dt>
                  <dd
                    className={`mt-1 font-mono text-[20px] font-bold leading-none ${
                      muted ? "text-[var(--ai-muted)]" : "text-[var(--ai-ink-2)]"
                    }`}
                  >
                    {card.value}
                  </dd>
                  <p className="mt-1 text-[10px] leading-4 text-[var(--ai-muted)]">
                    {card.caption}
                  </p>
                </div>
              );
            })}
          </dl>
        )}
      </div>
      {showChart && (
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
                    {row.value}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--ai-sunken)]">
                  <div
                    className="h-full rounded-full bg-[var(--ai-accent)]"
                    style={{ width: `${(row.raw / chartMax) * 100}%` }}
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
