"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "./api-rag";
import { fetchPublishTargets } from "./publish-targets";
import type { PlatformKey, PostMethod } from "@/components/dashboard/publish/types";

/*
 * The publish jobs behind the posts feed: one row per destination+format of
 * one push, newest first. The feed renders them as cards next to the Google
 * posts and media library, so the same fetch serves both the cards and the
 * "remove from platform" actions.
 *
 * Polls every 15s while mounted (the publishing worker moves rows through
 * queued → running → succeeded) and re-reads on demand after a publish.
 */

export interface PublishJob {
  job_id: string;
  status: string;
  platform: PlatformKey | null;
  method: PostMethod | null;
  external_asset_id: string | null;
  created_at: string;
  updated_at: string | null;
  scheduled_at: string | null;
  last_error: string | null;
  result: Record<string, unknown> | null;
  batch_id?: string | null;
  caption?: string | null;
  description?: string | null;
  media_url?: string | null;
  cta_type?: string | null;
  cta_url?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  /** When the post is due to be taken down again (a promotional post
   * with an end date). */
  delete_at?: string | null;
}

/** Rows a delete/cancel can still act on: everything not mid-flight and not
 * already gone. A running row is left alone — deleting a post the worker is
 * uploading right now races the publish call itself. */
export const DELETABLE_STATUSES = new Set(["succeeded", "accepted", "queued", "retrying", "blocked"]);
/** Rows that have not gone out yet — these get cancelled, never deleted. */
export const QUEUED_STATUSES = new Set(["accepted", "queued", "retrying", "blocked"]);

/** Terminal rows that never produced a platform artifact. They can be
 *  dismissed from the feed even for account surfaces (profile/banner),
 *  because there is nothing on the platform to remove. */
export const TERMINAL_STATUSES = new Set(["failed", "dead", "cancelled"]);

/**
 * Only in-flight work is left alone — deleting a post the worker is
 * uploading right now races the publish call itself. Everything else
 * (including a published profile picture or banner) can be dismissed from
 * the feed: account surfaces can't be removed from Google, but their feed
 * row is just a record, so removing it never touches the platform.
 */
export function isRemovableJob(job: Pick<PublishJob, "status" | "method">): boolean {
  if (job.status === "running") return false;
  return DELETABLE_STATUSES.has(job.status) || TERMINAL_STATUSES.has(job.status);
}

export function usePublishJobs() {
  const [jobs, setJobs] = useState<PublishJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setError(null);
    try {
      const rows = (await apiFetch("/api/v1/channels/publish?limit=50")) as PublishJob[];
      if (!mounted.current) return;
      setJobs(Array.isArray(rows) ? rows : []);
    } catch (e) {
      if (!mounted.current) return;
      if (!silent) setError(e instanceof Error ? e.message : "Could not load the published posts.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void refresh();
  }, [refresh]);

  // The worker moves rows between states after the page is already open.
  useEffect(() => {
    const id = setInterval(() => void refresh(true), 15000);
    return () => clearInterval(id);
  }, [refresh]);

  // Destination display names from the same source the composer uses, so a
  // raw asset id renders as the business name.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const set = await fetchPublishTargets();
      if (cancelled) return;
      const byAsset = new Map<string, string>();
      [...set.social, ...set.google].forEach((t) => {
        // A Google job names its branch by location id. The target row is
        // keyed by the channel id, so Google targets are indexed by location.
        const raw =
          t.platform === "google_reviews"
            ? (t.locationId ?? null)
            : t.id.includes(":")
              ? t.id.slice(t.id.indexOf(":") + 1)
              : null;
        if (raw) byAsset.set(`${t.platform}:${raw}`, t.name);
      });
      setNames(byAsset);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const displayName = useCallback(
    (job: PublishJob) => {
      const raw = job.external_asset_id ?? "";
      return names.get(`${job.platform}:${raw}`) ?? (raw ? raw.slice(0, 20) : "—");
    },
    [names],
  );

  /** Delete published posts from their platforms (or cancel the ones that
   * never went out). Best-effort per job: the server reports what it did, and
   * a platform refusal comes back marked with the reason instead of counting
   * as removed. */
  const removeJobs = useCallback(
    async (jobIds: string[]) => {
      if (jobIds.length === 0) return { removed: 0, failed: 0, error: null as string | null };
      setBusy(true);
      try {
        const updated = (await apiFetch("/api/v1/channels/publish/delete", {
          method: "POST",
          body: JSON.stringify({ job_ids: jobIds }),
        })) as PublishJob[];
        // Terminal rows are hard-deleted server-side. Re-read the list
        // instead of patching in place, so dismissed cards disappear now.
        await refresh(true);
        const failed = updated.filter(
          (row) => typeof row.result?.delete_error === "string",
        ).length;
        return {
          removed: updated.filter(
            (row) => row.status === "cancelled" && !row.result?.delete_error,
          ).length,
          failed,
          error: null as string | null,
        };
      } catch (e) {
        return { removed: 0, failed: 0, error: e instanceof Error ? e.message : "Removing the posts failed." };
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  /** Cancel a scheduled post before the worker sends it. */
  const cancelJob = useCallback(async (jobId: string) => {
    setBusy(true);
    try {
      const u = (await apiFetch(`/api/v1/channels/publish/${jobId}/cancel`, { method: "POST" })) as PublishJob;
      setJobs((prev) => (prev ?? []).map((j) => (j.job_id === u.job_id ? { ...j, status: u.status } : j)));
      return { ok: true as const, error: null as string | null };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : "Cancelling failed." };
    } finally {
      setBusy(false);
    }
  }, []);

  const deletableIds = useMemo(
    () => (jobs ?? []).filter(isRemovableJob).map((j) => j.job_id),
    [jobs],
  );

  return { jobs, error, busy, refresh, displayName, removeJobs, cancelJob, deletableIds };
}
