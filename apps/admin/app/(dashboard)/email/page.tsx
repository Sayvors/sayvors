"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchEmailStats, type EmailStats } from "@/lib/admin-api";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";
const DAY_OPTIONS = [1, 7, 30, 90] as const;
const OUTBOX_ORDER = ["queued", "sending", "sent", "failed", "dead", "suppressed"];
const EVENT_ORDER = [
  "queued",
  "sent",
  "delivered",
  "bounced",
  "complained",
  "opened",
  "clicked",
  "unsubscribed",
  "suppressed",
  "failed",
];

function count(map: Record<string, number> | undefined, key: string): number {
  return Number(map?.[key] ?? 0);
}

function fmt(value: number): string {
  return value.toLocaleString();
}

export default function EmailHealthPage() {
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState<EmailStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(
    async (background = false) => {
      if (!background) setRefreshing(true);
      try {
        const data = await fetchEmailStats(days);
        setStats(data);
        setError(null);
        setUpdatedAt(new Date());
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load email stats.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [days],
  );

  useEffect(() => {
    // Defer the first fetch so the effect body does not synchronously set
    // state; hidden tabs do not poll, and returning to the tab catches up.
    const first = window.setTimeout(() => void refresh(), 0);
    const tick = () => {
      if (!document.hidden) void refresh(true);
    };
    const onVisibility = () => {
      if (!document.hidden) void refresh(true);
    };
    timer.current = setInterval(tick, 30000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(first);
      document.removeEventListener("visibilitychange", onVisibility);
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  const outbox = stats?.outbox ?? {};
  const events = stats?.events ?? {};
  const queued = count(outbox, "queued");
  const sent = count(outbox, "sent");
  const failed = count(outbox, "failed");
  const dead = count(outbox, "dead");
  const suppressed = stats?.suppressed ?? 0;
  const total = OUTBOX_ORDER.reduce((sum, key) => sum + count(outbox, key), 0);

  const health =
    dead > 0 || failed > 0
      ? {
          tone: "danger",
          title: "Delivery failures need attention",
          body: "Dead letters are permanent provider rejections; failed rows include bounces and complaints. Check the worker log and the Resend dashboard.",
        }
      : queued > 50
        ? {
            tone: "warn",
            title: "Outbox is backing up",
            body: "More than 50 messages are waiting. Confirm the email-outbox worker loop is running.",
          }
        : {
            tone: "ok",
            title: "Outbox healthy",
            body: "No dead letters and no delivery failures in this window.",
          };

  const tone =
    health.tone === "danger"
      ? "border-red-200 bg-red-50 text-red-900"
      : health.tone === "warn"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : "border-emerald-200 bg-emerald-50 text-emerald-900";

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[18px] font-bold tracking-tight text-ink">Email health</h1>
          <p className="mt-0.5 text-[12px] text-ink/45">
            Durable outbox, provider events and suppression list. Counts cover the
            last {days} day{days === 1 ? "" : "s"}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-9 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] font-semibold text-ink"
            aria-label="Time window"
          >
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                Last {d} day{d === 1 ? "" : "s"}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            className={`h-9 rounded-[2px] bg-deep-violet px-3 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
          <Link
            href="/email/campaigns"
            className={`inline-flex h-9 items-center rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 text-[12px] font-semibold text-ink ${FOCUS}`}
          >
            Campaigns
          </Link>
          <a
            href="https://resend.com/emails"
            target="_blank"
            rel="noreferrer"
            className={`inline-flex h-9 items-center rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 text-[12px] font-semibold text-ink ${FOCUS}`}
          >
            Resend
          </a>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-[2px] border border-red-200 bg-red-50 p-3 text-[12px] text-red-800">
          {error}{" "}
          <button onClick={() => void refresh()} className="font-bold underline">
            Retry
          </button>
        </div>
      )}

      <div className={`rounded-[2px] border p-4 ${tone}`}>
        <p className="text-[13px] font-bold">{health.title}</p>
        <p className="mt-0.5 text-[12px] leading-relaxed opacity-80">{health.body}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          { label: "Queued", value: queued, hint: "waiting for worker" },
          { label: "Sent", value: sent, hint: "provider accepted" },
          { label: "Failed", value: failed, hint: "bounce / complaint" },
          { label: "Dead", value: dead, hint: "permanent rejection" },
          { label: "Suppressed", value: suppressed, hint: "all time" },
        ].map((card) => (
          <div key={card.label} className="panel p-3.5">
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
              {card.label}
            </p>
            <p className="mt-1 text-[24px] font-bold leading-none text-ink">
              {loading ? "—" : fmt(card.value)}
            </p>
            <p className="mt-1 text-[10.5px] text-ink/40">{card.hint}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[14px] font-bold text-ink">Outbox status</h2>
            <span className="text-[10.5px] text-ink/40">{fmt(total)} total</span>
          </div>
          <div className="mt-3 space-y-2">
            {OUTBOX_ORDER.map((key) => {
              const n = count(outbox, key);
              const width = total && n > 0 ? Math.max(2, Math.round((n / total) * 100)) : 0;
              return (
                <div key={key} className="flex items-center justify-between gap-3">
                  <span className="text-[12px] capitalize text-ink/65">{key}</span>
                  <div className="flex flex-1 items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                      <div
                        className={`h-full rounded-full ${
                          key === "dead" || key === "failed"
                            ? "bg-red-500"
                            : key === "queued"
                              ? "bg-amber-400"
                              : key === "sent"
                                ? "bg-emerald-500"
                                : "bg-ink/30"
                        }`}
                        style={{ width: `${width}%` }}
                      />
                    </div>
                    <span className="w-12 text-right text-[12px] font-semibold text-ink">
                      {fmt(n)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel p-4">
          <h2 className="text-[14px] font-bold text-ink">Provider events</h2>
          <p className="mt-0.5 text-[10.5px] text-ink/40">
            Delivery lifecycle received from the Resend webhook.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {EVENT_ORDER.map((key) => (
              <div
                key={key}
                className="flex items-center justify-between rounded-[2px] bg-[var(--ui-sunken)] px-2.5 py-1.5"
              >
                <span className="text-[11.5px] capitalize text-ink/60">{key}</span>
                <span className="text-[12px] font-bold text-ink">{fmt(count(events, key))}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="panel p-4 text-[11.5px] leading-relaxed text-ink/50">
        <p className="font-bold text-ink/70">What to check</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          <li>
            <strong className="text-ink/70">Queued</strong> rising: the email-outbox worker
            loop is not running or is behind.
          </li>
          <li>
            <strong className="text-ink/70">Dead</strong>: permanent provider rejection
            (invalid recipient, bad payload). Fix the cause, then retry the row.
          </li>
          <li>
            <strong className="text-ink/70">Suppressed</strong>: bounces, complaints and
            one-click unsubscribes. These addresses are never sent again.
          </li>
          <li>
            <strong className="text-ink/70">Events empty</strong> while mail is sent:{" "}
            <code>RESEND_WEBHOOK_SECRET</code> is missing, or the Resend webhook URL/events
            are wrong.
          </li>
        </ul>
        {updatedAt && (
          <p className="mt-2 text-[10.5px] text-ink/35">
            Updated {updatedAt.toLocaleTimeString()} · auto-refreshes every 30s
          </p>
        )}
      </div>
    </div>
  );
}
