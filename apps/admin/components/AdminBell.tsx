"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  fetchAdminNotifications,
  markAdminNotificationRead,
  markAllAdminNotificationsRead,
  type AdminNotificationItem,
} from "@/lib/admin-api";

/* Admin bell: unread notifications for requests, errors, etc. Polls every
 * 30s; opens a dropdown; clicking an item marks it read and navigates. */

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

const SEVERITY_DOT: Record<string, string> = {
  crit: "bg-red-500",
  warn: "bg-amber-500",
  info: "bg-sky-500",
};

export default function AdminBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AdminNotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  const load = async () => {
    try {
      const data = await fetchAdminNotifications(false, 50);
      setItems(data.items);
      setUnread(data.unread_count);
    } catch {
      /* keep last state */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 30_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const openItem = async (item: AdminNotificationItem) => {
    if (!item.read) {
      void markAdminNotificationRead(item.id).then(() => {
        setUnread((u) => Math.max(0, u - 1));
        setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, read: true } : i)));
      });
    }
    setOpen(false);
    if (item.href) router.push(item.href);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => { setOpen((o) => !o); if (!open) void load(); }}
        aria-label={`Admin notifications (${unread} unread)`}
        aria-expanded={open}
        className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] text-ink/55 transition hover:border-[var(--ui-line-strong)] hover:text-ink ${FOCUS_RING}`}
      >
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className="h-4 w-4">
          <path d="M6.5 9.5a5.5 5.5 0 0 1 11 0v3.4l1.7 3.1H4.8l1.7-3.1V9.5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          <path d="M10 18.5a2.2 2.2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[9px] font-bold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-[340px] overflow-hidden rounded-[3px] border border-[var(--ui-line)] bg-[var(--ui-surface-solid)] shadow-lg">
          <div className="flex items-center justify-between border-b border-[var(--ui-line)] px-3.5 py-2.5">
            <p className="text-[12px] font-bold text-[var(--ui-ink)]">Notifications</p>
            {unread > 0 && (
              <button
                onClick={() => {
                  void markAllAdminNotificationsRead().then(() => {
                    setUnread(0);
                    setItems((prev) => prev.map((i) => ({ ...i, read: true })));
                  });
                }}
                className={`text-[10.5px] font-semibold text-deep-violet hover:underline ${FOCUS_RING}`}
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-[380px] overflow-y-auto">
            {loading ? (
              <p className="px-3.5 py-6 text-center text-[11px] text-ink/40">Loading…</p>
            ) : items.length === 0 ? (
              <p className="px-3.5 py-6 text-center text-[11px] text-ink/40">No notifications.</p>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => void openItem(item)}
                  className={`block w-full border-b border-[var(--ui-line)] px-3.5 py-3 text-left transition last:border-0 hover:bg-[var(--ui-sunken)] ${FOCUS_RING} ${item.read ? "opacity-60" : ""}`}
                >
                  <span className="flex items-center gap-2">
                    <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${SEVERITY_DOT[item.severity] ?? "bg-ink/30"}`} />
                    <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{item.title}</span>
                    <span className="shrink-0 text-[10px] text-ink/40">{timeAgo(item.created_at)}</span>
                  </span>
                  {item.body && (
                    <span className="mt-1 block text-[11px] leading-relaxed text-ink/55">{item.body}</span>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
