"use client";

import { useEffect, useRef, useState } from "react";
import {
  fetchAcquisition,
  fetchOpportunities,
  fetchTimeseries,
  fetchVisibility,
  type AcquisitionResponse,
  type OpportunitiesResponse,
  type TimeseriesPoint,
  type VisibilityResponse,
} from "@/lib/api-analytics";
import { RangeChannelControls, useGoogleChannels } from "@/components/analytics/Controls";
import { StatCard } from "@/components/analytics/StatCard";
import { MetricChart } from "@/components/analytics/Charts";

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
    ])
      .then(([v, a, o, t]) => {
        if (cancelled) return;
        setVisibility(v);
        setAcquisition(a);
        setOpportunities(o);
        setPoints(t);
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
  const hasData = !!visibility && visibility.impressions_maps > 0;

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
      ) : !hasData && !loading ? (
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
              value={visibility ? fmt(visibility.impressions_maps) : "0"}
              sub="people who saw you"
              delta={visibility?.impressions_trend_pct}
              accent="bg-sky/10 text-sky"
              icon={ACTION_ICONS.impressions}
            />
            <StatCard
              loading={loading}
              label="Website clicks"
              value={acquisition ? fmt(acquisition.website_clicks.total) : "0"}
              delta={acquisition?.website_clicks.trend_pct}
              accent="bg-deep-violet/10 text-deep-violet"
              icon={ACTION_ICONS.website}
            />
            <StatCard
              loading={loading}
              label="Calls"
              value={acquisition ? fmt(acquisition.call_clicks.total) : "0"}
              delta={acquisition?.call_clicks.trend_pct}
              accent="bg-emerald/10 text-emerald"
              icon={ACTION_ICONS.calls}
            />
            <StatCard
              loading={loading}
              label="Directions"
              value={acquisition ? fmt(acquisition.direction_requests.total) : "0"}
              delta={acquisition?.direction_requests.trend_pct}
              accent="bg-amber/10 text-amber-600"
              icon={ACTION_ICONS.directions}
            />
          </div>

          {/* Chart + CTR */}
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
                {visibility ? `${visibility.click_through_pct ?? 0}%` : "—"}
              </p>
              <p className="text-[11px] text-ink/45">of impressions became a click, call or direction request</p>
              {visibility && (
                <div className="mt-4 space-y-2 border-t border-deep-violet/[0.06] pt-4 text-[12px] text-ink/60">
                  <p className="flex justify-between">
                    <span>Customer actions</span>
                    <span className="font-semibold text-ink">{fmt(visibility.customer_actions)}</span>
                  </p>
                  <p className="flex justify-between">
                    <span>Total reviews</span>
                    <span className="font-semibold text-ink">{fmt(acquisition?.customer_actions.total ?? 0)}</span>
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Opportunities */}
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
