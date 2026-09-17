"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import LogoLoader from "@/components/LogoLoader";
import type { BellNotification } from "@/components/dashboard/NotificationsBell";
import { apiFetch } from "@/lib/api-rag";

const TYPE_META: Record<string, { icon: string; tint: string; label: string }> = {
  sync_completed: { icon: "⟳", tint: "bg-sky-500/10 text-sky-600 dark:text-sky-300", label: "Sync" },
  review_pulled: { icon: "★", tint: "bg-amber-500/10 text-amber-600 dark:text-amber-300", label: "New review" },
  reply_posted: { icon: "✓", tint: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300", label: "Reply posted" },
  reply_failed: { icon: "!", tint: "bg-red-500/10 text-red-600 dark:text-red-400", label: "Reply failed" },
  review_edited: { icon: "✎", tint: "bg-violet-500/10 text-deep-violet dark:text-violet-300", label: "Review edited" },
};

function fullTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function DetailRows({ n }: { n: BellNotification }) {
  const data = n.data ?? {};
  const rows: [string, string][] = [];
  if (typeof data.listing === "string") rows.push(["Branch", data.listing]);
  if (typeof data.rating === "number") rows.push(["Rating", `${data.rating} / 5`]);
  if (typeof data.new_reviews === "number") rows.push(["New reviews", String(data.new_reviews)]);
  if (typeof data.review_id === "string") rows.push(["Review", data.review_id.replace(/^localith:/, "").slice(0, 24)]);
  return rows.length === 0 ? null : (
    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-ink/[0.03] p-2.5 text-[11.5px] dark:bg-fog/[0.04]">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-1.5">
          <dt className="shrink-0 font-semibold text-ink/45 dark:text-fog/45">{k}:</dt>
          <dd className="truncate text-ink/80 dark:text-fog/80">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function NotificationsPage() {
  const router = useRouter();
  const [items, setItems] = useState<BellNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const loadingRef = useRef(false);

  const load = useCallback(async (offset: number, append: boolean) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    if (append) setLoadingMore(true);
    else setLoading(true);
    try {
      const r = await apiFetch(
        `/api/v1/notifications?limit=30&offset=${offset}${filter === "unread" ? "&unread_only=true" : ""}`
      );
      const fresh = (r.items ?? []) as BellNotification[];
      setItems((prev) => (append ? [...prev, ...fresh] : fresh));
      setTotal(r.total ?? 0);
      if (typeof r?.unread === "number") setUnread(r.unread);
    } catch {
      /* error state renders below */
    } finally {
      setLoading(false);
      setLoadingMore(false);
      loadingRef.current = false;
    }
  }, [filter]);

  useEffect(() => {
    setItems([]);
    void load(0, false);
  }, [load]);

  async function openItem(n: BellNotification) {
    if (!n.read_at) {
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)));
      setUnread((u) => Math.max(0, u - 1));
      try {
        await apiFetch(`/api/v1/notifications/${n.id}/read`, { method: "POST" });
      } catch {
        /* corrected on next load */
      }
    }
    if (n.href) router.push(n.href);
  }

  async function markAllRead() {
    try {
      await apiFetch("/api/v1/notifications/read-all", { method: "POST" });
      setUnread(0);
      setItems((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })));
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-4">
        <div>
          <Breadcrumbs items={[{ label: "Notifications" }]} />
          <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-[20px] font-bold text-ink dark:text-fog">Notifications</h1>
              <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
                {total === 0
                  ? "Syncs, new reviews and reply outcomes land here."
                  : `${total} total${unread > 0 ? ` · ${unread} unread` : ""}`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex rounded-lg bg-ink/[0.04] p-0.5 dark:bg-fog/[0.06]">
                {(["all", "unread"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`rounded-md px-3 py-1.5 text-[12px] font-semibold capitalize outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                      filter === f ? "bg-white text-ink shadow-sm dark:bg-ink dark:text-fog" : "text-ink/45 dark:text-fog/45"
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
              {unread > 0 && (
                <button
                  onClick={() => void markAllRead()}
                  className="rounded-lg px-2.5 py-1.5 text-[12px] font-semibold text-deep-violet outline-none transition hover:bg-deep-violet/[0.06] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                >
                  Mark all read
                </button>
              )}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <LogoLoader size={28} />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center backdrop-blur-sm">
            <p className="text-[14px] font-semibold text-ink/70 dark:text-fog/70">
              {filter === "unread" ? "All caught up" : "No notifications yet"}
            </p>
            <p className="mt-1 text-[12px] text-ink/45 dark:text-fog/45">
              {filter === "unread"
                ? "Everything here has been read."
                : "New reviews, syncs and replies will show up here."}
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border-2 border-white bg-white/80 backdrop-blur-sm">
            {items.map((n) => {
              const meta = TYPE_META[n.type] ?? { icon: "•", tint: "bg-ink/[0.05] text-ink/50", label: n.type };
              return (
                <div key={n.id}>
                  <button
                    onClick={() => void openItem(n)}
                    className={`flex w-full items-start gap-3 px-4 py-3.5 text-left outline-none transition hover:bg-deep-violet/[0.03] focus-visible:bg-deep-violet/[0.03] ${
                      n.read_at ? "" : "bg-deep-violet/[0.025]"
                    }`}
                  >
                    <span aria-hidden className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-[15px] font-bold ${meta.tint}`}>
                      {meta.icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="text-[13px] font-bold text-ink dark:text-fog">{n.title}</span>
                        <span className="rounded-full bg-ink/[0.05] px-1.5 py-px text-[9px] font-bold uppercase tracking-wide text-ink/45 dark:bg-fog/[0.06] dark:text-fog/45">
                          {meta.label}
                        </span>
                        {!n.read_at && <span aria-label="Unread" className="h-2 w-2 rounded-full bg-deep-violet" />}
                      </span>
                      {n.body && (
                        <span className="mt-1 block text-[12.5px] leading-relaxed text-ink/65 dark:text-fog/65">
                          {n.body}
                        </span>
                      )}
                      <DetailRows n={n} />
                      <span className="mt-1.5 block text-[10.5px] text-ink/35 dark:text-fog/35">
                        {fullTime(n.created_at)}
                        {n.href ? " · tap to open" : ""}
                      </span>
                    </span>
                  </button>
                  <hr className="border-ink/[0.06] dark:border-fog/[0.06]" />
                </div>
              );
            })}
          </div>
        )}

        {!loading && items.length > 0 && items.length < total && (
          <div className="flex justify-center">
            <button
              onClick={() => void load(items.length, true)}
              disabled={loadingMore}
              className="rounded-xl bg-ink/[0.04] px-4 py-2 text-[12.5px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.07] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50 dark:bg-fog/[0.06] dark:text-fog/60"
            >
              {loadingMore ? "Loading…" : `Load more (${total - items.length} remaining)`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
