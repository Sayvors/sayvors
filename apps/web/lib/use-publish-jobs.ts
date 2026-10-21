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
  media_url?: string | null;
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

/**
 * Rows that publish an account surface instead of a post. A profile picture
 * or banner cannot be removed from the platform — it can only be replaced
 * by publishing a new one — so these never offer a Remove action.
 */
const ACCOUNT_SURFACE_METHODS = new Set<PostMethod>(["profile", "banner"]);

export function isRemovableJob(job: Pick<PublishJob, "status" | "method">): boolean {
  if (job.method && ACCOUNT_SURFACE_METHODS.has(job.method)) return false;
  return DELETABLE_STATUSES.has(job.status);
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
        const idx = t.id.indexOf(":");
        if (idx !== -1) byAsset.set(`${t.platform}:${t.id.slice(idx + 1)}`, t.name);
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
   * never went out). Best-effort per job: the server reports what it did. */
  const removeJobs = useCallback(
    async (jobIds: string[]) => {
      if (jobIds.length === 0) return { removed: 0, error: null as string | null };
      setBusy(true);
      try {
        const updated = (await apiFetch("/api/v1/channels/publish/delete", {
          method: "POST",
          body: JSON.stringify({ job_ids: jobIds }),
        })) as PublishJob[];
        setJobs((prev) =>
          (prev ?? []).map((j) => {
            const u = updated.find((x) => x.job_id === j.job_id);
            return u ? { ...j, status: u.status, result: u.result ?? j.result, last_error: u.last_error } : j;
          }),
        );
        return { removed: updated.length, error: null as string | null };
      } catch (e) {
        return { removed: 0, error: e instanceof Error ? e.message : "Removing the posts failed." };
      } finally {
        setBusy(false);
      }
    },
    [],
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
