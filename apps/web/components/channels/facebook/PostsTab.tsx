"use client";

import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import {
  fetchFacebookComments,
  fetchFacebookPosts,
  fetchFacebookScheduledPosts,
  type FacebookPost,
  type InstagramStoredComment,
} from "@/lib/api-meta";
import { Avatar, BubbleIcon, HeartIcon, INK, INK2, timeAgo } from "../instagram/ui";
import FacebookPostComposer from "./FacebookPostComposer";

/*
 * The Page's posts: the composer on top, everything already scheduled as a
 * strip of dated chips, and the live feed as a grid. Publishing bumps a
 * version counter that remounts the grid — its fetch is mount-owned, so a
 * fresh post shows up without the tenant hunting for a refresh button.
 */

const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

function Chip({ children }: { children: string }) {
  return (
    <span className="rounded-full border border-[var(--ui-line)] px-2 py-0.5 text-[11px] font-semibold text-[var(--ui-ink-2)]">
      {children}
    </span>
  );
}

function fmtWhen(unix: number | null): string {
  if (!unix) return "—";
  return new Date(unix * 1000).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function PostCard({ post, onOpen }: { post: FacebookPost; onOpen: () => void }) {
  const img = post.images[0] ?? post.full_picture ?? null;
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="ui-btn block w-full overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)] text-left"
      >
        {img && (
          <span className="block aspect-square w-full overflow-hidden bg-[var(--ui-sunken)]">
            <Image
              src={img}
              alt=""
              width={400}
              height={400}
              unoptimized
              className="h-full w-full object-cover"
            />
          </span>
        )}
        <span className="block p-3">
          <span className={`line-clamp-2 block text-[13px] ${INK}`}>
            {post.message || "(no text)"}
          </span>
          <span className={`mt-2 flex items-center gap-3 text-[12px] ${INK2}`}>
            <span className="flex items-center gap-1">
              <HeartIcon className="h-3.5 w-3.5" />
              {post.like_count}
            </span>
            <span className="flex items-center gap-1">
              <BubbleIcon className="h-3.5 w-3.5" />
              {post.comments_count}
            </span>
            <span className="ml-auto">{timeAgo(post.created_time) || ""}</span>
          </span>
        </span>
      </button>
    </li>
  );
}

function PostModal({
  pageId,
  post,
  onClose,
}: {
  pageId: string;
  post: FacebookPost;
  onClose: () => void;
}) {
  const [comments, setComments] = useState<InstagramStoredComment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchFacebookComments(pageId, { mediaId: post.id }).then(
      (data) => {
        if (!cancelled) setComments(data.comments);
      },
      (e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load comments.");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [pageId, post.id]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Post details"
    >
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <h3 className={`text-[15px] font-semibold ${INK}`}>Post</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-[8px] border border-[var(--ui-line)] px-2.5 py-1 text-[12px] font-semibold text-[var(--ui-ink)]"
          >
            Close
          </button>
        </div>

        <p className={`mt-3 whitespace-pre-wrap text-[13px] ${INK}`}>
          {post.message || "(no text)"}
        </p>
        {post.images.length > 0 && (
          <div className="mt-3 grid grid-cols-2 gap-2">
            {post.images.map((src, i) => (
              <span
                key={i}
                className="block overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
              >
                <Image
                  src={src}
                  alt=""
                  width={300}
                  height={300}
                  unoptimized
                  className="h-auto w-full object-cover"
                />
              </span>
            ))}
          </div>
        )}

        <p className={`mt-3 flex flex-wrap items-center gap-3 text-[12px] ${INK2}`}>
          <span className="flex items-center gap-1">
            <HeartIcon className="h-3.5 w-3.5" /> {post.like_count}
          </span>
          <span className="flex items-center gap-1">
            <BubbleIcon className="h-3.5 w-3.5" /> {post.comments_count}
          </span>
          <span>{timeAgo(post.created_time) || ""}</span>
          {post.permalink_url && (
            <a
              href={post.permalink_url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              Open on Facebook
            </a>
          )}
        </p>

        <div className="mt-4 border-t border-[var(--ui-line)] pt-3">
          <p className={`text-[13px] font-semibold ${INK}`}>Comments on this post</p>
          <p className={`mt-0.5 text-[12px] ${INK2}`}>
            Reply, hide or delete in the Comments tab — this is the history.
          </p>
          {error && (
            <p role="alert" className="mt-2 text-[12px] font-semibold text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          {comments !== null && comments.length === 0 && (
            <p className={`mt-2 text-[12px] ${INK2}`}>No comments yet.</p>
          )}
          <ul className="mt-2">
            {(comments ?? []).map((c) => (
              <li key={c.id} className="flex items-start gap-2 py-1.5">
                <Avatar name={c.author_name || "?"} />
                <p className="min-w-0 flex-1 text-[13px] leading-snug">
                  <span className={`font-semibold ${INK}`}>{c.author_name || "Facebook user"}</span>{" "}
                  <span className={c.deleted_at ? `line-through opacity-60 ${INK}` : INK}>
                    {c.content}
                  </span>
                  <span className={`ml-2 text-[11px] ${INK2}`}>
                    {timeAgo(c.platform_timestamp ?? c.created_at)}
                  </span>
                </p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function Feed({ pageId, reloadKey, onOpen }: { pageId: string; reloadKey: number; onOpen: (p: FacebookPost) => void }) {
  const [posts, setPosts] = useState<FacebookPost[] | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scheduled, setScheduled] = useState<Map<string, number>>(new Map());
  const [reload, setReload] = useState(0);

  // Event handlers (retry) own the synchronous reset; the effect's promise
  // callbacks own everything after the await.
  const refresh = useCallback(() => {
    setPosts(null);
    setError(null);
    setReload((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchFacebookPosts(pageId).then(
      (data) => {
        if (cancelled) return;
        setPosts(data.posts ?? []);
        setUnavailable(data.unavailable || null);
        setError(null);
      },
      (e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load posts.");
        }
      },
    );
    fetchFacebookScheduledPosts(pageId).then(
      (data) => {
        if (cancelled) return;
        const map = new Map<string, number>();
        for (const p of data.posts ?? []) map.set(p.id, p.scheduled_publish_time ?? 0);
        setScheduled(map);
      },
      () => {
        /* Meta refuses scheduled_posts on some Page setups — chips vanish,
           the feed stays. */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [pageId, reloadKey, reload]);

  if (unavailable) {
    return (
      <p className={`text-[13px] ${INK2}`}>{unavailable}</p>
    );
  }
  if (error && posts === null) {
    return (
      <div role="alert" className="rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4">
        <p className={`text-[13px] font-bold ${INK}`}>{error}</p>
        <button
          type="button"
          onClick={refresh}
          className="ui-btn mt-3 rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
        >
          Try again
        </button>
      </div>
    );
  }
  if (posts === null) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" aria-hidden>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="aspect-square animate-pulse rounded-[16px] bg-[var(--ui-sunken)]" />
        ))}
      </div>
    );
  }
  if (posts.length === 0) {
    return (
      <p className={`text-[13px] ${INK2}`}>
        No posts yet. Write the first one above — it lands on your Page the moment you publish.
      </p>
    );
  }

  const scheduledRows = posts.filter((p) => scheduled.has(p.id));

  return (
    <div className="space-y-4">
      {scheduledRows.length > 0 && (
        <div>
          <p className={`text-[12px] font-semibold ${INK2}`}>Scheduled</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {scheduledRows.map((p) => (
              <li
                key={p.id}
                className="flex items-center gap-2 rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2"
              >
                <span className={`max-w-[10rem] truncate text-[12px] ${INK}`}>
                  {p.message || "(no text)"}
                </span>
                <Chip>{fmtWhen(scheduled.get(p.id) ?? null)}</Chip>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {posts.map((p) => (
          <PostCard key={p.id} post={p} onOpen={() => onOpen(p)} />
        ))}
      </ul>
    </div>
  );
}

export default function PostsTab({ pageId }: { pageId: string }) {
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState<FacebookPost | null>(null);
  return (
    <section className={PANEL}>
      <h3 className={`text-[15px] font-semibold ${INK}`}>Posts</h3>
      <p className={`mt-1 text-[12px] ${INK2}`}>
        Publish text, links or photos to your Page — now or later. Tap a post to
        read its comment history.
      </p>
      <div className="mt-4 space-y-5">
        <FacebookPostComposer pageId={pageId} onPublished={() => setVersion((v) => v + 1)} />
        <Feed pageId={pageId} reloadKey={version} onOpen={setOpen} />
      </div>
      {open && (
        <PostModal pageId={pageId} post={open} onClose={() => setOpen(null)} />
      )}
    </section>
  );
}
