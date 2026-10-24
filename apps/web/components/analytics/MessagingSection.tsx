"use client";

import Link from "next/link";
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
 *
 * Theme: the Team page's flat system, which needs its `.team-ui` ancestor —
 * that class DEFINES the --ui-* variables (and the #F5F5F5 page); without it
 * every var() below silently resolves to nothing. Three colours only: ink,
 * surface, sunken — direction/status is carried by weight and inversion,
 * never by hue (the StatusBadge rule from the team page).
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
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
  const down = value < 0;
  // No hue: "worse" inverts to ink, "better" sits on sunken, "flat" dims.
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-[2px] px-2 py-0.5 text-[11px] font-bold tabular-nums ${
        down
          ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
          : up
            ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
            : "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]"
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
    /* .team-ui scopes the --ui-* variables and paints the #F5F5F5 page, so
       this reads as the Team page's world embedded in the Overview tab. */
    <section aria-label="Messages and response speed" className="team-ui rounded-[2px] p-4 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className={`text-[15px] font-bold ${INK}`}>Messages &amp; response speed</h2>
        {t.as_of && (
          <p className={`text-[11.5px] ${INK2}`}>
            updated {new Date(t.as_of).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} · last {days}d
          </p>
        )}
      </div>

      <div className="mt-5 grid gap-5 sm:gap-6 lg:grid-cols-3">
        {/* Response health — the two numbers Meta's badge is made of */}
        <div className="ui-card p-5">
          <h3 className={`text-[13px] font-bold ${INK}`}>Response health</h3>
          <div className="mt-5 flex items-end gap-10">
            <div>
              <p className={`text-[28px] font-black leading-none tabular-nums ${INK}`}>
                {median !== null ? fmtDuration(median) : "—"}
              </p>
              <p className={`mt-2 text-[11px] font-semibold uppercase tracking-wide ${INK2}`}>
                median first reply
              </p>
              {t.median_first_response_seconds_prev !== null && median !== null && (
                <div className="mt-2"><Delta value={countDelta(median, t.median_first_response_seconds_prev)} /></div>
              )}
            </div>
            <div>
              <p className={`text-[28px] font-black leading-none tabular-nums ${INK}`}>
                {rate !== null ? `${rate}%` : "—"}
              </p>
              <p className={`mt-2 text-[11px] font-semibold uppercase tracking-wide ${INK2}`}>
                conversations answered
              </p>
              {t.response_rate_prev !== null && rate !== null && (
                <div className="mt-2"><Delta value={Math.round(rate - t.response_rate_prev)} /></div>
              )}
            </div>
          </div>
          <p className={`mt-5 border-t border-[var(--ui-line)] pt-3 text-[11.5px] font-medium leading-relaxed ${meetsBoth ? INK : INK2}`}>
            {meetsBoth
              ? "✓ Very responsive — Meta's 90% / 15-min bar cleared"
              : `Meta's very-responsive bar: ${GOAL_RATE}% answered within ${GOAL_MEDIAN_MIN} min`}
          </p>
        </div>

        {/* Scorecard — volume per channel, previous period beside it */}
        <div className="ui-card p-5">
          <h3 className={`text-[13px] font-bold ${INK}`}>By channel</h3>
          <ul className="mt-4 divide-y divide-[var(--ui-line)]">
            {data.channels.map((c) => {
              const slug = c.platform === "google_reviews" ? "google-business" : c.platform;
              return (
                <li key={c.channel_id} className="flex items-center gap-3 py-3 first:pt-1 last:pb-1">
                  {/* The link IS the left slot, so the row keeps its shape */}
                  <Link
                    href={`/dashboard/channels/${slug}`}
                    className="group flex min-w-0 flex-1 items-center gap-3 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                  >
                    <PlatformMark platform={c.platform} size={16} />
                    <div className="min-w-0">
                      <p className={`truncate text-[12.5px] font-semibold group-hover:underline group-hover:underline-offset-2 ${INK}`}>
                        {platformLabel(c.platform)}
                      </p>
                      <p className={`mt-0.5 text-[11px] tabular-nums ${INK2}`}>
                        {c.conversations} conversations
                        {c.response_rate !== null ? ` · ${c.response_rate}% answered` : ""}
                        {c.comments_in > 0 ? ` · ${c.comments_in} comments` : ""}
                      </p>
                    </div>
                  </Link>
                  <div className="shrink-0 text-right">
                    <p className={`text-[13px] font-bold tabular-nums ${INK}`}>
                      {c.messages_in} <span className={`text-[10.5px] font-medium ${INK2}`}>in</span>
                    </p>
                    <div className="mt-1 flex justify-end">
                      <Delta value={countDelta(c.messages_in, c.messages_in_prev)} />
                    </div>
                  </div>
                  {c.unanswered_now !== null && c.unanswered_now > 0 && (
                    <span className="shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1 text-[11px] font-bold text-[var(--ui-on-ink)]">
                      {c.unanswered_now} waiting
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {/* Unanswered — the lost-sales card */}
        <div className="ui-card p-5">
          <h3 className={`text-[13px] font-bold ${INK}`}>Waiting on a reply</h3>
          {t.unanswered_now === 0 ? (
            <div className="my-8 text-center">
              <p className={`text-[26px] font-black leading-none ${INK}`} aria-hidden>✓</p>
              <p className={`mt-3 text-[13px] font-bold ${INK}`}>All caught up</p>
              <p className={`mt-1 text-[11.5px] ${INK2}`}>Every conversation has an answer.</p>
            </div>
          ) : (
            <div className="my-8 text-center">
              <p className={`text-[34px] font-black leading-none tabular-nums ${INK}`}>
                {t.unanswered_now ?? "—"}
              </p>
              <p className={`mt-3 text-[13px] font-semibold ${INK}`}>
                {t.unanswered_now === 1 ? "conversation" : "conversations"} with no reply yet
              </p>
              {t.oldest_unanswered_seconds !== null && (
                <p className={`mt-1 text-[11.5px] ${INK2}`}>
                  oldest waiting {fmtDuration(t.oldest_unanswered_seconds)}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Best-time heatmap — inbound volume by hour of day */}
        {data.by_hour_in && data.by_hour_in.some((v) => v > 0) && (
          <div className="ui-card p-5">
            <h3 className={`text-[13px] font-bold ${INK}`}>Best time to reply</h3>
            <p className={`mt-1 text-[11.5px] ${INK2}`}>
              When customers message you (last {days}d, UTC). Reply fastest in these hours.
            </p>
            <div className="mt-4 flex items-end gap-1" style={{ height: 64 }}>
              {data.by_hour_in.map((count, hour) => {
                const max = Math.max(...data.by_hour_in, 1);
                const pct = (count / max) * 100;
                return (
                  <div
                    key={hour}
                    className="flex flex-1 flex-col items-center justify-end"
                    title={`${hour}:00 — ${count} messages`}
                  >
                    <div
                      className="w-full rounded-t-[2px] bg-[var(--ui-ink)] transition-all"
                      style={{ height: `${Math.max(2, pct)}%`, opacity: count > 0 ? 1 : 0.15 }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="mt-1 flex justify-between text-[9px] tabular-nums text-[var(--ui-ink-2)]">
              <span>0h</span>
              <span>6h</span>
              <span>12h</span>
              <span>18h</span>
              <span>23h</span>
            </div>
          </div>
        )}
      </div>

      {/* Best-time heatmap — inbound volume by hour of day */}
      {data.by_hour_in && data.by_hour_in.some((v) => v > 0) && (
        <div className="ui-card p-5">
          <h3 className={`text-[13px] font-bold ${INK}`}>Best time to reply</h3>
          <p className={`mt-1 text-[11.5px] ${INK2}`}>
            When customers message you (last {days}d, UTC). Reply fastest in these hours.
          </p>
          <div className="mt-4 flex items-end gap-1" style={{ height: 64 }}>
            {data.by_hour_in.map((count, hour) => {
              const max = Math.max(...data.by_hour_in, 1);
              const pct = (count / max) * 100;
              return (
                <div
                  key={hour}
                  className="flex flex-1 flex-col items-center justify-end"
                  title={`${hour}:00 — ${count} messages`}
                >
                  <div
                    className="w-full rounded-t-[2px] bg-[var(--ui-ink)] transition-all"
                    style={{ height: `${Math.max(2, pct)}%`, opacity: count > 0 ? 1 : 0.15 }}
                  />
                </div>
              );
            })}
          </div>
          <div className="mt-1 flex justify-between text-[9px] tabular-nums text-[var(--ui-ink-2)]">
            <span>0h</span>
            <span>6h</span>
            <span>12h</span>
            <span>18h</span>
            <span>23h</span>
          </div>
        </div>
      )}

      {/* AI vs human — deflection framing. Reads stored ai_handled_out
          from the daily rollup; no request-time computation. */}
      <div className="ui-card p-5">
        <h3 className={`text-[13px] font-bold ${INK}`}>AI vs human</h3>
        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <p className={`text-[28px] font-black leading-none tabular-nums ${INK}`}>
              {t.ai_handled_out ?? 0}
            </p>
            <p className={`mt-2 text-[11px] font-semibold uppercase tracking-wide ${INK2}`}>
              AI-handled
            </p>
          </div>
          <div>
            <p className={`text-[28px] font-black leading-none tabular-nums ${INK}`}>
              {Math.max(0, (t.messages_out ?? 0) - (t.ai_handled_out ?? 0))}
            </p>
            <p className={`mt-2 text-[11px] font-semibold uppercase tracking-wide ${INK2}`}>
              human-handled
            </p>
          </div>
        </div>
        {(t.messages_out ?? 0) > 0 && (
          <p className={`mt-4 border-t border-[var(--ui-line)] pt-3 text-[11.5px] font-medium leading-relaxed ${INK2}`}>
            AI handled {Math.round(((t.ai_handled_out ?? 0) / t.messages_out) * 100)}% of outbound replies
            {t.ai_handled_out_prev !== null && (t.ai_handled_out_prev ?? 0) > 0
              ? ` (was ${Math.round(((t.ai_handled_out_prev ?? 0) / Math.max(1, t.messages_out_prev)) * 100)}% last period)`
              : ""}
          </p>
        )}
      </div>
    </section>
  );
}
