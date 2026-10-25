"use client";

import { useMemo, useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import GoogleBusinessLogo from "@/components/channels/GoogleBusinessLogo";
import LogoLoader from "@/components/LogoLoader";
import {
  QUEUED_STATUSES,
  isRemovableJob,
  usePublishJobs,
  type PublishJob,
} from "@/lib/use-publish-jobs";
import { useLocationPosts, type LocationPost } from "@/lib/location-posts";
import ScheduledPostsCalendar, { type ScheduledEntry } from "@/components/dashboard/ScheduledPostsCalendar";
import { METHOD_META, PLATFORM_META, type PlatformKey } from "@/components/dashboard/publish/types";

/*
 * Every post, on every connected network — Instagram, Facebook, WhatsApp
 * statuses and Google Business Profile. One list, newest first, with the
 * platform and the outcome on each card.
 *
 * Two sources feed the list: publishing jobs (the cross-platform composer)
 * and legacy Google location posts (the old per-branch flow, published via
 * Localith). Composer posts can be removed from the platform they went out
 * on (checked, then delete) or cancelled before they go out; legacy posts
 * are display-only — Localith exposes no delete API.
 */

/** One feed row: a composer job or a legacy Google location post. */
type FeedEntry =
  | { kind: "job"; at: number; job: PublishJob }
  | { kind: "legacy"; at: number; post: LocationPost };

type Chip = { label: string; cls: string };

function statusChip(job: PublishJob): Chip {
  if (job.status === "succeeded") return { label: "Published", cls: "bg-[#e7f8ef] text-[#0c7a43]" };
  if (job.status === "running") return { label: "Publishing…", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-400" };
  if (job.status === "failed" || job.status === "dead") return { label: "Failed", cls: "bg-red-500/10 text-red-700 dark:text-red-400" };
  if (job.status === "cancelled") {
    // A deleted post was removed from its platform; a cancelled one never
    // went out. Saying "deleted" for both would hide the difference.
    return job.result?.deleted === true
      ? { label: "Deleted", cls: "bg-ink/[0.05] text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45" }
      : { label: "Cancelled", cls: "bg-ink/[0.05] text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45" };
  }
  if (QUEUED_STATUSES.has(job.status)) {
    return { label: job.scheduled_at ? "Scheduled" : "Queued", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-400" };
  }
  return { label: job.status, cls: "bg-ink/[0.05] text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45" };
}

export default function PublishedPosts({ onPublish }: { onPublish: (date?: string) => void }) {
  const { jobs, error, busy, refresh, displayName, removeJobs, cancelJob, deletableIds } = usePublishJobs();
  const { posts: legacyPosts, error: legacyError, refresh: refreshLegacy } = useLocationPosts();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [armDelete, setArmDelete] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const feedError = error ?? legacyError;

  const scheduledEntries = useMemo<ScheduledEntry[]>(() => {
    return (jobs ?? [])
      .filter((j) => j.scheduled_at)
      .map((j) => ({
        id: j.job_id,
        name: (j.caption ?? j.method ?? "post").toString().slice(0, 40),
        scheduledAt: j.scheduled_at as string,
        platform: j.platform ?? "Google Business Profile",
        thumbnailUrl: (j.media_url as string) ?? undefined,
      }));
  }, [jobs]);

  const list = useMemo<FeedEntry[]>(() => {
    const entries: FeedEntry[] = [];
    for (const job of jobs ?? []) {
      entries.push({ kind: "job", at: Date.parse(job.created_at) || 0, job });
    }
    for (const post of legacyPosts ?? []) {
      // When it went out: publish time; when waiting: schedule time.
      const at = Date.parse(post.published_at ?? post.scheduled_on ?? post.created_at) || 0;
      entries.push({ kind: "legacy", at, post });
    }
    return entries.sort((a, b) => b.at - a.at);
  }, [jobs, legacyPosts]);

  const toggle = (id: string) => {
    setArmDelete(false);
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectedDeletable = deletableIds.filter((id) => checked.has(id));

  const bulkDelete = async () => {
    if (selectedDeletable.length === 0) return;
    const res = await removeJobs(selectedDeletable);
    setNotice(
      res.error
        ? { kind: "err", text: res.error }
        : res.removed === 0
          ? { kind: "err", text: "None of the selected posts could be removed — they may already be gone." }
          : { kind: "ok", text: `${res.removed} post${res.removed === 1 ? "" : "s"} removed from the platform or cancelled.` },
    );
    setChecked(new Set());
    setArmDelete(false);
    setTimeout(() => setNotice(null), 6000);
  };

  const doCancel = async (job: PublishJob) => {
    const res = await cancelJob(job.job_id);
    setNotice(
      res.error
        ? { kind: "err", text: res.error }
        : { kind: "ok", text: "Scheduled post cancelled — it will never go out." },
    );
    setTimeout(() => setNotice(null), 6000);
  };

  return (
    <div className="flex h-full flex-col">
      {/* ── Header ── */}
      <div className="shrink-0 border-b border-ink/[0.06] bg-white px-6 py-4 dark:border-fog/[0.06] dark:bg-ink">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[19px] font-bold text-ink dark:text-fog">Posts &amp; media</h1>
            <p className="mt-0.5 max-w-xl text-[12px] text-ink/45 dark:text-fog/45">
              Every post you published — Instagram, Facebook, WhatsApp and Google.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onPublish()}
              className="flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5">
                <path d="M12 19V5" strokeLinecap="round" />
                <path d="M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Publish
            </button>
            <button
              type="button"
              onClick={() => {
                void refresh();
                void refreshLegacy();
              }}
              aria-label="Refresh posts"
              title="Refresh"
              className="flex h-9 w-9 items-center justify-center rounded-[2px] border border-ink/[0.08] text-ink/45 transition hover:bg-ink/[0.04] hover:text-ink focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:border-fog/[0.1] dark:text-fog/45"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
                <path d="M20 11a8 8 0 1 0-2.3 5.7" strokeLinecap="round" />
                <path d="M20 4v7h-7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {notice && (
        <div className="shrink-0 px-6 pt-3">
          <div className="mx-auto max-w-6xl">
            <p
              role={notice.kind === "err" ? "alert" : "status"}
              className={`rounded-[2px] border px-3 py-2 text-[12px] font-medium ${
                notice.kind === "err"
                  ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              }`}
            >
              {notice.text}
            </p>
          </div>
        </div>
      )}

      {/* ── Feed ── */}
      <div className="shrink-0 px-6 pt-4">
    <div className="mx-auto max-w-6xl">
      <ScheduledPostsCalendar items={scheduledEntries} onScheduleDate={onPublish} />
    </div>
  </div>

  <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-6xl">
          {jobs === null && legacyPosts === null && !feedError && (
            <div className="flex h-44 items-center justify-center"><LogoLoader size={28} /></div>
          )}
          {feedError && (
            <p role="alert" className="rounded-[2px] border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] font-medium text-red-700 dark:text-red-400">
              {feedError}
            </p>
          )}
          {jobs !== null && legacyPosts !== null && list.length === 0 && !feedError && (
            <div className="rounded-[2px] border border-dashed border-ink/[0.12] bg-white px-6 py-14 text-center dark:border-fog/[0.12] dark:bg-ink">
              <p className="text-[15px] font-bold text-ink dark:text-fog">Nothing published yet</p>
              <p className="mx-auto mt-1 max-w-sm text-[12px] leading-relaxed text-ink/40 dark:text-fog/40">
                Publish a post to every connected network at once — it lands here with its status.
              </p>
              <button
                type="button"
                onClick={() => onPublish()}
                className="mt-5 rounded-[2px] bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90"
              >
                Publish a post
              </button>
            </div>
          )}
          {list.length > 0 && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((entry) =>
                entry.kind === "job" ? (
                  <PostCard
                    key={entry.job.job_id}
                    job={entry.job}
                    destination={displayName(entry.job)}
                    checked={checked.has(entry.job.job_id)}
                    onToggle={() => toggle(entry.job.job_id)}
                    onCancel={() => void doCancel(entry.job)}
                    busy={busy}
                  />
                ) : (
                  <LegacyPostCard key={entry.post.id} post={entry.post} />
                ),
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Bulk removal bar ── */}
      {checked.size > 0 && (
        <div className="shrink-0 border-t border-ink/[0.06] bg-white px-6 py-3 dark:border-fog/[0.06] dark:bg-ink">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3">
            <p className="min-w-0 flex-1 text-[12px] font-medium text-ink/55 dark:text-fog/55">
              {selectedDeletable.length} selected · published posts are deleted from their platform, scheduled ones are cancelled.
            </p>
            <button
              type="button"
              onClick={() => {
                const next = new Set<string>();
                deletableIds.forEach((id) => next.add(id));
                setChecked(next);
              }}
              className="rounded-[2px] border border-ink/[0.1] px-3 py-1.5 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:border-fog/[0.12] dark:text-fog/60"
            >
              Select all removable
            </button>
            {selectedDeletable.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  if (!armDelete) {
                    setArmDelete(true);
                    return;
                  }
                  void bulkDelete();
                }}
                disabled={busy}
                className={`rounded-[2px] px-4 py-2 text-[13px] font-semibold text-white transition disabled:opacity-50 ${
                  armDelete ? "bg-[#FF4F6E]" : "bg-deep-violet hover:bg-deep-violet/90"
                }`}
              >
                {busy ? "Working…" : armDelete ? `Delete ${selectedDeletable.length} now` : "Delete from platforms"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function legacyChip(post: LocationPost): Chip {
  if (post.status === "published") return { label: "Published", cls: "bg-[#e7f8ef] text-[#0c7a43]" };
  if (post.status === "scheduled") return { label: "Scheduled", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-400" };
  if (post.status === "failed") return { label: "Failed", cls: "bg-red-500/10 text-red-700 dark:text-red-400" };
  if (post.status === "archived") return { label: "Archived", cls: "bg-ink/[0.05] text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45" };
  return { label: "Draft", cls: "bg-ink/[0.05] text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45" };
}

/** A Google post from the old per-branch flow. It never passed through the
 * publishing job queue, so it has no remove/cancel actions — Localith
 * exposes no delete API and the Google-side copy keeps its own lifecycle. */
function LegacyPostCard({ post }: { post: LocationPost }) {
  const chip = legacyChip(post);
  const text = post.title ? [post.title, post.description].filter(Boolean).join(" — ") : post.description;
  const hasMetrics = post.views !== null || post.cta_clicks !== null;
  const shownAt = post.published_at ?? post.created_at;

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-[2px] border border-ink/[0.06] bg-white text-left dark:border-fog/[0.07] dark:bg-ink">
      <div className="relative block aspect-video overflow-hidden bg-ink/[0.04] dark:bg-fog/[0.06]">
        <JobThumb url={post.image_urls[0] ?? null} platform="google_reviews" />
        <span className="absolute left-2 top-2 rounded-[2px] bg-white/90 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-deep-violet dark:bg-ink/85">
          Google
        </span>
        <span className={`absolute right-2 top-2 rounded-[2px] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${chip.cls}`}>
          {chip.label}
        </span>
      </div>
      <div className="flex flex-1 flex-col p-3.5">
        <span className="truncate text-[13px] font-bold text-ink dark:text-fog">
          {post.location_name || post.business_name || "Google Business Profile"}
        </span>
        {text && (
          <span className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">{text}</span>
        )}
        {post.status === "failed" && post.error && (
          <span className="mt-1 line-clamp-2 text-[11px] font-medium text-red-600 dark:text-red-400" title={post.error}>
            {post.error}
          </span>
        )}
        <span className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
          {post.status === "scheduled" && post.scheduled_on && (
            <span className="rounded-[2px] bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
              {new Date(post.scheduled_on).toLocaleDateString()}
            </span>
          )}
          {hasMetrics && (
            <span className="rounded-[2px] bg-ink/[0.05] px-2 py-0.5 text-[10px] font-semibold text-ink/50 dark:bg-fog/[0.07] dark:text-fog/50">
              {post.views ?? 0} views{post.cta_clicks ? ` · ${post.cta_clicks} clicks` : ""}
            </span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-ink/35 dark:text-fog/35">
            {new Date(shownAt).toLocaleDateString()}
          </span>
        </span>
      </div>
    </div>
  );
}

function PostCard({
  job,
  destination,
  checked,
  onToggle,
  onCancel,
  busy,
}: {
  job: PublishJob;
  destination: string;
  checked: boolean;
  onToggle: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const chip = statusChip(job);
  const platform = job.platform as PlatformKey | null;
  const meta = platform ? PLATFORM_META[platform] : null;
  const removable = isRemovableJob(job);
  const cancellable = QUEUED_STATUSES.has(job.status);
  // A post that has already come down has no future date to show.
  const alreadyGone = job.result?.deleted === true;

  return (
    <div className="group flex w-full flex-col overflow-hidden rounded-[2px] border border-ink/[0.06] bg-white text-left dark:border-fog/[0.07] dark:bg-ink">
      <div className="relative block aspect-video overflow-hidden bg-ink/[0.04] dark:bg-fog/[0.06]">
        <JobThumb url={job.media_url} platform={platform} />
        <span className="absolute left-2 top-2 rounded-[2px] bg-white/90 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-deep-violet dark:bg-ink/85">
          {meta?.label ?? "Post"}
        </span>
        <span className="absolute right-2 top-2 flex flex-col items-end gap-1">
          <span className={`rounded-[2px] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${chip.cls}`}>
            {chip.label}
          </span>
          {job.method && (
            <span className="rounded-[2px] bg-deep-violet/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-deep-violet">
              {METHOD_META[job.method].label}
            </span>
          )}
        </span>
      </div>
      <div className="flex flex-1 flex-col p-3.5">
        <span className="truncate text-[13px] font-bold text-ink dark:text-fog">{destination}</span>
        <span className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
          {job.caption || "No caption."}
        </span>
        {job.status === "failed" && job.last_error && (
          <span className="mt-1 line-clamp-2 text-[11px] font-medium text-red-600 dark:text-red-400" title={job.last_error}>
            {job.last_error}
          </span>
        )}
        <span className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
          {removable && (
            <label className="flex cursor-pointer items-center gap-1.5 rounded-[2px] bg-ink/[0.05] px-2 py-1 text-[10px] font-semibold text-ink/60 dark:bg-fog/[0.07] dark:text-fog/60">
              <input
                type="checkbox"
                checked={checked}
                onChange={onToggle}
                aria-label={`Select this post for removal (${meta?.label ?? "unknown platform"})`}
                className="h-3.5 w-3.5 accent-deep-violet"
              />
              Remove
            </label>
          )}
          {job.delete_at && !alreadyGone && (
            <span
              className="rounded-[2px] bg-ink/[0.05] px-2 py-0.5 text-[10px] font-semibold text-ink/50 dark:bg-fog/[0.07] dark:text-fog/50"
              title={`Removed automatically on ${new Date(job.delete_at).toLocaleString()}`}
            >
              Comes down {new Date(job.delete_at).toLocaleDateString()}
            </span>
          )}
          {job.scheduled_at && (
            <span className="rounded-[2px] bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
              {new Date(job.scheduled_at).toLocaleDateString()}
            </span>
          )}
          {cancellable && (
            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              className="rounded-[2px] border border-ink/[0.1] px-2 py-0.5 text-[10px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:border-fog/[0.12] dark:text-fog/60"
            >
              Cancel
            </button>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-ink/35 dark:text-fog/35">
            {new Date(job.created_at).toLocaleDateString()}
          </span>
        </span>
      </div>
    </div>
  );
}

/** The post's own media, with the platform mark as fallback: a media URL
 * that 404s (deleted at the provider, expired storage link) must not leave
 * a broken-image glyph in the feed. */
function JobThumb({ url, platform }: { url?: string | null; platform: PlatformKey | null }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <span className="grid h-full w-full place-items-center text-ink/15 dark:text-fog/15">
        {platform === "google_reviews" ? <GoogleBusinessLogo size={28} /> : platform ? <PlatformMark platform={platform} size={28} /> : null}
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- provider + storage hosts (no next.config allowlist)
    <img
      src={url}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
    />
  );
}
