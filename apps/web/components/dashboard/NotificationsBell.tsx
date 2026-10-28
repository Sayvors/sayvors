"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import {
  loadSeenIds,
  notifyPill,
  pillKindFor,
  rememberSeenIds,
} from "@/lib/notifications";
import { useInboxRealtime, type InboxRealtimeEvent } from "@/lib/use-inbox-realtime";

export interface BellNotification {
  id: string;
  type: string;
  title: string;
  body: string | null;
  data: Record<string, unknown>;
  href: string | null;
  read_at: string | null;
  created_at: string;
}

const POLL_MS = 45000;

const TYPE_META: Record<string, { icon: string; tint: string }> = {
  sync_completed: { icon: "⟳", tint: "bg-sky-500/10 text-sky-600 dark:text-sky-300" },
  sync_failed: { icon: "⚠", tint: "bg-red-500/10 text-red-600 dark:text-red-400" },
  review_pulled: { icon: "★", tint: "bg-amber-500/10 text-amber-600 dark:text-amber-300" },
  reply_posted: { icon: "✓", tint: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300" },
  reply_failed: { icon: "!", tint: "bg-red-500/10 text-red-600 dark:text-red-400" },
  review_edited: { icon: "✎", tint: "bg-violet-500/10 text-deep-violet dark:text-violet-300" },
  review_ticket_created: { icon: "!", tint: "bg-coral/10 text-coral dark:text-coral" },
  review_ticket_updated: { icon: "✎", tint: "bg-violet-500/10 text-deep-violet dark:text-violet-300" },
  review_ticket_customer: { icon: "↩", tint: "bg-amber-500/10 text-amber-600 dark:text-amber-300" },
  post_scheduled: { icon: "🕑", tint: "bg-sky-500/10 text-sky-600 dark:text-sky-300" },
  post_published: { icon: "📝", tint: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300" },
  post_failed: { icon: "!", tint: "bg-red-500/10 text-red-600 dark:text-red-400" },
  media_scheduled: { icon: "🕑", tint: "bg-sky-500/10 text-sky-600 dark:text-sky-300" },
  media_published: { icon: "📸", tint: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300" },
  media_failed: { icon: "!", tint: "bg-red-500/10 text-red-600 dark:text-red-400" },
};

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  const m = Math.floor(ms / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export default function NotificationsBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<BellNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const seenRef = useRef<Set<string> | null>(null);
  const prevUnreadRef = useRef(0);

  const seenIds = () => {
    if (!seenRef.current) seenRef.current = loadSeenIds();
    return seenRef.current;
  };

  const remember = useCallback((ids: string[]) => {
    const seen = seenIds();
    let changed = false;
    for (const id of ids) {
      if (!seen.has(id)) {
        seen.add(id);
        changed = true;
      }
    }
    if (changed) rememberSeenIds(seen);
  }, []);

  const maybeFirePills = useCallback(
    (list: BellNotification[]) => {
      // Reminder pills surface ONLY failures and fresh arrivals needing
      // action — everything else lives quietly in this dropdown.
      const fresh = list
        .filter((n) => !n.read_at && !seenIds().has(n.id) && pillKindFor(n.type) !== null)
        .slice(-3);
      for (const n of fresh) {
        const kind = pillKindFor(n.type);
        if (kind) notifyPill(n.title, kind);
      }
      remember(list.map((n) => n.id));
    },
    [remember]
  );

  const refreshCount = useCallback(async () => {
    try {
      const r = await apiFetch("/api/v1/notifications/unread-count");
      if (typeof r?.unread !== "number") return;
      const before = prevUnreadRef.current;
      prevUnreadRef.current = r.unread;
      setUnread(r.unread);
      // Count rose → fetch the newcomers; pills fire for failures only.
      if (r.unread > before) {
        try {
          const list = await apiFetch("/api/v1/notifications?limit=10");
          maybeFirePills((list.items ?? []) as BellNotification[]);
        } catch {
          /* next poll retries */
        }
      }
    } catch {
      /* backend down — badge stays */
    }
  }, [maybeFirePills]);

  const openDropdown = useCallback(async () => {
    setOpen(true);
    setLoading(true);
    try {
      const r = await apiFetch("/api/v1/notifications?limit=8");
      const list = (r.items ?? []) as BellNotification[];
      setItems(list);
      // Seen in the dropdown = no pill later for these.
      remember(list.map((n) => n.id));
      if (typeof r?.unread === "number") {
        prevUnreadRef.current = r.unread;
        setUnread(r.unread);
      }
    } catch {
      /* list stays empty */
    } finally {
      setLoading(false);
    }
  }, [remember]);

  useEffect(() => {
    let id: number | null = null;

    const startPolling = () => {
      if (id !== null) return;
      if (document.hidden) return;
      id = window.setInterval(refreshCount, POLL_MS);
    };
    const stopPolling = () => {
      if (id !== null) {
        window.clearInterval(id);
        id = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        stopPolling();
      } else {
        // Catch up immediately on return, then resume the cadence.
        void refreshCount();
        startPolling();
      }
    };

    // Initial fetch + cadence only while the tab is visible.
    if (!document.hidden) {
      void refreshCount();
      startPolling();
    }
    document.addEventListener("visibilitychange", onVisibility);
    const onFocus = () => {
      if (!document.hidden) void refreshCount();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshCount]);

  /* The interval is the safety net, not the delivery mechanism: up to 45s
     between a review ticket appearing and the badge admitting it is a long
     time when a customer is waiting. Every notification publish (messages,
     lead escalations, tickets) rides the same socket the inbox already uses,
     so the badge is correct immediately and the poll only covers a dropped
     socket. The dropdown, if open, is refetched too so the new row is
     visible without a click. */
  const onRealtime = useCallback(
    (e: InboxRealtimeEvent) => {
      if (e.type !== "notification") return;
      void refreshCount();
      if (open) void openDropdown();
    },
    [refreshCount, open, openDropdown]
  );
  useInboxRealtime(onRealtime);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, []);

  async function markAllRead() {
    try {
      await apiFetch("/api/v1/notifications/read-all", { method: "POST" });
      setUnread(0);
      setItems((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })));
    } catch {
      /* ignore */
    }
  }

  async function openItem(n: BellNotification) {
    setOpen(false);
    if (!n.read_at) {
      setUnread((u) => Math.max(0, u - 1));
      try {
        await apiFetch(`/api/v1/notifications/${n.id}/read`, { method: "POST" });
      } catch {
        /* badge corrected on next poll */
      }
    }
    router.push(n.href ?? "/dashboard/notifications");
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => (open ? setOpen(false) : void openDropdown())}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        title="Notifications"
        className="relative flex h-10 w-10 items-center justify-center rounded-[2px] text-ink/55 outline-none transition hover:bg-deep-violet/[0.05] hover:text-ink focus-visible:ring-2 focus-visible:ring-deep-violet/40 md:h-9 md:w-9 dark:text-fog/55 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
      >
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-[18px] w-[18px]" aria-hidden>
          <path d="M10 2.5a5 5 0 00-5 5v2.6L3.6 12a.6.6 0 00.5.9h11.8a.6.6 0 00.5-.9L15 10.1V7.5a5 5 0 00-5-5Z" strokeLinejoin="round" />
          <path d="M8.3 15.5a1.8 1.8 0 003.4 0" strokeLinecap="round" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-coral px-1 text-[9px] font-bold tabular-nums text-white ring-2 ring-white dark:ring-ink">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        /* On a phone this is a viewport-anchored sheet, not a dropdown.
           Anchored to the bell it ran off-screen: the bell sits left of
           centre once the nav collapses, so `right-0` on a 320px panel put
           225px of it outside a 390px screen — a third of the panel visible.
           `inset-x-3` cannot overflow whatever the bell is doing, and
           `sm:` restores the original dropdown untouched. */
        <div
          role="dialog"
          aria-label="Notifications"
          className="fixed inset-x-3 top-14 z-50 max-h-[70vh] overflow-hidden rounded-xl border border-deep-violet/[0.08] bg-white shadow-xl dark:border-fog/[0.08] dark:bg-[#1d1636] sm:absolute sm:inset-x-auto sm:end-0 sm:top-full sm:mt-1 sm:w-80"
        >
          <div className="flex items-center justify-between border-b border-ink/[0.06] px-3.5 py-2.5 dark:border-fog/[0.06]">
            <p className="text-[13px] font-bold text-ink dark:text-fog">Notifications</p>
            <div className="flex items-center gap-2">
              {unread > 0 && (
                <button
                  onClick={() => void markAllRead()}
                  className="text-[11px] font-semibold text-deep-violet outline-none hover:underline focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                >
                  Mark all read
                </button>
              )}
              <Link
                href="/dashboard/notifications"
                onClick={() => setOpen(false)}
                className="text-[11px] font-semibold text-ink/50 outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-fog/50 dark:hover:text-fog"
              >
                View all
              </Link>
            </div>
          </div>
          <div className="max-h-[52vh] overflow-y-auto">
            {loading ? (
              <p className="px-3.5 py-6 text-center text-[12px] text-ink/40 dark:text-fog/40">Loading…</p>
            ) : items.length === 0 ? (
              <p className="px-3.5 py-6 text-center text-[12px] text-ink/40 dark:text-fog/40">
                Nothing yet — new reviews, syncs, replies, posts and photos will show up here.
              </p>
            ) : (
              items.map((n) => {
                const meta = TYPE_META[n.type] ?? { icon: "•", tint: "bg-ink/[0.05] text-ink/50" };
                return (
                  <button
                    key={n.id}
                    onClick={() => void openItem(n)}
                    className={`flex w-full items-start gap-2.5 border-b border-ink/[0.05] px-3.5 py-2.5 text-left outline-none transition last:border-0 hover:bg-deep-violet/[0.04] focus-visible:bg-deep-violet/[0.04] dark:border-fog/[0.05] ${n.read_at ? "" : "bg-deep-violet/[0.03]"}`}
                  >
                    <span aria-hidden className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${meta.tint}`}>
                      {meta.icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-semibold text-ink dark:text-fog">
                        {n.title}
                      </span>
                      {n.body && (
                        <span className="mt-0.5 line-clamp-2 block text-[11.5px] leading-snug text-ink/55 dark:text-fog/55">
                          {n.body}
                        </span>
                      )}
                      <span className="mt-0.5 block text-[10px] text-ink/35 dark:text-fog/35">
                        {timeAgo(n.created_at)} ago
                      </span>
                    </span>
                    {!n.read_at && <span aria-label="Unread" className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-deep-violet" />}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
