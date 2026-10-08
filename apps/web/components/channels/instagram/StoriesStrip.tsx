"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import {
  fetchInstagramStories,
  type InstagramStory,
} from "@/lib/api-meta";
import { INK, timeAgo } from "./ui";

/*
 * The stories row: circles for the account's own live stories, a tap opens
 * a plain black viewer. This is everything the API offers — only the
 * account's OWN stories exist here (other accounts' are private), they
 * expire after 24h, and nobody anywhere can read the viewer list.
 *
 * Renders nothing when no story is live, exactly like Instagram hides an
 * empty tray.
 */

function StoryViewer({
  story,
  onClose,
}: {
  story: InstagramStory;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Story"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
      onClick={onClose}
    >
      <div
        className="relative flex max-h-[88vh] w-full max-w-[420px] flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-2 text-white">
          <span className="text-[12px] tabular-nums">
            {timeAgo(story.timestamp) || "Live"} · disappears from Instagram after 24 hours
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close story"
            className="flex h-11 w-11 items-center justify-center rounded-full text-[16px] font-bold text-white focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white"
          >
            ✕
          </button>
        </div>
        {story.media_type === "VIDEO" && story.media_url ? (
          <video
            src={story.media_url}
            controls
            autoPlay
            playsInline
            className="max-h-[80vh] w-full rounded-[16px] object-contain"
          />
        ) : story.media_url ? (
          <Image
            src={story.media_url}
            alt="Story"
            width={640}
            height={1000}
            unoptimized
            className="max-h-[80vh] w-full rounded-[16px] object-contain"
          />
        ) : (
          <p className="p-6 text-center text-[13px] text-white/70">
            This story has no readable media — it may have just expired.
          </p>
        )}
      </div>
    </div>
  );
}

export default function StoriesStrip({ igId }: { igId: string }) {
  const [stories, setStories] = useState<InstagramStory[] | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchInstagramStories(igId).then(
      (d) => {
        if (!cancelled) setStories(d.stories ?? []);
      },
      () => {
        if (!cancelled) setStories([]);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [igId]);

  if (stories === null || stories.length === 0) return null;
  const open = openIdx != null ? stories[openIdx] : null;

  return (
    <>
      <div className="flex flex-wrap gap-3" role="list" aria-label="Live stories">
        {stories.map((s, i) => (
          <button
            key={s.id ?? `story-${i}`}
            type="button"
            role="listitem"
            onClick={() => setOpenIdx(i)}
            aria-label={s.media_type === "VIDEO" ? "Open video story" : "Open story"}
            className="relative h-16 w-16 overflow-hidden rounded-full border-2 border-[var(--ui-ink)] bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {s.media_type === "VIDEO" ? (
              <span className={`flex h-full items-center justify-center ${INK}`}>
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden>
                  <path d="M8 5v14l11-7z" />
                </svg>
              </span>
            ) : s.media_url ? (
              <Image
                src={s.media_url}
                alt=""
                width={64}
                height={64}
                unoptimized
                className="h-full w-full object-cover"
              />
            ) : (
              <span className={`flex h-full items-center justify-center text-[10px] ${INK}`}>
                story
              </span>
            )}
          </button>
        ))}
      </div>
      {open && (
        <StoryViewer
          story={open}
          onClose={() => setOpenIdx(null)}
        />
      )}
    </>
  );
}
