"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import {
  fetchInstagramPosts,
  type InstagramPost,
} from "@/lib/api-meta";
import PostModal from "./PostModal";
import { BubbleIcon, HeartIcon, INK, INK2 } from "./ui";

/*
 * The Instagram profile grid: three square columns, hover shows like and
 * comment counts, a post opens the split-screen viewer. Empty, loading and
 * error states are all first-class — an account with no posts says so in
 * words, never with a blank box.
 */

function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    // The promise callbacks own every state change, so mounting never
    // cascades a render.
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
  }, [...deps, reload]);
  // Event handlers may set state synchronously — the effect may not.
  const retry = () => {
    setLoading(true);
    setError(null);
    setReload((n) => n + 1);
  };
  return { data, error, loading, retry };
}

function CellBadge({ post }: { post: InstagramPost }) {
  if (post.children?.length > 1) {
    return (
      <span
        aria-hidden
        title="Carousel"
        className="absolute right-2 top-2 text-white drop-shadow"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
          <rect x="7" y="3" width="14" height="14" rx="2" opacity="0.9" />
          <rect x="3" y="7" width="4" height="14" rx="1.5" />
        </svg>
      </span>
    );
  }
  if (post.media_type === "VIDEO" || post.media_product_type === "REELS") {
    return (
      <span
        aria-hidden
        title={post.media_product_type === "REELS" ? "Reel" : "Video"}
        className="absolute right-2 top-2 text-white drop-shadow"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
          <path d="M8 5v14l11-7z" />
        </svg>
      </span>
    );
  }
  return null;
}

export default function PostsGrid({
  igId,
  accountUsername,
}: {
  igId: string;
  accountUsername?: string | null;
}) {
  const { data, error, loading, retry } = useAsync(
    () => fetchInstagramPosts(igId),
    [igId],
  );
  const [openId, setOpenId] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-1" aria-hidden>
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="aspect-square animate-pulse bg-[var(--ui-sunken)]" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4">
        <p className={`text-[13px] font-bold ${INK}`}>{error}</p>
        <button
          type="button"
          onClick={retry}
          className="ui-btn mt-3 rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
        >
          Try again
        </button>
      </div>
    );
  }

  if (data?.unavailable) {
    return <p className={`text-[13px] ${INK2}`}>{data.unavailable}</p>;
  }

  const posts = data?.posts ?? [];
  if (posts.length === 0) {
    return (
      <p className={`text-[13px] ${INK2}`}>
        No posts yet. When you publish on Instagram, they appear here as a grid —
        just like your profile.
      </p>
    );
  }

  const open = posts.find((p) => p.id === openId) ?? null;

  return (
    <>
      <div className="grid grid-cols-3 gap-1">
        {posts.map((p, i) => (
          <button
            key={p.id ?? `post-${i}`}
            type="button"
            onClick={() => setOpenId(p.id)}
            aria-label={
              p.caption ? `Open post: ${p.caption.slice(0, 60)}` : "Open post"
            }
            className="group relative aspect-square overflow-hidden bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {p.thumbnail_url || p.media_url ? (
              <Image
                src={(p.thumbnail_url ?? p.media_url)!}
                alt=""
                fill
                sizes="(max-width: 768px) 33vw, 200px"
                unoptimized
                className="object-cover"
              />
            ) : (
              <span className="flex h-full items-center justify-center text-[10px] text-[var(--ui-ink-2)]">
                {p.media_type || "media"}
              </span>
            )}
            <CellBadge post={p} />
            {/* Instagram's hover scrim: counts over a dimmed thumbnail. */}
            <span className="absolute inset-0 hidden items-center justify-center gap-5 bg-black/45 text-[13px] font-bold text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 sm:flex">
              <span className="flex items-center gap-1.5">
                <HeartIcon className="h-5 w-5" />
                {p.like_count.toLocaleString()}
              </span>
              <span className="flex items-center gap-1.5">
                <BubbleIcon className="h-5 w-5" />
                {p.comments_count.toLocaleString()}
              </span>
            </span>
          </button>
        ))}
      </div>

      {open && (
        <PostModal
          post={open}
          igId={igId}
          accountUsername={accountUsername ?? null}
          onClose={() => setOpenId(null)}
        />
      )}
    </>
  );
}
