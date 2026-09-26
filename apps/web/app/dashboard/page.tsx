"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api-rag";
import { approveReply, editReply, fetchBenchmark, fetchInsights, fetchOverview, fetchTimeseries, generateReply, regenerateReply, retryReply, type BenchmarkResponse, type Overview, type ReviewReplyDTO, type TimeseriesPoint } from "@/lib/api-analytics";
import { dedupeBusinesses } from "@/lib/channel-identity";
import { useI18n } from "@/lib/i18n/I18nProvider";
import Greeting from "@/components/dashboard/Greeting";
import { MetricChart, RatingDistribution, Sparkline } from "@/components/analytics/Charts";

const checklistDefs = [
  { id: "channel", labelKey: "stepConnect", href: "/dashboard/channels" },
  { id: "databank", labelKey: "stepDatabank", href: "/dashboard/databank" },
  { id: "auto-reply", labelKey: "stepAutoReply", href: "/dashboard/channels" },
  // Services + hours were dashboard tiles that read as metrics but were really
  // setup tasks. They belong in onboarding, not in the pulse row.
  { id: "services", labelKey: "stepServices", href: "/dashboard/services" },
  { id: "hours", labelKey: "stepHours", href: "/dashboard/locations?tab=hours" },
] as const;

const CHECKLIST_KEY = "sayvors.onboarding.checklist";

type DashboardChannel = { id: string; platform: string; display_name: string | null; listing_id?: string | null; source?: string | null };
type DashboardService = { is_offered: boolean };

interface IntelSnapshot {
  source: string;
  summary: string;
  stats: { positive: number; neutral: number; negative: number; total: number };
  themes: { name: string; mentions: number; avg_rating: number; positive_pct: number }[];
  /** Business Health Scorecard — only dimensions with mentions > 0 arrive. */
  dimensions?: {
    key: string;
    label: string;
    mentions: number;
    positive: number;
    negative: number;
    avg_rating: number;
    signal: "strong" | "mixed" | "weak";
  }[];
  actions?: { title: string; detail: string }[];
  /** Where this business leads / trails the anonymised cohort. */
  competitive?: { wins: string[]; gaps: string[]; scope: string | null };
  stale?: boolean;
}

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

function detailFromError(e: unknown, fallback: string): string {
  // apiFetch throws the raw response body — extract the server's detail
  // (e.g. "Failed to post reply to Google: No refresh token available").
  if (e instanceof Error) {
    try {
      const parsed = JSON.parse(e.message) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch {
      /* not JSON — keep the fallback */
    }
  }
  return fallback;
}

interface EditedItem {
  id: string;
  review_id: string;
  channel_id: string;
  rating: number;
  review_text: string | null;
  reviewer_name: string | null;
  previous_rating: number | null;
}

interface ScheduledItem {
  kind: "post" | "photo";
  id: string;
  title: string;
  location: string;
  at: string;
}

/** "Today 6:00 PM" / "tomorrow 9:00 AM" / "Sep 25 9:00 AM". */
function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `today ${time}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
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
  // Inline editing of a draft right on its dashboard card.
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [editingDraftText, setEditingDraftText] = useState("");
  const [savingDraftId, setSavingDraftId] = useState<string | null>(null);
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
  const [edited, setEdited] = useState<EditedItem[]>([]);
  const [editedTotal, setEditedTotal] = useState(0);
  const [editedOpen, setEditedOpen] = useState(false);
  const [editedDrafts, setEditedDrafts] = useState<Record<string, ReviewReplyDTO>>({});
  const [editedApprovingId, setEditedApprovingId] = useState<string | null>(null);
  const [editedRewritingId, setEditedRewritingId] = useState<string | null>(null);
  const [editedGeneratingId, setEditedGeneratingId] = useState<string | null>(null);
  const [editedError, setEditedError] = useState<string | null>(null);
  // Scheduled posts + photos: shown only when something is actually queued.
  const [scheduled, setScheduled] = useState<ScheduledItem[]>([]);
  const [scheduledTotal, setScheduledTotal] = useState(0);
  const [scheduledOpen, setScheduledOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const found: AttentionItem[] = [];
      try {
        const [overview, connsData, channelData] = await Promise.all([
          fetchOverview(30, null).catch(() => null),
          apiFetch("/api/v1/integrations/localith/connections").catch(() => null),
          apiFetch("/api/v1/channels/?limit=100").catch(() => null),
        ]);
        const conns = (Array.isArray(connsData) ? connsData : []) as {
          listing_name?: string; phone_number?: string | null; website_url?: string | null;
        }[];
        const rawChannels: DashboardChannel[] = (channelData?.channels ?? []).filter(
          (c: { platform: string }) => c.platform === "google_reviews"
        );
        const googleChannels = dedupeBusinesses(rawChannels);
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
         try {
           const data = await apiFetch("/api/v1/analytics/reviews/insights?edited=true&limit=50");
           if (!cancelled) {
             // A backend older than the edit-detection feature ignores the
             // edited param — filter locally so this card only ever lists
             // genuinely-edited reviews.
             const flagged = ((data.items ?? []) as { id: string; review_id: string; channel_id: string; rating: number; review_text: string | null; reviewer_name: string | null; previous_rating: number | null; edited?: boolean }[])
               .filter((it) => it.edited === true);
             const topEdited = flagged.slice(0, 5).map((it) => ({
               id: it.id,
               review_id: it.review_id,
               channel_id: it.channel_id,
               rating: it.rating,
               review_text: it.review_text,
               reviewer_name: it.reviewer_name,
               previous_rating: it.previous_rating,
             }));
             setEditedTotal(flagged.length);
             setEdited(topEdited);
             // The AI pipeline queues a follow-up draft (pending_approval)
             // for every edited review — pull it in so the merchant can
             // approve & publish right from this card.
             const channelSet = new Set(topEdited.map((it) => it.channel_id));
             const editedReviewIds = new Set(topEdited.map((it) => it.review_id));
             const draftMap: Record<string, ReviewReplyDTO> = {};
             await Promise.all(
               [...channelSet].map(async (chId) => {
                 try {
                   const r = await apiFetch(`/api/v1/channels/${chId}/reviews?status=pending_approval&limit=100`);
                   for (const d of (r.replies ?? []) as ReviewReplyDTO[]) {
                     if (!editedReviewIds.has(d.review_id)) continue;
                     const prev = draftMap[d.review_id];
                     if (!prev || (d.created_at ?? "") > (prev.created_at ?? "")) draftMap[d.review_id] = d;
                   }
                 } catch {
                   /* queue unavailable — card falls back to the no-draft hint */
                 }
               })
             );
             if (!cancelled) setEditedDrafts(draftMap);
           }
          } catch {
            /* edited section hidden on error */
          }
          try {
            // Scheduled posts + photos across branches (nearest first).
            // Any failure hides the row — never an error state.
            const rawConns = (Array.isArray(connsData) ? connsData : []) as {
              listing_id?: string; listing_name?: string;
            }[];
            const locs = rawConns.filter((c) => c.listing_id).slice(0, 10);
            const locNames: Record<string, string> = {};
            for (const c of rawConns) {
              if (c.listing_id) locNames[c.listing_id] = c.listing_name ?? "Location";
            }
            const sched: ScheduledItem[] = [];
            await Promise.all(locs.map(async (loc) => {
              const lid = loc.listing_id!;
              const [postRows, mediaRows] = await Promise.all([
                (async () => {
                  try {
                    const d = await apiFetch(`/api/v1/posts/?listing_id=${encodeURIComponent(lid)}`);
                    return (Array.isArray(d) ? d : []) as Record<string, unknown>[];
                  } catch {
                    return [] as Record<string, unknown>[];
                  }
                })(),
                (async () => {
                  try {
                    const d = await apiFetch(`/api/v1/media/?listing_id=${encodeURIComponent(lid)}`);
                    const arr = Array.isArray(d) ? d : (d as { media?: unknown }).media;
                    return (Array.isArray(arr) ? arr : []) as Record<string, unknown>[];
                  } catch {
                    return [] as Record<string, unknown>[];
                  }
                })(),
              ]);
              for (const p of postRows) {
                if (p.status === "scheduled" && typeof p.scheduled_on === "string") {
                  sched.push({
                    kind: "post", id: String(p.id ?? ""),
                    title: String(p.title || "Untitled post"),
                    location: locNames[lid] ?? "Location", at: p.scheduled_on,
                  });
                }
              }
              for (const m of mediaRows) {
                if (m.status === "scheduled" && typeof m.scheduled_on === "string") {
                  const caption = typeof m.caption === "string" && m.caption.trim()
                    ? m.caption.trim()
                    : `Photo · ${String(m.category ?? "gallery").replace(/_/g, " ")}`;
                  sched.push({
                    kind: "photo", id: String(m.id ?? ""),
                    title: caption, location: locNames[lid] ?? "Location",
                    at: m.scheduled_on,
                  });
                }
              }
            }));
            sched.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
            if (!cancelled) {
              setScheduledTotal(sched.length);
              setScheduled(sched.slice(0, 5));
            }
          } catch {
            /* scheduled row hidden on error */
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
        const missingPhone = conns.filter((c) => !c.phone_number);
        if (missingPhone.length > 0) {
          found.push({
            severity: "medium",
            title: missingPhone.length === 1
              ? `No phone number on ${missingPhone[0].listing_name ?? "your profile"}`
              : `No phone number on ${missingPhone.length} branches`,
            detail: "Customers can't call you from Google",
            href: "/dashboard/locations?tab=details",
          });
        }
        const missingSite = conns.filter((c) => !(c.website_url || "").trim());
        if (missingSite.length > 0) {
          found.push({
            severity: "medium",
            title: missingSite.length === 1
              ? `No website linked for ${missingSite[0].listing_name ?? "your profile"}`
              : `No website linked for ${missingSite.length} branches`,
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

  async function approveDraft(channelId: string, replyId: string) {    setApprovingId(replyId);
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

  async function saveDraftText(d: ReviewReplyDTO) {
    const text = editingDraftText.trim();
    if (!text) return;
    setSavingDraftId(d.id);
    setDraftError(null);
    try {
      const saved = await editReply(d.channel_id, d.id, text);
      setDrafts((prev) => prev.map((x) => (x.id === d.id ? { ...x, reply_text: saved.reply_text } : x)));
      setEditingDraftId(null);
    } catch (e) {
      setDraftError(detailFromError(e, "Could not save your edit. Try again."));
    } finally {
      setSavingDraftId(null);
    }
  }

  async function approveEditedDraft(d: ReviewReplyDTO, reviewId: string) {
    setEditedApprovingId(d.id);
    setEditedError(null);
    try {
      await approveReply(d.channel_id, d.id);
      // Publishing the updated reply clears the edited flag server-side
      // (review.replied → posted) — drop the card locally right away.
      setEdited((prev) => prev.filter((x) => x.review_id !== reviewId));
      setEditedTotal((t) => Math.max(0, t - 1));
      setEditedDrafts((prev) => {
        const next = { ...prev };
        delete next[reviewId];
        return next;
      });
    } catch (e) {
      setEditedError(detailFromError(e, "Could not publish that reply. Try again."));
    } finally {
      setEditedApprovingId(null);
    }
  }

  async function rewriteEditedDraft(d: ReviewReplyDTO) {
    if (editedRewritingId !== null) return;
    setEditedRewritingId(d.id);
    setEditedError(null);
    try {
      const fresh = await regenerateReply(d.channel_id, d.id, true);
      setEditedDrafts((prev) => ({
        ...prev,
        [d.review_id]: {
          ...d,
          reply_text: fresh.reply_text,
          generation_attempt: fresh.generation_attempt ?? (d.generation_attempt ?? 1) + 1,
        },
      }));
    } catch (e) {
      setEditedError(detailFromError(e, "Engine rewrite failed. Try again."));
    } finally {
      setEditedRewritingId(null);
    }
  }

  async function generateEditedDraft(d: EditedItem) {
    if (editedGeneratingId !== null) return;
    setEditedGeneratingId(d.id);
    setEditedError(null);
    try {
      const fresh = await generateReply(d.channel_id, {
        review_id: d.review_id,
        rating: d.rating,
        review_text: d.review_text,
        reviewer_name: d.reviewer_name,
      });
      setEditedDrafts((prev) => ({ ...prev, [d.review_id]: fresh }));
    } catch (e) {
      setEditedError(detailFromError(e, "Could not draft a reply. Try again."));
    } finally {
      setEditedGeneratingId(null);
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
    const showScheduled = scheduledTotal > 0;
    const showFailed = failedTotal > 0;
    const showFlagged = flaggedTotal > 0;
    const showEdited = editedTotal > 0;
    const allClear = !showDrafts && !showScheduled && !showFailed && !showFlagged && !showEdited && items.length === 0;
    const draftTitle =
      draftTotal === 1 ? "1 drafted reply needs your approval" : `${draftTotal} drafted replies across all locations need your approval`;
    const scheduledTitle =
      scheduledTotal === 1 ? "1 scheduled post or photo" : `${scheduledTotal} scheduled posts and photos`;
   const failedTitle =
     failedTotal === 1 ? "1 reply failed to publish" : `${failedTotal} replies failed to publish`;
   // Token-flavored failures genuinely need a Google re-consent; anything
   // else (API hiccups, transient errors) just needs a retry.
   const needsReconnect = failed.some((d) =>
     /refresh token|access token|invalid_grant|expired|auth|401|permission/i.test(d.error ?? "")
   );
    const flaggedTitle =
      flaggedTotal === 1 ? "1 review marked unavailable" : `${flaggedTotal} reviews marked unavailable on Google`;
   const editedTitle =
     editedTotal === 1 ? "1 review was edited by its author" : `${editedTotal} reviews were edited by their authors`;
   return (
    <section
      aria-label="Needs attention"
      data-tour="attention"
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
                          {editingDraftId === d.id ? (
                            <>
                              <textarea
                                value={editingDraftText}
                                onChange={(e) => setEditingDraftText(e.target.value)}
                                rows={4}
                                maxLength={1000}
                                autoFocus
                                className="mt-1.5 min-h-[80px] w-full resize-y rounded-lg border border-deep-violet/25 bg-white px-2.5 py-2 text-[12px] leading-relaxed text-ink outline-none focus:border-deep-violet/50"
                              />
                              <div className="mt-1.5 flex items-center justify-end gap-2">
                                <button
                                  onClick={() => setEditingDraftId(null)}
                                  disabled={savingDraftId !== null}
                                  className="rounded-lg px-2.5 py-1 text-[11px] font-semibold text-ink/50 hover:bg-ink/[0.04] disabled:opacity-40"
                                >
                                  Cancel
                                </button>
                                <button
                                  onClick={() => void saveDraftText(d)}
                                  disabled={!editingDraftText.trim() || savingDraftId !== null}
                                  className="rounded-lg bg-deep-violet px-3 py-1 text-[11px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
                                >
                                  {savingDraftId === d.id ? "Saving…" : "Save"}
                                </button>
                              </div>
                            </>
                          ) : (
                            <p className="mt-0.5 line-clamp-3 text-[12px] leading-relaxed text-ink/80">{d.reply_text}</p>
                          )}
                        </div>
                        <div className="mt-2 flex items-center justify-end gap-2">
                          {editingDraftId !== d.id && (
                            <button
                              onClick={() => { setEditingDraftId(d.id); setEditingDraftText(d.reply_text ?? ""); setDraftError(null); }}
                              disabled={enginingId !== null || approvingId !== null || approvingAll}
                              className="rounded-lg px-3 py-1.5 text-[11px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                            >
                              Edit
                            </button>
                          )}
                          <button
                            onClick={() => void engineRedraft(d)}
                            disabled={enginingId !== null || approvingId !== null || approvingAll || editingDraftId !== null}
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
                            disabled={approvingId !== null || approvingAll || enginingId !== null || editingDraftId !== null}
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
                      disabled={approvingAll || approvingId !== null || enginingId !== null || draftTotal === 0 || editingDraftId !== null}
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
          {showScheduled && (
            <li>
              <button
                onClick={() => setScheduledOpen((o) => !o)}
                aria-expanded={scheduledOpen}
                aria-controls="attention-scheduled-body"
                className="group flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky-500" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink">{scheduledTitle}</span>
                  <span className="block truncate text-[11px] text-ink/45">
                    {scheduled[0]
                      ? `Next: ${scheduled[0].title} · ${fmtWhen(scheduled[0].at)}`
                      : "Queued to publish to Google"}
                  </span>
                </span>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3.5 w-3.5 shrink-0 text-ink/25 transition group-hover:text-deep-violet ${scheduledOpen ? "rotate-180" : ""}`}>
                  <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {scheduledOpen && (
                <div id="attention-scheduled-body" className="space-y-2 px-2 pb-3 pt-1">
                  {scheduled.map((s) => (
                    <div key={`${s.kind}-${s.id}`} className="rounded-xl border border-ink/[0.06] bg-white p-3">
                      <div className="flex items-center gap-2">
                        <span aria-hidden className="text-[13px]">{s.kind === "post" ? "📝" : "📸"}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] font-semibold text-ink">{s.title}</span>
                          <span className="block truncate text-[11px] text-ink/45">{s.location} · goes live {fmtWhen(s.at)}</span>
                        </span>
                      </div>
                    </div>
                  ))}
                  <div className="flex gap-2">
                    {scheduled.some((s) => s.kind === "post") && (
                      <Link
                        href="/dashboard/posts"
                        className="flex flex-1 items-center justify-center gap-1 rounded-xl bg-deep-violet/[0.06] px-3 py-2.5 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.1] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                      >
                        Manage posts <span aria-hidden> →</span>
                      </Link>
                    )}
                    {scheduled.some((s) => s.kind === "photo") && (
                      <Link
                        href="/dashboard/media"
                        className="flex flex-1 items-center justify-center gap-1 rounded-xl bg-deep-violet/[0.06] px-3 py-2.5 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.1] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                      >
                        Manage media <span aria-hidden> →</span>
                      </Link>
                    )}
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
           {showEdited && (
             <li>
               <button
                 onClick={() => setEditedOpen((o) => !o)}
                 aria-expanded={editedOpen}
                 aria-controls="attention-edited-body"
                 className="group flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left outline-none transition hover:bg-ink/[0.02] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
               >
                 <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet" aria-hidden />
                 <span className="min-w-0 flex-1">
                   <span className="block truncate text-[13px] font-semibold text-ink">{editedTitle}</span>
                   <span className="block truncate text-[11px] text-ink/45">See what changed and respond to the new version</span>
                 </span>
                 <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3.5 w-3.5 shrink-0 text-ink/25 transition group-hover:text-deep-violet ${editedOpen ? "rotate-180" : ""}`}>
                   <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                 </svg>
               </button>
               {editedOpen && (
                 <div id="attention-edited-body" className="space-y-2 px-2 pb-3 pt-1">
                   {editedError && (
                     <p className="rounded-lg bg-coral/10 px-3 py-2 text-[11px] font-medium text-coral">{editedError}</p>
                   )}
                   {edited.map((d) => {
                     const locName = channelNames[d.channel_id] ?? "Location";
                     const draft = editedDrafts[d.review_id];
                     const busy = draft != null && editedApprovingId === draft.id;
                     return (
                       <div key={d.id} className="rounded-xl border border-ink/[0.06] bg-white p-3">
                         <div className="flex items-center gap-1.5 text-[11px] text-ink/50">
                           <span aria-label={`${d.rating} out of 5 stars`} className="font-bold text-amber-600">{"★".repeat(Math.max(0, Math.min(5, d.rating)))}</span>
                           {d.previous_rating != null && d.previous_rating !== d.rating && (
                             <span aria-label={`was ${d.previous_rating} stars`} className="text-[10px] font-medium text-ink/40 line-through">{d.previous_rating}★</span>
                           )}
                           <span className="truncate font-semibold text-ink">{d.reviewer_name ?? "Anonymous"}</span>
                           <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-medium text-ink/50">{locName}</span>
                         </div>
                         {d.review_text && (
                           <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/60">“{d.review_text}”</p>
                         )}
                         {draft ? (
                           <div className="mt-2 rounded-lg bg-deep-violet/[0.05] p-2.5">
                             <p className="text-[9px] font-bold uppercase tracking-wide text-deep-violet/60">
                               AI draft — refreshed for the edited review{(draft.generation_attempt ?? 1) > 1 ? ` · try #${draft.generation_attempt}` : ""}
                             </p>
                             <p className="mt-0.5 line-clamp-3 text-[12px] leading-relaxed text-ink/80">{draft.reply_text}</p>
                             <div className="mt-2 flex items-center justify-end gap-2">
                               <button
                                 onClick={() => void rewriteEditedDraft(draft)}
                                 disabled={editedRewritingId !== null || busy}
                                 title="Re-run the full AI pipeline on the new review text"
                                 className="inline-flex items-center gap-1 rounded-lg bg-deep-violet/[0.08] px-3 py-1.5 text-[11px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.15] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                               >
                                 {editedRewritingId === draft.id ? "Rewriting…" : "Rewrite"}
                               </button>
                               <button
                                 onClick={() => void approveEditedDraft(draft, d.review_id)}
                                 disabled={busy || editedApprovingId !== null}
                                 className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                               >
                                 {busy ? "Publishing…" : "Approve & publish"}
                               </button>
                             </div>
                           </div>
                         ) : (
                           <div className="mt-2 flex items-center justify-between gap-2 rounded-lg bg-ink/[0.03] px-3 py-2.5">
                             <p className="text-[11px] leading-4 text-ink/45">No AI draft for the new text yet.</p>
                             <button
                               onClick={() => void generateEditedDraft(d)}
                               disabled={editedGeneratingId === d.id}
                               className="shrink-0 rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98] disabled:opacity-50"
                             >
                               {editedGeneratingId === d.id ? (
                                 <><span className="mr-1 inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white align-[-2px]" /> Drafting…</>
                               ) : (
                                 "Generate draft now"
                               )}
                             </button>
                           </div>
                         )}
                         <div className="mt-2 flex items-center justify-between">
                           <span className="text-[10px] font-bold uppercase tracking-wide text-deep-violet/60">Edited after sync</span>
                           <Link href="/dashboard/reviews?tab=edited" className="text-[11px] font-bold text-deep-violet underline underline-offset-2 hover:text-deep-violet/80">See what changed →</Link>
                         </div>
                       </div>
                     );
                   })}
                   <Link href="/dashboard/reviews?tab=edited" className="flex items-center justify-center gap-1 rounded-xl bg-deep-violet/[0.06] px-3 py-2.5 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.1] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
                     Review &amp; respond to all {editedTotal} <span aria-hidden> →</span>
                   </Link>
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
  // Cohort comparison is already fetched — it feeds the "Where you stand" tile
  // instead of a "Connected businesses" counter nobody could act on.
  const [bench, setBench] = useState<BenchmarkResponse | null>(null);
  const [intel, setIntel] = useState<IntelSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function loadPulse() {
      try {
        const channelData = await apiFetch("/api/v1/channels/?limit=100");
        const rawChannels: DashboardChannel[] = (channelData.channels ?? []).filter(
          (channel: DashboardChannel) => channel.platform === "google_reviews"
        );
        const googleChannels = dedupeBusinesses(rawChannels);
        const [nextOverview, nextPoints, bench, nextIntel] = await Promise.all([
          fetchOverview(30, channelId || null),
          fetchTimeseries(30, channelId || null),
          fetchBenchmark(30, null).catch(() => null),
          apiFetch(`/api/v1/analytics/review-intelligence?days=90${channelId ? `&channel_id=${encodeURIComponent(channelId)}` : ""}`).catch(() => null),
        ]);
        if (cancelled) return;
        setChannels(googleChannels);
        setOverview(nextOverview);
        setPoints(nextPoints);
        setIntel(nextIntel);
        setBench(bench);
      } catch {
        if (!cancelled) {
          setOverview(null);
          setPoints([]);
          setChannels([]);
          setIntel(null);
          setBench(null);
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

  const totalReviews = overview?.total_reviews ?? 0;
  const ratingDistribution = overview?.rating_distribution ?? {};

  return (
    <section aria-label="Business pulse" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[16px] font-bold text-ink">Business pulse</h2>
          <p className="mt-0.5 text-[12px] text-ink/50">How you&apos;re doing, and the one thing to fix next.</p>
        </div>
        <div className="flex items-center gap-2">
          {channels.length > 0 && <select value={channelId} onChange={(event) => { setLoading(true); setChannelId(event.target.value); }} aria-label="Business scope" className="rounded-lg border border-ink/[0.08] bg-white px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 outline-none focus:border-deep-violet/30"><option value="">All businesses</option>{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed business"}</option>)}</select>}
          <span className="text-[11px] font-semibold text-ink/40">Last 30 days</span>
        </div>
      </div>

      {/* PULSE ROW — one honest number instead of four tiles of setup status.
          Services / hours moved to the launch checklist; market position gets
          its own panel below; the rating split lives in Customer voice. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <PulseStat
          label="Total reviews"
          value={totalReviews}
          detail={overview ? `${overview.avg_rating.toFixed(1)} average rating` : "No review data yet"}
          color="text-amber-600"
          href="/dashboard/reviews"
          delta={overview?.period.reviews_delta_pct}
          deltaSuffix="%"
          spark={points.map((p) => p.reviews_count)}
          sparkColor="#d97706"
        />
        <MarketPosition bench={bench} />
        <ThisWeekActions intel={intel} bench={bench} overview={overview} />
      </div>

      <CustomerVoice intel={intel} loading={loading} />

      <div className="grid gap-3 lg:grid-cols-[1.7fr_1fr]">
        <Link href="/dashboard/analytics" aria-label="Open analytics" className="group block rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40">
          {loading ? <div className="h-72 animate-pulse rounded-2xl border-2 border-white bg-white/60" /> : <span className="block rounded-2xl transition duration-200 group-hover:-translate-y-0.5 group-hover:shadow-lg group-hover:shadow-deep-violet/[0.08]"><MetricChart points={points} /></span>}
        </Link>
        <div className="space-y-3">
          <StarsCostingYou intel={intel} />
          <Link href="/dashboard/reviews" aria-label="Open reviews" className="group block rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-deep-violet/20 hover:shadow-lg hover:shadow-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
            <h3 className="mb-4 text-[14px] font-bold text-ink transition-colors group-hover:text-deep-violet">Review ratings</h3>
            <RatingDistribution distribution={ratingDistribution} total={totalReviews} />
            <div className="mt-5 border-t border-ink/[0.06] pt-4">
              <div className="flex items-center justify-between text-[11px] text-ink/45">
                <span>Response rate</span>
                <strong className="text-ink">
                  {totalReviews < MIN_REVIEWS_FOR_RATE
                    ? `needs ${MIN_REVIEWS_FOR_RATE - totalReviews} more`
                    : overview
                      ? `${Math.round(overview.response_rate)}%`
                      : "--"}
                </strong>
              </div>
              {totalReviews < MIN_REVIEWS_FOR_RATE ? (
                <p className="mt-1.5 text-[10px] text-ink/40">
                  Too few reviews for a meaningful rate — below {MIN_REVIEWS_FOR_RATE} reviews it is mostly luck.
                </p>
              ) : (
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/[0.06]">
                  <div className="h-full rounded-full bg-emerald" style={{ width: `${Math.min(100, overview?.response_rate ?? 0)}%` }} />
                </div>
              )}
            </div>
          </Link>
        </div>
      </div>
    </section>
  );
}

/** Response rate on a handful of reviews is noise, not a metric. */
const MIN_REVIEWS_FOR_RATE = 30;

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

/** A "2 of 2" ranking is noise. Below this, stay quiet rather than lie. */
const MIN_COHORT_FOR_RANK = 5;

/**
 * Where you stand against comparable businesses.
 *
 * An absolute 4.8★ is not a decision input — a position is. The cohort
 * (same city + category, other businesses on Sayvors) is already computed by
 * the benchmark endpoint, so this needs no extra request.
 */
function MarketPosition({ bench }: { bench: BenchmarkResponse | null }) {
  const cohort = bench?.cohort;
  const market = bench?.market ?? [];
  const count = cohort?.count ?? market.length;
  const rank = bench?.my_rank ?? null;
  const me = market.find((m) => m.is_you);
  const ahead = market.filter((m) => !m.is_you && me && m.reputation_score > me.reputation_score);
  const behind = market.filter((m) => !m.is_you && me && m.reputation_score < me.reputation_score).slice(0, 2);

  if (!bench || count < MIN_COHORT_FOR_RANK) {
    return (
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-ink/50">Where you stand</p>
        <p className="mt-1 text-[22px] font-bold text-ink/25">—</p>
        <p className="text-[10px] text-ink/40">
          Need {MIN_COHORT_FOR_RANK}+ comparable businesses before a ranking means anything
          {count > 0 ? ` — ${count} so far` : ""}.
        </p>
      </div>
    );
  }

  const percentile = rank && count ? Math.round(((count - rank + 1) / count) * 100) : null;
  return (
    <Link href="/dashboard/benchmark" aria-label="Where you stand" className="group block rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-deep-violet/20 hover:shadow-lg hover:shadow-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
      <p className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wide text-ink/50">
        <span>Where you stand</span>
        <span className="text-ink/25 transition group-hover:translate-x-0.5 group-hover:text-deep-violet" aria-hidden>→</span>
      </p>
      <p className="mt-1 text-[22px] font-bold text-deep-violet">
        {rank ? `#${rank}` : "—"}
        <span className="text-[12px] font-semibold text-ink/40"> of {count} {cohort?.label ?? "similar"}</span>
      </p>
      {percentile !== null && (
        <p className="mt-0.5 text-[11px] text-ink/55">
          Top {100 - percentile + 1}% · reputation {me ? Math.round(me.reputation_score) : "—"}
        </p>
      )}
      {(cohort?.median_rating != null || cohort?.median_response_rate != null) && (
        <p className="mt-1 text-[10px] text-ink/40">
          Median nearby: {cohort?.median_rating?.toFixed(1) ?? "—"}★
          {cohort?.median_response_rate != null ? ` · ${Math.round(cohort.median_response_rate)}% reply rate` : ""}
        </p>
      )}
      {(ahead.length > 0 || behind.length > 0) && (
        <p className="mt-1.5 truncate text-[10px] text-ink/45">
          {ahead.length > 0 && <span className="text-emerald">Ahead: {ahead.length} business{ahead.length === 1 ? "" : "es"}</span>}
          {ahead.length > 0 && behind.length > 0 && " · "}
          {behind.length > 0 && <span className="text-coral">Behind: {behind.map((b) => b.name).join(", ")}</span>}
        </p>
      )}
    </Link>
  );
}

/**
 * One action, not a dashboard. Prefers the LLM's own recommended action, falls
 * back to the competitive gap that is actually measurable today.
 */
function ThisWeekActions({ intel, bench, overview }: {
  intel: IntelSnapshot | null;
  bench: BenchmarkResponse | null;
  overview: Overview | null;
}) {
  const total = overview?.total_reviews ?? 0;
  const first = intel?.actions?.[0];
  const gap = intel?.competitive?.gaps?.[0];
  const wins = intel?.competitive?.wins?.[0];
  const rate = overview?.response_rate ?? null;
  const cohortRate = bench?.cohort?.median_response_rate ?? null;

  const lines: { title: string; detail: string }[] = [];
  if (first) lines.push({ title: first.title, detail: first.detail });
  if (gap) lines.push({ title: gap, detail: "What competitors do better — closing this is the cheapest win." });
  if (
    !first && !gap && total < MIN_REVIEWS_FOR_RATE && total > 0
  ) {
    lines.push({
      title: `Collect a few more reviews (${total} of ${MIN_REVIEWS_FOR_RATE})`,
      detail: "Response rate and trends stay hidden until the sample is big enough to be honest.",
    });
  }
  if (!lines.length && wins) {
    lines.push({ title: wins, detail: "Keep this going — it is already ahead of comparable businesses." });
  }
  if (!lines.length && rate != null && cohortRate != null && rate < cohortRate) {
    lines.push({
      title: `Reply faster — ${Math.round(rate)}% vs ${Math.round(cohortRate)}% nearby`,
      detail: "Comparable businesses reply to more of their reviews than you do.",
    });
  }

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink/50">What to do this week</p>
      {lines.length === 0 ? (
        <>
          <p className="mt-1 text-[22px] font-bold text-emerald">All clear</p>
          <p className="text-[10px] text-ink/40">Nothing urgent — keep the current playbook.</p>
        </>
      ) : (
        <ul className="mt-1.5 space-y-1.5">
          {lines.slice(0, 2).map((l) => (
            <li key={l.title}>
              <p className="text-[12.5px] font-semibold leading-snug text-ink">{l.title}</p>
              <p className="text-[10px] leading-snug text-ink/50">{l.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The weakest dimension from the scorecard — the thing actually costing stars.
 * Stays hidden when there is no negative signal, so it never nags an owner
 * whose business is in good shape.
 */
function StarsCostingYou({ intel }: { intel: IntelSnapshot | null }) {
  const dims = intel?.dimensions ?? [];
  const worst = dims
    .filter((d) => d.negative > 0)
    .sort((a, b) => b.negative - a.negative || a.avg_rating - b.avg_rating)[0];
  if (!worst) return null;
  return (
    <div className="rounded-2xl border-2 border-coral/30 bg-coral/[0.04] p-5 backdrop-blur-sm">
      <p className="text-[10px] font-bold uppercase tracking-widest text-coral">What&apos;s costing you stars</p>
      <p className="mt-1.5 text-[15px] font-bold text-ink">{worst.label}</p>
      <p className="mt-0.5 text-[12px] text-ink/60">
        {worst.negative} review{worst.negative === 1 ? "" : "s"} criticise it · avg {worst.avg_rating.toFixed(1)}★
      </p>
      <Link href="/dashboard/reviews" className="mt-2 inline-block text-[11px] font-semibold text-deep-violet outline-none hover:underline focus-visible:ring-2 focus-visible:ring-deep-violet/40">
        Fix this →
      </Link>
    </div>
  );
}

function CustomerVoice({ intel, loading }: { intel: IntelSnapshot | null; loading: boolean }) {
  if (loading) {
    return <div className="h-36 animate-pulse rounded-2xl border-2 border-white bg-white/60" aria-hidden />;
  }
  if (!intel || (intel.stats.total === 0 && (intel.themes ?? []).length === 0)) {
    return (
      <Link href="/dashboard/reviews" aria-label="Open reviews" className="group block rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-deep-violet/20 hover:shadow-lg hover:shadow-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40">
        <h3 className="text-[14px] font-bold text-ink transition-colors group-hover:text-deep-violet">Customer voice</h3>
        <p className="mt-1 text-[12px] text-ink/50">No analysis yet — open Reviews to run your first AI analysis and see what customers love and what hurts your rating.</p>
      </Link>
    );
  }
  const themes = intel.themes ?? [];
  const loves = themes.filter((t) => t.positive_pct >= 60).sort((a, b) => b.mentions - a.mentions).slice(0, 3);
  const hurts = themes.filter((t) => t.positive_pct < 60).sort((a, b) => a.positive_pct - b.positive_pct).slice(0, 2);
  const pos = intel.stats.positive;
  const neu = intel.stats.neutral;
  const neg = intel.stats.negative;
  const total = Math.max(1, pos + neu + neg);
  return (
    <section aria-label="Customer voice" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-[14px] font-bold text-ink">Customer voice</h3>
          <p className="text-[11px] text-ink/45">What customers praise — and what costs you stars.</p>
        </div>
        <Link href="/dashboard/reviews" className="text-[11px] font-semibold text-deep-violet outline-none hover:underline focus-visible:ring-2 focus-visible:ring-deep-violet/40">
          Full intelligence →
        </Link>
      </div>
      {intel.summary ? <p className="mt-2 line-clamp-2 text-[12.5px] leading-snug text-ink/70">{intel.summary}</p> : null}
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full" role="img" aria-label={`${pos} positive, ${neu} neutral, ${neg} negative`}>
        <div className="bg-emerald-500" style={{ width: `${(pos / total) * 100}%` }} />
        <div className="bg-amber-400" style={{ width: `${(neu / total) * 100}%` }} />
        <div className="bg-coral" style={{ width: `${(neg / total) * 100}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink/55">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-500" /> Positive {pos}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-400" /> Neutral {neu}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-coral" /> Negative {neg}</span>
        {intel.stale ? <span className="text-amber-600">Stale — re-run analysis in Reviews</span> : null}
      </div>
      {(loves.length > 0 || hurts.length > 0) && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {loves.length > 0 && (
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">Loved</p>
              <ul className="mt-1.5 space-y-1">
                {loves.map((t) => (
                  <li key={t.name} className="flex items-center justify-between gap-2 text-[12.5px]">
                    <span className="truncate font-medium text-ink">{t.name}</span>
                    <span className="shrink-0 tabular-nums text-ink/45">{t.mentions}× · {t.avg_rating.toFixed(1)}★</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {hurts.length > 0 && (
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-coral">Hurting</p>
              <ul className="mt-1.5 space-y-1">
                {hurts.map((t) => (
                  <li key={t.name} className="flex items-center justify-between gap-2 text-[12.5px]">
                    <span className="truncate font-medium text-ink">{t.name}</span>
                    <span className="shrink-0 tabular-nums text-ink/45">{t.mentions}× · {t.avg_rating.toFixed(1)}★</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
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
