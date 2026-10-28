"use client";

import type { BenchmarkResponse } from "@/lib/api-analytics";

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
  const hasDelta = delta !== undefined && delta !== null;
  return (
    <li className="flex items-center gap-2 py-2.5 first:pt-1 last:pb-1">
      <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--ui-ink)]">{label}</span>
      <span className="w-16 shrink-0 text-right text-[12px] font-bold tabular-nums text-[var(--ui-ink)]">{yours}</span>
      <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-[var(--ui-ink-2)]">{peers}</span>
      {hasDelta ? (
        <span className={`w-14 shrink-0 text-right text-[10px] font-bold tabular-nums ${(delta as number) >= 0 ? "text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}`}>
          {(delta as number) > 0 ? "+" : ""}{(delta as number).toFixed(1)}{suffix}
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
}: {
  benchmark: BenchmarkResponse | null;
  loading: boolean;
  onRefreshExternal?: () => void;
  refreshingExternal?: boolean;
}) {
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
    ? `${cohort?.label} (${peerCount} business${peerCount === 1 ? "" : "es"})`
    : "No peer set yet";
  const ratingDelta = benchmark.current_avg_rating - benchmark.similar_avg_rating;
  const reviewsDelta = benchmark.current_reviews_total - benchmark.similar_reviews_total;
  const responseDelta = benchmark.current_response_rate - benchmark.similar_response_rate;

  return (
    <div className="space-y-4 sm:space-y-5">
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
        {/* You vs peers */}
        <section aria-label="You vs nearby" className="ui-card p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">You vs nearby</h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">
                {peerLabel} · {cohort?.scope === "network" ? "Sayvors network" : "same city/category"} · Google reviews only.
              </p>
            </div>
            {!peerWeak && benchmark.my_rank && (
              <span className="rounded-[2px] bg-[var(--ui-sunken)] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
                Rank #{benchmark.my_rank} of {(benchmark.market?.length ?? cohort?.count ?? 0) + 1}
              </span>
            )}
          </div>

          <div className="mt-3 flex items-center gap-2 border-b border-[var(--ui-line)] pb-1 text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
            <span className="flex-1">Metric</span>
            <span className="w-16 text-right">You</span>
            <span className="w-16 text-right">Peers</span>
            <span className="w-14 text-right">Gap</span>
          </div>
          {peerWeak && (
            <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-2.5 text-[11px] text-[var(--ui-ink)]">
              Not enough peers for a median ({peerCount} business{peerCount === 1 ? "" : "es"}). We need at least 3 before showing a peer comparison.
            </p>
          )}
          <ul className="mt-2 divide-y divide-[var(--ui-line)]">
            <Row label="Average rating" yours={benchmark.current_avg_rating.toFixed(1) + "★"} peers={peerWeak ? "—" : benchmark.similar_avg_rating.toFixed(1) + "★"} delta={peerWeak ? null : ratingDelta} suffix="★" />
            <Row label="Total reviews" yours={String(benchmark.current_reviews_total)} peers={peerWeak ? "—" : String(benchmark.similar_reviews_total)} delta={peerWeak ? null : reviewsDelta} />
            <Row label="Response rate" yours={benchmark.current_response_rate.toFixed(0) + "%"} peers={peerWeak ? "—" : benchmark.similar_response_rate.toFixed(0) + "%"} delta={peerWeak ? null : responseDelta} suffix="%" />
            {rec && rec.my_pct !== null ? (
              <Row label="Reviews last 90d" yours={rec.my_pct.toFixed(0) + "%"} peers={peerWeak || rec.peer_median_pct === null ? "—" : rec.peer_median_pct.toFixed(0) + "%"} delta={peerWeak || rec.peer_median_pct === null ? null : rec.my_pct - rec.peer_median_pct} suffix="%" />
            ) : (
              <Row label="Reviews last 90d" yours="—" peers="—" />
            )}
          </ul>
          {cohort?.count === 0 && (
            <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
              You are the first business in this market on Sayvors. The peer median will appear as others join.
            </p>
          )}
        </section>

        {/* Gap to 4.5 */}
        <section aria-label="Gap to 4.5" className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Gap to 4.5★</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">How many 5-star reviews close the gap, at your current pace.</p>
          {!gap || gap.current_reviews === 0 ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">No reviews yet.</p>
          ) : gap.five_star_needed === 0 ? (
            <p className="mt-4 text-[13px] font-semibold text-[var(--ui-ink)]">
              You are at or above 4.5★. Keep the pace.
            </p>
          ) : (
            <>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-[30px] font-black leading-none tabular-nums text-[var(--ui-ink)]">{gap.five_star_needed}</span>
                <span className="text-[12px] font-semibold text-[var(--ui-ink-2)]">five-star reviews needed</span>
              </div>
              <p className="mt-2 text-[11px] text-[var(--ui-ink-2)]">
                From {gap.current_rating.toFixed(2)}★ across {gap.current_reviews} reviews.
                {gap.months !== null ? ` At ${gap.pace_per_month}/month, about ${gap.months} month${gap.months === 1 ? "" : "s"}.` : " Pace is not available yet."}
              </p>
              {gap.math && <p className="mt-1 break-all text-[10px] text-[var(--ui-ink-2)]">{gap.math}</p>}
            </>
          )}
        </section>
      </div>

      {/* Peer set disclosure */}
      <section aria-label="Peer set" className="ui-card p-5">
        <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Peer set</h3>
        <p className="text-[11px] text-[var(--ui-ink-2)]">
          Peer definition, sample, and what this comparison can and cannot tell you.
        </p>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Scope</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{cohort?.label ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Businesses</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{cohort?.count ?? 0}</dd>
          </div>
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">City / category</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">{cohort?.city ?? "—"} · {cohort?.category ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Source</dt>
            <dd className="mt-0.5 text-[12px] font-semibold text-[var(--ui-ink)]">Sayvors-connected listings</dd>
          </div>
        </dl>
        {peerWeak && (
          <p className="mt-2 text-[11px] font-semibold text-[var(--ui-ink)]">
            This cohort is too small for a median. At least 3 businesses are required before we show a peer comparison.
          </p>
        )}
        <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
          Median is the middle business in this peer set, not a national average. Sayvors-connected businesses only — not every competitor on Google. Treat small cohorts as directional.
        </p>
      </section>

      {benchmark.external && (
        <section aria-label="External peer set" className="ui-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">External peer set <span className="ml-1 rounded-[2px] bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">Pro</span></h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">
                Nearby listings from Google Places, not just Sayvors businesses.
              </p>
            </div>
            {onRefreshExternal && (
              <button
                onClick={onRefreshExternal}
                disabled={refreshingExternal}
                className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)] disabled:opacity-50"
              >
                {refreshingExternal ? "Refreshing…" : "Refresh peers"}
              </button>
            )}
          </div>

          {!benchmark.external.configured ? (
            <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink)]">
              Not connected. Add <code>GOOGLE_PLACES_API_KEY</code> to enable the external peer set. Until then we show the Sayvors cohort above, clearly labelled.
            </p>
          ) : !benchmark.external.available ? (
            <p className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink)]">
              {benchmark.external.count === 0
                ? "No external peers captured yet. Refresh to fetch nearby listings."
                : `Only ${benchmark.external.count} external peers captured. At least 3 are needed for a median.`}
            </p>
          ) : (
            <>
              <div className="mt-3 flex flex-wrap items-baseline gap-4">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Peer median rating</p>
                  <p className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">
                    {benchmark.external.median_rating !== null && benchmark.external.median_rating !== undefined ? benchmark.external.median_rating.toFixed(1) + "★" : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Peer median reviews</p>
                  <p className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{benchmark.external.median_reviews ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Peers</p>
                  <p className="text-[22px] font-black tabular-nums text-[var(--ui-ink)]">{benchmark.external.count}</p>
                </div>
              </div>
              <p className="mt-2 text-[10px] text-[var(--ui-ink-2)]">
                {benchmark.external.radius_m ? `Within ${benchmark.external.radius_m}m` : "Radius not recorded"}
                {benchmark.external.category ? ` · ${benchmark.external.category}` : ""}
                {benchmark.external.fetched_at ? ` · fetched ${new Date(benchmark.external.fetched_at).toLocaleDateString()}` : ""}
                {benchmark.external.stale ? " · stale" : ""}
              </p>
              {benchmark.external.peers && benchmark.external.peers.length > 0 && (
                <ul className="mt-3 grid gap-1 sm:grid-cols-2">
                  {benchmark.external.peers.slice(0, 6).map((p) => (
                    <li key={p.place_id} className="flex items-center gap-2 text-[11px]">
                      <span className="min-w-0 flex-1 truncate text-[var(--ui-ink)]">{p.name}</span>
                      <span className="shrink-0 tabular-nums text-[var(--ui-ink-2)]">
                        {p.rating !== null ? p.rating.toFixed(1) + "★" : "—"} · {p.review_count}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
