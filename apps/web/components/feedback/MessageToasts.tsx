"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import { isActiveThread } from "@/lib/active-thread";
import {
  useInboxRealtime,
  type InboxRealtimeEvent,
  type NotificationPayload,
} from "@/lib/use-inbox-realtime";

/*
 * Live message toasts: a customer speaks on any channel, the dashboard
 * pops a card bottom-right — who, what, and one tap into the thread.
 *
 * Rides the same inbox WebSocket (the "notification" event arrives on
 * the pipe the backend already forwards verbatim), so there is no second
 * endpoint and no polling. Tenant settings gate it server-side.
 *
 * Near-zero re-render budget: one subscription, one state array, and the
 * per-toast timers are driven by the exit-bar CSS animation ending — no
 * ticking interval, no context, no store. Hovering a card pauses its
 * countdown (animation-play-state), so reading a preview never loses it.
 * The thread currently open in the inbox never pops (active-thread.ts).
 */

const TTL_MS = 6000;
const EXIT_MS = 240;
const MAX_TOASTS = 3;

interface ToastItem {
  id: string;
  notification: NotificationPayload;
  seenAt: string;
}

function MessageToast({
  item,
  onClose,
}: {
  item: ToastItem;
  onClose: (id: string) => void;
}) {
  const [leaving, setLeaving] = useState(false);
  const [paused, setPaused] = useState(false);

  const beginExit = useCallback(() => setLeaving(true), []);

  useEffect(() => {
    if (!leaving) return;
    const t = window.setTimeout(() => onClose(item.id), EXIT_MS);
    return () => window.clearTimeout(t);
  }, [leaving, item.id, onClose]);

  const n = item.notification;
  const channelLabel = n.platform ? platformLabel(n.platform) : "";
  const name =
    n.contact_name || (channelLabel ? `${channelLabel} user` : "New message");
  const href =
    n.channel_id && n.contact_id
      ? `/dashboard/channels/inbox?channel=${encodeURIComponent(n.channel_id)}&key=${encodeURIComponent(n.contact_id)}`
      : "/dashboard/channels/inbox";

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className={`pointer-events-auto relative overflow-hidden rounded-[14px] border border-[var(--ui-line)] bg-[var(--ui-surface)] shadow-[0_12px_28px_rgba(20,16,31,0.16),0_3px_8px_rgba(20,16,31,0.10)] ${
        leaving ? "sayvors-toast-exit" : "sayvors-toast-enter"
      }`}
    >
      <button
        type="button"
        onClick={beginExit}
        aria-label="Dismiss notification"
        className="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-full text-[var(--ui-ink-2)] outline-none hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
      >
        <svg viewBox="0 0 14 14" className="h-3 w-3" aria-hidden>
          <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </button>

      <div className="flex items-start gap-3 p-3.5 pr-9">
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
        >
          <PlatformMark platform={n.platform || ""} size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <p className="truncate text-[13px] font-bold text-[var(--ui-ink)]">{name}</p>
            <time
              dateTime={item.seenAt}
              title={item.seenAt}
              className="shrink-0 text-[10.5px] tabular-nums text-[var(--ui-ink-2)]"
            >
              {item.seenAt}
            </time>
          </div>
          {channelLabel && (
            <p className="mt-0.5 flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
              <PlatformMark platform={n.platform || ""} size={10} />
              {channelLabel}
            </p>
          )}
          <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-snug text-[var(--ui-ink-2)]">
            {n.preview || "Sent you a message."}
          </p>
          <Link
            href={href}
            onClick={beginExit}
            className="mt-2.5 inline-block rounded-lg bg-[var(--ui-ink)] px-3 py-1.5 text-[11.5px] font-semibold text-[var(--ui-on-ink)] outline-none hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Open chat
          </Link>
        </div>
      </div>

      {/* The countdown IS the exit condition: when this bar finishes
          shrinking the card leaves. Paused on hover, so it never lies. */}
      <span
        aria-hidden
        className="sayvors-toast-bar absolute inset-x-0 bottom-0 h-[3px] bg-deep-violet/40"
        style={{ animationDuration: `${TTL_MS}ms` }}
        data-paused={paused || leaving ? "true" : "false"}
        onAnimationEnd={beginExit}
      />
    </div>
  );
}

export default function MessageToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const seen = useRef<Set<string>>(new Set());

  const onClose = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const onEvent = useCallback((e: InboxRealtimeEvent) => {
    if (e.type !== "notification" || e.notification?.kind !== "message") return;
    const n = e.notification;
    const id =
      n.message_id ||
      `${n.channel_id ?? ""}:${n.contact_id ?? ""}:${n.preview ?? ""}`;
    if (seen.current.has(id)) return;
    seen.current.add(id);
    if (seen.current.size > 300) seen.current = new Set([id]);
    // The agent is already reading this thread — a pop would be noise.
    if (isActiveThread(n.channel_id, n.contact_id)) return;
    const seenAt = new Date().toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
    setToasts((prev) =>
      [...prev, { id, notification: n, seenAt }].slice(-MAX_TOASTS),
    );
  }, []);

  useInboxRealtime(onEvent);

  return (
    <div
      aria-live="polite"
      className="team-ui pointer-events-none fixed bottom-4 left-4 right-4 z-[90] flex flex-col gap-2 sm:left-auto sm:w-[368px]"
    >
      <style>{`
        @keyframes sayvors-toast-in {
          0% { transform: translateY(12px) scale(0.96); opacity: 0; }
          100% { transform: translateY(0) scale(1); opacity: 1; }
        }
        @keyframes sayvors-toast-out {
          0% { transform: translateX(0) scale(1); opacity: 1; }
          100% { transform: translateX(28px) scale(0.97); opacity: 0; }
        }
        @keyframes sayvors-toast-progress {
          0% { transform: scaleX(1); }
          100% { transform: scaleX(0); }
        }
        .sayvors-toast-enter { animation: sayvors-toast-in 0.32s cubic-bezier(0.22, 1.2, 0.36, 1) both; }
        .sayvors-toast-exit { animation: sayvors-toast-out 0.24s cubic-bezier(0.4, 0, 1, 1) both; }
        .sayvors-toast-bar { transform-origin: left; animation-name: sayvors-toast-progress; animation-timing-function: linear; animation-fill-mode: both; }
        .sayvors-toast-bar[data-paused="true"] { animation-play-state: paused; }
        @media (prefers-reduced-motion: reduce) {
          .sayvors-toast-enter, .sayvors-toast-exit { animation-duration: 0.01s; }
        }
      `}</style>
      {toasts.map((t) => (
        <MessageToast key={t.id} item={t} onClose={onClose} />
      ))}
    </div>
  );
}
