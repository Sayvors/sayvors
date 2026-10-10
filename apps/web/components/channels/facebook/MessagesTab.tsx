"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { INK, INK2 } from "../instagram/ui";

/*
 * Messenger conversations with the Page, from our own inbox. Facebook
 * threads deep-link into the unified inbox like every other platform —
 * sending stays there, not here.
 */

const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

/* Mirrors the API's InboxThread schema (channels/schemas.py). */
type Thread = {
  key: string;
  channel_id: string;
  platform?: string | null;
  display_name?: string | null;
  last_message?: string | null;
  last_message_at?: string | null;
  unread?: number;
};

export default function MessagesTab() {
  const [data, setData] = useState<{ threads?: Thread[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // No synchronous setState here: the promise callbacks below own every
    // state change, so mounting never cascades a render.
    apiFetch("/api/v1/inbox/threads?limit=100").then(
      (d) => {
        if (!cancelled) {
          setData(d as { threads?: Thread[] });
          setError(null);
          setLoading(false);
        }
      },
      (e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Something went wrong.");
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p className={`text-[13px] ${INK2}`}>Loading messages…</p>;
  if (error) {
    return (
      <div role="alert" className={`rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4 text-[13px] font-bold ${INK}`}>
        {error}
      </div>
    );
  }
  const threads = (data?.threads ?? []).filter((t) => t.platform === "facebook");
  if (threads.length === 0) {
    return (
      <div className={PANEL}>
        <h3 className={`text-[15px] font-semibold ${INK}`}>Messages</h3>
        <p className={`mt-2 text-[13px] ${INK2}`}>
          No Facebook messages yet. They arrive here the moment someone messages your Page.
        </p>
      </div>
    );
  }
  return (
    <section className={PANEL}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className={`text-[15px] font-semibold ${INK}`}>Messages</h3>
        <span className={`text-[12px] ${INK2}`}>{threads.length} conversations</span>
      </div>
      <ul className="mt-4">
        {threads.map((t) => (
          <li
            key={t.key}
            className="flex flex-wrap items-center gap-3 border-b border-[var(--ui-line)] py-3 last:border-0"
          >
            <div className="min-w-[10rem] flex-1">
              <p className={`text-[13px] font-semibold ${INK}`}>
                {t.display_name || "Facebook user"}
                {!!t.unread && t.unread > 0 && (
                  <span className="ml-2 rounded-[8px] bg-[var(--ui-ink)] px-2 py-0.5 text-[11px] font-bold text-[var(--ui-on-ink)]">
                    {t.unread} new
                  </span>
                )}
              </p>
              <p className={`mt-0.5 line-clamp-1 text-[12px] ${INK2}`}>{t.last_message || "—"}</p>
            </div>
            {t.last_message_at && (
              <time
                dateTime={t.last_message_at}
                className={`shrink-0 text-[12px] tabular-nums ${INK2}`}
              >
                {new Date(t.last_message_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                })}
              </time>
            )}
            <div className="flex shrink-0 items-center gap-2">
              {/* In-dashboard route: same-tab Link, not a new tab. */}
              <Link
                href={`/dashboard/channels/inbox?channel=${encodeURIComponent(t.channel_id)}&key=${encodeURIComponent(t.key)}`}
                className="ui-btn rounded-lg bg-[var(--ui-ink)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-on-ink)]"
              >
                Open
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
