"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

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

  const refreshCount = useCallback(async () => {
    try {
      const r = await apiFetch("/api/v1/notifications/unread-count");
      if (typeof r?.unread === "number") setUnread(r.unread);
    } catch {
      /* backend down — badge stays */
    }
  }, []);

  const openDropdown = useCallback(async () => {
    setOpen(true);
    setLoading(true);
    try {
      const r = await apiFetch("/api/v1/notifications?limit=8");
      setItems((r.items ?? []) as BellNotification[]);
      if (typeof r?.unread === "number") setUnread(r.unread);
    } catch {
      /* list stays empty */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshCount();
    const id = window.setInterval(refreshCount, POLL_MS);
    const onFocus = () => void refreshCount();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshCount]);

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
    router.push("/dashboard/notifications");
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => (open ? setOpen(false) : void openDropdown())}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        title="Notifications"
        className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-deep-violet/[0.08] text-ink/50 outline-none transition hover:border-deep-violet/25 hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:border-fog/[0.1] dark:text-fog/50 dark:hover:text-deep-violet"
      >
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4" aria-hidden>
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
        <div className="absolute right-0 top-full z-50 mt-1 max-h-[70vh] w-80 overflow-hidden rounded-xl border border-deep-violet/[0.08] bg-white shadow-xl dark:border-deep-violet/[0.12] dark:bg-ink">
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
                Nothing yet — new reviews, syncs and replies will show up here.
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
