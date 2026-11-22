"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { fetchPulse, type PulseResponse } from "@/lib/api-analytics";
import { FactSource } from "@/components/analytics/FactSource";
import { GBP_DASHBOARD_URL } from "@/lib/google-links";
import { useI18n } from "@/lib/i18n/I18nProvider";

const PLATFORM_LABEL: Record<string, string> = {
  google_reviews: "Google",
  google: "Google",
  facebook: "Facebook",
  instagram: "Instagram",
  whatsapp: "WhatsApp",
};

function platformLabel(p: string): string {
  return PLATFORM_LABEL[p] ?? p.replace(/_/g, " ");
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function fmtAgo(iso: string | null, t: { justNow: string; minAgo: (n: number) => string; hAgo: (n: number) => string; dAgo: (n: number) => string }): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return t.justNow;
  if (mins < 60) return t.minAgo(mins);
  const hours = Math.round(mins / 60);
  if (hours < 24) return t.hAgo(hours);
  return t.dAgo(Math.round(hours / 24));
}

function areaLabel(t: ReturnType<typeof useI18n>["t"], category: string): string {
  const ca = t.analytics.complaintAreas as Record<string, string>;
  return ca[category] ?? category.replace(/_/g, " ");
}

function severityStyle(severity: string): string {
  if (severity === "high") return "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]";
  return "bg-[var(--ui-sunken)] text-[var(--ui-ink)]";
}

function DeltaChip({ value, suffix = "", noPriorLabel }: { value: number | null; suffix?: string; noPriorLabel: string }) {
  if (value === null || value === undefined) {
    return <span className="rounded-[8px] bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--ui-ink-2)]">{noPriorLabel}</span>;
  }
  const up = value > 0;
  const flat = value === 0;
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-[8px] px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${flat ? "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]" : up ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
      {!flat && (
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2.5 w-2.5 ${up ? "" : "rotate-180"}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {up ? "+" : ""}{value}{suffix}
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{label}</p>
      <p className="mt-0.5 truncate text-[16px] font-black tabular-nums text-[var(--ui-ink)]">{value}</p>
      {sub && <p className="truncate text-[10px] text-[var(--ui-ink-2)]">{sub}</p>}
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="ui-card p-5" aria-hidden>
      <div className="h-3 w-28 animate-pulse rounded-[8px] bg-[var(--ui-sunken)]" />
      <div className="mt-3 h-8 w-20 animate-pulse rounded-[8px] bg-[var(--ui-sunken)]" />
      <div className="mt-4 grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-[8px] bg-[var(--ui-sunken)]" />)}
      </div>
    </div>
  );
}

export default function PulseCards({
  days,
  channelId,
}: {
  days: number;
  channelId: string | null;
}) {
  const { t } = useI18n();
  const p = t.analytics.pulse;
  const query = useQuery({
    queryKey: queryKeys.analytics.pulse(days, channelId),
    queryFn: () => fetchPulse(days, channelId),
    staleTime: 30 * 1000,
  });

  if (query.isPending) {
    return (
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="ui-card p-4">
        <p className="text-[12px] font-semibold text-[var(--ui-ink-2)]">{p.couldNotLoad}</p>
      </div>
    );
  }

  const data: PulseResponse = query.data;
  const rep = data.reputation;
  const waiting = data.waiting;
  // Defensive defaults: an older API (or a rolling deploy) may not return the
  // newer cards yet. An absent list is "nothing to show", never a crash.
  const locations = data.locations ?? [];
  const oneThing = data.one_thing ?? null;
  const attention = data.attention ?? [];
  const synced = fmtAgo(rep.last_synced_at, { justNow: p.justNow, minAgo: p.minAgo, hAgo: p.hAgo, dAgo: p.dAgo });
  const waitingAsOf = fmtAgo(waiting.as_of, { justNow: p.justNow, minAgo: p.minAgo, hAgo: p.hAgo, dAgo: p.dAgo });
  const googleConnected = rep.sources.some(
    (s) => s.platform === "google_reviews" || s.platform === "google",
  );
  const googleInLocations = locations.some(
    (l) => l.platform === "google_reviews" || l.platform === "google",
  );
  const sourcesText = rep.sources.length
    ? rep.sources.map((s) => `${platformLabel(s.platform)} ${s.count}`).join(" · ")
    : p.noReviewsInPeriod;

  return (
    <div className="space-y-4 sm:space-y-5">
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
      {/* Reputation pulse */}
      <section aria-label={p.reputationPulse} className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{p.reputationPulse}</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">{p.lastVsPrior(days)}</p>
          </div>
          {rep.awaiting_reply > 0 && (
            <Link
              href="/dashboard/reviews?status=unanswered"
              className="ui-btn shrink-0 rounded-[8px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
            >
              {p.replyTo(rep.awaiting_reply)}
            </Link>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex items-baseline gap-1">
            <span className="text-[34px] font-black leading-none tabular-nums text-[var(--ui-ink)]">
              {rep.avg_rating > 0 ? rep.avg_rating.toFixed(1) : "-"}
            </span>
            <span className="text-[16px] font-bold text-[var(--ui-ink-2)]">&#9733;</span>
          </div>
          <DeltaChip value={rep.rating_delta} noPriorLabel={p.noPriorDataShort} />
          <span className="text-[10px] text-[var(--ui-ink-2)]">{p.vsPrior(days)}</span>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[var(--ui-line)] pt-3">
          <Stat label={p.newReviews} value={String(rep.new_reviews)} sub={rep.new_reviews_delta_pct !== null ? `${rep.new_reviews_delta_pct > 0 ? "+" : ""}${rep.new_reviews_delta_pct}% ${p.vsPriorPct}` : p.noPriorData} />
          <Stat label={p.responded} value={`${rep.response_rate}%`} sub={p.ofPeriodReviews} />
          <Stat label={p.awaitingReply} value={String(rep.awaiting_reply)} sub={rep.oldest_wait_days !== null ? p.oldestDays(rep.oldest_wait_days) : p.allClear} />
        </div>

        <FactSource
          source={
            rep.sources.length
              ? rep.sources.map((s) => platformLabel(s.platform)).join(" + ")
              : p.connectedReviewChannels
          }
          detail={p.lastDays(days)}
          note={[sourcesText, synced ? p.synced(synced) : null]
            .filter(Boolean)
            .join(" · ")}
          href={googleConnected ? GBP_DASHBOARD_URL : null}
          linkLabel={p.openGbpDashboard}
        />
      </section>

      {/* Who's waiting */}
      <section aria-label={p.whosWaiting} className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{p.whosWaiting}</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">{p.unansweredAcrossChannels}</p>
          </div>
          <Link
            href="/dashboard/channels/inbox"
            className="ui-btn shrink-0 rounded-[8px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
          >
            {p.openInbox}
          </Link>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[34px] font-black leading-none tabular-nums text-[var(--ui-ink)]">
              {waiting.unanswered_texts}
            </span>
            <span className="pb-0.5 text-[12px] font-semibold text-[var(--ui-ink-2)]">
              {waiting.unanswered_texts === 1 ? p.conversationWaiting : p.conversationsWaiting}
            </span>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[var(--ui-line)] pt-3">
          <Stat label={p.medianFirstReply} value={fmtDuration(waiting.median_first_response_seconds)} sub={`last ${days} days`} />
          <Stat label={p.waitingOver1h} value={String(waiting.waiting_over_1h)} sub={waiting.waiting_over_1h === 1 ? p.channel : p.channels} />
          <Stat
            label={p.missedCalls}
            value={waiting.missed_calls_available && waiting.missed_calls !== null ? String(waiting.missed_calls) : "-"}
            sub={waiting.missed_calls_available ? p.businessHours : p.callsNotConnected}
          />
        </div>

        <FactSource
          source={p.sayvorsInbox}
          detail={waitingAsOf ? p.asOf(waitingAsOf) : p.live}
          note={
            waiting.oldest_unanswered_seconds !== null
              ? p.oldestWaiting(fmtDuration(waiting.oldest_unanswered_seconds))
              : p.nothingWaiting
          }
        />
      </section>
      </div>

      <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
        {/* Location league */}
        <section aria-label={p.locationLeague} className="ui-card p-5 lg:col-span-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{p.locationLeague}</h3>
              <p className="text-[11px] text-[var(--ui-ink-2)]">{p.worstFirst}</p>
            </div>
            <Link
              href="/dashboard/analytics?tab=insights"
              className="ui-btn shrink-0 rounded-[8px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
            >
              {p.viewInsights}
            </Link>
          </div>
          {locations.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{p.noLocationData}</p>
          ) : (
            <ul className="mt-4 divide-y divide-[var(--ui-line)]">
              {locations.slice(0, 6).map((loc) => (
                <li key={loc.channel_id} className="flex flex-wrap items-center gap-2 py-2.5 first:pt-0 last:pb-0">
                  <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{loc.name}</span>
                  <span className={`shrink-0 rounded-[8px] px-1.5 py-0.5 text-[11px] font-bold tabular-nums ${loc.below_threshold ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                    {loc.avg_rating !== null ? loc.avg_rating.toFixed(1) : "-"}&#9733;
                  </span>
                  <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-[var(--ui-ink-2)]">{loc.new_reviews} {p.new}</span>
                  <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-[var(--ui-ink-2)]">{loc.response_rate}%</span>
                  <span className={`w-20 shrink-0 text-right text-[11px] tabular-nums ${loc.unanswered > 0 ? "font-bold text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)]"}`}>
                    {loc.unanswered} {p.waiting}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {locations.some((l) => l.below_threshold) && (
            <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
              {p.belowThreshold(locations.filter((l) => l.below_threshold).length, locations.length)}
            </p>
          )}
          <FactSource
            source={p.connectedListings}
            detail={p.lastDays(days)}
            note={synced ? p.synced(synced) : null}
            href={googleInLocations ? GBP_DASHBOARD_URL : null}
            linkLabel={p.openGbpDashboard}
          />
        </section>

        {/* One thing that changed */}
        <section aria-label={p.oneThingChanged} className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{p.oneThingChanged}</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">{p.biggestMove}</p>
          {!oneThing ? (
            <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{p.noComplaintMovement}</p>
          ) : (
            <>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-[14px] font-bold text-[var(--ui-ink)]">{areaLabel(t, oneThing.category)}</span>
                <DeltaChip value={oneThing.trend_pct} suffix="%" noPriorLabel={p.noPriorDataShort} />
              </div>
              <p className="mt-2 text-[12px] text-[var(--ui-ink)]">
                {p.mentionsInDays(oneThing.mentions, oneThing.period_days)}
                {oneThing.serious > 0 ? ` · ${p.serious(oneThing.serious)}` : ""}
                {oneThing.staff_named > 0 ? ` · ${p.staffNamed(oneThing.staff_named)}` : ""}.
              </p>
              {oneThing.top_terms.length > 0 && (
                <p className="mt-2 truncate text-[10px] text-[var(--ui-ink-2)]">
                  {oneThing.top_terms.map((t) => t.name).join(" · ")}
                </p>
              )}
              <Link
                href="/dashboard/analytics?tab=insights"
                className="mt-3 inline-block text-[11px] font-bold text-[var(--ui-ink)] underline underline-offset-2"
              >
                {p.seeTheReviews}
              </Link>
            </>
          )}
          <FactSource
            source={p.reviewComplaintTags}
            detail={`last ${oneThing?.period_days ?? days} days`}
            href={googleInLocations ? GBP_DASHBOARD_URL : null}
            linkLabel={p.openGbpDashboard}
          />
        </section>
      </div>

      {/* Needs attention */}
      <section aria-label={p.needsAttention} className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{p.needsAttention}</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">{p.prioritizedByRisk}</p>
          </div>
          {attention.length === 0 && (
            <span className="rounded-[8px] bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
              {p.allClearBadge}
            </span>
          )}
        </div>
        {attention.length > 0 && (
          <ul className="mt-3 divide-y divide-[var(--ui-line)]">
            {attention.map((item, i) => (
              <li key={`${item.kind}-${i}`} className="flex items-center gap-2 py-2.5 first:pt-0 last:pb-0">
                <span className={`shrink-0 rounded-[8px] px-1.5 py-0.5 text-[9px] font-bold uppercase ${severityStyle(item.severity)}`}>
                  {item.severity}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{item.title}</span>
                {item.detail && <span className="shrink-0 text-[10px] text-[var(--ui-ink-2)]">{item.detail}</span>}
                {item.href && (
                  <Link href={item.href} className="shrink-0 text-[11px] font-bold text-[var(--ui-ink)] underline underline-offset-2">
                    {p.open}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
        <FactSource
          source={p.priorityEngine}
          detail={p.derivedFromCards}
        />
      </section>
    </div>
  );
}
