"use client";

import { useEffect, useRef, useState } from "react";
import type { PostItem } from "./PostsPage";
import type { MediaItem } from "./MediaPage";

/* Shared presentation for the unified Posts & Media page. The page owns data
   and routing between feed / composer / detail; these are the surfaces. */

export interface FeedLocation {
  id: string;
  name: string;
}

export type FeedEntry =
  | { kind: "post"; key: string; createdAt: string; post: PostItem }
  | { kind: "media"; key: string; createdAt: string; media: MediaItem };

export function feedEntries(posts: PostItem[], media: MediaItem[]): FeedEntry[] {
  const entries: FeedEntry[] = [
    ...posts.map((p) => ({ kind: "post" as const, key: `post-${p.id}`, createdAt: p.createdAt, post: p })),
    ...media.map((m) => ({ kind: "media" as const, key: `media-${m.id}`, createdAt: m.createdAt, media: m })),
  ];
  return entries.sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0));
}

const TONE = {
  violet: "bg-deep-violet/10 text-deep-violet",
  emerald: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  amber: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400",
  sky: "bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400",
  red: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400",
  gray: "bg-ink/[0.05] text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45",
} as const;

export type Tone = keyof typeof TONE;

export function Pill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className={`shrink-0 rounded-[2px] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${TONE[tone]}`}>
      {children}
    </span>
  );
}

function postStatus(status: PostItem["status"]): { label: string; tone: Tone } {
  switch (status) {
    case "LIVE": return { label: "Live", tone: "emerald" };
    case "SCHEDULED": return { label: "Scheduled", tone: "amber" };
    case "FAILED": return { label: "Failed", tone: "red" };
    case "DRAFT": return { label: "Draft", tone: "sky" };
    default: return { label: "Archived", tone: "gray" };
  }
}

function mediaStatus(status: MediaItem["status"]): { label: string; tone: Tone } {
  switch (status) {
    case "PUBLISHED": return { label: "Published", tone: "emerald" };
    case "SCHEDULED": return { label: "Scheduled", tone: "amber" };
    case "FAILED": return { label: "Failed", tone: "red" };
    default: return { label: "In library", tone: "sky" };
  }
}

function formatDay(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
}

function prettyCategory(value: string): string {
  const s = value.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function CardThumb({ src, fallback }: { src?: string; fallback: React.ReactNode }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <>{fallback}</>;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- arbitrary remote hosts (no next.config allowlist)
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
    />
  );
}

export function PostCard({ post, onOpen }: { post: PostItem; onOpen: () => void }) {
  const status = postStatus(post.status);
  const type = post.post_type === "offer" ? "Offer" : post.post_type === "event" ? "Event" : null;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Open post ${post.title}`}
      className="group flex w-full cursor-pointer flex-col overflow-hidden rounded-[2px] border border-ink/[0.06] bg-white text-left outline-none transition hover:border-deep-violet/25 hover:shadow-md focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:border-fog/[0.07] dark:bg-ink"
    >
      <span className="relative block aspect-video overflow-hidden bg-gradient-to-br from-violet-soft/40 to-sky/20">
        <CardThumb
          src={post.images[0]}
          fallback={
            <span className="grid h-full w-full place-items-center text-[30px] font-black text-deep-violet/25">
              {post.title.trim().charAt(0).toUpperCase() || "P"}
            </span>
          }
        />
        <span className="absolute left-2 top-2 rounded-[2px] bg-white/90 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-deep-violet backdrop-blur dark:bg-ink/85">
          Post
        </span>
        <span className="absolute right-2 top-2 flex flex-col items-end gap-1">
          <Pill tone={status.tone}>{status.label}</Pill>
          {type && <Pill tone="sky">{type}</Pill>}
        </span>
        {post.images.length > 1 && (
          <span className="absolute bottom-2 right-2 rounded-[2px] bg-black/55 px-2 py-0.5 text-[10px] font-semibold text-white">
            {post.images.length} photos
          </span>
        )}
      </span>
      <span className="flex flex-1 flex-col p-3.5">
        <span className="truncate text-[13px] font-bold text-ink dark:text-fog">{post.title}</span>
        <span className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
          {post.description || "No description yet."}
        </span>
        <span className="mt-auto flex items-center gap-1.5 pt-3">
          {post.tags.slice(0, 2).map((t) => (
            <span key={t} className="rounded-[2px] bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet">
              #{t}
            </span>
          ))}
          <span className="ml-auto shrink-0 text-[10px] text-ink/35 dark:text-fog/35">{formatDay(post.createdAt)}</span>
        </span>
      </span>
    </button>
  );
}

export function MediaCard({ media, onOpen }: { media: MediaItem; onOpen: () => void }) {
  const status = mediaStatus(media.status);
  const isVideo = media.type === "VIDEO";
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Open media ${prettyCategory(media.category)}`}
      className="group flex w-full cursor-pointer flex-col overflow-hidden rounded-[2px] border border-ink/[0.06] bg-white text-left outline-none transition hover:border-deep-violet/25 hover:shadow-md focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:border-fog/[0.07] dark:bg-ink"
    >
      <span className="relative block aspect-video overflow-hidden bg-gradient-to-br from-violet-soft/40 to-sky/20">
        <CardThumb
          src={isVideo ? undefined : media.thumbnailUrl}
          fallback={
            isVideo ? (
              <span className="grid h-full w-full place-items-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-[2px] bg-white/25 backdrop-blur">
                  <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5 text-white"><path d="M8 5v14l11-7z" /></svg>
                </span>
              </span>
            ) : (
              <span className="grid h-full w-full place-items-center text-ink/20 dark:text-fog/20">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-8 w-8">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="M21 15l-5-5L5 21" />
                </svg>
              </span>
            )
          }
        />
        <span className="absolute left-2 top-2 rounded-[2px] bg-white/90 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-sky-700 backdrop-blur dark:bg-ink/85 dark:text-sky-400">
          Media
        </span>
        <span className="absolute right-2 top-2 flex flex-col items-end gap-1">
          <Pill tone={status.tone}>{status.label}</Pill>
          {media.isProfile && <Pill tone="violet">Profile</Pill>}
          {media.isCover && <Pill tone="emerald">Cover</Pill>}
        </span>
        <span className="absolute bottom-2 left-2 rounded-[2px] bg-black/55 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
          {isVideo ? "Video" : "Photo"}
        </span>
      </span>
      <span className="flex flex-1 flex-col p-3.5">
        <span className="truncate text-[13px] font-bold text-ink dark:text-fog">{prettyCategory(media.category)}</span>
        <span className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
          {isVideo ? "Video saved to your library." : "Photo saved to your library."}
        </span>
        <span className="mt-auto flex items-center gap-1.5 pt-3">
          {media.status === "SCHEDULED" && media.scheduledAt && (
            <span className="rounded-[2px] bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
              Publishes {formatDay(media.scheduledAt)}
            </span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-ink/35 dark:text-fog/35">{formatDay(media.createdAt)}</span>
        </span>
      </span>
    </button>
  );
}

export function FeedGrid({ entries, onOpenPost, onOpenMedia }: {
  entries: FeedEntry[];
  onOpenPost: (id: string) => void;
  onOpenMedia: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {entries.map((e) =>
        e.kind === "post" ? (
          <PostCard key={e.key} post={e.post} onOpen={() => onOpenPost(e.post.id)} />
        ) : (
          <MediaCard key={e.key} media={e.media} onOpen={() => onOpenMedia(e.media.id)} />
        )
      )}
    </div>
  );
}

function CreateMenu({ onCreatePost, onCreateMedia }: { onCreatePost: () => void; onCreateMedia: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5">
          <path d="M12 5v14M5 12h14" strokeLinecap="round" />
        </svg>
        Create
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Create"
          className="absolute right-0 z-40 mt-2 w-64 overflow-hidden rounded-[2px] border border-ink/[0.08] bg-white p-1.5 shadow-xl dark:border-fog/[0.1] dark:bg-ink"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => { setOpen(false); onCreatePost(); }}
            className="flex w-full items-start gap-3 rounded-[2px] px-3 py-2.5 text-left outline-none transition hover:bg-deep-violet/[0.06] focus-visible:bg-deep-violet/[0.06]"
          >
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-deep-violet/10 text-deep-violet">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path d="M4 5h16v11H8l-4 4V5z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold text-ink dark:text-fog">Create post</span>
              <span className="block text-[11px] text-ink/45 dark:text-fog/45">Offer, event or update — publish or schedule to Google.</span>
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => { setOpen(false); onCreateMedia(); }}
            className="flex w-full items-start gap-3 rounded-[2px] px-3 py-2.5 text-left outline-none transition hover:bg-deep-violet/[0.06] focus-visible:bg-deep-violet/[0.06]"
          >
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <rect x="3" y="4" width="18" height="16" rx="2" />
                <circle cx="8.5" cy="9" r="1.5" />
                <path d="M21 15l-4.5-4.5L6 21" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold text-ink dark:text-fog">Create media</span>
              <span className="block text-[11px] text-ink/45 dark:text-fog/45">Upload a photo or video to the location library.</span>
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

export function FeedHeader({ title, subtitle, stats, locations, selectedId, onSelectLocation, onCreatePost, onCreateMedia }: {
  title: string;
  subtitle: string;
  stats: { text: string; tone: Tone }[];
  locations: FeedLocation[];
  selectedId: string | null;
  onSelectLocation: (id: string) => void;
  onCreatePost: () => void;
  onCreateMedia: () => void;
}) {
  return (
    // relative+z: backdrop-blur here creates a stacking context; without a
    // z-index the feed cards' positioned badges paint over the create menu.
    <div className="relative z-30 shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-4 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80">
      <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[19px] font-bold text-ink dark:text-fog">{title}</h1>
          <p className="mt-0.5 max-w-xl text-[12px] text-ink/45 dark:text-fog/45">{subtitle}</p>
          {stats.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {stats.map((s) => (
                <Pill key={s.text} tone={s.tone}>{s.text}</Pill>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {locations.length > 0 && (
            <div className="relative">
              <select
                value={selectedId ?? ""}
                onChange={(e) => onSelectLocation(e.target.value)}
                aria-label="Location"
                className="w-52 appearance-none rounded-[2px] border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          )}
          <CreateMenu onCreatePost={onCreatePost} onCreateMedia={onCreateMedia} />
        </div>
      </div>
    </div>
  );
}

export function FeedEmpty({ hasLocations, onCreatePost, onCreateMedia }: {
  hasLocations: boolean;
  onCreatePost: () => void;
  onCreateMedia: () => void;
}) {
  return (
    <div className="flex flex-col items-center rounded-[2px] border border-dashed border-ink/[0.12] bg-white px-6 py-16 dark:border-fog/[0.12] dark:bg-ink">
      <span className="flex h-12 w-12 items-center justify-center rounded-[2px] bg-deep-violet/[0.08] text-deep-violet">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 10h18M9 20V10" strokeLinecap="round" />
        </svg>
      </span>
      <p className="mt-4 text-[15px] font-bold text-ink dark:text-fog">
        {hasLocations ? "Nothing published yet" : "Connect a Google location first"}
      </p>
      <p className="mt-1 max-w-sm text-center text-[12px] leading-relaxed text-ink/40 dark:text-fog/40">
        {hasLocations
          ? "Create your first post or upload photos so customers see fresh updates on your Google listing."
          : "Posts and media publish to a Google Business location — connect one from Channels and come back."}
      </p>
      {hasLocations && (
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <button onClick={onCreatePost} className="rounded-[2px] bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90">
            Create a post
          </button>
          <button onClick={onCreateMedia} className="rounded-[2px] border border-ink/[0.1] px-4 py-2 text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:border-fog/[0.12] dark:text-fog/60 dark:hover:bg-fog/[0.05]">
            Upload media
          </button>
        </div>
      )}
    </div>
  );
}
