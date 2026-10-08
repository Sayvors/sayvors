"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  fetchInstagramPosts,
  type InstagramPost,
} from "@/lib/api-meta";
import { apiFetch } from "@/lib/api-rag";

/*
 * Comments / Messages lists, read live from Instagram. Posts live in
 * PostsGrid (the profile-style grid + viewer).
 *
 * No follower list anywhere: Meta does not expose one, so there is nothing to
 * show and no link to offer. Everything below comes from the account's own
 * data, and every person carries a real instagram.com link.
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    // No synchronous setState here: the promise callbacks below own every
    // state change, so mounting never cascades a render.
    fn().then(
      (d) => {
        if (!cancelled) {
          setData(d);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading };
}

function Notice({ children }: { children: React.ReactNode }) {
  return <p className={`mt-3 rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] ${INK2}`}>{children}</p>;
}

function LinkBtn({
  href,
  children,
  primary,
}: {
  href: string;
  children: React.ReactNode;
  primary?: boolean;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={
        primary
          ? `ui-btn rounded-lg bg-[var(--ui-ink)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-on-ink)]`
          : `rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[12px] font-semibold ${INK}`
      }
    >
      {children}
    </a>
  );
}

/* ── Comments ────────────────────────────────────────────────────────── */

export function CommentsTab({ igId }: { igId: string }) {
  const { data, error, loading } = useAsync(() => fetchInstagramPosts(igId), [igId]);
  if (loading) return <p className={`text-[13px] ${INK2}`}>Loading comments…</p>;
  if (error) {
    return (
      <div role="alert" className={`rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4 text-[13px] font-bold ${INK}`}>
        {error}
      </div>
    );
  }
  if (data?.unavailable) return <Notice>{data.unavailable}</Notice>;

  const comments = (data?.posts ?? []).flatMap((p: InstagramPost) =>
    p.comments.map((c) => ({ ...c, permalink: p.permalink })),
  );

  if (comments.length === 0) {
    return (
      <div className={PANEL}>
        <h3 className={`text-[15px] font-semibold ${INK}`}>Comments</h3>
        <p className={`mt-2 text-[13px] ${INK2}`}>
          No comments on your recent posts yet. This is where people who engage with you will appear, each
          with a link to their profile.
        </p>
      </div>
    );
  }

  return (
    <section className={PANEL}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className={`text-[15px] font-semibold ${INK}`}>Comments</h3>
        <span className={`text-[12px] ${INK2}`}>{comments.length} on recent posts</span>
      </div>
      <ul className="mt-4">
        {comments.map((c) => (
          <li
            key={`${c.id}-${c.media_id}`}
            className="flex flex-wrap items-start gap-3 border-b border-[var(--ui-line)] py-3 last:border-0"
          >
            <span
              aria-hidden
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)] text-[12px] font-bold text-[var(--ui-ink)]"
            >
              {(c.username || "?").charAt(0).toUpperCase()}
            </span>
            <div className="min-w-[10rem] flex-1">
              <p className={`text-[13px] font-semibold ${INK}`}>
                {c.username ? `@${c.username}` : "Unknown"}
                {c.like_count > 0 && (
                  <span className={`ml-2 text-[12px] font-normal ${INK2}`}>
                    {c.like_count} like{c.like_count === 1 ? "" : "s"}
                  </span>
                )}
              </p>
              {c.text && <p className={`mt-1 text-[13px] ${INK}`}>{c.text}</p>}
              {c.timestamp && (
                <p className={`mt-1 text-[12px] ${INK2}`}>
                  {new Date(c.timestamp).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                  })}
                </p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {c.permalink && <LinkBtn href={c.permalink}>Post</LinkBtn>}
              {c.profile_url && <LinkBtn href={c.profile_url} primary>Profile</LinkBtn>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ── Messages ────────────────────────────────────────────────────────── */

/* Mirrors the API's InboxThread schema (channels/schemas.py): key is the
 * stable thread id, username carries the IG handle when one exists. */
type Thread = {
  key: string;
  channel_id: string;
  platform?: string | null;
  display_name?: string | null;
  username?: string | null;
  last_message?: string | null;
  last_message_at?: string | null;
  unread?: number;
};

export function MessagesTab() {
  const { data, error, loading } = useAsync(
    () => apiFetch("/api/v1/inbox/threads?limit=100") as Promise<{ threads?: Thread[] }>,
    [],
  );
  if (loading) return <p className={`text-[13px] ${INK2}`}>Loading messages…</p>;
  if (error) {
    return (
      <div role="alert" className={`rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4 text-[13px] font-bold ${INK}`}>
        {error}
      </div>
    );
  }
  const threads = (data?.threads ?? []).filter((t) => t.platform === "instagram");
  if (threads.length === 0) {
    return (
      <div className={PANEL}>
        <h3 className={`text-[15px] font-semibold ${INK}`}>Messages</h3>
        <p className={`mt-2 text-[13px] ${INK2}`}>
          No Instagram messages yet. They arrive here the moment someone sends your business a DM.
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
                {t.display_name || (t.username ? `@${t.username}` : "Instagram user")}
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
                className={`ui-btn rounded-lg bg-[var(--ui-ink)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-on-ink)]`}
              >
                Open
              </Link>
              {t.username && <LinkBtn href={`https://instagram.com/${t.username}`}>Profile</LinkBtn>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}