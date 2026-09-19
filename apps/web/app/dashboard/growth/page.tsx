"use client";

import { useEffect, useRef, useState } from "react";
import {
  fetchAcquisition,
  fetchOpportunities,
  fetchOverview,
  fetchTimeseries,
  fetchVisibility,
  type AcquisitionResponse,
  type OpportunitiesResponse,
  type Overview,
  type TimeseriesPoint,
  type VisibilityResponse,
} from "@/lib/api-analytics";
import { apiFetch } from "@/lib/api-rag";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";
import { StatCard } from "@/components/analytics/StatCard";
import { MetricChart } from "@/components/analytics/Charts";

function num(v: unknown): number {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
}

interface PresencePerf {
  searchViews: number;
  mapViews: number;
  websiteClicks: number;
  directionRequests: number;
  phoneCalls: number;
  windowLabel: string;
}

function presencePerf(prof: {
  connection?: { metrics_start?: string | null; metrics_end?: string | null };
  metrics?: { listings?: Record<string, number | string | null>[] };
} | null): PresencePerf | null {
  const row = prof?.metrics?.listings?.[0];
  if (!row) return null;
  const conn = prof?.connection ?? {};
  return {
    searchViews: num(row.googleSearchDesktop) + num(row.googleSearchMobile),
    mapViews: num(row.googleMapsDesktop) + num(row.googleMapsMobile),
    websiteClicks: num(row.websiteClicks),
    directionRequests: num(row.directions),
    phoneCalls: num(row.callClicks),
    windowLabel: conn.metrics_start && conn.metrics_end
      ? `${conn.metrics_start} → ${conn.metrics_end}`
      : "last 30 days",
  };
}

const TYPE_STYLES: Record<string, { bg: string; label: string }> = {
  operations: { bg: "bg-coral/10 text-coral", label: "Operations" },
  reputation: { bg: "bg-deep-violet/[0.07] text-deep-violet", label: "Reputation" },
  marketing: { bg: "bg-magenta/[0.08] text-magenta", label: "Marketing" },
  profile: { bg: "bg-sky/10 text-sky", label: "Profile" },
};

const ACTION_ICONS: Record<string, React.ReactNode> = {
  impressions: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  website: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  calls: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.13.96.36 1.9.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0122 16.92z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  directions: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5" aria-hidden>
      <path d="M12 2l10 10-10 10L2 12 12 2z" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9 12h6M13 9l3 3-3 3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

export default function GrowthPage() {
  const [days, setDays] = useState<number>(30);
  const [channelId, setChannelId] = useState<string | null>(null);
  const channels = useGoogleChannels();
  const [visibility, setVisibility] = useState<VisibilityResponse | null>(null);
  const [acquisition, setAcquisition] = useState<AcquisitionResponse | null>(null);
  const [opportunities, setOpportunities] = useState<OpportunitiesResponse | null>(null);
  const [points, setPoints] = useState<TimeseriesPoint[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [presence, setPresence] = useState<PresencePerf | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const hasLoaded = useRef(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchVisibility(days, channelId),
      fetchAcquisition(days, channelId),
      fetchOpportunities(days, channelId),
      fetchTimeseries(days, channelId),
      fetchOverview(days, channelId).catch(() => null),
      apiFetch("/api/v1/integrations/localith/profile").catch(() => null),
    ])
      .then(([v, a, o, t, ov, prof]) => {
        if (cancelled) return;
        setVisibility(v);
        setAcquisition(a);
        setOpportunities(o);
        setPoints(t);
        setOverview(ov);
        setPresence(presencePerf(prof));
        setError(false);
        hasLoaded.current = true;
      })
      .catch(() => {
        if (!cancelled && !hasLoaded.current) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, channelId, refreshToken]);

  const fmt = (n: number) => new Intl.NumberFormat("en").format(n);
  const nativePerf = !!visibility && visibility.impressions_maps > 0;
  // Localith snapshot fills the cards when the native daily sync has no rows yet.
  const usePresence = !nativePerf && !!presence;
  const impressions = nativePerf
    ? (visibility?.impressions_maps ?? 0)
    : (presence ? presence.searchViews + presence.mapViews : 0);
  const website = nativePerf
    ? (acquisition?.website_clicks.total ?? 0)
    : (presence?.websiteClicks ?? 0);
  const calls = nativePerf
    ? (acquisition?.call_clicks.total ?? 0)
    : (presence?.phoneCalls ?? 0);
  const directions = nativePerf
    ? (acquisition?.direction_requests.total ?? 0)
    : (presence?.directionRequests ?? 0);
  const actions = website + calls + directions;
  const ctr = nativePerf
    ? (visibility?.click_through_pct ?? null)
    : impressions > 0
      ? Math.round((actions / impressions) * 100 * 100) / 100
      : null;
  const viaNote = usePresence ? " · via Localith" : "";
  const hasOpps = (opportunities?.opportunities.length ?? 0) > 0;
  const showMain = nativePerf || usePresence;
  const showEmpty = !showMain && !hasOpps && !loading;

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff] p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Growth</h1>
          <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
            Google visibility, customer acquisition and where to grow next.
          </p>
        </div>
        <RangeChannelControls
          days={days}
          setDays={(d) => {
            setDays(d);
            setLoading(true);
          }}
          channelId={channelId}
          setChannelId={(c) => {
            setChannelId(c);
            setLoading(true);
          }}
          channels={channels}
        />
      </div>

      {error && !loading ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[13px] font-semibold text-ink/60">Couldn&apos;t load growth data.</p>
          <button
            onClick={() => {
              setError(false);
              setLoading(true);
              setRefreshToken((t) => t + 1);
            }}
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            Retry
          </button>
        </div>
      ) : showEmpty ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-white bg-white/80 py-16 text-center backdrop-blur-sm">
          <p className="text-[14px] font-bold text-ink">No performance data yet</p>
          <p className="max-w-sm text-[12px] text-ink/50">
            Google performance metrics sync automatically for connected channels — check back after the next sync.
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              loading={loading}
              label="Maps impressions"
              value={fmt(impressions)}
              sub={usePresence ? `people who saw you${viaNote}` : "people who saw you"}
              delta={nativePerf ? visibility?.impressions_trend_pct : undefined}
              accent="bg-sky/10 text-sky"
              icon={ACTION_ICONS.impressions}
            />
            <StatCard
              loading={loading}
              label="Website clicks"
              value={fmt(website)}
              sub={usePresence ? `last ${days} days${viaNote}` : undefined}
              delta={nativePerf ? acquisition?.website_clicks.trend_pct : undefined}
              accent="bg-deep-violet/10 text-deep-violet"
              icon={ACTION_ICONS.website}
            />
            <StatCard
              loading={loading}
              label="Calls"
              value={fmt(calls)}
              sub={usePresence ? `last ${days} days${viaNote}` : undefined}
              delta={nativePerf ? acquisition?.call_clicks.trend_pct : undefined}
              accent="bg-emerald/10 text-emerald"
              icon={ACTION_ICONS.calls}
            />
            <StatCard
              loading={loading}
              label="Directions"
              value={fmt(directions)}
              sub={usePresence ? `last ${days} days${viaNote}` : undefined}
              delta={nativePerf ? acquisition?.direction_requests.trend_pct : undefined}
              accent="bg-amber/10 text-amber-600"
              icon={ACTION_ICONS.directions}
            />
          </div>

          {/* Chart + CTR */}
          {showMain && (
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {loading ? (
                <div className="h-72 animate-pulse rounded-2xl border-2 border-white bg-white/60" aria-hidden />
              ) : (
                <MetricChart points={points} />
              )}
            </div>
            <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
              <h3 className="text-[14px] font-bold text-ink">Conversion</h3>
              <p className="mt-3 text-[32px] font-bold text-ink">
                {ctr !== null ? `${ctr}%` : "—"}
              </p>
              <p className="text-[11px] text-ink/45">of impressions became a click, call or direction request{usePresence ? " · via Localith" : ""}</p>
              <div className="mt-4 space-y-2 border-t border-deep-violet/[0.06] pt-4 text-[12px] text-ink/60">
                <p className="flex justify-between">
                  <span>Customer actions</span>
                  <span className="font-semibold text-ink">{fmt(actions)}</span>
                </p>
                <p className="flex justify-between">
                  <span>Total reviews</span>
                  <span className="font-semibold text-ink">{fmt(overview?.total_reviews ?? 0)}</span>
                </p>
                <p className="flex justify-between">
                  <span>Response rate</span>
                  <span className="font-semibold text-ink">{overview ? `${Math.round(overview.response_rate)}%` : "—"}</span>
                </p>
              </div>
            </div>
          </div>
          )}

          {/* Opportunities — independent of performance data */}
          <section aria-label="Growth opportunities" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
            <h3 className="mb-4 text-[14px] font-bold text-ink">AI growth opportunities</h3>
            {loading || !opportunities ? (
              <div className="space-y-2" aria-hidden>
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-10 animate-pulse rounded-lg bg-ink/[0.06]" />
                ))}
              </div>
            ) : opportunities.opportunities.length === 0 ? (
              <p className="py-4 text-center text-[12px] text-ink/35">No opportunities right now — you&apos;re on top of it.</p>
            ) : (
              <ol className="space-y-2.5">
                {opportunities.opportunities.map((o) => {
                  const style = TYPE_STYLES[o.type] ?? TYPE_STYLES.reputation;
                  return (
                    <li key={o.priority} className="flex items-start gap-3 rounded-xl p-3 transition hover:bg-ink/[0.02]">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-deep-violet to-magenta text-[11px] font-bold text-white">
                        {o.priority}
                      </span>
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-ink">
                          {o.title}
                          <span className={`rounded px-1.5 py-px text-[9px] font-bold uppercase ${style.bg}`}>{style.label}</span>
                        </p>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-ink/50">{o.detail}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
