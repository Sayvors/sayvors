"use client";

import { useEffect, useRef, useState } from "react";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import {
  fetchMessagingOverview,
  type MessagingOverview,
} from "@/lib/api-analytics";

/*
 * Messages & response speed across WhatsApp / Instagram / Facebook.
 *
 * Reads the backend's stored daily rollups (`channel_daily_metrics`) — the
 * worker computes, this section just renders. It owns its fetch and fails
 * quiet: any error renders nothing, so a rollup hiccup can never take down
 * the Overview page around it.
 */

const CARD = "rounded-2xl border-2 border-white bg-white p-4 sm:p-5";
const GOAL_RATE = 90; // Meta's "Very responsive" bar, mirrored by the API
const GOAL_MEDIAN_MIN = 15;

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86_400).toFixed(1)} d`;
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return null;
  const up = value > 0;
  const flat = value === 0;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-px text-[10px] font-bold tabular-nums ${
        up ? "bg-emerald/10 text-emerald" : flat ? "bg-ink/[0.05] text-ink/50" : "bg-coral/10 text-coral"
      }`}
    >
      {up ? "+" : ""}{value}%
    </span>
  );
}

/** Inbound delta is "more" (busy) — neutral colour; reply volume up = good. */
function countDelta(cur: number, prev: number): number | null {
  if (prev === 0) return null;
  return Math.round((cur - prev) / prev * 100);
}

/** One active rollup row is enough to show the section, even at zero traffic. */
function hasMessagingData(d: MessagingOverview | null): boolean {
  return !!d && (d.channels.length > 0 || d.totals.messages_in > 0 || d.totals.messages_out > 0);
}

export default function MessagingSection({
  days,
  refreshToken,
  onHasData,
}: {
  days: number;
  refreshToken: number;
  /** Tells the page whether messaging has anything to show, so a
   *  WhatsApp-only tenant skips the "No review data yet" empty state. */
  onHasData?: (has: boolean) => void;
}) {
  const [data, setData] = useState<MessagingOverview | null>(null);
  const hasLoaded = useRef(false);

  useEffect(() => {
    let cancelled = false;
    fetchMessagingOverview(days)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          hasLoaded.current = true;
          onHasData?.(hasMessagingData(d));
        }
      })
      .catch(() => {
        // Fail quiet: the section vanishes rather than erroring the page.
        if (!cancelled && !hasLoaded.current) {
          setData(null);
          onHasData?.(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [days, refreshToken, onHasData]);

  // No rows yet (worker hasn't run / brand-new tenant) — show nothing.
  if (!data || !hasMessagingData(data)) {
    return null;
  }

  const t = data.totals;
  const median = t.median_first_response_seconds;
  const rate = t.response_rate;
  const meetsRate = rate !== null && rate >= GOAL_RATE;
  const meetsMedian = median !== null && median < GOAL_MEDIAN_MIN * 60;
  const meetsBoth = meetsRate && meetsMedian;

  return (
    <section aria-label="Messages and response speed" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[15px] font-bold text-ink">Messages &amp; response speed</h2>
        {t.as_of && (
          <p className="text-[10.5px] text-ink/40">
            updated {new Date(t.as_of).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} · last {days}d
          </p>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {/* Response health — the two numbers Meta's badge is made of */}
        <div className={CARD}>
          <h3 className="text-[13px] font-bold text-ink">Response health</h3>
          <div className="mt-3 flex items-end gap-5">
            <div>
              <p className="text-[26px] font-black leading-none text-ink tabular-nums">
                {median !== null ? fmtDuration(median) : "—"}
              </p>
              <p className="mt-1 text-[10.5px] font-semibold uppercase tracking-wide text-ink/40">
                median first reply
              </p>
              {t.median_first_response_seconds_prev !== null && median !== null && (
                <div className="mt-1"><Delta value={countDelta(median, t.median_first_response_seconds_prev)} /></div>
              )}
            </div>
            <div>
              <p className="text-[26px] font-black leading-none text-ink tabular-nums">
                {rate !== null ? `${rate}%` : "—"}
              </p>
              <p className="mt-1 text-[10.5px] font-semibold uppercase tracking-wide text-ink/40">
                conversations answered
              </p>
              {t.response_rate_prev !== null && rate !== null && (
                <div className="mt-1"><Delta value={Math.round(rate - t.response_rate_prev)} /></div>
              )}
            </div>
          </div>
          <p className={`mt-3 border-t border-deep-violet/[0.06] pt-2.5 text-[11px] font-medium ${meetsBoth ? "text-emerald" : "text-ink/50"}`}>
            {meetsBoth
              ? "Very responsive — Meta's 90% / 15-min bar cleared"
              : `Meta's very-responsive bar: ${GOAL_RATE}% answered within ${GOAL_MEDIAN_MIN} min`}
          </p>
        </div>

        {/* Scorecard — volume per channel, previous period beside it */}
        <div className={CARD}>
          <h3 className="text-[13px] font-bold text-ink">By channel</h3>
          <ul className="mt-3 divide-y divide-ink/[0.05]">
            {data.channels.map((c) => (
              <li key={c.channel_id} className="flex items-center gap-2.5 py-2">
                <PlatformMark platform={c.platform} size={14} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-semibold text-ink">
                    {platformLabel(c.platform)}
                  </p>
                  <p className="text-[10.5px] text-ink/45 tabular-nums">
                    {c.conversations} conversations
                    {c.response_rate !== null ? ` · ${c.response_rate}% answered` : ""}
                    {c.comments_in > 0 ? ` · ${c.comments_in} comments` : ""}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-[12px] font-bold text-ink tabular-nums">
                    {c.messages_in} <span className="text-[10px] font-medium text-ink/40">in</span>
                  </p>
                  <div className="mt-0.5 flex justify-end">
                    <Delta value={countDelta(c.messages_in, c.messages_in_prev)} />
                  </div>
                </div>
                {c.unanswered_now !== null && c.unanswered_now > 0 && (
                  <span className="shrink-0 rounded-full bg-coral/10 px-2 py-0.5 text-[10px] font-bold text-coral">
                    {c.unanswered_now} waiting
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Unanswered — the lost-sales card */}
        <div className={CARD}>
          <h3 className="text-[13px] font-bold text-ink">Waiting on a reply</h3>
          {t.unanswered_now === 0 ? (
            <div className="mt-6 mb-4 text-center">
              <p className="text-[24px] font-black leading-none text-emerald" aria-hidden>✓</p>
              <p className="mt-2 text-[12px] font-semibold text-emerald">All caught up</p>
              <p className="mt-0.5 text-[11px] text-ink/45">Every conversation has an answer.</p>
            </div>
          ) : (
            <div className="mt-6 mb-4 text-center">
              <p className="text-[30px] font-black leading-none text-ink tabular-nums">
                {t.unanswered_now ?? "—"}
              </p>
              <p className="mt-2 text-[12px] font-semibold text-ink/70">
                {t.unanswered_now === 1 ? "conversation" : "conversations"} with no reply yet
              </p>
              {t.oldest_unanswered_seconds !== null && (
                <p className="mt-0.5 text-[11px] text-ink/45">
                  oldest waiting {fmtDuration(t.oldest_unanswered_seconds)}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
