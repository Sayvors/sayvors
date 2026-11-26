import type { AiVisibilitySource } from "@/lib/api-ai-visibility";

type Copy = {
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
  platformCoverage: string;
  foundPublic: string;
  notFoundPublic: string;
  unknownPublic: string;
  privateNote: string;
};

const PLATFORMS = [
  ["Google Business Profile", "https://business.google.com/"],
  ["Facebook Page", "https://www.facebook.com/pages/create"],
  ["Instagram Business", "https://business.instagram.com/"],
  ["TikTok Business", "https://www.tiktok.com/business/"],
  ["LinkedIn Company Page", "https://www.linkedin.com/company/setup/new/"],
  ["YouTube", "https://www.youtube.com/creators/"],
] as const;

export default function ResearchProvenance({
  coverage,
  sources,
  copy,
}: {
  coverage: Record<string, unknown>;
  sources: AiVisibilitySource[];
  copy: Copy;
}) {
  const search =
    coverage.search && typeof coverage.search === "object"
      ? (coverage.search as Record<string, unknown>)
      : {};
  const thirdParty = Number(coverage.third_party_source_count ?? 0);
  const owned = Number(
    coverage.owned_source_count ?? Math.max(0, sources.length - thirdParty),
  );
  const platforms = Array.isArray(coverage.platforms)
    ? (coverage.platforms as Array<Record<string, unknown>>)
    : [];
  return (
    <details className="border-y border-[var(--ai-line)] py-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[12px] font-bold marker:content-none">
        <span>{copy.howSearched}</span>
        <span className="font-mono text-[10px] font-normal text-[var(--ai-muted)]">
          {String(search.provider ?? "Bing public web")}
        </span>
      </summary>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        {[
          [copy.searchResults, String(search.result_count ?? 0)],
          [copy.sourcesFetched, String(search.fetched_count ?? sources.length)],
          [copy.thirdPartySources, String(thirdParty)],
          [copy.ownedSources, String(owned)],
        ].map(([label, value]) => (
          <div
            key={label}
            className="rounded-[var(--ai-radius-control)] bg-[var(--ai-sunken)] px-3 py-2"
          >
            <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ai-muted)]">
              {label}
            </p>
            <p className="mt-1 font-mono text-[15px] font-bold text-[var(--ai-ink)]">
              {value}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[9px] font-bold uppercase tracking-wide text-[var(--ai-muted)]">
        {copy.searchQuery}
      </p>
      <code className="mt-1 block overflow-x-auto rounded-[var(--ai-radius-control)] border border-[var(--ai-line)] px-3 py-2 text-[11px] text-[var(--ai-ink-2)]">
        {String(search.query ?? "—")}
      </code>
      <p className="mt-3 text-[11px] leading-5 text-[var(--ai-muted)]">
        {copy.searchProvider}: {String(search.provider ?? "Bing public web")} ·{" "}
        {copy.socialNotChecked}
      </p>
      {platforms.length > 0 && (
        <div className="mt-4 border-t border-[var(--ai-line)] pt-3">
          <p className="text-[12px] font-bold text-[var(--ai-ink)]">
            {copy.platformCoverage}
          </p>
          <div className="mt-2 divide-y divide-[var(--ai-line)] border-y border-[var(--ai-line)]">
            {platforms.map((row) => {
              const status = String(row.status ?? "unknown");
              const found = status === "found" && row.url;
              const label =
                status === "found"
                  ? copy.foundPublic
                  : status === "not_found"
                    ? copy.notFoundPublic
                    : copy.unknownPublic;
              return (
                <div
                  key={String(row.platform)}
                  className="flex flex-wrap items-center justify-between gap-2 py-2 text-[11px]"
                >
                  <span className="font-bold text-[var(--ai-ink)]">
                    {String(row.platform)}
                  </span>
                  {found ? (
                    <a
                      href={String(row.url)}
                      target="_blank"
                      rel="noreferrer"
                      className="font-semibold text-[var(--ai-ok)] underline"
                    >
                      {label} ↗
                    </a>
                  ) : (
                    <span className="text-[var(--ai-muted)]">
                      {label} ·{" "}
                      <a
                        href={String(row.setup_url)}
                        target="_blank"
                        rel="noreferrer"
                        className="font-semibold text-[var(--ai-accent)] underline"
                      >
                        Publish publicly ↗
                      </a>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] leading-5 text-[var(--ai-muted)]">
            {copy.privateNote}
          </p>
        </div>
      )}
      <div className="mt-4 border-t border-[var(--ai-line)] pt-3">
        <p className="text-[12px] font-bold text-[var(--ai-ink)]">
          {copy.publishingChecklist}
        </p>
        <p className="mt-1 text-[11px] leading-5 text-[var(--ai-muted)]">
          {copy.publishingHint}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {PLATFORMS.map(([label, href]) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-8 items-center rounded-full border border-[var(--ai-line-strong)] px-3 text-[10px] font-bold text-[var(--ai-accent)] transition-colors hover:bg-[var(--ai-sunken)]"
            >
              {label} ↗
            </a>
          ))}
        </div>
      </div>
    </details>
  );
}
