"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import PresenceChart from "@/components/analytics/PresenceChart";
import { FactSource } from "@/components/analytics/FactSource";
import { GBP_DASHBOARD_URL, listingMapsUrl } from "@/lib/google-links";
import { timeAgo } from "@/lib/relative-time";
import type { TimeseriesPoint } from "@/lib/api-analytics";

/* ── Google presence (Localith snapshot — live even with 0 reviews) ── */

export interface PresenceData {
  listingName: string;
  windowLabel: string | null;
  searchViews: number;
  mapViews: number;
  websiteClicks: number;
  directionRequests: number;
  phoneCalls: number;
  totalReviews: number;
  averageRating: number;
  /** Google's own Maps URL / place id; either one makes a real verify link. */
  mapsUrl?: string | null;
  placeId?: string | null;
  /** When the underlying Localith/GBP snapshot was last refreshed. */
  syncedAt?: string | null;
  branchCount?: number;
}

function num(v: unknown): number {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
}

export function presenceFromProfile(prof: {
  connection?: {
    listing_name?: string;
    metrics_start?: string | null;
    metrics_end?: string | null;
    total_reviews?: number;
    average_rating?: number;
    maps_url?: string | null;
    listing_google_id?: string | null;
    metrics_synced_at?: string | null;
    last_synced_at?: string | null;
  };
  metrics?: { listings?: Record<string, number | string | null>[] };
  item_metrics?: { listings?: Record<string, number | string | null>[] };
} | null): PresenceData | null {
  const perf = prof?.metrics?.listings?.[0];
  const rev = prof?.item_metrics?.listings?.[0];
  if (!perf && !rev) return null;
  const conn = prof?.connection ?? {};
  return {
    listingName: conn.listing_name ?? "",
    windowLabel: conn.metrics_start && conn.metrics_end ? `${conn.metrics_start} → ${conn.metrics_end}` : null,
    searchViews: num(perf?.googleSearchDesktop) + num(perf?.googleSearchMobile),
    mapViews: num(perf?.googleMapsDesktop) + num(perf?.googleMapsMobile),
    websiteClicks: num(perf?.websiteClicks),
    directionRequests: num(perf?.directions),
    phoneCalls: num(perf?.callClicks),
    totalReviews: num(rev?.numberOfReviews ?? conn.total_reviews),
    averageRating: num(rev?.averageRating ?? conn.average_rating),
    mapsUrl: conn.maps_url ?? null,
    placeId: conn.listing_google_id ?? null,
    syncedAt: conn.metrics_synced_at ?? conn.last_synced_at ?? null,
    branchCount: 1,
  };
}

/* Two chart groups plus the snapshot's window footnote. Theme: the Team
 * page's flat system — the .team-ui ancestor lives on the analytics shell,
 * so the --ui-* vars resolve here. */
export default function PresenceSection({
  presence,
  points,
  channelLabels,
  scopeLabel,
  locale,
  loading,
}: {
  presence: PresenceData;
  points: TimeseriesPoint[];
  channelLabels: Record<string, string>;
  scopeLabel: string;
  locale: string;
  loading: boolean;
}) {
  const { t } = useI18n();
  const copy = t.analytics.presence;
  const p = presence;
  // Prefer the listing's own Maps URL / place id. An aggregate view has no
  // single listing, so it links to the GBP location manager instead of
  // pretending a search result is the tenant's listing.
  const mapsHref = listingMapsUrl({ mapsUrl: p.mapsUrl, placeId: p.placeId });
  const verifyHref = mapsHref ?? GBP_DASHBOARD_URL;
  const synced = timeAgo(p.syncedAt);
  const branchNote =
    p.branchCount && p.branchCount > 1 ? `${p.branchCount} branches` : null;

  const labels = {
    discovery: copy.presenceDiscovery,
    actions: copy.presenceActions,
    impressions: copy.impressions,
    searchViews: copy.searchViews,
    mapViews: copy.mapViews,
    websiteClicks: copy.websiteClicks,
    directionRequests: copy.directionRequests,
    phoneCalls: copy.phoneCalls,
    messages: copy.messages,
    bookings: copy.bookings,
    reviewsMetric: copy.reviewsMetric,
    repliesMetric: copy.repliesMetric,
    customerActions: copy.customerActions,
    totalLabel: copy.totalLabel,
    perBranchDay: copy.perBranchDay,
    dailyAvg: copy.dailyAvg,
    peak: copy.peak,
    on: copy.on,
    scopeTotal: copy.scopeTotal,
    scopeByBranch: copy.scopeByBranch,
    noMetricYet: copy.noMetricYet,
    noMetricHint: copy.noMetricHint,
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 sm:gap-6 lg:grid-cols-2">
        <PresenceChart
          points={points}
          channelLabels={channelLabels}
          labels={labels}
          group="discovery"
          locale={locale}
          loading={loading}
          scopeLabel={scopeLabel}
          source="Google Business Profile"
          sourceDetail={p.windowLabel ?? copy.last30Days}
          sourceHref={verifyHref}
          sourceLinkLabel={mapsHref ? "Verify on Google Maps" : "Open GBP dashboard"}
        />
        <PresenceChart
          points={points}
          channelLabels={channelLabels}
          labels={labels}
          group="actions"
          locale={locale}
          loading={loading}
          scopeLabel={scopeLabel}
          source="Google Business Profile"
          sourceDetail={p.windowLabel ?? copy.last30Days}
          sourceHref={verifyHref}
          sourceLinkLabel={mapsHref ? "Verify on Google Maps" : "Open GBP dashboard"}
        />
      </div>
      <div className="ui-card p-4 sm:p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">
            {copy.title}
            {p.listingName ? ` — ${p.listingName}` : ""}
          </h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">
            {p.windowLabel ?? copy.last30Days} · {copy.viaLocalith}
          </p>
        </div>
        <FactSource
          source="Google Business Profile"
          detail={p.windowLabel ?? copy.last30Days}
          note={[branchNote, synced ? `synced ${synced}` : null]
            .filter(Boolean)
            .join(" · ") || null}
          href={verifyHref}
          linkLabel={mapsHref ? "Verify on Google Maps" : "Open GBP dashboard"}
        />
      </div>
    </div>
  );
}
