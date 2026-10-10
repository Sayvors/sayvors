"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchInstagramMediaInsights,
  type InstagramComment,
  type InstagramPost,
} from "@/lib/api-meta";
import PlatformMark from "@/components/channels/PlatformMark";
import {
  Avatar,
  BubbleIcon,
  HeartIcon,
  INK,
  INK2,
  timeAgo,
} from "./ui";

/*
 * Instagram's own post detail: media left, comments right.
 *
 * Counts are read-only by Meta's design — there is no endpoint to like,
 * share or bookmark through the Graph API, so nothing here pretends to be a
 * button. The double-tap heart is the one Instagram gesture kept as pure
 * visual flourish; the count it sits on never changes, because it cannot.
 * Insights (reach / saves / shares) are owner-only and load lazily so a
 * missing insights permission never blocks the post itself.
 */

function CommentRow({ comment }: { comment: InstagramComment }) {
  const who = comment.username || "Unknown";
  return (
    <li className="flex items-start gap-3 px-5 py-3">
      <Avatar name={who} />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] leading-snug">
          <span className={`font-semibold ${INK}`}>
            {comment.username ? `@${comment.username}` : who}
          </span>{" "}
          <span className={INK}>{comment.text || "—"}</span>
        </p>
        <p className={`mt-1 flex items-center gap-2 text-[12px] ${INK2}`}>
          {timeAgo(comment.timestamp) && <span>{timeAgo(comment.timestamp)}</span>}
          {comment.like_count > 0 && <span>{comment.like_count} likes</span>}
        </p>
        {comment.replies?.length > 0 && (
          <ul className="mt-2 space-y-2 border-l-2 border-[var(--ui-line)] pl-3">
            {comment.replies.map((r, ri) => (
              <li key={`${r.id ?? "r"}-${ri}`}>
                <p className="text-[12px] leading-snug">
                  <span className={`font-semibold ${INK}`}>
                    {r.username ? `@${r.username}` : "Unknown"}
                  </span>{" "}
                  <span className={INK}>{r.text || "—"}</span>
                </p>
                <p className={`mt-0.5 flex items-center gap-2 text-[11px] ${INK2}`}>
                  {timeAgo(r.timestamp) && <span>{timeAgo(r.timestamp)}</span>}
                  {r.like_count > 0 && <span>{r.like_count} likes</span>}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

type Slide = {
  key: string;
  mediaType: string | null;
  mediaUrl: string | null;
  thumbnailUrl: string | null;
};

function slidesFor(post: InstagramPost): Slide[] {
  if (post.children?.length > 0) {
    return post.children.map((c, i) => ({
      key: c.id ?? `slide-${i}`,
      mediaType: c.media_type,
      mediaUrl: c.media_url,
      thumbnailUrl: c.thumbnail_url,
    }));
  }
  return [
    {
      key: post.id ?? "post",
      mediaType: post.media_type,
      mediaUrl: post.media_url,
      thumbnailUrl: post.thumbnail_url,
    },
  ];
}

export default function PostModal({
  post,
  igId,
  accountUsername,
  onClose,
}: {
  post: InstagramPost;
  igId: string;
  accountUsername: string | null;
  onClose: () => void;
}) {
  const [closing, setClosing] = useState(false);
  const [burst, setBurst] = useState(0);
  const [slide, setSlide] = useState(0);
  const [insights, setInsights] = useState<{
    reach: number | null;
    impressions: number | null;
    saves: number | null;
    shares: number | null;
    views: number | null;
  } | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const slides = slidesFor(post);
  const current = slides[Math.min(slide, slides.length - 1)];
  const isVideo = current.mediaType === "VIDEO";

  const dismiss = useCallback(() => {
    setClosing(true);
    window.setTimeout(onClose, 150);
  }, [onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
      if (e.key === "ArrowRight" && slides.length > 1)
        setSlide((s) => (s + 1) % slides.length);
      if (e.key === "ArrowLeft" && slides.length > 1)
        setSlide((s) => (s - 1 + slides.length) % slides.length);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeBtnRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [dismiss, slides.length]);

  // Owner-only insights, fetched once per open. Unavailable is normal (no
  // insights scope) and just means the line stays hidden.
  useEffect(() => {
    if (!post.id) return;
    let cancelled = false;
    fetchInstagramMediaInsights(igId, post.id, post.media_product_type ?? post.media_type).then(
      (data) => {
        if (!cancelled) setInsights(data.available ? data : null);
      },
      () => {
        if (!cancelled) setInsights(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [igId, post.id, post.media_product_type, post.media_type]);

  const isReel = post.media_product_type === "REELS";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={post.caption ? `Post: ${post.caption.slice(0, 60)}` : "Post"}
      className={`fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 sm:p-6 ${
        closing ? "post-modal-out" : "post-modal-in"
      }`}
      onClick={dismiss}
    >
      <style>{`
        @keyframes postModalIn {
          from { opacity: 0; transform: scale(0.96); }
          to { opacity: 1; transform: scale(1); }
        }
        @keyframes postModalOut {
          from { opacity: 1; }
          to { opacity: 0; }
        }
        @keyframes heartBurst {
          0% { opacity: 0; transform: scale(0.3); }
          25% { opacity: 1; transform: scale(1.15); }
          60% { opacity: 1; transform: scale(1); }
          100% { opacity: 0; transform: scale(1.05); }
        }
        .post-modal-in { animation: postModalIn 180ms ease-out; }
        .post-modal-out { animation: postModalOut 150ms ease-in forwards; }
        .post-heart-burst { animation: heartBurst 900ms ease-out forwards; }
        @media (prefers-reduced-motion: reduce) {
          .post-modal-in, .post-modal-out, .post-heart-burst { animation: none; }
        }
      `}</style>

      <div
        className="flex h-[min(88vh,720px)] w-full max-w-[960px] flex-col overflow-hidden rounded-[16px] bg-[var(--ui-surface)] shadow-2xl md:flex-row"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Media side — black like Instagram's viewer, media fit inside. */}
        <div
          className="relative flex min-h-[240px] flex-1 items-center justify-center bg-black"
          onDoubleClick={() => setBurst((n) => n + 1)}
        >
          {isVideo && current.mediaUrl ? (
            <video
              key={current.key}
              src={current.mediaUrl}
              poster={current.thumbnailUrl ?? undefined}
              controls
              playsInline
              className="max-h-full max-w-full"
            />
          ) : current.mediaUrl ? (
            <Image
              key={current.key}
              src={current.mediaUrl}
              alt={post.caption || "Instagram post"}
              width={900}
              height={900}
              unoptimized
              className="max-h-full max-w-full object-contain"
            />
          ) : (
            <span className="flex flex-col items-center gap-2 text-white/70">
              <PlatformMark platform="instagram" size={40} />
              <span className="text-[13px]">No media returned for this post</span>
            </span>
          )}

          {burst > 0 && (
            <span
              key={burst}
              aria-hidden
              className="post-heart-burst pointer-events-none absolute text-white drop-shadow"
            >
              <HeartIcon className="h-24 w-24" />
            </span>
          )}

          {isReel && (
            <span
              aria-hidden
              className="absolute left-3 top-3 rounded-[8px] bg-black/60 px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-white"
            >
              Reel
            </span>
          )}

          {slides.length > 1 && (
            <>
              <button
                type="button"
                aria-label="Previous image"
                onClick={() => setSlide((s) => (s - 1 + slides.length) % slides.length)}
                className="absolute left-2 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-[18px] font-bold text-white focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white"
              >
                ‹
              </button>
              <button
                type="button"
                aria-label="Next image"
                onClick={() => setSlide((s) => (s + 1) % slides.length)}
                className="absolute right-2 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-[18px] font-bold text-white focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white"
              >
                ›
              </button>
              <div className="absolute bottom-3 flex gap-1.5" aria-hidden>
                {slides.map((s, i) => (
                  <span
                    key={s.key}
                    className={`h-1.5 w-1.5 rounded-full ${i === slide ? "bg-white" : "bg-white/40"}`}
                  />
                ))}
              </div>
            </>
          )}

          <button
            ref={closeBtnRef}
            type="button"
            onClick={dismiss}
            aria-label="Close post"
            className="absolute right-3 top-3 flex h-11 w-11 items-center justify-center rounded-full bg-black/60 text-[16px] font-bold text-white focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white md:hidden"
          >
            ✕
          </button>
        </div>

        {/* Comments side — the real surface: caption, counts, comments. */}
        <div className="flex w-full shrink-0 flex-col border-[var(--ui-line)] md:w-[360px] md:border-l lg:w-[400px]">
          <div className="flex items-center justify-between border-b border-[var(--ui-line)] px-5 py-3">
            <p className={`flex items-center gap-2 text-[13px] font-semibold ${INK}`}>
              <Avatar name={accountUsername || "IG"} />
              {accountUsername ? `@${accountUsername}` : "Instagram"}
            </p>
            <div className="flex items-center gap-1">
              {post.permalink && (
                <a
                  href={post.permalink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[12px] font-semibold ${INK} focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]`}
                >
                  View
                </a>
              )}
              <button
                type="button"
                onClick={dismiss}
                aria-label="Close post"
                className="hidden h-11 w-11 items-center justify-center rounded-full text-[16px] font-bold text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] md:flex"
              >
                ✕
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {post.caption && (
              <div className="flex items-start gap-3 border-b border-[var(--ui-line)] px-5 py-3">
                <Avatar name={accountUsername || "IG"} />
                <p className="min-w-0 flex-1 text-[13px] leading-snug">
                  <span className={`font-semibold ${INK}`}>
                    {accountUsername ? `@${accountUsername}` : "Instagram"}
                  </span>{" "}
                  <span className={INK}>{post.caption}</span>
                  <span className={`mt-1 block text-[12px] ${INK2}`}>
                    {timeAgo(post.timestamp)}
                  </span>
                </p>
              </div>
            )}
            {post.comments.length > 0 ? (
              <ul>
                {post.comments.slice(0, 20).map((c, i) => (
                  <CommentRow key={`${c.id ?? "c"}-${i}`} comment={c} />
                ))}
              </ul>
            ) : (
              <p className={`px-5 py-6 text-[13px] ${INK2}`}>
                No comments yet on this post.
              </p>
            )}
          </div>

          {/* Counts exactly as Instagram states them — labels, not buttons:
              the Graph API has no like/share/bookmark write endpoint. */}
          <div className="border-t border-[var(--ui-line)] px-5 py-3">
            <div className={`flex items-center gap-4 ${INK}`}>
              <HeartIcon className="h-6 w-6" />
              <BubbleIcon className="h-6 w-6" />
            </div>
            <p className={`mt-2 text-[13px] font-bold ${INK}`}>
              {post.like_count.toLocaleString()}{" "}
              {post.like_count === 1 ? "like" : "likes"}
            </p>
            <p className={`mt-0.5 text-[12px] ${INK2}`}>
              {post.comments_count.toLocaleString()}{" "}
              {post.comments_count === 1 ? "comment" : "comments"}
              {post.comments_count > post.comments.length &&
                post.permalink && (
                  <>
                    {" · "}
                    <a
                      href={post.permalink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`font-semibold underline underline-offset-2 ${INK}`}
                    >
                      see all on Instagram
                    </a>
                  </>
                )}
            </p>
            {insights && (
              <p className={`mt-1 text-[12px] tabular-nums ${INK2}`}>
                {[
                  insights.views != null && `${insights.views.toLocaleString()} views`,
                  insights.reach != null && `${insights.reach.toLocaleString()} reached`,
                  insights.impressions != null &&
                    `${insights.impressions.toLocaleString()} impressions`,
                  insights.saves != null && `${insights.saves.toLocaleString()} saves`,
                  insights.shares != null && `${insights.shares.toLocaleString()} shares`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
