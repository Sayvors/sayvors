"use client";

import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api-rag";
import { fetchPublishTargets } from "./publish-targets";
import { queryKeys } from "./query-keys";
import type { PlatformKey, PostMethod } from "@/components/dashboard/publish/types";

/*
 * Publish jobs feed: one row per destination+format of one push, newest first.
 * Uses TanStack Query for shared caching, dedupe, and background refresh.
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
  /** When the post is due to be taken down again (a promotional post with an end date). */
  delete_at?: string | null;
}

/** Rows a delete/cancel can still act on. */
export const DELETABLE_STATUSES = new Set(["succeeded", "accepted", "queued", "retrying", "blocked"]);
/** Rows that have not gone out yet — these get cancelled, never deleted. */
export const QUEUED_STATUSES = new Set(["accepted", "queued", "retrying", "blocked"]);
/** Terminal rows that never produced a platform artifact. */
export const TERMINAL_STATUSES = new Set(["failed", "dead", "cancelled"]);
const ACTIVE_STATUSES = new Set(["accepted", "queued", "running", "retrying", "blocked"]);

/** Only in-flight work is left alone; everything else can be dismissed/removed. */
export function isRemovableJob(job: Pick<PublishJob, "status" | "method">): boolean {
  if (job.status === "running") return false;
  return DELETABLE_STATUSES.has(job.status) || TERMINAL_STATUSES.has(job.status);
}

export function usePublishJobs() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const jobsQuery = useQuery({
    queryKey: queryKeys.posts.publishJobs(50),
    queryFn: async () => (await apiFetch("/api/v1/channels/publish?limit=50")) as PublishJob[],
    staleTime: 15_000,
    refetchInterval: (query) => {
      const rows = (query.state.data as PublishJob[] | undefined) ?? [];
      return rows.some((j) => ACTIVE_STATUSES.has(j.status)) ? 15_000 : 60_000;
    },
  });

  const targetsQuery = useQuery({
    queryKey: queryKeys.posts.publishTargets(),
    queryFn: fetchPublishTargets,
    staleTime: 5 * 60_000,
  });

  const jobs = jobsQuery.data ?? null;
  const error = jobsQuery.error instanceof Error ? jobsQuery.error.message : jobsQuery.error ? "Could not load the published posts." : null;

  const names = useMemo(() => {
    const byAsset = new Map<string, string>();
    const set = targetsQuery.data;
    if (!set) return byAsset;
    [...set.social, ...set.google].forEach((t) => {
      const raw =
        t.platform === "google_reviews"
          ? (t.locationId ?? null)
          : t.id.includes(":")
            ? t.id.slice(t.id.indexOf(":") + 1)
            : null;
      if (raw) byAsset.set(`${t.platform}:${raw}`, t.name);
    });
    return byAsset;
  }, [targetsQuery.data]);

  const refresh = useCallback(async (_silent = false) => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.posts.publishJobs(50) });
  }, [queryClient]);

  const displayName = useCallback(
    (job: PublishJob) => {
      const raw = job.external_asset_id ?? "";
      return names.get(`${job.platform}:${raw}`) ?? (raw ? raw.slice(0, 20) : "—");
    },
    [names],
  );

  /** Queue background removal/cancellation for published posts. */
  const removeJobs = useCallback(
    async (jobIds: string[]) => {
      if (jobIds.length === 0) return { removed: 0, failed: 0, queued: false, jobId: null as string | null, error: null as string | null };
      setBusy(true);
      try {
        const res = (await apiFetch("/api/v1/channels/publish/delete/background", {
          method: "POST",
          body: JSON.stringify({ job_ids: jobIds }),
        })) as { job_id?: string; status?: string };
        await refresh(true);
        return { removed: 0, failed: 0, queued: true, jobId: res.job_id ?? null, error: null as string | null };
      } catch (e) {
        return { removed: 0, failed: 0, queued: false, jobId: null as string | null, error: e instanceof Error ? e.message : "Removing the posts failed." };
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
      await apiFetch(`/api/v1/channels/publish/${jobId}/cancel`, { method: "POST" });
      await refresh(true);
      return { ok: true as const, error: null as string | null };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : "Cancelling failed." };
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const deletableIds = useMemo(
    () => (jobs ?? []).filter(isRemovableJob).map((j) => j.job_id),
    [jobs],
  );

  return { jobs, error, busy, refresh, displayName, removeJobs, cancelJob, deletableIds };
}