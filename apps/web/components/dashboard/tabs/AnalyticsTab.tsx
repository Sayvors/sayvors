"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { fetchMessagingOverview, type MessagingOverview } from "@/lib/api-analytics";
import { ChannelLogo } from "../ChannelLogos";

interface AnalyticsTabProps {
  channelSlug: string;
  channelName: string;
}

interface ChannelRow {
  id: string;
  platform: string;
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86_400).toFixed(1)} d`;
}

export default function AnalyticsTab({ channelSlug, channelName }: AnalyticsTabProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [data, setData] = useState<MessagingOverview | null>(null);
  const [channelId, setChannelId] = useState<string | null>(null);

  // Resolve the channel UUID from the slug (slug == platform for messaging channels).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = (await apiFetch("/api/v1/channels?limit=100")) as { channels?: ChannelRow[] };
        const match = (res?.channels ?? []).find(
          (c: ChannelRow) => c.platform === channelSlug,
        );
        if (!cancelled) setChannelId(match?.id ?? null);
      } catch {
        if (!cancelled) setChannelId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [channelSlug]);

  useEffect(() => {
    if (channelId === null) {
      // No channel found for this slug — nothing to show.
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetchMessagingOverview(30, channelId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId]);

  const totals = data?.totals;
  const stats = totals
    ? [
        { label: "Messages In", value: totals.messages_in.toLocaleString(), change: null },
        { label: "Messages Out", value: totals.messages_out.toLocaleString(), change: null },
        { label: "Conversations", value: totals.conversations.toLocaleString(), change: null },
        { label: "Response Rate", value: totals.response_rate !== null ? `${totals.response_rate}%` : "—", change: null },
      ]
    : [];

  return (
    <div className="p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-[16px] font-bold text-ink flex items-center gap-2">
          <ChannelLogo channel={channelSlug} />
          {channelName} Analytics
        </h2>
        <p className="mt-0.5 text-[13px] text-ink/60">
          Messaging performance over the last 30 days (stored rollups).
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-ink/20 border-t-deep-violet" />
        </div>
      )}

      {!loading && error && (
        <div className="rounded-2xl border border-ink/[0.06] bg-white/80 p-6 text-center">
          <p className="text-[13px] text-ink/60">Could not load analytics. Try again later.</p>
        </div>
      )}

      {!loading && !error && !data && (
        <div className="rounded-2xl border border-ink/[0.06] bg-white/80 p-6 text-center">
          <p className="text-[13px] text-ink/60">No messaging data yet. Data appears after the daily rollup runs.</p>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {stats.map((s) => (
              <div key={s.label} className="rounded-2xl border-2 border-white bg-white/80 p-4">
                <p className="text-[11px] font-semibold text-ink/50">{s.label}</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-[22px] font-bold text-ink">{s.value}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Response health */}
          <div className="rounded-2xl border-2 border-white bg-white/80 p-4 sm:p-5">
            <h3 className="mb-3 text-[13px] font-bold text-ink">Response Health</h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div>
                <p className="text-[11px] font-semibold text-ink/50">Median First Reply</p>
                <p className="mt-1 text-[18px] font-bold text-ink">{fmtDuration(totals!.median_first_response_seconds)}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-ink/50">P90 First Reply</p>
                <p className="mt-1 text-[18px] font-bold text-ink">{fmtDuration(totals!.p90_first_response_seconds)}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-ink/50">Unanswered Now</p>
                <p className="mt-1 text-[18px] font-bold text-ink">{totals!.unanswered_now ?? "—"}</p>
              </div>
            </div>
            <p className="mt-3 text-[10px] text-ink/40">
              Meta "Very responsive" gate: 90% answered, median under 15 min.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
