"use client";

import type { BenchmarkResponse } from "@/lib/api-analytics";
import { FactSource } from "@/components/analytics/FactSource";
import { GBP_DASHBOARD_URL, mapsPlaceUrl } from "@/lib/google-links";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type CardsDict = Dict["bench"]["cards"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

function Row({
  label,
  yours,
  peers,
  delta,
  suffix = "",
}: {
  label: string;
  yours: string;
  peers: string;
  delta?: number | null;
  suffix?: string;
}) {
  const { locale } = useI18n();
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const hasDelta = delta !== undefined && delta !== null;
  return (
    <li className="flex items-center gap-2 py-2.5 first:pt-1 last:pb-1">
      <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--ui-ink)]">{label}</span>
      <span className="w-16 shrink-0 text-right text-[12px] font-bold tabular-nums text-[var(--ui-ink)]">{yours}</span>
      <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-[var(--ui-ink-2)]">{peers}</span>
      {hasDelta ? (
        <span className={`w-14 shrink-0 text-right text-[10px] font-bold tabular-nums ${(delta as number) >= 0 ? "text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}`}>
          {(delta as number) > 0 ? "+" : ""}{fmt(Math.round((delta as number) * 10) / 10)}{suffix}
        </span>
      ) : (
        <span className="w-14 shrink-0 text-right text-[10px] text-[var(--ui-ink-2)]">—</span>
      )}
    </li>
  );
}

export default function BenchmarkCards({
  benchmark,
  loading,
  onRefreshExternal,
  refreshingExternal,
  googleConnected = false,
}: {
  benchmark: BenchmarkResponse | null;
  loading: boolean;
  onRefreshExternal?: () => void;
  refreshingExternal?: boolean;
  /** Whether a Google Business Profile is connected; gates the GBP link. */
  googleConnected?: boolean;
}) {
  const { t, locale } = useI18n();
  const bc: CardsDict = t.bench.cards;
  const gbp = t.bench.fact.gbp;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  if (loading || !benchmark) {
    return (
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <div className="ui-card h-48 animate-pulse" aria-hidden />
        <div className="ui-card h-48 animate-pulse" aria-hidden />
      </div>
    );
  }

  const rec = benchmark.recency;
  const gap = benchmark.gap_to_target;
  const cohort = benchmark.cohort;
  const peerCount = cohort?.count ?? 0;
  // A median from fewer than three peers is not a benchmark. Show the user's
  // own numbers, but label the peer side "not enough peers" instead of
  // presenting a one-business median as a market.
  const peerWeak = peerCount < 3;
  const peerLabel = peerCount
    ? `${cohort?.label} (${peerCount === 1 ? bc.peersOne : fill(bc.peersN, { n: fmt(peerCount) })})`
    : bc.noPeerSet;
  const ratingDelta = benchmark.current_avg_rating - benchmark.similar_avg_rating;
  const reviewsDelta = benchmark.current_reviews_total - benchmark.similar_reviews_total;
  const responseDelta = benchmark.current_response_rate - benchmark.similar_response_rate;
  const ext = benchmark.external;
  const deltaWindow = ext?.delta_window_days ?? 30;
  const fmtDelta = (value: number | null | undefined, suffix = "") => {
    if (value === null || value === undefined) return "—";
    return `${value > 0 ? "+" : ""}${fmt(Math.round(value * 100) / 100)}${suffix}`;
  };

  return (
    <div className="space-y-4 sm:space-y-5">
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
        {/* You vs peers */}
        <section aria-label={bc.youVs} className="ui-card p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bc.youVs}</h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">
                {fill(bc.scopeLine, { peers: peerLabel, scope: cohort?.scope === "network" ? bc.network : bc.city })}
              </p>
            </div>
            {!peerWeak && benchmark.my_rank && (
              <span className="rounded-[2px] bg-[var(--ui-sunken)] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
                {fill(bc.rankLine, { rank: fmt(benchmark.my_rank), total: fmt((benchmark.market?.length ?? cohort?.count ?? 0) + 1) })}
              </span>
            )}
          </div>

          <div className="mt-3 flex items-center gap-2 border-b border-[var(--ui-line)] pb-1 text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
            <span className="flex-1">{bc.metric}</span>
            <span className="w-16 text-right">{bc.you}</span>
            <span className="w-16 text-right">{bc.peers}</span>
            <span className="w-14 text-right">{bc.gap}</span>
          </div>
          {peerWeak && (
            <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-2.5 text-[11px] text-[var(--ui-ink)]">
              {peerCount === 1 ? bc.notEnoughOne : fill(bc.notEnoughN, { n: fmt(peerCount) })}
            </p>
          )}
          <ul className="mt-2 divide-y divide-[var(--ui-line)]">
            <Row label={bc.avgRating} yours={fmt(Math.round(benchmark.current_avg_rating * 10) / 10) + "★"} peers={peerWeak ? "—" : fmt(Math.round(benchmark.similar_avg_rating * 10) / 10) + "★"} delta={peerWeak ? null : ratingDelta} suffix="★" />
            <Row label={bc.totalReviews} yours={fmt(benchmark.current_reviews_total)} peers={peerWeak ? "—" : fmt(benchmark.similar_reviews_total)} delta={peerWeak ? null : reviewsDelta} />
            <Row label={bc.responseRate} yours={fmt(Math.round(benchmark.current_response_rate)) + "%"} peers={peerWeak ? "—" : fmt(Math.round(benchmark.similar_response_rate)) + "%"} delta={peerWeak ? null : responseDelta} suffix="%" />
            {rec && rec.my_pct !== null ? (
              <Row label={bc.last90} yours={fmt(Math.round(rec.my_pct)) + "%"} peers={peerWeak || rec.peer_median_pct === null ? "—" : fmt(Math.round(rec.peer_median_pct)) + "%"} delta={peerWeak || rec.peer_median_pct === null ? null : rec.my_pct - rec.peer_median_pct} suffix="%" />
            ) : (
              <Row label={bc.last90} yours="—" peers="—" />
            )}
          </ul>
          {cohort?.count === 0 && (
            <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
              {bc.firstInMarket}
            </p>
          )}
          <FactSource
            source={bc.sourceVal}
            detail={fill(bc.daysDetail, { n: fmt(benchmark.days) })}
            note={bc.medianNoteShort}
            href={googleConnected ? GBP_DASHBOARD_URL : null}
            linkLabel={gbp}
          />
        </section>

        {/* Gap to 4.5 */}
        <section aria-label={bc.gapTitle} className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bc.gapTitle}</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">{bc.gapSub}</p>
          {!gap || gap.current_reviews === 0 ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{bc.noReviews}</p>
          ) : gap.five_star_needed === 0 ? (
            <p className="mt-4 text-[13px] font-semibold text-[var(--ui-ink)]">
              {bc.atAbove}
            </p>
          ) : (
            <>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-[30px] font-black leading-none tabular-nums text-[var(--ui-ink)]">{fmt(gap.five_star_needed)}</span>
                <span className="text-[12px] font-semibold text-[var(--ui-ink-2)]">{bc.needed}</span>
              </div>
              <p className="mt-2 text-[11px] text-[var(--ui-ink-2)]">
                {fill(bc.fromLine, { rating: fmt(Math.round(gap.current_rating * 100) / 100), n: fmt(gap.current_reviews) })}
                {gap.months !== null ? ` ${gap.months === 1 ? fill(bc.paceLineOne, { pace: fmt(gap.pace_per_month) }) : fill(bc.paceLineN, { pace: fmt(gap.pace_per_month), m: fmt(gap.months) })}` : ` ${bc.paceNone}`}
              </p>
              {gap.math && <p className="mt-1 break-all text-[10px] text-[var(--ui-ink-2)]">{gap.math}</p>}
            </>
          )}
          <FactSource
            source={bc.gapSource}
            detail={
              gap
                ? fill(bc.gapDetailN, { n: fmt(gap.current_reviews) })
                : bc.gapDetailNone
            }
            href={googleConnected ? GBP_DASHBOARD_URL : null}
            linkLabel={gbp}
          />
        </section>
      </div>

      {/* Peer set disclosure */}
      <section aria-label={bc.peerTitle} className="ui-card p-5">
        <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bc.peerTitle}</h3>
        <p className="text-[11px] text-[var(--ui-ink-2)]">
          {bc.peerSub}
        </p>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.scope}</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{cohort?.label ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.businesses}</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{fmt(cohort?.count ?? 0)}</dd>
          </div>
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.cityCat}</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{cohort?.city ?? "—"} · {cohort?.category ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.source}</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{bc.sourceVal}</dd>
          </div>
        </dl>
        {peerWeak && (
          <p className="mt-2 text-[11px] font-semibold text-[var(--ui-ink)]">
            {bc.tooSmall}
          </p>
        )}
        <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
          {bc.medianNote}
        </p>
        <FactSource
          source={bc.sourceVal}
          detail={bc.medianNoteDetail}
          note={bc.medianNoteMethod}
          href={googleConnected ? GBP_DASHBOARD_URL : null}
          linkLabel={gbp}
        />
      </section>

      {benchmark.external && (
        <section aria-label={bc.extTitle} className="ui-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{bc.extTitle} <span className="ml-1 rounded-[2px] bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">{bc.pro}</span></h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">
                {bc.extSub}
              </p>
            </div>
            {onRefreshExternal && (
              <button
                onClick={onRefreshExternal}
                disabled={refreshingExternal}
                className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)] disabled:opacity-50"
              >
                {refreshingExternal ? bc.refreshing : bc.refreshPeers}
              </button>
            )}
          </div>

          {!benchmark.external.configured ? (
            <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink)]">
              {bc.extNotConnPre} <code>GOOGLE_PLACES_API_KEY</code> {bc.extNotConnPost}
            </p>
          ) : !benchmark.external.available ? (
            <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink)]">
              {benchmark.external.count === 0
                ? bc.extNone
                : fill(bc.extFew, { n: fmt(benchmark.external.count) })}
            </p>
          ) : (
            <>
              <div className="mt-3 flex flex-wrap items-baseline gap-4">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.peerMedianRating}</p>
                  <p className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                    {benchmark.external.median_rating !== null && benchmark.external.median_rating !== undefined ? fmt(Math.round(benchmark.external.median_rating * 10) / 10) + "★" : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.peerMedianReviews}</p>
                  <p className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{benchmark.external.median_reviews !== null && benchmark.external.median_reviews !== undefined ? fmt(benchmark.external.median_reviews) : "—"}</p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.peersLabel}</p>
                  <p className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{fmt(benchmark.external.count)}</p>
                </div>
              </div>
              {(benchmark.external.median_rating_delta != null ||
                benchmark.external.median_reviews_delta != null ||
                benchmark.external.median_velocity_per_month != null) && (
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <div className="rounded-[2px] bg-[var(--ui-sunken)] p-2.5">
                    <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{fill(bc.deltaRating, { n: fmt(deltaWindow) })}</p>
                    <p className="mt-1 text-[16px] font-black tabular-nums text-[var(--ui-ink)]">
                      {fmtDelta(benchmark.external.median_rating_delta, "★")}
                    </p>
                  </div>
                  <div className="rounded-[2px] bg-[var(--ui-sunken)] p-2.5">
                    <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{fill(bc.deltaReviews, { n: fmt(deltaWindow) })}</p>
                    <p className="mt-1 text-[16px] font-black tabular-nums text-[var(--ui-ink)]">
                      {fmtDelta(benchmark.external.median_reviews_delta)}
                    </p>
                  </div>
                  <div className="rounded-[2px] bg-[var(--ui-sunken)] p-2.5">
                    <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{bc.deltaVelocity}</p>
                    <p className="mt-1 text-[16px] font-black tabular-nums text-[var(--ui-ink)]">
                      {fmtDelta(benchmark.external.median_velocity_per_month)}
                    </p>
                  </div>
                </div>
              )}
              <FactSource
                source={bc.extSource}
                detail={[
                  benchmark.external.radius_m
                    ? fill(bc.extWithin, { n: fmt(benchmark.external.radius_m) })
                    : bc.noRadius,
                  benchmark.external.category,
                  benchmark.external.fetched_at
                    ? fill(bc.extFetched, { date: new Date(benchmark.external.fetched_at).toLocaleDateString(dateLocale) })
                    : null,
                  benchmark.external.stale ? bc.stale : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
                note={
                  benchmark.external.peers?.length
                    ? bc.peerNote
                    : null
                }
              />
              {benchmark.external.peers && benchmark.external.peers.length > 0 && (
                <ul className="mt-3 grid gap-1 sm:grid-cols-2">
                  {benchmark.external.peers.slice(0, 6).map((p) => {
                    const href = mapsPlaceUrl(p.place_id);
                    return (
                      <li key={p.place_id} className="flex items-center gap-2 text-[11px]">
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={fill(bc.mapsTitle, { name: p.name })}
                            className="inline-flex min-w-0 flex-1 items-center gap-1 truncate text-[var(--ui-ink)] underline decoration-[var(--ui-line-strong)] underline-offset-2 outline-none transition hover:decoration-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                          >
                            <span className="truncate">{p.name}</span>
                            <span aria-hidden className="shrink-0 text-[9px]">↗</span>
                            <span className="sr-only"> (opens in a new tab)</span>
                          </a>
                        ) : (
                          <span className="min-w-0 flex-1 truncate text-[var(--ui-ink)]">{p.name}</span>
                        )}
                        <span className="shrink-0 tabular-nums text-[var(--ui-ink-2)]">
                          {p.rating !== null ? fmt(Math.round(p.rating * 10) / 10) + "★" : "—"} · {fmt(p.review_count)}
                        </span>
                        {(p.rating_delta != null || p.reviews_delta != null) && (
                          <span className="w-20 shrink-0 text-right text-[10px] font-semibold tabular-nums text-[var(--ui-ink-2)]">
                            {p.rating_delta != null ? `${p.rating_delta > 0 ? "+" : ""}${fmt(Math.round(p.rating_delta * 100) / 100)}★` : ""}
                            {p.reviews_delta != null ? ` · ${p.reviews_delta > 0 ? "+" : ""}${fmt(p.reviews_delta)}` : ""}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
