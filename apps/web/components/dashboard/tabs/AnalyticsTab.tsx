"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { fetchMessagingOverview, type MessagingOverview } from "@/lib/api-analytics";
import { ChannelLogo } from "../ChannelLogos";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type TabDict = Dict["channelHub"]["workspace"]["tab"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

function fmtDuration(seconds: number | null, tb: TabDict, fmt: (n: number) => string): string {
  if (seconds === null) return "—";
  if (seconds < 60) return fill(tb.durS, { n: fmt(Math.round(seconds)) });
  if (seconds < 3600) return fill(tb.durMin, { n: fmt(Math.round(seconds / 60)) });
  if (seconds < 86_400) return fill(tb.durH, { n: fmt(Math.round((seconds / 3600) * 10) / 10) });
  return fill(tb.durD, { n: fmt(Math.round((seconds / 86_400) * 10) / 10) });
}

interface AnalyticsTabProps {
  channelSlug: string;
  channelName: string;
}

interface ChannelRow {
  id: string;
  platform: string;
}

export default function AnalyticsTab({ channelSlug, channelName }: AnalyticsTabProps) {
  const { t, locale } = useI18n();
  const tb = t.channelHub.workspace.tab;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
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
        { label: tb.msgIn, value: fmt(totals.messages_in), change: null },
        { label: tb.msgOut, value: fmt(totals.messages_out), change: null },
        { label: tb.convs, value: fmt(totals.conversations), change: null },
        { label: tb.respRate, value: totals.response_rate !== null ? `${fmt(totals.response_rate)}%` : "—", change: null },
      ]
    : [];

  return (
    <div className="p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-[16px] font-bold text-ink flex items-center gap-2">
          <ChannelLogo channel={channelSlug} />
          {fill(tb.analyticsTitle, { name: channelName })}
        </h2>
        <p className="mt-0.5 text-[13px] text-ink/60">
          {tb.analyticsSub}
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-ink/20 border-t-deep-violet" />
        </div>
      )}

      {!loading && error && (
        <div className="rounded-2xl border border-ink/[0.06] bg-white/80 p-6 text-center">
          <p className="text-[13px] text-ink/60">{tb.loadError}</p>
        </div>
      )}

      {!loading && !error && !data && (
        <div className="rounded-2xl border border-ink/[0.06] bg-white/80 p-6 text-center">
          <p className="text-[13px] text-ink/60">{tb.noData}</p>
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
            <h3 className="mb-3 text-[13px] font-bold text-ink">{tb.respHealth}</h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div>
                <p className="text-[11px] font-semibold text-ink/50">{tb.medianReply}</p>
                <p className="mt-1 text-[18px] font-bold text-ink">{fmtDuration(totals!.median_first_response_seconds, tb, fmt)}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-ink/50">{tb.p90Reply}</p>
                <p className="mt-1 text-[18px] font-bold text-ink">{fmtDuration(totals!.p90_first_response_seconds, tb, fmt)}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-ink/50">{tb.unanswered}</p>
                <p className="mt-1 text-[18px] font-bold text-ink">{totals!.unanswered_now === null || totals!.unanswered_now === undefined ? "—" : fmt(totals!.unanswered_now)}</p>
              </div>
            </div>
            <p className="mt-3 text-[10px] text-ink/40">
              {tb.metaGate}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
