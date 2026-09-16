"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api-rag";
import { approveReply, fetchInsights, fetchOverview, fetchTimeseries, regenerateReply, retryReply, type Overview, type ReviewReplyDTO, type TimeseriesPoint } from "@/lib/api-analytics";
import { useI18n } from "@/lib/i18n/I18nProvider";
import Greeting from "@/components/dashboard/Greeting";
import { MetricChart, RatingDistribution, Sparkline } from "@/components/analytics/Charts";

const checklistDefs = [
  { id: "channel", labelKey: "stepConnect", href: "/dashboard/channels" },
  { id: "databank", labelKey: "stepDatabank", href: "/dashboard/databank" },
  { id: "auto-reply", labelKey: "stepAutoReply", href: "/dashboard/automations" },
] as const;

const CHECKLIST_KEY = "sayvors.onboarding.checklist";

type DashboardChannel = { id: string; platform: string; display_name: string | null };
type DashboardService = { is_offered: boolean };

interface AttentionItem {
  severity: "high" | "medium";
  title: string;
  detail: string;
  href: string;
}

/** One row per review — newest draft wins (the backend may hold older duplicates). */
function dedupeDraftsByReview(list: ReviewReplyDTO[]): ReviewReplyDTO[] {
  const seen = new Map<string, ReviewReplyDTO>();
  for (const d of list) {
    const prev = seen.get(d.review_id);
    if (!prev || d.created_at > prev.created_at) seen.set(d.review_id, d);
  }
  return [...seen.values()];
}

function AttentionQueue() {
  const [items, setItems] = useState<AttentionItem[] | null>(null);
  const [drafts, setDrafts] = useState<ReviewReplyDTO[]>([]);
  const [draftTotal, setDraftTotal] = useState(0);
  const [channelIds, setChannelIds] = useState<string[]>([]);
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});
  const [draftsOpen, setDraftsOpen] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [enginingId, setEnginingId] = useState<string | null>(null);
  const [approvingAll, setApprovingAll] = useState(false);
  const [approveProgress, setApproveProgress] = useState({ done: 0, total: 0 });
  const [draftError, setDraftError] = useState<string | null>(null);
  const [failed, setFailed] = useState<ReviewReplyDTO[]>([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedOpen, setFailedOpen] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [remakingAll, setRemakingAll] = useState(false);
  const [remakeProgress, setRemakeProgress] = useState({ done: 0, total: 0 });
  const [failedError, setFailedError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<{ channel_id: string; review_id: string; rating: number; review_text: string | null; reviewer_name: string | null }[]>([]);
  const [flaggedTotal, setFlaggedTotal] = useState(0);
  const [flaggedOpen, setFlaggedOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const found: AttentionItem[] = [];
      try {
        const [overview, profile, channelData] = await Promise.all([
          fetchOverview(30, null).catch(() => null),
          apiFetch("/api/v1/integrations/localith/profile").catch(() => null),
          apiFetch("/api/v1/channels/?limit=100").catch(() => null),
        ]);
        const googleChannels = (channelData?.channels ?? []).filter(
          (c: { platform: string }) => c.platform === "google_reviews"
        );
        if (!cancelled) setChannelIds(googleChannels.map((c: { id: string }) => c.id));
        const names: Record<string, string> = {};
        for (const ch of channelData?.channels ?? []) {
          if (ch?.id) names[ch.id] = ch.display_name ?? "Google location";
        }
        if (!cancelled) setChannelNames(names);
        let pendingTotal = 0;
        const pendingLists: ReviewReplyDTO[][] = await Promise.all(
          googleChannels.map(async (c: { id: string }) => {
            try {
              const r = await apiFetch(`/api/v1/channels/${c.id}/reviews?status=pending_approval&limit=5`);
              pendingTotal += r.pending ?? 0;
              return (r.replies ?? []) as ReviewReplyDTO[];
            } catch {
              /* channel counted as zero when its queue can't load */
              return [];
            }
          })
        );
        if (!cancelled && pendingTotal > 0) {
          setDraftTotal(pendingTotal);
          setDrafts(dedupeDraftsByReview(pendingLists.flat()).slice(0, 5));
        }
        await Promise.all(
          googleChannels.map(async (c: { id: string }) => {
            try {
              const r = await apiFetch(`/api/v1/channels/${c.id}/reviews?status=failed&limit=100`);
              return (r.replies ?? []) as ReviewReplyDTO[];
            } catch {
              /* channel counted as zero when its queue can't load */
              return [];
            }
          })
         ).then((failedLists) => {
           if (cancelled) return;
           const uniqueFailed = dedupeDraftsByReview(failedLists.flat());
           setFailedTotal(uniqueFailed.length);
           setFailed(uniqueFailed.slice(0, 5));
         });
         try {
           const data = await apiFetch("/api/v1/analytics/reviews/insights?status=skipped&limit=20");
           if (!cancelled) {
             const total = data.total ?? 0;
             setFlaggedTotal(total);
             setFlagged((data.items ?? []).map((it: { channel_id: string; review_id: string; rating: number; review_text: string | null; reviewer_name: string | null }) => ({
               channel_id: it.channel_id,
               review_id: it.review_id,
               rating: it.rating,
               review_text: it.review_text,
               reviewer_name: it.reviewer_name,
             })));
           }
         } catch {
           /* flagged section hidden on error */
         }
         const delta = overview?.period.rating_delta;
        if (typeof delta === "number" && delta < 0) {
          found.push({
            severity: "high",
            title: `Rating dipped ${Math.abs(delta)}★ this month`,
            detail: "Check what changed and respond fast",
            href: "/dashboard/reviews",
          });
        }
        const conn = profile?.connection;
        if (conn && !conn.phone_number) {
          found.push({
            severity: "medium",
            title: "No phone number on your profile",
            detail: "Customers can't call you from Google",
            href: "/dashboard/locations?tab=details",
          });
        }
        if (conn && !(conn.website_url || "").trim()) {
          found.push({
            severity: "medium",
            title: "No website linked",
            detail: "Add one to turn views into visits",
            href: "/dashboard/locations?tab=details",
          });
        }
      } catch {
        /* offline — card stays hidden */
      }
      if (!cancelled) setItems(found.slice(0, 3));
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function approveDraft(channelId: string, replyId: string) {
    setApprovingId(replyId);
    setDraftError(null);
    try {
      await approveReply(channelId, replyId);
      setDrafts((prev) => prev.filter((d) => d.id !== replyId));
      setDraftTotal((t) => Math.max(0, t - 1));
    } catch (e) {
      // apiFetch throws the raw response body — extract the server's detail
      // (e.g. "Failed to post reply to Google: No refresh token available").
      let msg = "Could not publish that reply. Try again.";
      if (e instanceof Error) {
        try {
          const parsed = JSON.parse(e.message) as { detail?: unknown };
          if (typeof parsed.detail === "string") msg = parsed.detail;
        } catch {
          /* not JSON — keep the generic message */
        }
      }
      setDraftError(msg);
    } finally {
      setApprovingId(null);
    }
  }

  async function engineRedraft(d: ReviewReplyDTO) {
    if (enginingId !== null) return;
    setEnginingId(d.id);
    setDraftError(null);
    try {
      const fresh = await regenerateReply(d.channel_id, d.id, true);
      setDrafts((prev) => prev.map((x) => (x.id === d.id ? { ...x, reply_text: fresh.reply_text, generation_attempt: fresh.generation_attempt ?? (x.generation_attempt ?? 1) + 1 } : x)));
    } catch (e) {
      // apiFetch throws the raw response body — extract the server's detail
      // (e.g. "Engine generation failed: 403 Access denied").
      let msg = "Engine rewrite failed. Try again.";
      if (e instanceof Error) {
        try {
          const parsed = JSON.parse(e.message) as { detail?: unknown };
          if (typeof parsed.detail === "string") msg = parsed.detail;
        } catch {
          /* not JSON — keep the generic message */
        }
      }
      setDraftError(msg);
    } finally {
      setEnginingId(null);
    }
  }

  async function approveAll() {
    if (approvingAll || approvingId !== null || enginingId !== null) return;
    setApprovingAll(true);
    setDraftError(null);
    try {
      const lists = await Promise.all(
        channelIds.map(async (id) => {
          try {
            const r = await apiFetch(`/api/v1/channels/${id}/reviews?status=pending_approval&limit=100`);
            return (r.replies ?? []) as ReviewReplyDTO[];
          } catch {
            return [];
          }
        })
      );
      const all = dedupeDraftsByReview(lists.flat());
      setApproveProgress({ done: 0, total: all.length });
      let ok = 0;
      const failed: string[] = [];
      for (const d of all) {
        try {
          await approveReply(d.channel_id, d.id);
          ok += 1;
        } catch {
          failed.push(d.id);
        }
        setApproveProgress({ done: ok + failed.length, total: all.length });
      }
      setDrafts((prev) => prev.filter((d) => failed.includes(d.id)));
      setDraftTotal((t) => Math.max(0, t - ok));
      if (failed.length > 0) {
        setDraftError(`Published ${ok} of ${all.length}. ${failed.length} failed — try again.`);
      }
    } catch {
      setDraftError("Could not publish. Try again.");
    } finally {
      setApprovingAll(false);
      setApproveProgress({ done: 0, total: 0 });
    }
  }

  async function remakeDraft(d: ReviewReplyDTO) {
    if (generatingId !== null || remakingAll) return;
    // A live draft already covers this review — drop the stale failed row.
    if (drafts.some((x) => x.review_id === d.review_id)) {
      setFailed((prev) => prev.filter((x) => x.id !== d.id));
      setFailedTotal((t) => Math.max(0, t - 1));
      return;
    }
    setGeneratingId(d.id);
    setFailedError(null);
    try {
      // Backend retry regenerates the text when generation failed, or
      // simply returns the row to the approval queue when publishing failed.
      const fresh = await retryReply(d.channel_id, d.id);
      setFailed((prev) => prev.filter((x) => x.id !== d.id));
      setFailedTotal((t) => Math.max(0, t - 1));
      setDrafts((prev) => dedupeDraftsByReview([...prev, fresh]).slice(0, 5));
      setDraftTotal((t) => t + 1);
    } catch {
      setFailedError("Retry failed. Check the error and try again.");
    } finally {
      setGeneratingId(null);
    }
  }

  async function remakeAll() {
    if (remakingAll || generatingId !== null) return;
    setRemakingAll(true);
    setFailedError(null);
    try {
      const lists = await Promise.all(
        channelIds.map(async (id) => {
          try {
            const r = await apiFetch(`/api/v1/channels/${id}/reviews?status=failed&limit=100`);
            return (r.replies ?? []) as ReviewReplyDTO[];
          } catch {
            return [];
          }
        })
      );
      const targets = dedupeDraftsByReview(lists.flat()).filter(
        (d) => !drafts.some((x) => x.review_id === d.review_id)
      );
      setRemakeProgress({ done: 0, total: targets.length });
      const freshOnes: ReviewReplyDTO[] = [];
      const stillFailed: ReviewReplyDTO[] = [];
      for (const d of targets) {
        try {
          const f = await retryReply(d.channel_id, d.id);
          freshOnes.push(f);
        } catch {
          stillFailed.push(d);
        }
        setRemakeProgress({ done: freshOnes.length + stillFailed.length, total: targets.length });
      }
      if (freshOnes.length > 0) {
        setDrafts((prev) => dedupeDraftsByReview([...prev, ...freshOnes]).slice(0, 5));
        setDraftTotal((t) => t + freshOnes.length);
      }
      // Refresh the failed list fresh — rows covered by live drafts stay hidden.
      const covered = new Set(freshOnes.map((f) => f.review_id));
      const remaining = dedupeDraftsByReview(stillFailed).filter((d) => !covered.has(d.review_id));
      setFailed(remaining.slice(0, 5));
      setFailedTotal(remaining.length);
      if (stillFailed.length > 0) {
        setFailedError(`${stillFailed.length} could not be retried. Try again.`);
      }
    } catch {
      setFailedError("Could not retry the drafts. Try again.");
    } finally {
      setRemakingAll(false);
      setRemakeProgress({ done: 0, total: 0 });
    }
  }

  if (items === null) return null;
   const showDrafts = draftTotal > 0;
   const showFailed = failedTotal > 0;
   const showFlagged = flaggedTotal > 0;
   const allClear = !showDrafts && !showFailed && !showFlagged && items.length === 0;
   const draftTitle =
     draftTotal === 1 ? "1 drafted reply needs your approval" : `${draftTotal} drafted replies across all locations need your approval`;
   const failedTitle =
     failedTotal === 1 ? "1 reply failed to publish" : `${failedTotal} replies failed to publish`;
   // Token-flavored failures genuinely need a Google re-consent; anything
   // else (API hiccups, transient errors) just needs a retry.
   const needsReconnect = failed.some((d) =>
     /refresh token|access token|invalid_grant|expired|auth|401|permission/i.test(d.error ?? "")
   );
    const flaggedTitle =
      flaggedTotal === 1 ? "1 review marked unavailable" : `${flaggedTotal} reviews marked unavailable on Google`;
   return (
    <section
      aria-label="Needs attention"
      className={`rounded-2xl border-2 bg-white/80 p-4 backdrop-blur-sm ${allClear ? "border-emerald-200/60" : "border-white"}`}
    >
      <div className="mb-2 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${allClear ? "bg-emerald-500" : "bg-coral"}`} aria-hidden />
        <h2 className="text-[14px] font-bold text-ink">{allClear ? "All clear" : "Needs attention"}</h2>
        {allClear && <span className="text-[12px] text-ink/45">nothing urgent right now</span>}
      </div>
      {!allClear && (
        <ul className="divide-y divide-ink/[0.05]">
          {showDrafts && (
            <li>
              <button
                onClick={() => setDraftsOpen((o) => !o)}
                aria-expanded={draftsOpen}
                aria-controls="attention-drafts-body"
                className="group flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink">{draftTitle}</span>
                  <span className="block truncate text-[11px] text-ink/45">Check them and publish to Google</span>
                </span>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3.5 w-3.5 shrink-0 text-ink/25 transition group-hover:text-deep-violet ${draftsOpen ? "rotate-180" : ""}`}>
                  <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {draftsOpen && (
                <div id="attention-drafts-body" className="space-y-2 px-2 pb-3 pt-1">
                  {draftError && (
                    <p className="rounded-lg bg-coral/10 px-3 py-2 text-[11px] font-medium text-coral">{draftError}</p>
                  )}
                   {drafts.map((d) => {
                     const busy = approvingId === d.id;
                     const locName = channelNames[d.channel_id] ?? "Location";
                     return (
                       <div key={d.id} className="rounded-xl border border-ink/[0.06] bg-white p-3">
                         <div className="flex items-center gap-1.5 text-[11px] text-ink/50">
                           <span aria-label={`${d.rating} out of 5 stars`} className="font-bold text-amber-600">{"★".repeat(Math.max(0, Math.min(5, d.rating)))}</span>
                           <span className="truncate font-semibold text-ink">{d.reviewer_name ?? "Anonymous"}</span>
                           <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-medium text-ink/50">{locName}</span>
                         </div>
                        {d.review_text && (
                          <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/60">“{d.review_text}”</p>
                        )}
                        <div className="mt-2 rounded-lg bg-deep-violet/[0.05] p-2.5">
                          <p className="text-[9px] font-bold uppercase tracking-wide text-deep-violet/60">
                            AI draft{(d.generation_attempt ?? 1) > 1 ? ` · try #${d.generation_attempt}` : ""}
                          </p>
                          <p className="mt-0.5 line-clamp-3 text-[12px] leading-relaxed text-ink/80">{d.reply_text}</p>
                        </div>
                        <div className="mt-2 flex items-center justify-end gap-2">
                          <button
                            onClick={() => void engineRedraft(d)}
                            disabled={enginingId !== null || approvingId !== null || approvingAll}
                            title="Re-run the full AI pipeline: analysis, strategies, databank tools, validation"
                            className="inline-flex items-center gap-1 rounded-lg bg-deep-violet/[0.08] px-3 py-1.5 text-[11px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.15] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                          >
                            {enginingId === d.id ? (
                              <><span className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/30 border-t-deep-violet" /> Engine…</>
                            ) : (
                              <>
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3" aria-hidden>
                                  <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                                Didn't like it? Rewrite
                              </>
                            )}
                          </button>
                          <button
                            onClick={() => void approveDraft(d.channel_id, d.id)}
                            disabled={approvingId !== null || approvingAll || enginingId !== null}
                            className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                          >
                            {busy ? "Publishing…" : "Approve & publish"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  {draftTotal > drafts.length && (
                    <Link
                      href="/dashboard/analytics"
                      className="flex items-center justify-center gap-1 rounded-xl bg-deep-violet/[0.06] px-3 py-2.5 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.1] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                    >
                      See all {draftTotal} and approve
                      <span aria-hidden> →</span>
                    </Link>
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={() => void approveAll()}
                      disabled={approvingAll || approvingId !== null || enginingId !== null || draftTotal === 0}
                      className="flex-1 rounded-xl bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.99] disabled:opacity-50"
                    >
                       {approvingAll
                         ? `Publishing ${approveProgress.done} of ${approveProgress.total} across all locations…`
                         : `Approve & publish all across all locations (${draftTotal})`}
                     </button>
<Link
                       href="/dashboard/reviews?tab=need_approval"
                       className="relative flex items-center justify-center gap-1 rounded-xl bg-deep-violet/[0.06] px-3 py-2.5 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.1] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                     >
                       Visit all reviews
                       <span aria-hidden> →</span>
                       {draftTotal > 0 && (
                         <span aria-hidden className="absolute -right-1 -top-1 flex h-3 w-3">
                           <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-coral opacity-60" />
                           <span className="relative inline-flex h-3 w-3 rounded-full bg-coral ring-2 ring-white" />
                         </span>
                       )}
                     </Link>
                  </div>
                </div>
              )}
            </li>
          )}
          {showFailed && (
            <li>
              <button
                onClick={() => setFailedOpen((o) => !o)}
                aria-expanded={failedOpen}
                aria-controls="attention-failed-body"
                className="group flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink">{failedTitle}</span>
                  <span className="block truncate text-[11px] text-ink/45">
                    {needsReconnect
                      ? "Google access expired — reconnect, then make new drafts"
                      : "Publishing failed — make new drafts and try again"}
                  </span>
                </span>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3.5 w-3.5 shrink-0 text-ink/25 transition group-hover:text-deep-violet ${failedOpen ? "rotate-180" : ""}`}>
                  <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {failedOpen && (
                <div id="attention-failed-body" className="space-y-2 px-2 pb-3 pt-1">
                  {failedError && (
                    <p className="rounded-lg bg-coral/10 px-3 py-2 text-[11px] font-medium text-coral">{failedError}</p>
                  )}
                   {failed.map((d) => {
                     const busy = generatingId === d.id;
                     const locName = channelNames[d.channel_id] ?? "Location";
                     return (
                       <div key={d.id} className="rounded-xl border border-ink/[0.06] bg-white p-3">
                         <div className="flex items-center gap-1.5 text-[11px] text-ink/50">
                           <span aria-label={`${d.rating} out of 5 stars`} className="font-bold text-amber-600">{"★".repeat(Math.max(0, Math.min(5, d.rating)))}</span>
                           <span className="truncate font-semibold text-ink">{d.reviewer_name ?? "Anonymous"}</span>
                           <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-medium text-ink/50">{locName}</span>
                         </div>
                        {d.review_text && (
                          <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/60">“{d.review_text}”</p>
                        )}
                        <div className="mt-2 rounded-lg bg-ink/[0.03] p-2.5">
                          <p className="text-[9px] font-bold uppercase tracking-wide text-ink/40">
                            Failed draft{(d.generation_attempt ?? 1) > 1 ? ` · try #${d.generation_attempt}` : ""}
                          </p>
                          <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-ink/60">{d.reply_text || "—"}</p>
                        </div>
                        {d.error && (
                          <p className="mt-1.5 rounded-lg bg-coral/10 px-2.5 py-1.5 text-[11px] font-medium leading-relaxed text-coral">
                            {d.error}
                          </p>
                        )}
                        <div className="mt-2 flex items-center justify-end">
                          <button
                            onClick={() => void remakeDraft(d)}
                            disabled={generatingId !== null || remakingAll}
                            className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                          >
                            {busy ? "Retrying…" : d.reply_text ? "Retry publishing" : "Retry AI drafting"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  <div className="flex gap-2">
                    <Link
                      href="/dashboard/outbox"
                      className="flex flex-1 items-center justify-center gap-1 rounded-xl bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                    >
                      Open outbox
                      <span aria-hidden> →</span>
                    </Link>
                    <Link
                      href="/dashboard/channels"
                      className="flex flex-1 items-center justify-center gap-1 rounded-xl bg-ink/[0.04] px-3 py-2.5 text-[12px] font-bold text-ink/60 outline-none transition hover:bg-ink/[0.07] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                    >
                      {needsReconnect ? "Reconnect Google" : "Manage connection"}
                      <span aria-hidden> →</span>
                    </Link>
                  </div>
                  <button
                    onClick={() => void remakeAll()}
                    disabled={remakingAll || generatingId !== null || failedTotal === 0}
                    className="w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.99] disabled:opacity-50"
                  >
                    {remakingAll
                      ? `Retrying ${remakeProgress.done} of ${remakeProgress.total}…`
                      : `Retry all (${failedTotal})`}
                  </button>
                </div>
              )}
             </li>
           )}
           {showFlagged && (
             <li>
               <button
                 onClick={() => setFlaggedOpen((o) => !o)}
                 aria-expanded={flaggedOpen}
                 aria-controls="attention-flagged-body"
                 className="group flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
               >
                 <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                 <span className="min-w-0 flex-1">
                   <span className="block truncate text-[13px] font-semibold text-ink">{flaggedTitle}</span>
                   <span className="block truncate text-[11px] text-ink/45">Marked unavailable — no AI draft needed</span>
                 </span>
                 <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3.5 w-3.5 shrink-0 text-ink/25 transition group-hover:text-deep-violet ${flaggedOpen ? "rotate-180" : ""}`}>
                   <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                 </svg>
               </button>
               {flaggedOpen && (
                 <div id="attention-flagged-body" className="space-y-2 px-2 pb-3 pt-1">
                   {flagged.map((d) => {
                     const locName = channelNames[d.channel_id] ?? "Location";
                     return (
                       <div key={d.review_id} className="rounded-xl border border-ink/[0.06] bg-white p-3">
                         <div className="flex items-center gap-1.5 text-[11px] text-ink/50">
                           <span aria-label={`${d.rating} out of 5 stars`} className="font-bold text-amber-600">{"★".repeat(Math.max(0, Math.min(5, d.rating)))}</span>
                           <span className="truncate font-semibold text-ink">{d.reviewer_name ?? "Anonymous"}</span>
                           <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-medium text-ink/50">{locName}</span>
                         </div>
                         {d.review_text && (
                           <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/60">"{d.review_text}"</p>
                         )}
                         <div className="mt-2 flex items-center justify-between">
                           <span className="text-[10px] font-bold uppercase tracking-wide text-amber-600/60">Unavailable on Google</span>
                           <Link href="/dashboard/reviews?tab=flagged" className="text-[11px] font-bold text-deep-violet underline underline-offset-2 hover:text-deep-violet/80">View all flagged →</Link>
                         </div>
                       </div>
                     );
                   })}
                   <Link href="/dashboard/reviews?tab=flagged" className="flex items-center justify-center gap-1 rounded-xl bg-ink/[0.04] px-3 py-2.5 text-[12px] font-bold text-ink/60 outline-none transition hover:bg-ink/[0.07] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
                     See all {flaggedTotal} flagged reviews <span aria-hidden> →</span>
                   </Link>
                 </div>
               )}
             </li>
           )}
           {items.map((item) => (
            <li key={item.title}>
              <Link href={item.href} className="group flex items-center gap-3 rounded-xl px-2 py-2.5 outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${item.severity === "high" ? "bg-coral" : "bg-amber-500"}`} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink">{item.title}</span>
                  <span className="block truncate text-[11px] text-ink/45">{item.detail}</span>
                </span>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink/25 transition group-hover:translate-x-0.5 group-hover:text-deep-violet">
                  <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BusinessPulse() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [points, setPoints] = useState<TimeseriesPoint[]>([]);
  const [channels, setChannels] = useState<DashboardChannel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [serviceCount, setServiceCount] = useState(0);
  const [offeredCount, setOfferedCount] = useState(0);
  const [hoursStatus, setHoursStatus] = useState<{ open: boolean | null; label: string; detail: string }>({
    open: null, label: "--", detail: "Not configured yet",
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function loadPulse() {
      try {
        const channelData = await apiFetch("/api/v1/channels/?limit=100");
        const googleChannels = (channelData.channels ?? []).filter(
          (channel: DashboardChannel) => channel.platform === "google_reviews"
        );
        const [nextOverview, nextPoints, serviceResults] = await Promise.all([
          fetchOverview(30, channelId || null),
          fetchTimeseries(30, channelId || null),
          Promise.all((channelId ? googleChannels.filter((channel: DashboardChannel) => channel.id === channelId) : googleChannels).map((channel: DashboardChannel) => apiFetch(`/api/v1/channels/${channel.id}/services`))),
        ]);
        if (cancelled) return;
        const allServices = serviceResults.flatMap((result) => (result.services ?? []) as DashboardService[]);
        setChannels(googleChannels);
        setOverview(nextOverview);
        setPoints(nextPoints);
        setServiceCount(allServices.length);
        setOfferedCount(allServices.filter((service) => service.is_offered).length);
      } catch {
        if (!cancelled) {
          setOverview(null);
          setPoints([]);
          setChannels([]);
          setServiceCount(0);
          setOfferedCount(0);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadPulse();
    return () => {
      cancelled = true;
    };
  }, [channelId]);

  // Live open/closed status from stored regular hours (independent of scope).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const prof = await apiFetch("/api/v1/integrations/localith/profile");
        const listingId = prof?.connection?.listing_id;
        if (!listingId) return;
        const data = await apiFetch(`/api/v1/locations/${listingId}`);
        const regular = data?.hours?.regular;
        if (!regular || typeof regular !== "object") return;
        const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
        const now = new Date();
        const today = regular[days[now.getDay()]];
        if (!today) return;
        const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
        const fmt = (t: string) => {
          const [h, m] = t.split(":").map(Number);
          if (Number.isNaN(h)) return t;
          const ap = h >= 12 ? "PM" : "AM";
          const h12 = h % 12 === 0 ? 12 : h % 12;
          return `${h12}:${String(m ?? 0).padStart(2, "0")} ${ap}`;
        };
        if (!cancelled) {
          if (today.closed || !today.open || !today.close) {
            setHoursStatus({ open: false, label: "Closed", detail: "Closed today" });
          } else if (today.open <= hhmm && hhmm < today.close) {
            setHoursStatus({ open: true, label: "Open now", detail: `Closes ${fmt(today.close)}` });
          } else if (hhmm < today.open) {
            setHoursStatus({ open: false, label: "Closed", detail: `Opens today ${fmt(today.open)}` });
          } else {
            setHoursStatus({ open: false, label: "Closed", detail: `Opens ${fmt(today.open)} tomorrow` });
          }
        }
      } catch {
        /* keep placeholder when offline or unconfigured */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const totalReviews = overview?.total_reviews ?? 0;
  const ratingDistribution = overview?.rating_distribution ?? {};

  return (
    <section aria-label="Business pulse" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[16px] font-bold text-ink">Business pulse</h2>
          <p className="mt-0.5 text-[12px] text-ink/50">A quick view of your connected businesses and customer activity.</p>
        </div>
        <div className="flex items-center gap-2">
          {channels.length > 0 && <select value={channelId} onChange={(event) => { setLoading(true); setChannelId(event.target.value); }} aria-label="Business scope" className="rounded-lg border border-ink/[0.08] bg-white px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 outline-none focus:border-deep-violet/30"><option value="">All businesses</option>{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed business"}</option>)}</select>}
          <span className="text-[11px] font-semibold text-ink/40">Last 30 days</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <PulseStat label="Total reviews" value={totalReviews} detail={overview ? `${overview.avg_rating.toFixed(1)} average rating` : "No review data yet"} color="text-amber-600" href="/dashboard/reviews" delta={overview?.period.reviews_delta_pct} deltaSuffix="%" spark={points.map((p) => p.reviews_count)} sparkColor="#d97706" />
        <PulseStat label="Connected businesses" value={channels.length} detail={channels.length ? "Google Business channels" : "No Google channel yet"} color="text-deep-violet" href="/dashboard/locations" />
        <PulseStat label="Services offered" value={offeredCount} detail={serviceCount ? `${serviceCount} services configured` : "No service data yet"} color="text-emerald-600" href="/dashboard/services" />
        <PulseStat
          label="Working hours"
          value={hoursStatus.label}
          detail={hoursStatus.detail}
          color={hoursStatus.open === null ? "text-sky-600" : hoursStatus.open ? "text-emerald-600" : "text-coral"}
          href="/dashboard/locations?tab=hours"
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-[1.7fr_1fr]">
        <Link href="/dashboard/analytics" aria-label="Open analytics" className="group block rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40">
          {loading ? <div className="h-72 animate-pulse rounded-2xl border-2 border-white bg-white/60" /> : <span className="block rounded-2xl transition duration-200 group-hover:-translate-y-0.5 group-hover:shadow-lg group-hover:shadow-deep-violet/[0.08]"><MetricChart points={points} /></span>}
        </Link>
        <Link href="/dashboard/reviews" aria-label="Open reviews" className="group block rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-deep-violet/20 hover:shadow-lg hover:shadow-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
          <h3 className="mb-4 text-[14px] font-bold text-ink transition-colors group-hover:text-deep-violet">Review ratings</h3>
          <RatingDistribution distribution={ratingDistribution} total={totalReviews} />
          <div className="mt-5 border-t border-ink/[0.06] pt-4">
            <div className="flex items-center justify-between text-[11px] text-ink/45"><span>Response rate</span><strong className="text-ink">{overview ? `${Math.round(overview.response_rate)}%` : "--"}</strong></div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/[0.06]"><div className="h-full rounded-full bg-emerald" style={{ width: `${Math.min(100, overview?.response_rate ?? 0)}%` }} /></div>
          </div>
        </Link>
      </div>
    </section>
  );
}

function PulseStat({ label, value, detail, color, href, delta, deltaSuffix = "", spark, sparkColor }: { label: string; value: number | string; detail: string; color: string; href?: string; delta?: number | null; deltaSuffix?: string; spark?: number[]; sparkColor?: string }) {
  const cls = "group block rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-deep-violet/20 hover:shadow-lg hover:shadow-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40";
  const deltaChip = typeof delta === "number" ? (
    <span className={`ml-1.5 inline-flex items-center gap-0.5 rounded-full px-1.5 py-px align-middle text-[10px] font-bold tabular-nums ${delta > 0 ? "bg-emerald/10 text-emerald" : delta < 0 ? "bg-coral/10 text-coral" : "bg-ink/[0.05] text-ink/50"}`}>
      {delta !== 0 && (
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-2 w-2 ${delta < 0 ? "rotate-180" : ""}`} aria-hidden>
          <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {delta > 0 ? "+" : ""}{delta}{deltaSuffix}
    </span>
  ) : null;
  const inner = (
    <>
      <p className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wide text-ink/50">
        <span>{label}</span>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className="h-3 w-3 text-ink/25 transition group-hover:translate-x-0.5 group-hover:text-deep-violet"><path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </p>
      <p className={`mt-1 flex items-center justify-between gap-2 text-[22px] font-bold ${color}`}>
        <span>{value}{deltaChip}</span>
        {spark && spark.length > 1 && <Sparkline values={spark} color={sparkColor} />}
      </p>
      <p className="truncate text-[10px] text-ink/40">{detail}</p>
    </>
  );
  return href ? <Link href={href} aria-label={label} className={cls}>{inner}</Link> : <div className={cls}>{inner}</div>;
}

const EMPTY_CHECKLIST: Record<string, boolean> = {};
let cachedRaw: string | null = null;
let cachedValue: Record<string, boolean> = EMPTY_CHECKLIST;

function readChecklist(): Record<string, boolean> {
  if (typeof window === "undefined") return EMPTY_CHECKLIST;
  const raw = window.localStorage.getItem(CHECKLIST_KEY);
  if (raw === cachedRaw) return cachedValue;
  if (raw === null) {
    cachedValue = EMPTY_CHECKLIST;
  } else {
    try {
      cachedValue = JSON.parse(raw) ?? EMPTY_CHECKLIST;
    } catch {
      cachedValue = EMPTY_CHECKLIST;
    }
  }
  cachedRaw = raw;
  return cachedValue;
}

const checklistListeners = new Set<() => void>();

function subscribeChecklist(callback: () => void) {
  checklistListeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    checklistListeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

function getServerChecklist(): Record<string, boolean> {
  return EMPTY_CHECKLIST;
}

function writeChecklist(next: Record<string, boolean>) {
  try {
    window.localStorage.setItem(CHECKLIST_KEY, JSON.stringify(next));
  } catch {
    // storage unavailable — updates still broadcast for this session
  }
  checklistListeners.forEach((listener) => listener());
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { dir, t } = useI18n();
  const done = useSyncExternalStore(subscribeChecklist, readChecklist, getServerChecklist);

  const checklistItems = checklistDefs.map((d) => ({
    ...d,
    label: t.dashboard.start[d.labelKey],
  }));

  const toggleItem = useCallback((id: string) => {
    const current = readChecklist();
    writeChecklist({ ...current, [id]: !current[id] });
  }, []);

  const completed = checklistItems.filter((i) => done[i.id]).length;
  const total = checklistItems.length;
  const progress = total === 0 ? 0 : Math.round((completed / total) * 100);
  const allDone = completed === total;
  const nextItem = checklistItems.find((i) => !done[i.id]) ?? null;
  const [dismissed, setDismissed] = useState(() => {
    try {
      return typeof window !== "undefined" && window.localStorage.getItem("sayvors.onboarding.checklist.dismissed") === "1";
    } catch {
      return false;
    }
  });
  const dismissChecklist = useCallback(() => {
    try {
      window.localStorage.setItem("sayvors.onboarding.checklist.dismissed", "1");
    } catch {
      /* storage unavailable */
    }
    setDismissed(true);
  }, []);
  const showChecklist = !allDone || !dismissed;
  const [checklistOpen, setChecklistOpen] = useState(() => {
    try {
      return typeof window === "undefined" || window.localStorage.getItem("sayvors.onboarding.checklist.open") !== "0";
    } catch {
      return true;
    }
  });
  const toggleChecklist = useCallback(() => {
    const next = !checklistOpen;
    try {
      window.localStorage.setItem("sayvors.onboarding.checklist.open", next ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
    setChecklistOpen(next);
  }, [checklistOpen]);

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-5 bg-[#f3f0ff]">
      {/* Getting Started checklist — first thing a new user must see */}
      {showChecklist && (
        <section
          aria-label={t.dashboard.start.title}
          className="relative overflow-hidden rounded-2xl bg-white p-5 shadow-md shadow-deep-violet/[0.08] ring-2 ring-deep-violet/30"
        >
          <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-deep-violet via-magenta to-coral" />
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
                <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z" />
                <path d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 01-4 2z" />
                <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
                <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
              </svg>
            </span>
            <button
              onClick={toggleChecklist}
              aria-expanded={checklistOpen}
              aria-controls="onboarding-checklist-body"
              className="flex min-w-0 flex-1 items-center gap-2 rounded-lg text-left outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40"
            >
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-[15px] font-bold text-ink">{t.dashboard.start.title}</span>
                  <span className="rounded-full bg-deep-violet/[0.08] px-2.5 py-0.5 text-[11px] font-bold tabular-nums text-deep-violet">
                    {allDone ? t.dashboard.start.allSet : t.dashboard.start.doneOf.replace("{done}", String(completed)).replace("{total}", String(total))}
                  </span>
                </span>
                <span className="mt-0.5 block text-[12px] text-ink/55">
                  {allDone
                    ? t.dashboard.start.subtitleDone
                    : t.dashboard.start.subtitleTodo}
                </span>
              </span>
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-4 w-4 shrink-0 text-ink/30 transition-transform ${checklistOpen ? "rotate-180" : ""}`}>
                <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {allDone && (
              <button
                onClick={dismissChecklist}
                className="shrink-0 rounded-lg px-2 py-1 text-[12px] font-semibold text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink"
              >
                {t.dashboard.start.dismiss}
              </button>
            )}
          </div>

          {checklistOpen && (
          <div id="onboarding-checklist-body" className="mt-3">
          {/* Progress bar */}
          <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-deep-violet/[0.08]" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label={t.dashboard.start.title}>
            <div
              className="h-full rounded-full bg-gradient-to-r from-deep-violet via-magenta to-coral transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>

          <ol className="space-y-2">
            {checklistItems.map((item, index) => {
              const isDone = !!done[item.id];
              const isNext = nextItem?.id === item.id;
              return (
                <li
                  key={item.id}
                  className={`flex items-center gap-3 rounded-xl border p-3 transition ${
                    isDone
                      ? "border-transparent bg-ink/[0.02]"
                      : isNext
                        ? "border-deep-violet/30 bg-deep-violet/[0.04] shadow-sm"
                        : "border-ink/[0.06] bg-white"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold tabular-nums ${
                      isDone
                        ? "bg-deep-violet text-white"
                        : isNext
                          ? "bg-deep-violet text-white ring-4 ring-deep-violet/15"
                          : "bg-ink/[0.06] text-ink/45"
                    }`}
                  >
                    {isDone ? (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className={`text-[13px] font-semibold ${isDone ? "text-ink/40 line-through" : "text-ink"}`}>
                      {item.label}
                      {isNext && !isDone && (
                        <span className="ml-2 rounded-full bg-deep-violet px-2 py-0.5 align-middle text-[9px] font-bold uppercase tracking-wide text-white">
                          {t.dashboard.start.upNext}
                        </span>
                      )}
                    </p>
                  </div>
                  {isNext && !isDone ? (
                    <Link
                      href={item.href}
                      className="shrink-0 rounded-lg bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/30 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98]"
                    >
                      {t.dashboard.start.start}
                      <span aria-hidden> {dir === "rtl" ? "←" : "→"}</span>
                    </Link>
                  ) : (
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        onClick={() => toggleItem(item.id)}
                        aria-label={isDone ? t.dashboard.start.reopenStep.replace("{label}", item.label) : t.dashboard.start.markDone.replace("{label}", item.label)}
                        title={isDone ? t.dashboard.start.reopen : t.dashboard.start.skip}
                        className={`rounded-lg px-2 py-1 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                          isDone ? "text-ink/35 hover:text-ink/60" : "text-deep-violet/70 hover:bg-deep-violet/[0.06] hover:text-deep-violet"
                        }`}
                      >
                        {isDone ? t.dashboard.start.reopen : t.dashboard.start.skip}
                      </button>
                      <Link
                        href={item.href}
                        aria-label={t.dashboard.start.openStep.replace("{label}", item.label)}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/30 outline-none transition hover:bg-deep-violet/[0.06] hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                      >
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className="h-3.5 w-3.5">
                          <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </Link>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
          </div>
          )}
        </section>
      )}

      {/* Header */}
      <div>
        <Greeting name={user?.first_name ?? t.dashboard.greetingFallback} />
        <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">
          {t.dashboard.subtitle}
        </p>
      </div>

      {/* Needs attention — the daily driver */}
      <AttentionQueue />

      <BusinessPulse />

    </div>
  );
}
