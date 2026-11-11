"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApproveReply, useEditReply } from "@/lib/mutation-hooks";
import { queryKeys } from "@/lib/query-keys";
import { useSearchParams } from "next/navigation";
import Image from "next/image";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import GoogleReviewCard, { GoogleStars, ReviewAvatar } from "@/components/reviews/GoogleReviewCard";
import { streamReviewReply, type StreamEvent } from "@/lib/api-review-engine";
import { approveReply, dismissReviewEdit, editReply, generateReply, regenerateReply, rejectReply, verifyPostedReplies, type ReviewInsight, type ReviewReplyDTO } from "@/lib/api-analytics";
import { clearAbuseFlag, flagReviewAbusive, markAbuseReported, setAbuseVerdict } from "@/lib/api-abuse";
import MeaningInspector from "@/components/reviews/MeaningInspector";
import AskForReview from "@/components/dashboard/AskForReview";
import BulkReviewRequests from "@/components/dashboard/BulkReviewRequests";
import GoogleQuestionsCard from "@/components/dashboard/GoogleQuestionsCard";
import ReviewRequestLog from "@/components/dashboard/ReviewRequestLog";
import QRCodeGenerator from "@/components/dashboard/QRCodeGenerator";
import { ALL_BRANCHES, groupValue, parseGroupValue, useLocationGroups } from "@/lib/location-groups";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type IntelDict = Dict["reviews"]["intel"];
type InsightDict = Dict["reviews"]["insight"];

type HeuristicCtx = {
  hx: IntelDict;
  fmt: (n: number) => string;
  fmtRating: (n: number) => string;
};

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

type ReviewTab = "all" | "unanswered" | "replied" | "positive" | "negative" | "need_approval" | "flagged" | "edited" | "removed" | "abusive" | "needs_human";

/**
 * How many reviews the intelligence report refused to categorise.
 *
 * The report holds these back rather than guessing, but a silent holdout reads
 * as a complete report — which is how a mis-read review stayed invisible in
 * the first place. So the count travels with the report and is shown.
 */
type HeldOutCounts = {
  needs_human: number;
  not_analysed: number;
  unclassified: number;
  total: number;
};
type View = { kind: "list" } | { kind: "detail"; id: string } | { kind: "star"; stars: number; from: "list" | "intelligence" } | { kind: "intelligence" } | { kind: "ask" };

interface ReviewItem {
  id: string;
  locationId: string;
  review_id: string;
  locationName: string;
  reviewer: string;
  reviewerPhoto?: string;
  rating: number;
  comment: string;
  createdAt: string;
  replied: boolean;
  skipped: boolean;
  edited: boolean;
  editedAt: string | null;
  previousRating: number | null;
  previousText: string | null;
  sentiment?: string;
  reviewUrl?: string;
  media: { url?: string | null; kind?: string; label?: string | null }[];
  removed: boolean;
  meaning: ReviewInsight["meaning"] | null;
  abuseFlagged: boolean;
  abuseScore: number | null;
  abuseLabels: string[];
  abuseVerdict: string | null;
  abuseReported: boolean;
  reply_text?: string;
  repliedAt?: string;
  publishedReplyId?: string;
  publishedReplyText?: string;
  publishedReplyAt?: string;
  status?: string;
  replyId?: string;
  // Google's moderation state of the published reply: "pending" while Google
  // reviews it, "approved" once it is public, "rejected" if refused.
  google_reply_state?: string | null;
}

interface LocationOption {
  id: string;
  name: string;
  channelId?: string;
}

const PAGE_SIZE = 4;

const PRIMARY_TABS: ReviewTab[] = ["all", "need_approval", "edited"];
const MORE_TABS: ReviewTab[] = ["unanswered", "flagged", "replied", "positive", "negative", "needs_human", "abusive", "removed"];

export default function ReviewsPage() {
  return (
    <Suspense>
      <ReviewsInner />
    </Suspense>
  );
}

function ReviewsInner() {
  const { t, locale } = useI18n();
  const rv = t.reviews;
  const ra = rv.actions;
  const ap = rv.approval;
  const dt = rv.detail;
  const ab = rv.abuse;
  const fmtRating = (n: number) =>
    n.toLocaleString(dateLocale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const { groups } = useLocationGroups();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const approveReplyHook = useApproveReply();
  const editReplyHook = useEditReply();
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [tab, setTab] = useState<ReviewTab>("all");
  const [initialTabSet, setInitialTabSet] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  // Read tab from URL after hydration to avoid SSR mismatch
  useEffect(() => {
    if (!initialTabSet) {
      const t = searchParams.get("tab");
      if (t === "need_approval" || t === "unanswered" || t === "replied" || t === "positive" || t === "negative" || t === "all" || t === "edited") {
        setTab(t as ReviewTab);
      }
      setInitialTabSet(true);
    }
  }, [searchParams, initialTabSet]);
  const [view, setView] = useState<View>({ kind: "list" });
  // listing_id -> channel id, for resolving a group to review channels.
  const [listingChannels, setListingChannels] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [replyDraft, setReplyDraft] = useState("");
  const [replying, setReplying] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Channels already asked to verify stale rows against Google this visit.
  // The DB status is reconciled by the 60s poll, but a reply Google accepted
  // can sit "failed" until then — asking Google directly closes that gap.
  const verifiedChannels = useRef<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [needApprovalPage, setNeedApprovalPage] = useState(1);
  const [approvingAllPending, setApprovingAllPending] = useState(false);
   const [approvingId, setApprovingId] = useState<string | null>(null);
   const [pendingReplies, setPendingReplies] = useState<ReviewReplyDTO[]>([]);
   const [skippingId, setSkippingId] = useState<string | null>(null);
  const [discardingId, setDiscardingId] = useState<string | null>(null);
  const [draftTexts, setDraftTexts] = useState<Record<string, string>>({});
  // Inline editing of the shown response (any status) in review detail.
  const [editingResponse, setEditingResponse] = useState<string | null>(null);
  const [responseText, setResponseText] = useState("");
  const [savingResponse, setSavingResponse] = useState(false);
  const [regenId, setRegenId] = useState<string | null>(null);
  const [replyMode, setReplyMode] = useState<"manual" | "ai">("manual");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiTrace, setAiTrace] = useState<StreamEvent[] | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fetchInFlight = useRef(false);
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});

  // Groups key on listing_id, which is also what this page's locations are, so
  // resolving a group only means picking its members' review channels.
  const selectedGroupId = parseGroupValue(selectedId);
  const selectedGroup = selectedGroupId
    ? groups.find((g) => g.id === selectedGroupId) ?? null
    : null;
  const groupChannels = selectedGroup
    ? locations
        .filter((l) => selectedGroup.listing_ids.includes(l.id))
        .map((l) => listingChannels[l.id] ?? l.channelId)
        .filter(Boolean) as string[]
    : [];

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Native Google channels are the single source of locations now.
        const data = await apiFetch("/api/v1/channels?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string }) => channel.platform === "google_reviews")
          .map((channel: {
            id: string;
            display_name: string | null;
            listing_id?: string | null;
          }) => ({
            id: channel.listing_id ?? channel.id,
            name: channel.display_name ?? rv.header.locationFallback,
            channelId: channel.id,
          }));
        if (!cancelled) {
          const names: Record<string, string> = {};
          // listing_id -> channel id, so a group (keyed on listing_id) can
          // be resolved to the channel the reviews API filters by.
          const byListing: Record<string, string> = {};
          for (const channel of data.channels ?? []) {
            if (channel?.id) names[channel.id] = channel.display_name ?? rv.header.locationFallback;
            if (channel?.id && channel?.listing_id) byListing[channel.listing_id] = channel.id;
          }
          setChannelNames(names);
          setListingChannels(byListing);
          setLocations(googleChannels);
          if (googleChannels.length) setSelectedId(ALL_BRANCHES);
        }
      } catch {
        if (!cancelled) {
          setLocations([]);
          setSelectedId(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const loadInsights = async (channelIds?: string[]) => {
    // No channel filter = every branch (All branches). A group passes its
    // members' channels and we merge the pages, because the API takes one
    // channel at a time and a group is by definition several.
    const ids = channelIds && channelIds.length > 0 ? channelIds : [undefined];
    const pages = await Promise.all(
      ids.map(async (channelId) => {
        const base = channelId ? `channel_id=${encodeURIComponent(channelId)}&` : "";
        // Two calls on purpose. The API hides reviews Google no longer returns, so
        // the Removed tab would always be empty if we only asked for the default
        // set. Both land in one list; `removed` on the item decides which tab shows
        // it, and the counts below keep the two apart.
        const [live, gone] = await Promise.all([
          apiFetch(`/api/v1/analytics/reviews/insights?${base}limit=200`),
          apiFetch(`/api/v1/analytics/reviews/insights?${base}limit=200&removed=true`),
        ]);
        return [...(live.items ?? []), ...(gone.items ?? [])];
      }),
    );
    const fallback = locations.find((l) => l.id === selectedId)?.name ?? "";
    // The same review can arrive from overlapping calls; keep the first copy.
    const seen = new Set<string>();
    const merged: ReviewInsight[] = [];
    for (const item of pages.flat()) {
      const key = String((item as { id?: string }).id ?? "");
      if (key && seen.has(key)) continue;
      if (key) seen.add(key);
      merged.push(item as ReviewInsight);
    }
    return mapInsights(merged, channelNames, fallback, rv.userFallback);
  };

  const loadPendingReplies = async () => {
    // Same source as the dashboard "Needs attention" queue: the
    // review_replies table via /channels/{id}/reviews?status=pending_approval.
    // Use the channels already loaded by the page — re-fetching /channels here
    // doubled the request volume on every refresh.
    const ids = locations.map((l) => l.channelId).filter(Boolean) as string[];
    if (ids.length === 0) {
      setPendingReplies([]);
      return;
    }
    const lists: ReviewReplyDTO[][] = await Promise.all(
      ids.map(async (id) => {
        try {
          const r = await apiFetch(`/api/v1/channels/${id}/reviews?status=pending_approval&limit=100`);
          return (r.replies ?? []) as ReviewReplyDTO[];
        } catch {
          return [];
        }
      })
    );
    // One row per review — newest draft wins (backend may hold older duplicates).
    const seen = new Map<string, ReviewReplyDTO>();
    for (const d of lists.flat()) {
      const prev = seen.get(d.review_id);
      if (!prev || d.created_at > prev.created_at) seen.set(d.review_id, d);
    }
    const merged = [...seen.values()].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    setPendingReplies(merged);

    // Ask Google directly about stale rows once per channel per page load.
    // The endpoint only heals on definitive evidence (Google shows the reply),
    // so this is safe to run unattended.
    for (const id of ids) {
      if (verifiedChannels.current.has(id)) continue;
      verifiedChannels.current.add(id);
      void verifyPostedReplies(id)
        .then((r) => {
          if ((r.healed ?? 0) > 0) void loadPendingReplies();
        })
        .catch(() => {
          /* best effort — the next poll reconciles */
        });
    }
  };

  const fetchReviews = async (withSync: boolean) => {
    // Mutations and the Reconcile button can fire while the query is still
    // loading; one in-flight pass is enough and prevents request storms.
    if (fetchInFlight.current) return;
    fetchInFlight.current = true;
    setRefreshing(true);
    try {
      const loc = locations.find((l) => l.id === selectedId);
      const items = await loadInsights(selectedGroup ? groupChannels : loc?.channelId ? [loc.channelId] : undefined);
      setReviews(items);
      await loadPendingReplies();
      // Native Google polls on its own 5-minute cadence; this button reloads
      // the stored reviews instead of triggering a provider sync.
      if (withSync) setBanner({ kind: "ok", text: ra.refreshed });
    } catch {
      setReviews([]);
      setBanner({ kind: "err", text: ra.loadError });
    } finally {
      fetchInFlight.current = false;
      setRefreshing(false);
    }
  };

  const reviewsQuery = useQuery({
    queryKey: ["reviews", "list", selectedId, selectedGroup?.id ?? null, groupChannels.join(",")],
    queryFn: async () => {
      const loc = locations.find((l) => l.id === selectedId);
      const items = await loadInsights(selectedGroup ? groupChannels : loc?.channelId ? [loc.channelId] : undefined);
      await loadPendingReplies();
      return items;
    },
    // Wait for the channel snapshot: firing before it made the query run
    // once with an empty location list and again after channels arrived.
    enabled: !loading,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  useEffect(() => {
    const items = reviewsQuery.data;
    if (items) setReviews(items);
  }, [reviewsQuery.data]);
  useEffect(() => {
    if (reviewsQuery.isError) setReviews([]);
  }, [reviewsQuery.isError]);

  // `reviews` holds live AND removed rows; every count below is over the live
  // set only, so a review Google dropped never inflates a number the merchant
  // is judged on.
  const live = useMemo(() => reviews.filter((r) => !r.removed), [reviews]);

  const counts = useMemo(() => ({
    all: live.length,
    unanswered: live.filter((r) => !r.replied && !r.skipped).length,
    replied: live.filter((r) => r.replied).length,
    positive: live.filter((r) => r.rating >= 4).length,
    negative: live.filter((r) => r.rating <= 2).length,
    // The approval queue is the source of truth for this count.
    need_approval: pendingReplies.length,
    flagged: live.filter((r) => r.skipped).length,
    edited: live.filter((r) => r.edited).length,
    removed: reviews.length - live.length,
    abusive: live.filter((r) => r.abuseFlagged).length,
    // Readings the AI could not ground, plus reviews never analysed at all.
    // Must stay identical to the needsHumanRows filter below, or the tab count
    // disagrees with what the tab shows.
    needs_human: live.filter((r) => !r.meaning || r.meaning.needs_human === true).length,
  }), [live, reviews, pendingReplies]);

  // The Removed tab is the one view that is deliberately the opposite set.
  const removedRows = useMemo(() => reviews.filter((r) => r.removed), [reviews]);
  const abusiveRows = useMemo(() => live.filter((r) => r.abuseFlagged), [live]);
  const needsHumanRows = useMemo(
    () => live.filter((r) => !r.meaning || r.meaning.needs_human === true),
    [live]
  );
  const filtered = (
    tab === "removed"
      ? removedRows
      : tab === "abusive"
        ? abusiveRows
        : tab === "needs_human"
          ? needsHumanRows
          : live
  ).filter((r) => {
    if (tab === "removed" || tab === "abusive" || tab === "needs_human") return true;
    if (tab === "unanswered") return !r.replied && !r.skipped;
    if (tab === "replied") return r.replied;
    if (tab === "need_approval") return !r.replied && !r.skipped;
    if (tab === "positive") return r.rating >= 4;
    if (tab === "negative") return r.rating <= 2;
    if (tab === "flagged") return r.skipped;
    if (tab === "edited") return r.edited;
    return true;
  });

  const active = view.kind === "detail" ? reviews.find((r) => r.id === view.id) ?? null : null;
  const starGroup = view.kind === "star" ? live.filter((r) => r.rating === view.stars) : [];
  const intelligence = useMemo(() => buildIntelligence(live, { hx: rv.intel, fmt, fmtRating }), [live, rv.intel, fmt, fmtRating]);

  // Stored intelligence (analyze once, serve from DB; re-run on demand).
  const [aiIntel, setAiIntel] = useState<{
    intel: Intelligence; source: string; model: string | null; ragUsed: boolean;
    analyzedAt: string | null; stale: boolean; newCount: number;
    heldOut: HeldOutCounts | null;
  } | null>(null);
  const [intelLoading, setIntelLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  // Analysis interval. Presets map to `days`; the month picker sends an
  // explicit range so the backend scopes the review set and the LLM run to it.
  const [intelDays, setIntelDays] = useState(90);
  const [intelMonth, setIntelMonth] = useState("");

  const intelInterval = useMemo(() => {
    if (intelMonth) {
      const [y, m] = intelMonth.split("-").map(Number);
      const from = new Date(Date.UTC(y, m - 1, 1));
      const to = new Date(Date.UTC(y, m, 1));
      return {
        days: 0,
        date_from: from.toISOString().slice(0, 10),
        date_to: to.toISOString().slice(0, 10),
        label: from.toLocaleDateString(dateLocale, { month: "long", year: "numeric", timeZone: "UTC" }),
      };
    }
    const labels: Record<number, string> = { 7: ra.last7, 30: ra.last30, 90: ra.last90, 365: ra.last12 };
    return { days: intelDays, date_from: null as string | null, date_to: null as string | null, label: labels[intelDays] ?? fill(ra.lastNDays, { n: fmt(intelDays) }) };
  }, [intelDays, intelMonth]);

  const intelQuery = useMemo(() => {
    const p = new URLSearchParams();
    const loc = locations.find((l) => l.id === selectedId);
    if (loc?.channelId) p.set("channel_id", loc.channelId);
    if (intelInterval.date_from) {
      p.set("date_from", intelInterval.date_from);
      p.set("date_to", intelInterval.date_to!);
    } else {
      p.set("days", String(intelInterval.days));
    }
    return p.toString();
  }, [intelInterval, locations, selectedId]);

  useEffect(() => {
    if (view.kind !== "intelligence") return;
    let cancelled = false;
    setIntelLoading(true);
    (async () => {
      try {
        const data = await apiFetch(`/api/v1/analytics/review-intelligence?${intelQuery}`);
        if (!cancelled) setAiIntel(data ? mergeAiIntel(data, intelligence) : null);
      } catch {
        if (!cancelled) setAiIntel(null);
      } finally {
        if (!cancelled) setIntelLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedId, intelQuery]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    try {
      const loc = locations.find((l) => l.id === selectedId);
      const data = await apiFetch("/api/v1/analytics/review-intelligence/analyze", {
        method: "POST",
        body: JSON.stringify({
          channel_id: loc?.channelId ?? null,
          days: intelInterval.days,
          date_from: intelInterval.date_from,
          date_to: intelInterval.date_to,
        }),
      }, 180000); // LLM analysis can take a while on first run
      setAiIntel(mergeAiIntel(data, intelligence));
      setBanner({ kind: "ok", text: fill(ra.analysisStored, { label: intelInterval.label.toLowerCase() }) });
    } catch {
      setBanner({ kind: "err", text: ra.analysisFailed });
    } finally {
      setAnalyzing(false);
      setTimeout(() => setBanner(null), 3000);
    }
  };

  const NEED_APPROVAL_PAGE_SIZE = 5;

  const openDetail = (id: string) => {
    setReplyDraft("");
    setReplyMode("manual");
    setAiTrace(null);
    setAiError(null);
    setEditingResponse(null);
    setResponseText("");
    abortRef.current?.abort();
    setView({ kind: "detail", id });
  };

  function detailMsg(e: unknown, fallback: string): string {
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

  function getDraftText(d: ReviewReplyDTO): string {
    return draftTexts[d.id] ?? d.reply_text ?? "";
  }

  function isDraftEdited(d: ReviewReplyDTO): boolean {
    return (draftTexts[d.id] ?? "") !== (d.reply_text ?? "");
  }

  async function regenDraft(d: ReviewReplyDTO, engine = false) {
    setRegenId(d.id);
    try {
      const fresh = await regenerateReply(d.channel_id, d.id, engine);
      setPendingReplies((prev) => prev.map((x) => (x.id === d.id ? { ...x, reply_text: fresh.reply_text, generation_attempt: fresh.generation_attempt ?? (x.generation_attempt ?? 1) + 1 } : x)));
      setDraftTexts((prev) => ({ ...prev, [d.id]: fresh.reply_text }));
      setBanner({ kind: "ok", text: engine ? ra.rewrittenEngine : ra.rewrittenAi });
      setTimeout(() => setBanner(null), 3000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, engine ? ra.rewriteFailed : ra.regenFailed) });
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setRegenId(null);
    }
  }

  async function saveDraft(d: ReviewReplyDTO) {
    try {
      const text = getDraftText(d);
      const saved = await editReply(d.channel_id, d.id, text);
      setPendingReplies((prev) => prev.map((x) => (x.id === d.id ? { ...x, reply_text: saved.reply_text } : x)));
      setBanner({ kind: "ok", text: ra.saved });
      setTimeout(() => setBanner(null), 3000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, ra.saveEditsFailed) });
      setTimeout(() => setBanner(null), 5000);
    }
  }

  // A review can be flagged replied with no response row on file at all — the
  // reply was published outside Sayvors, so the "replied" Kafka event set the
  // flag without ever creating a ReviewReply. Nothing for the Edit card above
  // to bind to, which is why an already-answered review looked like a dead
  // end. Create the draft first, then approve it: the click is the merchant's
  // approval, and this is the only path that can republish over a live reply.
  async function publishUpdatedReply(item: ReviewItem) {
    const text = responseText.trim();
    if (!text) return;
    setSavingResponse(true);
    try {
      const row = item.replyId
        ? await editReply(item.locationId, item.replyId, text)
        : await generateReply(item.locationId, {
            review_id: item.review_id,
            rating: item.rating,
            review_text: item.comment,
            reviewer_name: item.reviewer,
            custom_text: text,
          });
      await approveReply(item.locationId, row.id);
      setReviews((prev) =>
        prev.map((r) =>
          r.id === item.id ? { ...r, replyId: row.id, reply_text: text, status: "posted" } : r
        )
      );
      setResponseText("");
      setEditingResponse(null);
      await loadPendingReplies();
      setBanner({ kind: "ok", text: ra.replyPublished });
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, ra.publishUpdateFailed) });
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setSavingResponse(false);
    }
  }

  // Every response is editable: pending edits in place, failed re-queues,
  // posted goes back to Need Approval (backend) so the update only goes
  // live after a fresh approval.
  async function saveResponse(item: ReviewItem) {
    if (!item.replyId || !responseText.trim()) return;
    setSavingResponse(true);
    try {
      const wasPosted = item.status === "posted";
      const saved = await editReplyHook.mutateAsync({ channelId: item.locationId, replyId: item.replyId, replyText: responseText.trim() });
      setReviews((prev) => prev.map((r) => r.id === item.id ? { ...r, reply_text: saved.reply_text, status: saved.status } : r));
      setEditingResponse(null);
      await loadPendingReplies();
      setBanner({
        kind: "ok",
        text: wasPosted ? ra.responseUpdatedApproval : ra.responseUpdated,
      });
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, ra.saveResponseFailed) });
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setSavingResponse(false);
    }
  }

  function responseBadge(status?: string, googleState?: string | null) {
    const base = "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide";
    // Google moderates replies: "posted" in Sayvors only means Google accepted
    // the write. Show the moderation state until Google approves it.
    if (status === "posted" && googleState === "pending") {
      return <span className={`${base} bg-amber-100 text-amber-700`}>{rv.badges.moderating}</span>;
    }
    if (status === "posted" && googleState === "rejected") {
      return <span className={`${base} bg-red-100 text-red-700`}>{rv.badges.rejectedByGoogle}</span>;
    }
    if (status === "posted") return <span className={`${base} bg-emerald-100 text-emerald-700`}>{rv.badges.published}</span>;
    if (status === "pending_approval") return <span className={`${base} bg-amber-100 text-amber-700`}>{rv.badges.pending}</span>;
    if (status === "failed") return <span className={`${base} bg-red-100 text-red-700`}>{rv.badges.failed}</span>;
    if (status === "approved") return <span className={`${base} bg-sky-100 text-sky-700`}>{rv.badges.approved}</span>;
    return <span className={`${base} bg-ink/[0.05] text-ink/40`}>{rv.badges.response}</span>;
  }

  async function approveDraft(d: ReviewReplyDTO) {
    setApprovingId(d.id);
    try {
      if (isDraftEdited(d)) await editReplyHook.mutateAsync({ channelId: d.channel_id, replyId: d.id, replyText: getDraftText(d) });
      await approveReplyHook.mutateAsync({ channelId: d.channel_id, replyId: d.id });
      setPendingReplies((prev) => prev.filter((x) => x.id !== d.id));
      setBanner({ kind: "ok", text: ra.approvedPublished });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, ra.approveFailed) });
      setTimeout(() => setBanner(null), 6000);
    } finally {
      setApprovingId(null);
    }
  }

  async function discardDraft(d: ReviewReplyDTO) {
    setDiscardingId(d.id);
    try {
      await rejectReply(d.channel_id, d.id);
      setPendingReplies((prev) => prev.filter((x) => x.id !== d.id));
      setBanner({ kind: "ok", text: ra.discarded });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, ra.discardFailed) });
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setDiscardingId(null);
    }
  }

  async function approveAllDrafts() {
    if (approvingAllPending || approvingId !== null) return;
    setApprovingAllPending(true);
    let ok = 0;
    for (const d of pendingReplies) {
      try {
        if (isDraftEdited(d)) await editReplyHook.mutateAsync({ channelId: d.channel_id, replyId: d.id, replyText: getDraftText(d) });
        await approveReplyHook.mutateAsync({ channelId: d.channel_id, replyId: d.id });
        ok += 1;
      } catch {}
    }
    setBanner({
      kind: ok === pendingReplies.length ? "ok" : "err",
      text: ok === pendingReplies.length
        ? ok === 1
          ? ra.approveAllOne
          : fill(ra.approveAllN, { n: fmt(ok) })
        : fill(ra.approveAllPartial, { ok: fmt(ok), total: fmt(pendingReplies.length) }),
    });
    setTimeout(() => setBanner(null), 5000);
    await loadPendingReplies();
    void fetchReviews(false);
    setApprovingAllPending(false);
  }

  const [abuseBusy, setAbuseBusy] = useState<string | null>(null);

  const runAbuseAction = async (
    action: "flag-abuse" | "abuse-verdict" | "abuse-reported" | "clear-abuse",
    opts: { verdict?: "confirmed" | "dismissed"; note?: string; ok: string } | null
  ) => {
    if (view.kind !== "detail" || !active) return;
    setAbuseBusy(action);
    try {
      if (action === "flag-abuse") {
        await flagReviewAbusive(active.id, opts?.note);
      } else if (action === "clear-abuse") {
        await clearAbuseFlag(active.id);
      } else if (action === "abuse-reported") {
        await markAbuseReported(active.id);
      } else {
        await setAbuseVerdict(active.id, opts?.verdict ?? "confirmed");
      }
      setBanner({ kind: "ok", text: opts?.ok ?? ra.done });
      setTimeout(() => setBanner(null), 4000);
      void fetchReviews(false);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, ra.updateReportFailed) });
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setAbuseBusy(null);
    }
  };

  const handleSkip = async () => {
    if (view.kind !== "detail") return;
    setSkippingId(active!.id);
    try {
      await apiFetch(`/api/v1/analytics/reviews/insights/${active!.id}/skip`, { method: "POST" });
      setBanner({ kind: "ok", text: ra.skipOk });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch {
      setBanner({ kind: "err", text: ra.skipFailed });
      setTimeout(() => setBanner(null), 3000);
    } finally {
      setSkippingId(null);
    }
  };

  const handleFlag = async (reviewId: string) => {
    try {
      await apiFetch(`/api/v1/analytics/reviews/insights/${reviewId}/skip`, { method: "POST" });
      setBanner({ kind: "ok", text: ra.flagOk });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch {
      setBanner({ kind: "err", text: ra.flagFailed });
      setTimeout(() => setBanner(null), 3000);
    }
  };

  const [dismissingEdit, setDismissingEdit] = useState(false);
  const handleDismissEdit = async () => {
    if (view.kind !== "detail") return;
    setDismissingEdit(true);
    try {
      await dismissReviewEdit(active!.id);
      setReviews((rs) => rs.map((r) =>
        r.id === active!.id
          ? {
              ...r,
              edited: false,
              editedAt: null,
              previousRating: null,
              previousText: null,
              reply_text: r.publishedReplyText,
              status: r.publishedReplyText ? "posted" : undefined,
              replyId: r.publishedReplyId,
            }
          : r
      ));
    } catch {
      setBanner({ kind: "err", text: ra.dismissEditFailed });
      setTimeout(() => setBanner(null), 3000);
    } finally {
      setDismissingEdit(false);
    }
  };

  const generateAiReply = async () => {
    if (view.kind !== "detail") return;
    const r = reviews.find((x) => x.id === view.id);
    if (!r) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setAiLoading(true);
    setReplyMode("ai");
    setAiError(null);
    setAiTrace([]);
    try {
      // Resolve the Automations channel for this review's location.
      // Reviews page stores channelId in ReviewItem.locationId (from insights.channel_id)
      // and also via selected location's channelId.
      const loc = locations.find((l) => l.id === selectedId);
      const channelId = (r as unknown as { locationId?: string }).locationId || loc?.channelId || selectedId || undefined;
      const reviewText = r.comment && r.comment !== "(star rating only)" ? r.comment : "";
      if (!reviewText) throw new Error(ra.starOnlyError);

      let finalText: string | null = null;
      let lastRelevance: StreamEvent["relevance"] | null = null;
      let finalStatus: string | undefined;

      for await (const ev of streamReviewReply(
        {
          review_text: reviewText,
          rating: r.rating,
          reviewer_name: r.reviewer || undefined,
          channel: "google_review",
          channel_id: channelId,
        },
        ctrl.signal,
      )) {
        setAiTrace((prev) => [...(prev ?? []), ev]);
        if (ev.step === "relevance" && ev.relevance) lastRelevance = ev.relevance;
        if (ev.relevance) lastRelevance = ev.relevance;
        if ((ev as unknown as { relevance?: StreamEvent["relevance"] }).relevance) {
          lastRelevance = (ev as unknown as { relevance: StreamEvent["relevance"] }).relevance;
        }
        if (ev.step === "done" && ev.response) {
          finalText = ev.response.response_text;
          finalStatus = (ev.response as unknown as { status?: string }).status ?? (ev.response.validation?.passed ? "approved" : "needs_review");
          // Prefer top-level relevance if present in done event
          const doneRel = (ev.response as unknown as { relevance?: StreamEvent["relevance"] }).relevance;
          if (doneRel) lastRelevance = doneRel;
          // Also check merged relevance on response
          if ((ev as unknown as { response?: { relevance?: StreamEvent["relevance"] } }).response?.relevance) {
            lastRelevance = (ev as unknown as { response: { relevance: StreamEvent["relevance"] } }).response.relevance;
          }
        }
        // Playground also emits relevance as its own step — capture it
        if (ev.relevance) lastRelevance = ev.relevance;
      }

      if (!finalText) throw new Error(ra.engineEmpty);
      setReplyDraft(finalText);

      // If the engine flagged it as possibly off-topic, surface it inline — same wording as playground.
      if (lastRelevance?.verdict === "off_topic") {
        setBanner({
          kind: "err",
          text: fill(ra.offtopic, { reason: lastRelevance.reason ?? "" }),
        });
        setTimeout(() => setBanner(null), 6000);
      } else if (finalStatus === "needs_review") {
        setBanner({ kind: "err", text: ra.needsReview });
        setTimeout(() => setBanner(null), 5000);
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      const msg = e instanceof Error ? e.message : ra.engineFailed;
      // Surface engine's own 400 when Automations model is missing
      if (msg.includes("No reply model configured") || msg.includes("Channel not found")) {
        setAiError(ra.noModel);
        setBanner({ kind: "err", text: ra.engineNotConfigured });
      } else if (msg.toLowerCase().includes("star-only")) {
        setAiError(msg);
      } else {
        // Brief fallback: keep pipeline honest — don't silently invent a template as if it were the engine.
        setAiError(msg.slice(0, 280));
        setBanner({ kind: "err", text: fill(ra.engineError, { msg: msg.slice(0, 120) }) });
      }
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setAiLoading(false);
    }
  };

  const copyDraft = async () => {
    if (view.kind !== "detail" || !replyDraft.trim()) return;
    setReplying(true);
    try {
      await navigator.clipboard.writeText(replyDraft.trim());
      setBanner({ kind: "ok", text: ra.copied });
    } catch {
      setBanner({ kind: "err", text: ra.copyFailed });
    } finally {
      setReplying(false);
      setTimeout(() => setBanner(null), 3000);
    }
  };

  // Live reviews only: a review Google dropped is not part of the average,
  // the response rate, or the distribution the merchant is judged on.
  const analytics = useMemo(() => {
    const total = live.length;
    const dist = [5, 4, 3, 2, 1].map((s) => ({ stars: s, count: live.filter((r) => r.rating === s).length }));
    const avg = total ? live.reduce((a, r) => a + r.rating, 0) / total : 0;
    const replied = live.filter((r) => r.replied).length;
    const thisMonth = live.filter((r) => r.createdAt.slice(0, 7) === "2026-09").length;
    const lastMonth = live.filter((r) => r.createdAt.slice(0, 7) === "2026-08").length;
    const months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"].map((m) => ({
      label: m.slice(5),
      count: live.filter((r) => r.createdAt.slice(0, 7) === m).length,
    }));
    const maxMonth = Math.max(1, ...months.map((m) => m.count));
    return { total, dist, avg, replied, responseRate: total ? Math.round((replied / total) * 100) : 0, thisMonth, lastMonth, months, maxMonth };
  }, [live]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const visiblePending = pendingReplies.slice(0, needApprovalPage * NEED_APPROVAL_PAGE_SIZE);

  const pickTab = (t: ReviewTab) => {
    setTab(t);
    setPage(1);
    setNeedApprovalPage(1);
  };

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-4 py-3 backdrop-blur sm:px-6 sm:py-4 dark:border-fog/[0.06] dark:bg-ink/80" data-tour="reviews-header">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog">{rv.header.title}</h1>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">
              {fill(rv.header.summary, { total: fmt(counts.all), unanswered: fmt(counts.unanswered), replied: fmt(counts.replied) })}
            </p>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <div className="relative w-full sm:w-auto">
              <select value={selectedId ?? ""} onChange={(e) => { setSelectedId(e.target.value); setPage(1); setView({ kind: "list" }); }}
                className="w-full appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog sm:w-52">
                <option value={ALL_BRANCHES}>{locations.length > 0 ? fill(rv.header.allBranchesCount, { n: fmt(locations.length) }) : rv.header.allBranches}</option>
                {groups
                  .map((g) => ({
                    id: g.id,
                    name: g.name,
                    n: g.listing_ids.filter((id) => locations.some((l) => l.id === id)).length,
                  }))
                  .filter((g) => g.n > 0)
                  .map((g) => <option key={g.id} value={groupValue(g.id)}>{g.name} ({g.n})</option>)}
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <button onClick={() => fetchReviews(true)} disabled={refreshing} className="btn-secondary flex-1 justify-center disabled:opacity-50 sm:flex-none">
              {refreshing ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> {rv.header.syncing}</span> : rv.header.reconcile}
            </button>
            <a href="/dashboard/reviews/issues" className="btn-secondary flex-1 justify-center text-center sm:flex-none">{rv.header.tickets}</a>
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{banner.text}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-4 sm:px-6 sm:py-5">
        <div className="mx-auto max-w-6xl">
          {view.kind === "detail" && (
            <nav className="mb-3 flex items-center gap-1.5 text-[11px] text-ink/40 dark:text-fog/40 sm:text-[12px]">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">{rv.header.title}</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">{rv.header.crumbDetail}</span>
            </nav>
          )}

          {view.kind === "star" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">{rv.header.title}</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              {view.from === "intelligence" ? (
                <>
                  <button onClick={() => setView({ kind: "intelligence" })} className="font-medium hover:text-deep-violet">{rv.header.crumbIntel}</button>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </>
              ) : null}
              <span className="font-semibold text-ink dark:text-fog">{fill(rv.header.crumbStar, { stars: fmt(view.stars) })}</span>
            </nav>
          )}

          {view.kind === "intelligence" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">{rv.header.title}</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">{rv.header.crumbIntel}</span>
            </nav>
          )}

{view.kind === "list" && (
              <div className="mx-auto max-w-6xl px-0 sm:px-4">
                <div className="grid grid-cols-12 gap-4">
                  {/* Left column: 3/4 - Reviews list */}
                  <div className="col-span-12 lg:col-span-8 space-y-4">
<div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto pb-1 sm:flex-wrap" role="tablist" aria-label={rv.tabs.filtersAria}>
                        {PRIMARY_TABS.map((tabKey) => (
                          <button
                            key={tabKey}
                            role="tab"
                            aria-selected={tab === tabKey}
                            onClick={() => pickTab(tabKey)}
                            className={`relative inline-flex shrink-0 items-center gap-1.5 rounded-xl border px-3 py-2 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                              tab === tabKey
                                ? tabKey === "need_approval" && counts.need_approval > 0
                                  ? "border-coral/40 bg-coral/[0.06] text-coral"
                                  : "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet"
                                : "border-ink/[0.08] bg-white text-ink/60 hover:border-ink/[0.16] hover:text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60 dark:hover:text-fog"
                            }`}
                          >
                            {rv.tabs[tabKey]} ({fmt(counts[tabKey])})
                            {tabKey === "need_approval" && counts.need_approval > 0 && (
                              <span aria-hidden className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
                                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-coral opacity-60" />
                                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-coral ring-2 ring-white dark:ring-ink" />
                              </span>
                            )}
                          </button>
                        ))}
                        <div className="relative shrink-0">
                          <button
                            aria-haspopup="menu"
                            aria-expanded={moreOpen}
                            onClick={() => setMoreOpen((o) => !o)}
                            className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                              MORE_TABS.includes(tab)
                                ? "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet"
                                : "border-ink/[0.08] bg-white text-ink/60 hover:border-ink/[0.16] hover:text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60 dark:hover:text-fog"
                            }`}
                          >
                            {MORE_TABS.includes(tab) ? `${rv.tabs[tab]} (${fmt(counts[tab])})` : rv.tabs.more}
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3 w-3 transition ${moreOpen ? "rotate-180" : ""}`}>
                              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </button>
                          {moreOpen && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setMoreOpen(false)} />
                              <div role="menu" className="absolute left-0 top-full z-20 mt-1 w-44 rounded-xl border border-ink/[0.08] bg-white py-1 shadow-lg dark:border-fog/[0.1] dark:bg-ink">
                                {MORE_TABS.map((tabKey) => (
                                  <button
                                    key={tabKey}
                                    role="menuitem"
                                    onClick={() => { pickTab(tabKey); setMoreOpen(false); }}
                                    className={`flex w-full items-center justify-between px-3 py-2 text-left text-[12px] font-medium outline-none transition hover:bg-ink/[0.03] focus-visible:bg-ink/[0.03] dark:hover:bg-fog/[0.05] ${
                                      tab === tabKey ? "font-bold text-deep-violet" : "text-ink/70 dark:text-fog/70"
                                    }`}
                                  >
                                    {rv.tabs[tabKey]}
                                    <span className="text-[11px] tabular-nums opacity-60">{fmt(counts[tabKey])}</span>
                                  </button>
                                ))}
                              </div>
                            </>
                          )}
                        </div>
                      </div>

                    {tab === "need_approval" ? (
                      pendingReplies.length === 0 ? (
                        <div className="flex flex-col items-center rounded-2xl border-2 border-dashed border-deep-violet/15 bg-white/70 px-6 py-14 text-center backdrop-blur-sm dark:border-fog/[0.12] dark:bg-ink/60">
                          <span aria-hidden className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald/10 text-2xl">✓</span>
                          <p className="mt-3 text-[14px] font-bold text-ink dark:text-fog">{ap.clearTitle}</p>
                          <p className="mt-1 max-w-xs text-[12px] leading-relaxed text-ink/45">
                            {ap.clearBody}
                          </p>
                        </div>
                      ) : (
                        <>
                          {/* Queue header */}
                          <div className="overflow-hidden rounded-2xl border-2 border-white bg-gradient-to-r from-deep-violet/[0.08] via-magenta/[0.04] to-transparent p-4 backdrop-blur-sm">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="flex items-center gap-3">
                                <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-deep-violet text-white shadow-sm shadow-deep-violet/30">
                                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                                    <path d="M3 13h4l2 3h6l2-3h4" strokeLinecap="round" strokeLinejoin="round" />
                                    <path d="M5 6h14l2 7v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5l2-7Z" strokeLinecap="round" strokeLinejoin="round" />
                                  </svg>
                                </span>
                                <div>
                                  <h3 className="text-[15px] font-bold text-ink dark:text-fog">
                                    {ap.queueTitle}
                                    <span className="ml-2 rounded-full bg-deep-violet px-2 py-0.5 text-[11px] font-bold tabular-nums text-white">{fmt(pendingReplies.length)}</span>
                                  </h3>
                                  <p className="text-[12px] text-ink/50 dark:text-fog/50">
                                    {pendingReplies.length === 1 ? ap.draftOne : fill(ap.draftN, { n: fmt(pendingReplies.length) })} {ap.draftSuffix}
                                  </p>
                                </div>
                              </div>
                              <button
                                onClick={() => void approveAllDrafts()}
                                disabled={approvingAllPending || approvingId !== null}
                                className="inline-flex items-center gap-1.5 rounded-xl bg-emerald px-4 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-emerald/25 outline-none transition hover:bg-emerald/90 focus-visible:ring-2 focus-visible:ring-emerald/40 active:scale-[0.98] disabled:opacity-50"
                              >
                                {approvingAllPending ? (
                                  <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> {ap.approvingAll}</>
                                ) : (
                                  <>
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5" aria-hidden>
                                      <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                    {ap.approveAll}
                                  </>
                                )}
                              </button>
                            </div>
                          </div>

                          {/* Draft cards */}
                          <div className="space-y-3">
                            {visiblePending.map((d) => {
                              const busy = approvingId === d.id;
                              const edited = isDraftEdited(d);
                              const text = getDraftText(d);
                              const parts = (d.reviewer_name ?? "Anonymous").trim().split(/\s+/).filter(Boolean);
                              const initials = parts.length > 1
                                ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
                                : (parts[0]?.slice(0, 2) ?? "A").toUpperCase();
                              const days = d.created_at ? Math.floor((Date.now() - new Date(d.created_at).getTime()) / 86_400_000) : null;
                              const when = days === null ? "" : days <= 0 ? ap.today : days === 1 ? ap.yesterday : days < 30 ? fill(ap.daysAgo, { n: fmt(days) }) : new Date(d.created_at).toLocaleDateString(dateLocale, { month: "short", day: "numeric" });
                              return (
                                <article
                                  key={d.id}
                                  className="rounded-2xl border-2 border-white bg-white/90 p-4 shadow-sm backdrop-blur-sm transition duration-200 hover:border-deep-violet/20 hover:shadow-md hover:shadow-deep-violet/[0.07]"
                                >
                                  {/* Reviewer */}
                                  <div className="flex items-start gap-3">
                                    <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet">
                                      {initials}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                                        <p className="truncate text-[13px] font-bold text-ink dark:text-fog">{d.reviewer_name ?? ap.anonymous}</p>
                                        <GoogleStars rating={d.rating} />
                                      </div>
                                                                            <p className="mt-0.5 text-[11px] text-ink/40">
                                        {fill(ap.leftReview, { stars: fmt(d.rating) })} · {when}
                                        {(d as ReviewReplyDTO & { review_url?: string }).review_url && (
                                          <>
                                            {" · "}
                                            <a
                                              href={(d as ReviewReplyDTO & { review_url?: string }).review_url}
                                              target="_blank"
                                              rel="noreferrer"
                                              className="font-semibold text-deep-violet underline-offset-2 hover:underline"
                                            >
                                              {ap.viewOnGoogle}
                                            </a>
                                          </>
                                        )}
                                      </p>
                                    </div>
                                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-600">
                                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                                      {ap.pending}
                                    </span>
                                  </div>

                                  {/* Original review */}
                                  {d.review_text && (
                                    <blockquote className="mt-3 rounded-r-lg border-l-[3px] border-deep-violet/30 bg-ink/[0.025] py-2 pl-3 pr-2 dark:bg-fog/[0.04]">
                                      <p className="line-clamp-3 text-[13px] italic leading-5 text-ink/65 dark:text-fog/60">&quot;{d.review_text}&quot;</p>
                                    </blockquote>
                                  )}

                                  {/* AI draft */}
                                  <div className="mt-3 rounded-xl border border-deep-violet/[0.14] bg-deep-violet/[0.03] p-3">
                                    <div className="mb-2 flex items-center justify-between gap-2">
                                      <span className="inline-flex items-center gap-1.5">
                                        <span className="inline-flex items-center gap-1 rounded-full bg-deep-violet px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white">
                                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-2.5 w-2.5" aria-hidden>
                                            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" strokeLinecap="round" strokeLinejoin="round" />
                                          </svg>
                                          {ap.aiDraft}
                                        </span>
                                        {(d.generation_attempt ?? 1) > 1 && (
                                          <span className="text-[10px] font-semibold text-ink/40 dark:text-fog/40">
                                            {fill(ap.tryN, { n: fmt(d.generation_attempt ?? 1) })}
                                          </span>
                                        )}
                                      </span>
                                      <span className="inline-flex shrink-0 items-center gap-1">
                                        <button
                                          onClick={() => void regenDraft(d, true)}
                                          disabled={regenId === d.id || busy || approvingAllPending}
                                          title={ap.runEngineTitle}
                                          className="inline-flex items-center gap-1 rounded-lg bg-deep-violet/[0.08] px-2 py-1 text-[11px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.15] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                                        >
                                          {regenId === d.id ? (
                                            <><span className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/30 border-t-deep-violet" /> {ap.engineBusy}</>
                                          ) : (
                                            <>
                                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3" aria-hidden>
                                                <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" strokeLinecap="round" strokeLinejoin="round" />
                                              </svg>
                                              {ap.runEngine}
                                            </>
                                          )}
                                        </button>
                                        <button
                                          onClick={() => void regenDraft(d)}
                                          disabled={regenId === d.id || busy || approvingAllPending}
                                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-deep-violet outline-none transition hover:bg-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                                        >
                                          {regenId === d.id ? (
                                            <><span className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/30 border-t-deep-violet" /> {ap.rewriting}</>
                                          ) : (
                                            <>
                                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3" aria-hidden>
                                                <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" strokeLinecap="round" strokeLinejoin="round" />
                                              </svg>
                                              {ap.rewrite}
                                            </>
                                          )}
                                        </button>
                                      </span>
                                    </div>
                                    <textarea
                                      value={text}
                                      onChange={(e) => setDraftTexts((prev) => ({ ...prev, [d.id]: e.target.value }))}
                                      rows={3}
                                      maxLength={1000}
                                      aria-label={ap.draftAria}
                                      className="w-full resize-y rounded-lg border border-deep-violet/[0.15] bg-white p-3 text-[13px] leading-6 text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/50 focus:ring-2 focus:ring-deep-violet/[0.12] dark:bg-ink dark:text-fog"
                                    />
                                    <div className="mt-1.5 flex items-center justify-between text-[10px] font-medium">
                                      <span className={edited ? "text-amber-600" : "text-ink/35"}>
                                        {edited ? ap.editedHint : ap.groundedHint}
                                      </span>
                                      <span className="tabular-nums text-ink/35">{fmt(text.length)}/1000</span>
                                    </div>
                                  </div>

                                  {/* Actions */}
                                  <div className="mt-3 flex flex-wrap items-center gap-2">
                                    <button
                                      onClick={() => void approveDraft(d)}
                                      disabled={busy || approvingAllPending}
                                      className="inline-flex items-center gap-1.5 rounded-xl bg-emerald px-4 py-2 text-[12px] font-bold text-white shadow-sm shadow-emerald/25 outline-none transition hover:bg-emerald/90 focus-visible:ring-2 focus-visible:ring-emerald/40 active:scale-[0.98] disabled:opacity-50"
                                    >
                                      {busy ? (
                                        <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> {ap.publishing}</>
                                      ) : (
                                        <>
                                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5" aria-hidden>
                                            <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
                                          </svg>
                                          {ap.approvePublish}
                                        </>
                                      )}
                                    </button>
                                    {edited && (
                                      <button
                                        onClick={() => void saveDraft(d)}
                                        disabled={busy}
                                        className="rounded-xl bg-deep-violet/[0.07] px-3.5 py-2 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.12] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                                      >
                                        {ap.saveEdits}
                                      </button>
                                    )}
                                    <button
                                      onClick={() => void discardDraft(d)}
                                      disabled={busy || discardingId === d.id || approvingAllPending}
                                      className="rounded-xl px-3.5 py-2 text-[12px] font-semibold text-rose-600 outline-none transition hover:bg-rose-500/[0.08] focus-visible:ring-2 focus-visible:ring-rose-500/40 disabled:opacity-50"
                                    >
                                      {discardingId === d.id ? ap.discarding : ap.discard}
                                    </button>
                                  </div>
                                </article>
                              );
                            })}
                          </div>

                          {/* See more */}
                          {visiblePending.length < pendingReplies.length && (
                            <button
                              onClick={() => setNeedApprovalPage((p) => p + 1)}
                              className="w-full rounded-xl bg-deep-violet/[0.06] py-2.5 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.1] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                            >
                              {fill(ap.seeMore, { left: fmt(pendingReplies.length - visiblePending.length) })}
                            </button>
                          )}
                        </>
                      )
                    ) : filtered.length === 0 ? (
                      <div className="flex flex-col items-center rounded-2xl border border-dashed border-ink/[0.12] bg-white py-16 dark:border-fog/[0.12] dark:bg-ink">
                          <p className="text-[14px] font-medium text-ink/40">
                            {live.length === 0 && tab === "all"
                              ? rv.list.emptyAll
                              : tab === "flagged"
                                ? rv.list.emptyFlagged
                                : tab === "edited"
                                  ? rv.list.emptyEdited
                                  : rv.list.emptyView}
                          </p>
                      </div>
                    ) : (
                      <>
                        <div className="space-y-2">
                          {paged.map((r) => (
                            <GoogleReviewCard
                              key={r.id}
                              review={{
                                id: r.id,
                                reviewer: r.reviewer,
                                reviewerPhoto: r.reviewerPhoto,
                                rating: r.rating,
                                comment: r.comment,
                                createdAt: r.createdAt,
                                locationName: r.locationName,
                                replied: r.replied,
                                replyText: r.publishedReplyText ?? r.reply_text,
                                replyAt: r.publishedReplyAt ?? r.repliedAt,
                                 skipped: r.skipped,
                                 edited: r.edited,
                                 previousText: r.previousText,
                                 previousRating: r.previousRating,
                                 sentiment: r.sentiment,
                                 reviewUrl: r.reviewUrl,
                               }}
                               onOpen={openDetail}
                               onFlag={handleFlag}
                             />
                          ))}
                        </div>
                        <div className="flex items-center justify-between pt-1">
                          <p className="text-[11px] text-ink/40">{fill(rv.list.pageOf, { page: fmt(safePage), pages: fmt(totalPages), n: fmt(filtered.length) })}</p>
                          <div className="flex gap-1">
                            <button onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1} className="btn-secondary !px-3 !py-1.5 disabled:opacity-40">{rv.list.prev}</button>
                            {Array.from({ length: totalPages }).slice(0, 5).map((_, i) => (
                              <button key={i} onClick={() => setPage(i + 1)}
                                className={`rounded-lg px-2.5 py-1.5 text-[12px] font-semibold ${safePage === i + 1 ? "bg-deep-violet text-white" : "text-ink/50 hover:bg-ink/[0.04]"}`}>
                                {fmt(i + 1)}
                              </button>
                            ))}
                            <button onClick={() => setPage(Math.min(totalPages, safePage + 1))} disabled={safePage >= totalPages} className="btn-secondary !px-3 !py-1.5 disabled:opacity-40">{rv.list.next}</button>
                          </div>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Right column: 1/4 - Insights */}
                  <div className="col-span-12 lg:col-span-4 space-y-4">
                    <GoogleQuestionsCard />
                    {/* Rating breakdown leads the column: the star mix is the
                        fastest read on business health, and it is the way in
                        to the full intelligence view. */}
                    <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                      <button onClick={() => setView({ kind: "intelligence" })} className="block w-full text-left">
                        <h3 className="text-[13px] font-semibold text-ink dark:text-fog">{rv.stats.breakdown}</h3>
                        <p className="text-[11px] text-ink/35">{rv.stats.breakdownSub}</p>
                      </button>
                      <div className="mt-3 space-y-1">
                        {analytics.dist.map((d) => (
                          <button key={d.stars} onClick={() => setView({ kind: "star", stars: d.stars, from: "list" })}
                            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-deep-violet/[0.05] hover:ring-1 hover:ring-deep-violet/20">
                            <span className="w-8 text-[11px] font-medium text-ink/50">{fmt(d.stars)} ★</span>
                            <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                              <span className="block h-full rounded-full bg-gradient-to-r from-[#FBBC05] to-[#EA4335]" style={{ width: `${analytics.total ? (d.count / analytics.total) * 100 : 0}%` }} />
                            </span>
                            <span className="w-8 text-right text-[11px] text-ink/50">{fmt(d.count)}</span>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3 text-ink/30"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                          </button>
                        ))}
                      </div>
                      <button onClick={() => setView({ kind: "intelligence" })}
                        className="mt-3 w-full rounded-xl bg-deep-violet/[0.06] py-2 text-[12px] font-bold text-deep-violet transition hover:bg-deep-violet hover:text-white">
                        {rv.stats.seeMore}
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <StatCard label={rv.stats.avg} value={`${fmt(Math.round(analytics.avg * 10) / 10)} ★`} />
                      <StatCard label={rv.stats.total} value={fmt(analytics.total)} />
                      <StatCard label={rv.stats.responseRate} value={`${fmt(analytics.responseRate)}%`} />
                      <StatCard label={rv.stats.unanswered} value={fmt(counts.unanswered)} />
                      <StatCard label={rv.stats.flagged} value={fmt(counts.flagged)} />
                    </div>
                    {/* Ask for reviews — the growth side of the same job. Lives
                        here rather than on the dashboard: a merchant comes to
                        this page to work their reviews, so "get more of them"
                        belongs beside the counts that motivate it. */}
                    <button
                      onClick={() => setView({ kind: "ask" })}
                      className="block w-full rounded-2xl border border-ink/[0.06] bg-white p-4 text-left transition hover:border-deep-violet/25 hover:bg-deep-violet/[0.02] dark:border-fog/[0.06] dark:bg-ink"
                    >
                      <div className="flex items-center gap-2.5">
                        <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                            <rect x="3" y="3" width="7" height="7" rx="1" />
                            <rect x="14" y="3" width="7" height="7" rx="1" />
                            <rect x="3" y="14" width="7" height="7" rx="1" />
                            <path d="M14 14h3v3h-3zM21 14v.01M14 21v.01M21 21v.01M18 18h.01" />
                          </svg>
                        </span>
                        <div className="min-w-0">
                          <h3 className="text-[13px] font-semibold text-ink dark:text-fog">{rv.stats.askTitle}</h3>
                          <p className="text-[11px] leading-snug text-ink/35">{rv.stats.askBody}</p>
                        </div>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="ml-auto h-3.5 w-3.5 shrink-0 text-ink/30"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </div>
                    </button>
                    <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                      <h3 className="text-[13px] font-semibold text-ink dark:text-fog">{rv.stats.trend}</h3>
                      <p className="text-[11px] text-ink/35">{fill(rv.stats.trendSub, { this: fmt(analytics.thisMonth), last: fmt(analytics.lastMonth) })}</p>
                      <div className="mt-3 flex h-24 items-end gap-2">
                        {analytics.months.map((m) => (
                          <div key={m.label} className="flex flex-1 flex-col items-center gap-1">
                            <div className="flex w-full flex-1 items-end rounded-md bg-ink/[0.04] dark:bg-fog/[0.05]">
                              <div className="w-full rounded-md bg-deep-violet/70" style={{ height: `${Math.max(6, (m.count / analytics.maxMonth) * 100)}%` }} />
                            </div>
                            <span className="text-[9px] text-ink/40">{m.label}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

          {view.kind === "star" && (
            <StarInsightPage
              stars={view.stars}
              group={starGroup}
              total={live.length}
              onBack={() => setView(view.from === "intelligence" ? { kind: "intelligence" } : { kind: "list" })}
              onOpen={(id) => openDetail(id)}
            />
          )}

          {view.kind === "detail" && active && (
            <div className="space-y-3" style={{ fontFamily: "Roboto, Arial, sans-serif" }}>
              {/* Case header — Material row */}
              <div className="rounded-lg border border-[#DADCE0] bg-white">
                {/* Top bar: avatar + identity + status + Google mark */}
                <div className="flex items-start gap-3 px-4 pt-4">
                  <ReviewAvatar name={active.reviewer} photoUrl={active.reviewerPhoto} />
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-[14px] font-medium leading-5 text-[#202124]">{active.reviewer}</h2>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] leading-4 text-[#5F6368]">
                      <span className="inline-flex items-center gap-1">
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-3.5 w-3.5">
                          <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5v-11Z" stroke="currentColor" strokeWidth={1.5} />
                          <path d="M4.5 7.5 12 13l7.5-5.5" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        {dt.postedOn}
                        <span className="font-medium tracking-tight">
                          <span className="text-[#4285F4]">G</span><span className="text-[#EA4335]">o</span><span className="text-[#FBBC05]">o</span><span className="text-[#4285F4]">g</span><span className="text-[#34A853]">l</span><span className="text-[#EA4335]">e</span>
                        </span>
                      </span>
                      <span aria-hidden className="text-[#DADCE0]">•</span>
                      <span title={active.createdAt}>{active.createdAt ? new Date(active.createdAt.length === 10 ? `${active.createdAt}T00:00:00` : active.createdAt).toLocaleDateString(dateLocale, { month: "short", day: "numeric", year: "numeric" }) : "—"}</span>
                    </div>
                    <p className="mt-1 truncate text-[12px] leading-4 text-[#5F6368]">{active.locationName}</p>
                  </div>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-[#DADCE0]">
                    <Image src="/google.svg" alt="Google" width={16} height={16} className="h-4 w-4" />
                  </span>
                </div>

                {/* Rating + status row — green for replied = In Progress pattern */}
                <div className="mx-4 mt-3 flex flex-wrap items-center gap-2 border-y border-[#E8EAED] py-3">
                  <span className="flex items-center gap-1.5">
                    <Stars rating={active.rating} />
                    <span className="text-[12px] font-medium text-[#202124]">{fmtRating(active.rating)}</span>
                  </span>
                  <span aria-hidden className="text-[#DADCE0]">•</span>
                  {active.replied ? (
                    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#137333]">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#34A853]" /> {dt.replied}
                    </span>
                  ) : active.skipped ? (
                    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#5F6368]">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#AAAAAA]" /> {dt.unavailable}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#5F6368]">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#FABB05]" /> {dt.needsReply}
                    </span>
                  )}
                  <span aria-hidden className="text-[#DADCE0]">•</span>
                  <span className="text-[12px] text-[#5F6368]">{fill(dt.updated, { when: active.createdAt ? (() => { const d = new Date(active.createdAt.length === 10 ? `${active.createdAt}T00:00:00` : active.createdAt); const days = Math.floor((Date.now() - d.getTime())/86400000); if (days<=0) return ap.today; if (days===1) return ap.yesterday; if (days<7) return fill(ap.daysAgo, { n: fmt(days) }); return d.toLocaleDateString(dateLocale, {month:"short", day:"numeric"}); })() : "—" })}</span>
                  <span className="flex-1" />
                  {active.reviewUrl && (
                    <a href={active.reviewUrl} target="_blank" rel="noreferrer" className="text-[12px] font-medium text-[#1A73E8] hover:text-[#174EA6] hover:underline underline-offset-2">
                      {dt.viewOnGoogle}
                    </a>
                  )}
                </div>

                {/* Reviewer edited this review — before/after comparison */}
                {active.edited && (
                  <div className="mx-4 mt-3 rounded-lg border border-[#FDE293] bg-[#FEF7E0]/50 px-3 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="flex items-center gap-1.5 text-[12px] font-medium text-[#B45309]">
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-3.5 w-3.5">
                          <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
                        </svg>
                        {dt.editedTitle}
                      </p>
                      <button
                        onClick={() => void handleDismissEdit()}
                        disabled={dismissingEdit}
                        className="shrink-0 rounded-full border border-[#FDE293] px-3 py-1 text-[12px] font-medium text-[#B45309] transition hover:bg-[#FEF7E0]/60 disabled:opacity-40"
                      >
                        {dismissingEdit ? dt.leaving : dt.leaveIt}
                      </button>
                    </div>
                    <p className="mt-1.5 text-[11px] leading-4 text-[#8A6A3B]">
                      {dt.leaveHint}
                    </p>
                    <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
                      {/* Before */}
                      <div className="rounded-lg border border-[#F0DCA8] bg-white/70 px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-[#B45309]">{dt.before}</span>
                          {active.previousRating != null && (
                            <span className="ml-auto inline-flex items-center gap-1.5">
                              <GoogleStars rating={active.previousRating} size="h-3 w-3" />
                              <span className="text-[11px] font-medium text-[#B45309]">{fmtRating(active.previousRating)}</span>
                            </span>
                          )}
                        </div>
                        <p className="mt-1.5 line-clamp-5 text-[12.5px] italic leading-[18px] text-[#8A6A3B] line-through decoration-[#D9B98C]/70 decoration-1">
                          {active.previousText || dt.noComment}
                        </p>
                      </div>
                      {/* After */}
                      <div className="rounded-lg border border-[#DADCE0] bg-white px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-[#5F6368]">{dt.after}</span>
                          <span className="ml-auto inline-flex items-center gap-1.5">
                            <GoogleStars rating={active.rating} size="h-3 w-3" />
                            <span className="text-[11px] font-medium text-[#202124]">{fmtRating(active.rating)}</span>
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-5 text-[12.5px] leading-[18px] text-[#202124]">
                          {active.comment || dt.noComment}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Comment — clean quote, no purple */}
                <div className="px-4 py-3">
                  <p className="whitespace-pre-wrap break-words text-[13px] leading-6 text-[#202124]">{active.comment ? `"${active.comment}"` : <span className="italic text-[#5F6368]">{dt.noComment}</span>}</p>
                  <ReviewMedia media={active.media} />
                </div>

                {/* Report to Google — the decision is ours, the filing is manual */}
                {active.abuseFlagged ? (
                  <div className="mx-4 mb-4 rounded-lg border border-[#F4B400]/40 bg-[#FEF7E0] p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-[13px] font-semibold text-[#7A4F01]">
                        {ab.title}
                      </p>
                      {active.abuseReported ? (
                        <span className="rounded-full bg-[#E6F4EA] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#137333]">
                          {ab.reported}
                        </span>
                      ) : (
                        <span className="rounded-full bg-[#FEF0C0] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#8A6100]">
                          {ab.notReported}
                        </span>
                      )}
                      <span className="flex-1" />
                      <button
                        onClick={() => void runAbuseAction("clear-abuse", { ok: ra.flagWithdrawn })}
                        disabled={abuseBusy !== null}
                        className="text-[11px] font-medium text-[#7A4F01] hover:underline disabled:opacity-40"
                      >
                        {ab.withdraw}
                      </button>
                    </div>

                    {/* AI triage — advisory only, never acts on its own */}
                    <div className="mt-2.5 rounded-md border border-[#F4B400]/30 bg-white/70 px-3 py-2.5">
                      {active.abuseScore == null ? (
                        <p className="text-[12px] text-[#7A4F01]">
                          {ab.triageUnavailable}
                        </p>
                      ) : (
                        <>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[12px] font-medium text-[#202124]">
                              {ab.triageTitle}
                            </span>
                            <span className="rounded-full bg-[#FCE8E6] px-2 py-0.5 text-[10px] font-bold text-[#C5221F]">
                              {fill(ab.violationPct, { n: fmt(Math.round(active.abuseScore * 100)) })}
                            </span>
                            {active.abuseLabels.map((l) => (
                              <span key={l} className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-medium text-ink/70">
                                {l.replace(/_/g, " ")}
                              </span>
                            ))}
                          </div>
                          <p className="mt-1.5 text-[11px] leading-4 text-[#5F6368]">
                            {ab.advisory}
                          </p>
                        </>
                      )}
                    </div>

                    {active.abuseVerdict ? (
                      <p className="mt-2.5 text-[12px] font-medium text-[#202124]">
                        {active.abuseVerdict === "confirmed" ? ab.verdictConfirmed : ab.verdictDismissed}
                      </p>
                    ) : (
                      <div className="mt-2.5 flex flex-wrap items-center gap-2">
                        <span className="text-[12px] text-[#7A4F01]">{ab.askVerdict}</span>
                        <button
                          onClick={() => void runAbuseAction("abuse-verdict", {
                            verdict: "confirmed",
                            ok: ra.confirmedReport,
                          })}
                          disabled={abuseBusy !== null}
                          className="rounded-md bg-[#7A4F01] px-3 py-1.5 text-[12px] font-medium text-white transition hover:opacity-90 disabled:opacity-50"
                        >
                          {ab.yesReport}
                        </button>
                        <button
                          onClick={() => void runAbuseAction("abuse-verdict", {
                            verdict: "dismissed",
                            ok: ra.dismissedNormal,
                          })}
                          disabled={abuseBusy !== null}
                          className="rounded-md border border-[#7A4F01]/40 px-3 py-1.5 text-[12px] font-medium text-[#7A4F01] transition hover:bg-[#FEF7E0] disabled:opacity-50"
                        >
                          {ab.noLeave}
                        </button>
                      </div>
                    )}

                    {!active.abuseReported && (
                      <div className="mt-2.5 border-t border-[#F4B400]/30 pt-2.5">
                        <p className="text-[12px] leading-5 text-[#7A4F01]">
                          {ab.howPre} <strong>{ab.howReport}</strong>{ab.howMid}
                          &nbsp;<strong>{ab.howOption}</strong> {ab.howEnd}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          {active.reviewUrl && (
                            <a
                              href={active.reviewUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="rounded-md border border-[#7A4F01]/40 px-3 py-1.5 text-[12px] font-medium text-[#7A4F01] transition hover:bg-[#FEF7E0]"
                            >
                              {ab.openGoogle}
                            </a>
                          )}
                          <button
                            onClick={() => void runAbuseAction("abuse-reported", {
                              ok: ra.markedReported,
                            })}
                            disabled={abuseBusy !== null}
                            className="rounded-md border border-[#7A4F01]/40 px-3 py-1.5 text-[12px] font-medium text-[#7A4F01] transition hover:bg-[#FEF7E0] disabled:opacity-50"
                          >
                            {abuseBusy === "abuse-reported" ? ab.saving : ab.reportDone}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  !active.removed && !active.skipped && (
                    <div className="mx-4 mb-4 flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => void runAbuseAction("flag-abuse", {
                          ok: ra.flaggedTriage,
                        })}
                        disabled={abuseBusy !== null}
                        className="rounded-md border border-[#E8EAED] px-3 py-1.5 text-[12px] font-medium text-[#5F6368] transition hover:bg-ink/[0.04] disabled:opacity-40"
                      >
                        {abuseBusy === "flag-abuse" ? ab.flagBusy : ab.flagBtn}
                      </button>
                      <span className="text-[11px] text-[#5F6368]">
                        {ab.flagHint}
                      </span>
                    </div>
                  )
                )}

                {/* Meaning — what the AI understood, and the controls to fix it */}
                <div className="px-4 pb-4">
                  <MeaningInspector
                    review={
                      {
                        id: active.id,
                        review_id: active.review_id,
                        meaning: active.meaning,
                      } as unknown as ReviewInsight
                    }
                    onSaved={(updated) => {
                      setReviews((prev) =>
                        prev.map((r) =>
                          r.id === active.id ? { ...r, meaning: updated.meaning ?? null } : r
                        )
                      );
                      setBanner({ kind: "ok", text: ra.meaningSaved });
                      setTimeout(() => setBanner(null), 4000);
                    }}
                    onError={(m) => {
                      setBanner({ kind: "err", text: m });
                      setTimeout(() => setBanner(null), 6000);
                    }}
                  />
                </div>

                {/* Reply composer — Material, not violet */}
                <div className="mx-4 mb-4 rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-4">
                  <h3 className="text-[13px] font-medium text-[#202124]">{dt.yourReply}</h3>
                  {active.publishedReplyText &&
                    active.publishedReplyText !== active.reply_text && (
                      <div className="mt-3 rounded-md border border-[#CEEAD6] bg-[#E6F4EA] px-3 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-[12px] font-medium text-[#137333]">
                            {dt.publishedReply}
                          </p>
                          {active.publishedReplyAt && (
                            <span className="text-[11px] text-[#137333]/70">
                              {new Date(active.publishedReplyAt).toLocaleDateString(dateLocale, {
                                month: "short",
                                day: "numeric",
                                year: "numeric",
                              })}
                            </span>
                          )}
                        </div>
                        <p
                          dir="auto"
                          className="mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-5 text-[#202124]"
                        >
                          {active.publishedReplyText}
                        </p>
                      </div>
                    )}
                  {active.reply_text && (
                    <div className="mt-3 rounded-md border border-[#DADCE0] bg-white px-3 py-3">
                      <div className="flex items-center gap-2">
                        <p className="text-[12px] font-medium text-[#202124]">
                          {active.publishedReplyText &&
                          active.reply_text !== active.publishedReplyText
                            ? dt.newDraft
                            : dt.yourResponse}
                        </p>
                        {responseBadge(active.status, active.google_reply_state)}
                        <span className="flex-1" />
                        {editingResponse === active.id ? null : active.replyId ? (
                          <button
                            onClick={() => { setEditingResponse(active.id); setResponseText(active.reply_text ?? ""); }}
                            className="text-[12px] font-medium text-[#1A73E8] hover:underline"
                          >
                            {dt.edit}
                          </button>
                        ) : null}
                      </div>
                      {editingResponse === active.id ? (
                        <>
                          <textarea
                            value={responseText}
                            onChange={(e) => setResponseText(e.target.value)}
                            rows={4}
                            maxLength={1000}
                            autoFocus
                            className="mt-2 min-h-[96px] w-full resize-y rounded-md border border-[#DADCE0] bg-white px-3 py-2.5 text-[13px] leading-5 text-[#202124] outline-none focus:border-[#1A73E8] focus:ring-1 focus:ring-[#1A73E8]"
                          />
                          {active.status === "posted" && (
                            <p className="mt-1.5 text-[11px] leading-4 text-[#5F6368]">
                              {dt.approvalHint}
                            </p>
                          )}
                          <div className="mt-2 flex items-center justify-end gap-2">
                            <button
                              onClick={() => setEditingResponse(null)}
                              disabled={savingResponse}
                              className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[#5F6368] hover:bg-ink/[0.04] disabled:opacity-40"
                            >
                              {dt.cancel}
                            </button>
                            <button
                              onClick={() => void saveResponse(active)}
                              disabled={!responseText.trim() || savingResponse}
                              className="rounded-md bg-[#1A73E8] px-4 py-1.5 text-[12px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50"
                            >
                              {savingResponse ? dt.saving : dt.saveResponse}
                            </button>
                          </div>
                        </>
                      ) : (
                        <p className="mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-5 text-[#202124]">{active.reply_text}</p>
                      )}
                    </div>
                  )}
                  {active.removed ? (
                    <div className="mt-2 flex items-start gap-2 rounded-md border border-[#E8EAED] bg-[#F8F9FA] px-3 py-2.5">
                      <span aria-hidden className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-[#AAAAAA]" />
                      <div>
                        <p className="text-[12px] font-medium text-[#5F6368]">{dt.removedTitle}</p>
                        <p className="mt-0.5 text-[12px] leading-4 text-[#5F6368]/80">
                          {dt.removedBody}
                        </p>
                      </div>
                    </div>
                  ) : active.replied ? (
                     <>
                       <div className="mt-2 flex items-start gap-2 rounded-md border border-[#CEEAD6] bg-[#E6F4EA] px-3 py-2.5">
                         <span aria-hidden className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-[#34A853]" />
                         <div>
                           <p className="text-[12px] font-medium text-[#137333]">{dt.repliedTitle}</p>
                           <p className="mt-0.5 text-[12px] leading-4 text-[#137333]/80">
                             {active.reply_text
                                ? dt.repliedHasText
                               : dt.repliedNoText}
                           </p>
                         </div>
                       </div>
                       {!active.replyId && editingResponse !== active.id && (
                         <button
                           onClick={() => {
                             setEditingResponse(active.id);
                             setResponseText(active.reply_text ?? "");
                           }}
                           className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-[#1A73E8] px-3 py-1.5 text-[12px] font-medium text-[#1A73E8] transition hover:bg-[#E8F0FE]"
                         >
                           {dt.editRepublish}
                         </button>
                       )}
                       {!active.replyId && editingResponse === active.id && (
                         <div className="mt-3">
                           <label className="text-[12px] font-medium text-[#202124]" htmlFor="update-reply">
                             {dt.liveReplyLabel}
                           </label>
                           <textarea
                             id="update-reply"
                             value={responseText}
                             onChange={(e) => setResponseText(e.target.value)}
                             rows={4}
                             maxLength={1000}
                             placeholder={dt.liveReplyPh}
                             className="mt-2 min-h-[96px] w-full resize-y rounded-md border border-[#DADCE0] bg-white px-3 py-2.5 text-[13px] leading-5 text-[#202124] placeholder:text-[#5F6368]/60 outline-none focus:border-[#1A73E8] focus:ring-1 focus:border-[#1A73E8]"
                           />
                           <div className="mt-2 flex items-center justify-end gap-2">
                             <button
                               onClick={() => { setEditingResponse(null); setResponseText(""); }}
                               disabled={savingResponse}
                               className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[#5F6368] hover:bg-ink/[0.04] disabled:opacity-40"
                             >
                               Cancel
                             </button>
                             <button
                               onClick={() => void publishUpdatedReply(active)}
                               disabled={!responseText.trim() || savingResponse}
                               className="rounded-md bg-[#1A73E8] px-4 py-1.5 text-[12px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50"
                             >
                               {savingResponse ? dt.publishing : dt.republish}
                             </button>
                           </div>
                           <p className="mt-1.5 text-[11px] leading-4 text-[#5F6368]">
                             {dt.publishHint}
                           </p>
                         </div>
                       )}
                     </>
                   ) : active.skipped ? (
                     <div className="mt-2 flex items-start gap-2 rounded-md border border-[#E8EAED] bg-[#F8F9FA] px-3 py-2.5">
                       <span aria-hidden className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-[#AAAAAA]" />
                       <div>
                         <p className="text-[12px] font-medium text-[#5F6368]">{dt.skippedTitle}</p>
                         <p className="mt-0.5 text-[12px] leading-4 text-[#5F6368]/80">The reviewer deleted this review or Google removed it. {dt.skippedBody}</p>
                       </div>
                     </div>
                   ) : (
                     <>
                       <div className="mt-3 inline-flex rounded-full border border-[#DADCE0] bg-white p-1">
                         <button
                           onClick={() => setReplyMode("manual")}
                           className={`rounded-full px-3 py-1 text-[12px] font-medium transition ${replyMode === "manual" ? "bg-[#1A73E8] text-white shadow-sm" : "text-[#5F6368] hover:text-[#202124]"}`}
                         >
                           {dt.writeSelf}
                         </button>
                         <button
                           onClick={() => generateAiReply()}
                           className={`rounded-full px-3 py-1 text-[12px] font-medium transition ${replyMode === "ai" ? "bg-[#1A73E8] text-white shadow-sm" : "text-[#5F6368] hover:text-[#202124]"}`}
                         >
                           {dt.writeAi}
                         </button>
                       </div>
                       <button
                         onClick={() => void handleSkip()}
                         disabled={skippingId === active?.id}
                         className="mt-2 inline-flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-medium text-[#5F6368] transition hover:bg-ink/[0.04] disabled:opacity-40"
                       >
                         {skippingId === active?.id ? dt.marking : dt.markUnavailable}
                       </button>
                      {aiLoading ? (
                        <div className="mt-3 space-y-2 rounded-md border border-[#DADCE0] bg-white px-3 py-3">
                          <div className="flex items-center gap-2">
                            <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#DADCE0] border-t-[#1A73E8]" />
                            <p className="text-[12px] font-medium text-[#202124]">{dt.engineBusy}</p>
                          </div>
                          <p className="text-[11px] leading-4 text-[#5F6368]">
                            {dt.engineSameAs} <a href="/dashboard/reviews/playground" target="_blank" rel="noreferrer" className="font-medium text-[#1A73E8] hover:underline">{dt.playground}</a> {dt.engineSteps}
                          </p>
                          {aiTrace && aiTrace.length > 0 && (
                            <div className="max-h-48 overflow-auto rounded bg-[#F8F9FA] px-2 py-2 font-mono text-[10px] leading-4 text-[#5F6368] scrollbar-thin">
                              {aiTrace.map((ev, i) => {
                                let resultLabel: string | null = null;
                                if (ev.result) {
                                  try {
                                    const parsed = JSON.parse(ev.result);
                                    if (typeof parsed.count === "number") {
                                      resultLabel = `${parsed.count} result(s)${parsed.count === 0 ? " — no verified product, so no pitch" : ""}`;
                                    }
                                  } catch {
                                    resultLabel = ev.result.slice(0, 160);
                                  }
                                }
                                return (
                                  <div key={i} className="py-0.5">
                                    <span className="font-medium text-[#202124]">{ev.step}</span>
                                    {ev.message ? ` — ${ev.message}` : ""}
                                    {ev.model ? ` (${ev.model})` : ""}
                                    {ev.relevance ? ` • relevance: ${ev.relevance.verdict}` : ""}
                                    {ev.tool ? ` • ${ev.tool} ${ev.args ? JSON.stringify(ev.args) : ""}` : ""}
                                    {resultLabel ? <span className="block truncate pl-2 text-[#137333]">→ {resultLabel}</span> : null}
                                    {ev.strategy ? ` • ${ev.strategy.name ?? ev.strategy.id ?? ""}` : ""}
                                    {ev.issues ? ` • ${ev.issues.length} issue(s)` : ""}
                                    {ev.requirements ? ` • ${ev.requirements.length} requirements` : ""}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      ) : (
                        <>
                          <textarea
                            value={replyDraft}
                            onChange={(e) => { setReplyDraft(e.target.value); setReplyMode("manual"); }}
                            rows={4}
                            maxLength={1000}
                            placeholder={replyMode === "ai" ? dt.aiPh : dt.manualPh}
                            className="mt-3 min-h-[96px] w-full resize-y rounded-md border border-[#DADCE0] bg-white px-3 py-2.5 text-[13px] leading-5 text-[#202124] placeholder:text-[#5F6368]/60 outline-none focus:border-[#1A73E8] focus:ring-1 focus:ring-[#1A73E8]"
                          />
                          {aiError && (
                            <p className="mt-2 rounded-md border border-[#FAD2CF] bg-[#FCE8E6] px-2.5 py-2 text-[12px] leading-4 text-[#C5221F]">{aiError}</p>
                          )}
                          {aiTrace && aiTrace.length > 0 && !aiError && (
                            <details className="mt-2 rounded-md border border-[#E8EAED] bg-white" open>
                              <summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-medium text-[#1A73E8] hover:underline">
                                {fill(dt.traceSummary, { n: fmt(aiTrace.length) })}
                              </summary>
                              <div className="max-h-64 overflow-auto border-t border-[#E8EAED] bg-[#FCFDFF] px-3 py-2 font-mono text-[10px] leading-4 text-[#5F6368]">
                                {aiTrace.map((ev, i) => (
                                  <div key={i} className="border-b border-[#F1F3F4] py-1 last:border-0">
                                    <div>
                                      <span className="font-medium text-[#202124]">{ev.step}</span>
                                      {ev.message ? ` — ${ev.message}` : ""}
                                      {ev.model ? ` (${ev.model})` : ""}
                                      {ev.relevance ? ` • relevance: ${ev.relevance.verdict} — ${ev.relevance.reason ?? ""}` : ""}
                                    </div>
                                    {ev.tool && (
                                      <div className="ml-2 mt-0.5 rounded bg-white px-1.5 py-0.5 ring-1 ring-[#E8EAED]">
                                        🔧 {ev.tool} {ev.args ? JSON.stringify(ev.args) : ""}
                                      </div>
                                    )}
                                    {ev.result &&
                                      (() => {
                                        let label = ev.result.slice(0, 300);
                                        try {
                                          const p = JSON.parse(ev.result);
                                          if (typeof p.count === "number") {
                                            label = `${p.count} result(s) — ${p.count === 0 ? "no verified product, so no pitch (correct)" : JSON.stringify(p.results?.[0] ?? "").slice(0, 120)}`;
                                          }
                                        } catch {}
                                        return <div className="ml-2 mt-0.5 break-all text-[#137333]">→ {label}</div>;
                                      })()}
                                    {ev.strategy && (
                                      <div className="ml-2 mt-0.5">
                                        STRATEGY: {ev.strategy.name ?? ev.strategy.id} {ev.strategy.reason ? `— ${ev.strategy.reason}` : ""}
                                        {ev.strategy.condition_note ? ` (${ev.strategy.condition_note})` : ""}
                                      </div>
                                    )}
                                    {ev.issues && ev.issues.length > 0 && (
                                      <div className="ml-2 mt-0.5 space-y-0.5">
                                        {ev.issues.map((iss: { label: string; detail: string }, j: number) => (
                                          <div key={j}>
                                            ISSUE: {iss.label} — {iss.detail}
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                    {ev.requirements && <div className="ml-2 mt-0.5 whitespace-pre-wrap break-words">{ev.requirements.map((r: string, j: number) => <div key={j}>• {r}</div>)}</div>}
                                    {ev.fulfillment && (
                                      <div className="ml-2 mt-0.5 space-y-0.5">
                                        {ev.fulfillment.map((f: { strategy: string; status: string; reason: string }, j: number) => (
                                          <div key={j} className={f.status === "pass" ? "text-[#137333]" : "text-[#C5221F]"}>
                                            {f.status.toUpperCase()}: {f.strategy} — {f.reason}
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                    {ev.claims && ev.claims.length > 0 && (
                                      <div className="ml-2 mt-0.5 space-y-0.5">
                                        {ev.claims.map((c: { claim: string; status: string; kind: string }, j: number) => (
                                          <div key={j} className={c.status === "GROUNDED" ? "text-[#137333]" : "text-[#C5221F]"}>
                                            {c.status}: “{c.claim.slice(0, 80)}” [{c.kind}]
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                    {ev.checks && (
                                      <div className="ml-2 mt-0.5 flex flex-wrap gap-1">
                                        {Object.entries(ev.checks).map(([k, v]) => (
                                          <span key={k} className={`rounded px-1 py-0.5 text-[9px] font-medium ${v ? "bg-[#E6F4EA] text-[#137333]" : "bg-[#FCE8E6] text-[#C5221F]"}`}>
                                            {v ? "✓" : "✗"} {k}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                ))}
                                <a href="/dashboard/reviews/playground" target="_blank" rel="noreferrer" className="mt-2 inline-block font-sans text-[11px] font-medium text-[#1A73E8] hover:underline">
                                  {dt.openPlayground}
                                </a>
                              </div>
                            </details>
                          )}
                        </>
                      )}
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {replyMode === "ai" && !aiLoading && (
                          <button onClick={() => generateAiReply()} className="text-[12px] font-medium text-[#1A73E8] hover:underline">
                            {replyDraft ? dt.regen : dt.generate}
                          </button>
                        )}
                        <span className="flex-1" />
                        <span className="text-[11px] text-[#5F6368]">{fmt(replyDraft.length)}/1000</span>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button onClick={() => copyDraft()} disabled={!replyDraft.trim() || replying || aiLoading} className="inline-flex items-center justify-center rounded-md bg-[#1A73E8] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50">
                          {replying ? <span className="inline-flex items-center gap-1.5"><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> {dt.copying}</span> : dt.copyDraft}
                        </button>
                        <span className="inline-flex items-center text-[11px] leading-4 text-[#5F6368]">{dt.copyHint}</span>
                      </div>
                      <p className="mt-2 text-[11px] leading-4 text-[#5F6368]">{dt.powered}</p>
                    </>
                  )}
                </div>

                {/* Meta — subtle gray, icon style */}
                <div className="flex flex-wrap gap-4 border-t border-[#E8EAED] px-4 py-3 text-[12px]">
                  <span className="inline-flex items-center gap-1.5 text-[#5F6368]">
                    <span aria-hidden className="text-[11px]">◐</span> {dt.sentiment} <span className="font-medium capitalize text-[#202124]">{active.sentiment ?? "—"}</span>
                  </span>
                  <span aria-hidden className="text-[#E8EAED]">|</span>
                  <span className="inline-flex items-center gap-1.5 text-[#5F6368]">
                    <span aria-hidden>🗓</span> {active.createdAt || "—"}
                  </span>
                </div>
              </div>

              <div className="rounded-lg border border-[#DADCE0] bg-white">
                <InsightCard review={active} />
              </div>
              <button onClick={() => setView({ kind: "list" })} className="text-[13px] font-medium text-[#1A73E8] hover:underline">{dt.back}</button>
            </div>
          )}

          {view.kind === "intelligence" && (
            <IntelligencePage
              intelligence={aiIntel?.intel ?? intelligence}
              total={reviews.length}
              locationName={locations.find((l) => l.id === selectedId)?.name ?? ""}
              aiMeta={aiIntel ? { source: aiIntel.source, model: aiIntel.model, ragUsed: aiIntel.ragUsed, analyzedAt: aiIntel.analyzedAt, stale: aiIntel.stale, newCount: aiIntel.newCount, heldOut: aiIntel.heldOut } : null}
              aiLoading={intelLoading}
              analyzing={analyzing}
              onAnalyze={() => runAnalysis()}
              onBack={() => setView({ kind: "list" })}
              onOpenStar={(s) => setView({ kind: "star", stars: s, from: "intelligence" })}
              intelDays={intelDays}
              intelMonth={intelMonth}
              intelInterval={intelInterval}
              setIntelDays={setIntelDays}
              setIntelMonth={setIntelMonth}
            />
          )}

          {view.kind === "ask" && (
            <>
              <nav className="mb-4 flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
                <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">{rv.header.title}</button>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                <span className="font-semibold text-ink dark:text-fog">{rv.stats.askTitle}</span>
              </nav>
              {/* Two ways to get more reviews: share a link with contacts, or
                  put the QR on the counter. Both lived on the dashboard, where
                  they competed with the numbers for the same attention. */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <AskForReview />
                <QRCodeGenerator />
              </div>
              <div className="mt-4">
                <BulkReviewRequests
                  channelId={
                    selectedId && selectedId !== ALL_BRANCHES
                      ? locations.find((l) => l.id === selectedId)?.channelId ?? null
                      : null
                  }
                />
              </div>
              <div className="mt-4">
                <ReviewRequestLog />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Photos a reviewer attached to the review. The API stores our own copy and
// returns a path relative to the API origin, so it is prefixed here the same
// way every other API call is.
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

function ReviewMedia({ media }: { media: ReviewItem["media"] }) {
  const { t, locale } = useI18n();
  const dt = t.reviews.detail;
  const num = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const photos = (media ?? []).filter((m) => m && m.kind !== "video" && m.url);
  const videos = (media ?? []).filter((m) => m && m.kind === "video");
  if (photos.length === 0 && videos.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {photos.map((m, i) => {
        const src = String(m.url).startsWith("http") ? String(m.url) : `${API_ORIGIN}${m.url}`;
        return (
          <a key={i} href={src} target="_blank" rel="noreferrer" className="group relative block">
            {/* Plain img: Google serves review photos from arbitrary hosts
                (googleusercontent, wikimedia, ...). next/image would reject
                any host that is not on a fixed allowlist. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={src}
              alt={m.label || fill(dt.mediaPhoto, { i: num(i + 1) })}
              width={96}
              height={96}
              loading="lazy"
              className="h-24 w-24 rounded-lg border border-[#E8EAED] object-cover transition group-hover:opacity-80"
            />
          </a>
        );
      })}
      {videos.map((m, i) => (
        <span
          key={`v${i}`}
          title={m.label || dt.mediaVideo}
          className="inline-flex h-24 w-24 items-center justify-center rounded-lg border border-[#E8EAED] bg-[#F8F9FA] text-[11px] text-[#5F6368]"
        >
          {dt.mediaVideoShort}
        </span>
      ))}
    </div>
  );
}

function mapInsights(raw: unknown, channelNames: Record<string, string>, fallbackName: string, fallbackUser: string): ReviewItem[] {  if (!Array.isArray(raw)) return [];
  return raw.map((it: unknown, i: number) => {
    const r = (it ?? {}) as Record<string, unknown>;
    const channelId = String(r.channel_id ?? "");
    return {
      id: String(r.id ?? r.review_id ?? `insight_${i}`),
      review_id: String(r.review_id ?? r.id ?? ""),
      locationId: channelId,
      locationName: channelNames[channelId] ?? fallbackName,
      reviewer: String(r.reviewer_name ?? fallbackUser),
      reviewerPhoto: typeof r.reviewer_photo_url === "string" ? r.reviewer_photo_url : undefined,
      rating: Number(r.rating ?? 0),
      comment: String(r.review_text ?? "(star rating only)"),
      createdAt: String(r.review_updated_at ?? r.created_at ?? "").slice(0, 10),
      replied: r.replied === true,
      skipped: r.skipped === true,
      edited: r.edited === true,
      editedAt: typeof r.edited_at === "string" ? r.edited_at : null,
      previousRating: typeof r.previous_rating === "number" ? r.previous_rating : null,
      previousText: typeof r.previous_review_text === "string" ? r.previous_review_text : null,
      sentiment: typeof r.sentiment === "string" ? r.sentiment : undefined,
      reviewUrl: typeof r.review_url === "string" ? r.review_url : undefined,
      media: Array.isArray(r.media) ? (r.media as ReviewItem["media"]) : [],
      removed: typeof r.removed_at === "string",
      meaning: (r.meaning as ReviewItem["meaning"]) ?? null,
      abuseFlagged: r.abuse_flagged === true,
      abuseScore: typeof r.abuse_score === "number" ? r.abuse_score : null,
      abuseLabels: Array.isArray(r.abuse_labels) ? r.abuse_labels.map(String) : [],
      abuseVerdict: typeof r.abuse_verdict === "string" ? r.abuse_verdict : null,
      abuseReported: typeof r.abuse_reported_at === "string",
      reply_text: typeof r.reply_text === "string" ? r.reply_text : undefined,
      repliedAt: typeof r.replied_at === "string" ? r.replied_at : undefined,
      publishedReplyId: typeof r.published_reply_id === "string" ? r.published_reply_id : undefined,
      publishedReplyText: typeof r.published_reply_text === "string" ? r.published_reply_text : undefined,
      publishedReplyAt: typeof r.published_reply_at === "string" ? r.published_reply_at : undefined,
      // The API sends the response row's state as `reply_status`; reading
      // `status` always yielded undefined, so the badge and the
      // "sends this back for approval" hint never rendered.
      status: typeof r.reply_status === "string" ? r.reply_status : undefined,
      replyId: typeof r.reply_id === "string" ? r.reply_id : undefined,
      google_reply_state: typeof r.reply_state === "string" ? r.reply_state : null,
    };
  });
}

function StarInsightPage({ stars, group, total, onBack, onOpen }: { stars: number; group: ReviewItem[]; total: number; onBack: () => void; onOpen: (id: string) => void }) {
  const { t, locale } = useI18n();
  const st = t.reviews.star;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const share = total ? Math.round((group.length / total) * 100) : 0;
  const replied = group.filter((r) => r.replied).length;
  const signals = topSignals(group.map((r) => r.comment));
  const band = stars >= 4 ? "high" : stars === 3 ? "mid" : "low";
  const verdict = band === "high" ? st.verdictHigh : band === "mid" ? st.verdictMid : st.verdictLow;
  const action = band === "high" ? st.actionHigh : band === "mid" ? st.actionMid : st.actionLow;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[17px] font-bold text-ink dark:text-fog">{fill(st.title, { stars: fmt(stars) })}</h2>
          <p className="text-[12px] text-ink/55 dark:text-fog/60">{fill(st.subtitle, { n: fmt(group.length), pct: fmt(share), r: fmt(replied), t: fmt(group.length) })}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${stars >= 4 ? "bg-emerald-100 text-emerald-700" : stars === 3 ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"}`}>
          {band === "high" ? st.high : band === "mid" ? st.mixed : st.low}
        </span>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">{st.overview}</h3>
          <p className="text-[12px] leading-relaxed text-ink/60">{verdict}</p>
          <p className="mt-3 text-[12px] text-ink/60">{fill(st.shareResponse, { share: fmt(share), resp: fmt(group.length ? Math.round((replied / group.length) * 100) : 0) })}</p>
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">{st.topSignals}</h3>
          {signals.length ? (
            <ul className="space-y-2">
              {signals.map((s) => (
                <li key={s} className="rounded-lg bg-ink/[0.04] px-2.5 py-1.5 text-[12px] font-semibold text-ink/70">{s}</li>
              ))}
            </ul>
          ) : <p className="text-[12px] text-ink/40">{group.length ? st.noSignals : st.noReviews}</p>}
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">{st.recommended}</h3>
          <p className="text-[12px] leading-relaxed text-ink/60">{action}</p>
          <p className="mt-3 text-[11px] text-ink/40">{st.derived}</p>
        </section>
      </div>
      <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
        <h3 className="mb-2 text-[13px] font-semibold text-ink dark:text-fog">{st.matching}</h3>
        {group.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-ink/40">{st.noReviews}</p>
        ) : (
          <div className="space-y-1.5">
            {group.map((r) => (
              <button key={r.id} onClick={() => onOpen(r.id)} className="block w-full truncate rounded-lg px-2.5 py-2 text-left text-[12px] text-ink/70 ring-1 ring-ink/[0.05] hover:ring-deep-violet/30 dark:text-fog/70">
                <span className="font-semibold text-ink dark:text-fog">{r.reviewer}</span> — &quot;{r.comment}&quot;
              </button>
            ))}
          </div>
        )}
      </div>
      <button onClick={onBack} className="text-[12px] font-medium text-ink/40 hover:text-ink">{st.back}</button>
    </div>
  );
}

function topSignals(comments: string[]): string[] {
  const lex = ["wait", "slow", "staff", "service", "clean", "price", "friendly", "quick", "helpful", "busy", "support", "quality"];
  const counts = lex.map((w) => ({ w, c: comments.filter((t) => t.toLowerCase().includes(w)).length })).filter((x) => x.c > 0);
  if (counts.length) {
    return counts.sort((a, b) => b.c - a.c).slice(0, 4).map((x) => `${x.w} ×${x.c}`);
  }
  // No lexicon hits — fall back to the most frequent meaningful words
  // actually present in the comments, so the panel never lies about data.
  const stop = new Set(["that", "this", "with", "from", "have", "still", "they", "them", "your", "about", "there", "their", "what", "when", "which", "were", "been", "very", "just", "will", "would", "could", "should", "much", "more", "most", "than", "then", "also", "well", "even", "only", "into", "over", "such", "using", "star", "rating", "only"]);
  const freq = new Map<string, number>();
  for (const t of comments) {
    for (const w of t.toLowerCase().match(/[a-z]{4,}/g) ?? []) {
      if (!stop.has(w)) freq.set(w, (freq.get(w) ?? 0) + 1);
    }
  }
  return [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([w, c]) => `${w} ×${c}`);
}

interface IntelTheme {
  name: string;
  keywords: string[];
  mentions: number;
  avgRating: number;
  positivePct: number;
  phrases: string[];
  sampleIds: string[];
}

interface IntelDimension {
  key: string;
  label: string;
  standard: boolean;
  mentions: number;
  positive: number;
  negative: number;
  avg_rating: number;
  positive_pct: number;
  signal: "strong" | "mixed" | "weak";
  confidence: "low" | "medium" | "high";
  verdict: string;
  evidence: { quote: string; rating: number }[];
}

interface IntelCompetitive {
  wins: string[];
  gaps: string[];
  scope: string | null;
}

interface Intelligence {
  avg: number;
  sentimentScore: number;
  sentimentLabel: string;
  confidence: number;
  summary: string;
  love: IntelTheme[];
  dislike: IntelTheme[];
  drivers: { theme: string; s5: number; s4: number; s3: number; low: number }[];
  opportunities: { level: "HIGH" | "MEDIUM" | "MAINTAIN"; title: string; detail: string; impact: string }[];
  strengths: { title: string; mentions: number; avg: number }[];
  sentimentSplit: { positive: number; neutral: number; negative: number };
  topics: { name: string; count: number }[];
  actions: { title: string; detail: string }[];
  /** Business Health Scorecard — only dimensions with mentions > 0 arrive. */
  dimensions: IntelDimension[];
  /** Where this business leads / trails the cohort. */
  competitive: IntelCompetitive;
}

// Local dimension set for the instant heuristic view. `key` matches the
// backend taxonomy (analytics/dimensions.py) so AI and heuristic scorecards
// line up; "Quality" and "Cleanliness" collapse into the canonical
// Product/Service Quality and Cleanliness & Environment dimensions server-side.
const THEME_DEFS: { name: string; keywords: string[]; key: string }[] = [
  { key: "support", name: "Staff & Service", keywords: ["staff", "service", "helpful", "professional", "friendly", "welcoming"] },
  { key: "quality", name: "Quality", keywords: ["quality", "great", "excellent", "good"] },
  { key: "environment", name: "Cleanliness", keywords: ["clean"] },
  { key: "speed", name: "Speed", keywords: ["fast", "quick", "slow", "wait", "queue"] },
  { key: "value", name: "Value", keywords: ["price", "pricing", "expensive", "value", "cheap"] },
  { key: "credibility", name: "Communication", keywords: ["communication", "response", "support", "rude"] },
  { key: "availability", name: "Availability", keywords: ["busy", "availability", "wait", "long"] },
  { key: "location", name: "Location", keywords: ["location", "parking", "area"] },
];

/** Reviews touching a dimension's keywords — the basis for pos/neg counts. */
function matchedRows(keywords: string[], reviews: ReviewItem[]): ReviewItem[] {
  return reviews.filter((r) => keywords.some((k) => r.comment.toLowerCase().includes(k)));
}

function buildIntelligence(reviews: ReviewItem[], ctx: HeuristicCtx): Intelligence {
  const { hx, fmt, fmtRating } = ctx;
  const total = reviews.length;
  const avg = total ? reviews.reduce((a, r) => a + r.rating, 0) / total : 0;
  const pos = reviews.filter((r) => r.rating >= 4).length;
  const neu = reviews.filter((r) => r.rating === 3).length;
  const neg = reviews.filter((r) => r.rating <= 2).length;
  const sentimentScore = total ? Math.round((pos / total) * 5 * 10) / 10 : 0;
  const sentimentLabel = !total ? hx.noData : pos / total >= 0.6 ? hx.sentimentPos : neg / total >= 0.4 ? hx.sentimentNeg : hx.sentimentMix;

  const themeStats = (def: { name: string; keywords: string[] }): IntelTheme => {
    const matched = reviews.filter((r) => def.keywords.some((k) => r.comment.toLowerCase().includes(k)));
    const mentions = matched.length;
    const avgRating = mentions ? matched.reduce((a, r) => a + r.rating, 0) / mentions : 0;
    const positivePct = mentions ? Math.round((matched.filter((r) => r.rating >= 4).length / mentions) * 100) : 0;
    const phrases = Array.from(new Set(
      matched.flatMap((r) => r.comment.split(/[.,!]/).map((s) => s.trim()).filter((s) => def.keywords.some((k) => s.toLowerCase().includes(k))).slice(0, 1))
    )).slice(0, 3);
    return { name: def.name, keywords: def.keywords, mentions, avgRating, positivePct, phrases, sampleIds: matched.slice(0, 2).map((r) => r.id) };
  };
  const themes = THEME_DEFS.map(themeStats).sort((a, b) => b.mentions - a.mentions);
  const love = themes.filter((t) => t.positivePct >= 60 && t.mentions > 0).slice(0, 5);
  const dislike = themes.filter((t) => t.positivePct < 60 && t.mentions > 0).sort((a, b) => a.positivePct - b.positivePct).slice(0, 4);

  const drivers = themes.slice(0, 6).map((t) => {
    const inGroup = (fn: (r: ReviewItem) => boolean) => reviews.filter((r) => fn(r) && t.keywords.some((k) => r.comment.toLowerCase().includes(k))).length;
    return { theme: t.name, s5: inGroup((r) => r.rating === 5), s4: inGroup((r) => r.rating === 4), s3: inGroup((r) => r.rating === 3), low: inGroup((r) => r.rating <= 2) };
  });

  const waitTheme = themes.find((t) => t.name === "Speed");
  const valueTheme = themes.find((t) => t.name === "Value");
  const staffTheme = themes.find((t) => t.name === "Staff & Service");

  const summary = !total
    ? hx.summaryNoData
    : fill(hx.summaryTpl, {
        label: sentimentLabel.toLowerCase(),
        loves: love.map((t) => t.name.toLowerCase()).slice(0, 3).join(", ") || hx.loveFallback,
        drags: dislike.map((t) => t.name.toLowerCase()).slice(0, 2).join(hx.andJoin) || hx.dragFallback,
        tail: waitTheme && waitTheme.mentions > 0 ? hx.tailWait : hx.tailDefault,
      });

  return {
    avg, sentimentScore, sentimentLabel,
    confidence: total ? Math.min(96, 70 + total * 3) : 0,
    summary, love, dislike, drivers,
    opportunities: [
      ...(waitTheme && waitTheme.mentions > 0 ? [{ level: "HIGH" as const, title: hx.oppWaitTitle, detail: fill(hx.oppWaitDetail, { n: fmt(waitTheme.mentions), a: fmtRating(waitTheme.avgRating) }), impact: "HIGH" }] : []),
      ...(valueTheme && valueTheme.mentions > 0 ? [{ level: "MEDIUM" as const, title: hx.oppValueTitle, detail: fill(hx.oppValueDetail, { n: fmt(valueTheme.mentions) }), impact: "MEDIUM" }] : []),
      ...(staffTheme && staffTheme.mentions > 0 ? [{ level: "MAINTAIN" as const, title: hx.oppStaffTitle, detail: fill(hx.oppStaffDetail, { n: fmt(staffTheme.mentions), a: fmtRating(staffTheme.avgRating) }), impact: "GUARD" }] : []),
    ],
    strengths: love.slice(0, 3).map((t) => ({ title: t.name, mentions: t.mentions, avg: t.avgRating })),
    sentimentSplit: { positive: pos, neutral: neu, negative: neg },
    topics: themes.map((t) => ({ name: t.name, count: t.mentions })),
    // Local scorecard so the heuristic view is as useful as the AI one — the
    // same six dimensions, counted from the reviews already in memory.
    dimensions: themes
      .filter((t) => t.mentions > 0)
      .map((t) => {
        const m = matchedRows(t.keywords, reviews);
        const posN = m.filter((r) => r.rating >= 4).length;
        const negN = m.filter((r) => r.rating <= 2).length;
        const judged = posN + negN;
        const pct = judged ? Math.round((posN / judged) * 100) : 0;
        return {
          key: THEME_DEFS.find((d) => d.name === t.name)?.key ?? t.name.toLowerCase(),
          label: t.name,
          standard: true,
          mentions: t.mentions,
          positive: posN,
          negative: negN,
          avg_rating: t.avgRating,
          positive_pct: pct,
          signal: (negN === 0 && posN > 0 ? "strong" : posN === 0 && negN > 0 ? "weak" : pct >= 70 ? "strong" : pct <= 30 ? "weak" : "mixed") as IntelDimension["signal"],
          confidence: (t.mentions >= 5 ? "high" : t.mentions >= 3 ? "medium" : "low") as IntelDimension["confidence"],
          verdict: `${posN ? fill(hx.verdictPraise, { n: fmt(posN) }) : ""}${posN && negN ? " · " : ""}${negN ? fill(hx.verdictCrit, { n: fmt(negN) }) : ""} ${fill(hx.verdictAvg, { a: fmtRating(t.avgRating) })}`.replace(/^ · /, ""),
          evidence: m.slice(0, 2).map((r) => ({ quote: r.comment.slice(0, 140), rating: r.rating })),
        };
      }),
    competitive: { wins: [], gaps: [], scope: null },
    actions: [
      ...(waitTheme && waitTheme.mentions > 0 ? [{ title: hx.actionWaitTitle, detail: fill(hx.actionWaitDetail, { n: fmt(waitTheme.mentions) }) }] : []),
      { title: fill(hx.actionRespondTitle, { n: fmt(reviews.filter((r) => !r.replied).length) }), detail: hx.actionRespondDetail },
      ...(staffTheme ? [{ title: hx.actionStaffTitle, detail: hx.actionStaffDetail }] : []),
    ].slice(0, 5),
  };
}

function mergeAiIntel(data: {
  source: string; model: string | null;
  summary: string;
  themes: { name: string; mentions: number; avg_rating: number; positive_pct: number; phrases: string[]; trend: string }[];
  opportunities: { level: "HIGH" | "MEDIUM" | "MAINTAIN"; title: string; detail: string; impact: string }[];
  strengths: { title: string; mentions: number; avg: number }[];
  actions: { title: string; detail: string }[];
  dimensions: IntelDimension[];
  competitive: IntelCompetitive;
  rag_used: boolean;
  analyzed_at: string | null;
  stale: boolean;
  current_count: number;
  review_count: number;
  /** Verified numbers. `held_out` = reviews the report refused to categorise. */
  stats?: {
    held_out?: { needs_human: number; not_analysed: number; unclassified: number; total: number } | null;
  } | null;
}, base: Intelligence): {
  intel: Intelligence; source: string; model: string | null; ragUsed: boolean;
  analyzedAt: string | null; stale: boolean; newCount: number;
  heldOut: HeldOutCounts | null;
} {
  const toTheme = (t: (typeof data.themes)[number]): IntelTheme => ({
    name: t.name, keywords: [], mentions: t.mentions,
    avgRating: t.avg_rating, positivePct: t.positive_pct,
    phrases: t.phrases ?? [], sampleIds: [],
  });
  const themes = data.themes.map(toTheme);
  return {
    intel: {
      ...base,
      summary: data.summary || base.summary,
      love: themes.filter((t) => t.positivePct >= 60 && t.mentions > 0).slice(0, 5),
      dislike: themes.filter((t) => t.positivePct < 60 && t.mentions > 0)
        .sort((a, b) => a.positivePct - b.positivePct).slice(0, 4),
      opportunities: data.opportunities.length ? data.opportunities : base.opportunities,
      strengths: data.strengths.length
        ? data.strengths.map((s) => ({ title: s.title, mentions: s.mentions, avg: s.avg }))
        : base.strengths,
      actions: data.actions.length ? data.actions : base.actions,
      topics: themes.map((t) => ({ name: t.name, count: t.mentions })),
      // Backend scorecard wins when present (it is verified against the review
      // rows server-side); otherwise keep the locally computed one.
      dimensions: data.dimensions?.length ? data.dimensions : base.dimensions,
      competitive: data.competitive ?? base.competitive,
    },
    source: data.source,
    model: data.model,
    ragUsed: data.rag_used,
    analyzedAt: data.analyzed_at ?? null,
    stale: data.stale === true,
    newCount: Math.max(0, (data.current_count ?? 0) - (data.review_count ?? 0)),
    heldOut: data.stats?.held_out ?? null,
  };
}

function ThemeBars({ topics }: { topics: { name: string; count: number }[] }) {
  const { t, locale } = useI18n();
  const ih = t.reviews.intel;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const max = Math.max(1, ...topics.map((t) => t.count));
  if (!topics.length) return <p className="text-[12px] text-ink/40">{ih.noThemes}</p>;
  return (
    <div className="space-y-1.5">
      {topics.slice(0, 8).map((t) => (
        <div key={t.name} className="flex items-center gap-2">
          <span className="w-32 truncate text-[11px] font-semibold capitalize text-ink/70">{t.name}</span>
          <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-ink/[0.06]">
            <span className="block h-full rounded-full bg-gradient-to-r from-deep-violet to-magenta" style={{ width: `${Math.max(4, (t.count / max) * 100)}%` }} />
          </span>
          <span className="w-8 text-right text-[11px] tabular-nums text-ink/50">×{fmt(t.count)}</span>
        </div>
      ))}
    </div>
  );
}

const PERIOD_PRESETS = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
  { days: 365, label: "12m" },
];

/**
 * Driver-table heat scale: the more reviews a cell holds, the deeper the
 * green. Intensity is relative to the busiest cell in the table so small
 * accounts still get a readable spread, and the legend states that.
 */
const HEAT_STEPS = [
  { label: "0", sample: "0", cls: "bg-[#F8F9FA] text-[#5F6368] ring-1 ring-[#E8EAED]" },
  { label: "few", sample: "1", cls: "bg-[#E6F4EA] text-[#137333]" },
  { label: "some", sample: "3", cls: "bg-[#A8DAB5] text-[#0B3D1E]" },
  { label: "many", sample: "6", cls: "bg-[#5BB974] text-[#062A14]" },
  { label: "most", sample: "9+", cls: "bg-[#188038] text-white" },
];

function heatCell(value: number, max: number): { cls: string } {
  if (value <= 0) return { cls: HEAT_STEPS[0].cls };
  // Relative thresholds so a table whose busiest cell is 2 is still readable.
  const ratio = max > 0 ? value / max : 0;
  if (ratio > 0.66) return { cls: HEAT_STEPS[4].cls };
  if (ratio > 0.33) return { cls: HEAT_STEPS[3].cls };
  if (ratio > 0.15) return { cls: HEAT_STEPS[2].cls };
  return { cls: HEAT_STEPS[1].cls };
}

function IntelligencePage({ intelligence: intel, total, locationName, aiMeta, aiLoading, analyzing, onAnalyze, onBack, onOpenStar, intelDays, intelMonth, intelInterval, setIntelDays, setIntelMonth }: {
  intelligence: Intelligence; total: number; locationName: string;
  aiMeta: { source: string; model: string | null; ragUsed: boolean; analyzedAt: string | null; stale: boolean; newCount: number; heldOut: HeldOutCounts | null } | null;
  aiLoading: boolean;
  analyzing: boolean;
  onAnalyze: () => void;
  onBack: () => void; onOpenStar: (s: number) => void;
  intelDays: number; intelMonth: string;
  intelInterval: { days: number; date_from: string | null; date_to: string | null; label: string };
  setIntelDays: (d: number) => void; setIntelMonth: (m: string) => void;
}) {
  const i = intel;
  const { t, locale } = useI18n();
  const ih = t.reviews.intel;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const fmtRating = (n: number) =>
    n.toLocaleString(dateLocale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const periodName = (d: number) => d === 7 ? ih.p7 : d === 30 ? ih.p30 : d === 90 ? ih.p90 : ih.p365;
  const heatWord = (label: string) =>
    label === "0" ? label : ih.heat[label as keyof typeof ih.heat] ?? label;
  const isAI = aiMeta?.source === "ai";
  const isLoading = aiLoading || analyzing;

  const badge = isLoading
    ? { text: analyzing ? ih.badgeAnalyzing : ih.badgeLoading, icon: "◐", cls: "bg-[#1A73E8]/10 text-[#1A73E8] border border-[#1A73E8]/20" }
    : isAI
      ? { text: fill(ih.badgeAi, { model: aiMeta?.model ?? ih.modelFallback, rag: aiMeta?.ragUsed ? ih.badgeRag : "" }), icon: "✦", cls: "bg-[#E6F4EA] text-[#137333] border border-[#CEEAD6]" }
      : aiMeta
        ? { text: ih.badgeHeuristic, icon: "◈", cls: "bg-[#F1F3F4] text-[#5F6368] border border-[#DADCE0]" }
        : { text: ih.badgeNone, icon: "○", cls: "bg-[#FEF7E0] text-[#EA8600] border border-[#FDE293]" };

  const analyzedLabel = aiMeta?.analyzedAt
    ? `${new Date(aiMeta.analyzedAt).toLocaleString(dateLocale)}${aiMeta.stale ? fill(ih.analyzedStale, { n: fmt(aiMeta.newCount) }) : ih.analyzedFresh}`
    : null;

  // Derived business impact
  const unanswered = total - Math.round((intel as unknown as { avg: number }).avg ? total * 0.6 : 0); // placeholder, will use real replied count if available
  const atRiskPct = total ? Math.round(((i.dislike.reduce((a, b) => a + b.mentions, 0) / Math.max(1, total)) * 100)) : 0;
  const revenueRisk = i.dislike.length ? fill(ih.churnRisk, { n: fmt(atRiskPct) }) : ih.churnLow;
  const sentimentDelta = i.sentimentScore >= 3.5 ? ih.momentumPos : i.sentimentScore >= 2.5 ? ih.momentumMix : ih.momentumNeg;

  // Busiest driver cell — the denominator for the heat scale.
  const driverMax = useMemo(
    () => Math.max(0, ...i.drivers.flatMap((d) => [d.s5, d.s4, d.s3, d.low])),
    [i.drivers]
  );

  return (
    <div className="space-y-4" style={{ fontFamily: "Roboto, Arial, sans-serif" }}>
      {/* HEADER — Google Material, clean & functional */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[16px] font-medium leading-6 text-[#202124]">{ih.title}</h2>
              <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium leading-none ${badge.cls}`}>
                <span aria-hidden>{badge.icon}</span> {badge.text}
              </span>
              {isAI && !isLoading && (
                <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-[11px] text-[#5F6368] ring-1 ring-[#DADCE0]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#34A853]" /> {ih.verified}
                </span>
              )}
        </div>

            <p className="mt-1 text-[13px] leading-5 text-[#5F6368]">
              <span className="font-medium text-[#202124]">{locationName || ih.allLocations}</span>
              <span className="mx-1.5 text-[#DADCE0]">•</span>
              <span className="font-medium text-[#202124]">{intelInterval.label}</span>
              <span className="mx-1.5 text-[#DADCE0]">•</span>
              {fill(ih.kpiReviews, { n: fmt(total) })} • {isAI ? fill(ih.aiAnalysis, { model: aiMeta?.model ? ` • ${aiMeta.model}` : "" }) : ih.heuristicLine}
            </p>
            {analyzedLabel && <p className="mt-1 text-[12px] text-[#5F6368]">{fill(ih.updated, { when: analyzedLabel })}</p>}
            {aiMeta?.stale && (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-[#FEF7E0] px-2.5 py-1 text-[12px] font-medium text-[#EA8600]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#EA8600]" /> {fill(ih.staleLine, { n: fmt(aiMeta.newCount) })}
              </p>
            )}
            {(aiMeta?.heldOut?.total ?? 0) > 0 && (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-[#FEF7E0] px-2.5 py-1 text-[12px] text-[#7A4F01]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#F4B400]" />
                {fill(ih.heldOut, { n: fmt(aiMeta?.heldOut?.total ?? 0) })}
                {aiMeta?.heldOut?.needs_human
                  ? fill(ih.heldOutHuman, { n: fmt(aiMeta.heldOut.needs_human) })
                  : ""}
                {aiMeta?.heldOut?.not_analysed ? fill(ih.heldOutPending, { n: fmt(aiMeta.heldOut.not_analysed) }) : ""}
                {ih.heldOutCta}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="hidden sm:inline-flex rounded-md border border-[#DADCE0] bg-white px-3 py-2 text-[13px] font-medium text-[#1A73E8] hover:bg-[#F8F9FA]"
            >
              {ih.back}
            </button>
            <button
              onClick={onAnalyze}
              disabled={analyzing || aiLoading}
              className="inline-flex items-center gap-1.5 rounded-md bg-[#1A73E8] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50"
            >
              {analyzing ? (
                <>
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" /> {ih.analyzing}
                </>
              ) : isAI ? ih.reanalyze : ih.analyze}
            </button>
          </div>
        </div>

        {/* INTERVAL — scopes every number on this page to the selected window */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#E8EAED] pt-3">
          <span className="text-[12px] font-medium text-[#5F6368]">{ih.period}</span>
          <div className="flex flex-wrap items-center gap-1.5">
            {PERIOD_PRESETS.map((p) => {
              const active = !intelMonth && intelDays === p.days;
              return (
                <button
                  key={p.days}
                  onClick={() => { setIntelDays(p.days); setIntelMonth(""); }}
                  disabled={isLoading}
                  className={`rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-50 ${
                    active
                      ? "border-[#1A73E8] bg-[#E8F0FE] text-[#1967D2]"
                      : "border-[#DADCE0] bg-white text-[#5F6368] hover:bg-[#F8F9FA]"
                  }`}
                >
                  {periodName(p.days)}
                </button>
              );
            })}
            <label className="ml-1 inline-flex items-center gap-1.5 text-[12px] text-[#5F6368]">
              <span className="sr-only">{ih.monthAria}</span>
              <input
                type="month"
                value={intelMonth}
                disabled={isLoading}
                onChange={(e) => setIntelMonth(e.target.value)}
                className="rounded-md border border-[#DADCE0] px-2 py-1 text-[12px] text-[#202124] disabled:opacity-50"
              />
            </label>
            {intelMonth && (
              <button
                onClick={() => setIntelMonth("")}
                className="rounded-full border border-[#DADCE0] bg-white px-2 py-1 text-[11px] font-medium text-[#5F6368] hover:bg-[#F8F9FA]"
              >
                {ih.clear}
              </button>
            )}
          </div>
          {isLoading && <span className="text-[12px] text-[#5F6368]">{fill(ih.loadingPeriod, { label: intelInterval.label.toLowerCase() })}…</span>}
        </div>

        {/* Source transparency — makes AI vs heuristic crystal clear */}
        <div className="mt-3 flex flex-wrap gap-2 border-t border-[#E8EAED] pt-3 text-[12px]">
          <span className={`inline-flex items-center gap-1.5 ${isAI ? "text-[#137333]" : "text-[#5F6368]"}`}>
            <span className={`h-2 w-2 rounded-full ${isAI ? "bg-[#34A853]" : "bg-[#5F6368]"}`} />
            {isAI ? ih.srcAi : ih.srcHeuristic}
          </span>
          <span className="text-[#DADCE0]">•</span>
          <span className="text-[#5F6368]">{isAI && aiMeta?.ragUsed ? ih.ragYes : isAI ? ih.ragReviewsOnly : ih.ragNo}</span>
        </div>
      </div>

      {/* HERO KPIs — Material cards, neutral + one green accent */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">{ih.kpiAvg}</p>
          <p className="mt-1 text-[22px] font-normal leading-7 text-[#202124]">{fmtRating(i.avg)} <span className="text-[#FBBC05]">★</span></p>
          <p className="mt-1 text-[12px] text-[#5F6368]">{i.sentimentLabel} • {fill(ih.kpiReviews, { n: fmt(total) })}</p>
        </div>
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">{ih.kpiSentiment}</p>
          <div className="mt-1 flex items-baseline gap-2">
            <p className="text-[22px] font-normal leading-7 text-[#202124]">{fmtRating(i.sentimentScore)}</p>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${i.sentimentScore >= 3.5 ? "bg-[#E6F4EA] text-[#137333]" : i.sentimentScore >= 2.5 ? "bg-[#FEF7E0] text-[#EA8600]" : "bg-[#FCE8E6] text-[#C5221F]"}`}>
              {sentimentDelta}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#E8EAED]">
            <div className="h-full rounded-full bg-[#1A73E8]" style={{ width: `${Math.min(100, (i.sentimentScore / 5) * 100)}%` }} />
          </div>
        </div>
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">{ih.kpiConfidence}</p>
          <p className="mt-1 text-[22px] font-normal leading-7 text-[#202124]">{fmt(i.confidence)}%</p>
          <p className="mt-1 text-[12px] text-[#5F6368]">{total >= 20 ? ih.confHigh : total >= 8 ? ih.confMid : ih.confLow}</p>
        </div>
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">{ih.kpiRisk}</p>
          <p className="mt-1 text-[14px] font-medium leading-5 text-[#202124]">{revenueRisk}</p>
          <p className="mt-1 text-[12px] text-[#5F6368]">{ih.riskFix}</p>
        </div>
      </div>

      {/* BUSINESS HEALTH SCORECARD — standard dimensions, evidence-cited.
          Only dimensions someone actually mentioned reach this view. */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F1F3F4] text-[#5F6368]">▦</span>
          <h3 className="text-[14px] font-medium text-[#202124]">{ih.scoreTitle}</h3>
          <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[11px] font-medium text-[#5F6368]">
            {i.dimensions.length === 1 ? ih.dimOne : fill(ih.dimN, { n: fmt(i.dimensions.length) })}
          </span>
        </div>
        {i.dimensions.length === 0 ? (
          <p className="mt-3 text-[13px] text-[#5F6368]">
            {ih.scoreEmpty}
          </p>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {i.dimensions.map((d) => {
              const tone =
                d.signal === "strong"
                  ? { chip: "bg-[#E6F4EA] text-[#137333]", bar: "#34A853", word: ih.strong }
                  : d.signal === "weak"
                    ? { chip: "bg-[#FCE8E6] text-[#C5221F]", bar: "#EA4335", word: ih.weak }
                    : { chip: "bg-[#FEF7E0] text-[#EA8600]", bar: "#FBBC05", word: ih.mixed };
              return (
                <div key={d.key} className="rounded-lg border border-[#E8EAED] p-3.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium leading-5 text-[#202124]">{d.label}</p>
                      {!d.standard && (
                        <span className="mt-0.5 inline-block rounded bg-[#E8F0FE] px-1.5 py-0.5 text-[10px] font-medium text-[#1967D2]">
                          {ih.discovered}
                        </span>
                      )}
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${tone.chip}`}>
                      {tone.word}
                    </span>
                  </div>

                  {d.verdict && <p className="mt-1.5 text-[12px] leading-5 text-[#5F6368]">{d.verdict}</p>}

                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[#5F6368]">
                    <span className="inline-flex items-center gap-1">
                      <span aria-hidden>👍</span> {fill(ih.posCount, { n: fmt(d.positive) })}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <span aria-hidden>👎</span> {fill(ih.negCount, { n: fmt(d.negative) })}
                    </span>
                    <span className="tabular-nums">{fill(ih.avgShort, { n: fmtRating(d.avg_rating) })}</span>
                    <span className="rounded bg-[#F1F3F4] px-1.5 py-0.5 font-medium">
                      {fill(ih.confLine, { c: d.confidence === "low" ? ih.confValLow : d.confidence === "medium" ? ih.confValMid : ih.confValHigh })}
                    </span>
                  </div>

                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#E8EAED]">
                    <span
                      className="block h-full rounded-full"
                      style={{ width: `${Math.max(3, d.positive_pct)}%`, backgroundColor: tone.bar }}
                    />
                  </div>

                  {d.evidence.length > 0 && (
                    <ul className="mt-2.5 space-y-1 border-t border-[#F1F3F4] pt-2">
                      {d.evidence.map((e, idx) => (
                        <li key={idx} className="flex gap-1.5 text-[11px] leading-4 text-[#5F6368]">
                          <span aria-hidden className="shrink-0 tabular-nums">{e.rating}★</span>
                          <span className="italic">“{e.quote}”</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* COMPETITIVE POSITION — where you lead / trail, vs the platform cohort */}
      {(i.competitive.wins.length > 0 || i.competitive.gaps.length > 0) && (
        <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F1F3F4] text-[#5F6368]">⚖</span>
            <h3 className="text-[14px] font-medium text-[#202124]">{ih.compTitle}</h3>
            {i.competitive.scope && (
              <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[11px] font-medium text-[#5F6368]">
                {i.competitive.scope}
              </span>
            )}
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {i.competitive.wins.length > 0 && (
              <div className="rounded-lg border border-[#CEEAD6] bg-[#F6FEF8] p-3.5">
                <p className="text-[12px] font-medium uppercase tracking-wide text-[#137333]">{ih.compLead}</p>
                <ul className="mt-2 space-y-1.5">
                  {i.competitive.wins.map((w, idx) => (
                    <li key={idx} className="text-[12px] leading-5 text-[#202124]">• {w}</li>
                  ))}
                </ul>
              </div>
            )}
            {i.competitive.gaps.length > 0 && (
              <div className="rounded-lg border border-[#F6C7C3] bg-[#FEF7F6] p-3.5">
                <p className="text-[12px] font-medium uppercase tracking-wide text-[#C5221F]">{ih.compTrail}</p>
                <ul className="mt-2 space-y-1.5">
                  {i.competitive.gaps.map((g, idx) => (
                    <li key={idx} className="text-[12px] leading-5 text-[#202124]">• {g}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* AI EXEC SUMMARY — hero card, clearly AI when AI, muted when heuristic */}
      <div className={`rounded-lg border bg-white p-5 ${isAI ? "border-[#CEEAD6] shadow-sm" : "border-[#DADCE0]"}`}>
        <div className="flex items-center gap-2">
          <span className={`flex h-7 w-7 items-center justify-center rounded-full ${isAI ? "bg-[#E6F4EA] text-[#137333]" : "bg-[#F1F3F4] text-[#5F6368]"}`}>
            {isAI ? "✦" : "◈"}
          </span>
          <h3 className="text-[14px] font-medium text-[#202124]">{isAI ? ih.execAi : ih.execHeuristic}</h3>
          {!isAI && <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[11px] font-medium text-[#5F6368]">{ih.execHint}</span>}
        </div>
        {isLoading ? (
          <div className="mt-3 space-y-2">
            <div className="h-4 w-full animate-pulse rounded bg-[#F1F3F4]" />
            <div className="h-4 w-5/6 animate-pulse rounded bg-[#F1F3F4]" />
          </div>
        ) : (
          <p className="mt-3 text-[13px] leading-6 text-[#202124]">{i.summary}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {[5, 4, 3, 2, 1].map((s) => (
            <button key={s} onClick={() => onOpenStar(s)} className="rounded-full border border-[#DADCE0] bg-white px-3 py-1 text-[12px] font-medium text-[#1A73E8] hover:bg-[#F8F9FA]">
              {fill(ih.starDetail, { s: fmt(s) })}
            </button>
          ))}
        </div>
      </div>

      {/* LOVE / DISLIKE — balanced, actionable */}
      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            <span className="h-2 w-2 rounded-full bg-[#34A853]" /> {ih.loveTitle}
            <span className="ml-auto text-[11px] font-normal text-[#5F6368]">{i.love.length ? fill(ih.loveCount, { n: fmt(i.love.length) }) : ""}</span>
          </h3>
          {i.love.length === 0 ? <p className="mt-3 text-[13px] text-[#5F6368]">{ih.loveEmpty}</p> : (
            <div className="mt-3 space-y-3">
              {i.love.map((t) => (
                <div key={t.name}>
                  <div className="flex justify-between text-[13px]">
                    <span className="font-medium text-[#202124]">{t.name}</span>
                    <span className="font-medium text-[#137333]">{fill(ih.pctPositive, { n: fmt(t.positivePct) })}</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#E8EAED]"><div className="h-full rounded-full bg-[#34A853]" style={{ width: `${t.positivePct}%` }} /></div>
                  <p className="mt-1 text-[12px] text-[#5F6368]">{fill(ih.mentionsAvg, { n: fmt(t.mentions), a: fmtRating(t.avgRating), quote: t.phrases[0] ? fill(ih.quoteSuffix, { q: t.phrases[0].slice(0, 60) }) : "" })}</p>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 border-t border-[#E8EAED] pt-3 text-[12px] text-[#5F6368]"><span className="font-medium text-[#202124]">{ih.nextLabel}</span> {ih.nextLove}</p>
        </section>
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            <span className="h-2 w-2 rounded-full bg-[#EA4335]" /> {ih.hurtTitle}
            <span className="ml-auto text-[11px] font-normal text-[#5F6368]">{i.dislike.length ? fill(ih.loveCount, { n: fmt(i.dislike.length) }) : ih.hurtNone}</span>
          </h3>
          {i.dislike.length === 0 ? <p className="mt-3 rounded-md bg-[#E6F4EA] px-3 py-2 text-[13px] text-[#137333]">{ih.hurtEmpty}</p> : (
            <div className="mt-3 space-y-3">
              {i.dislike.map((t) => (
                <div key={t.name}>
                  <div className="flex justify-between text-[13px]"><span className="font-medium text-[#202124]">{t.name}</span><span className="text-[#5F6368]">{fill(ih.mentionsOnly, { n: fmt(t.mentions) })}</span></div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#E8EAED]"><div className="h-full rounded-full bg-[#EA4335]" style={{ width: `${Math.min(100, t.mentions * 12)}%` }} /></div>
                  <p className="mt-1 text-[12px] text-[#5F6368]">{fill(ih.hurtLine, { a: fmtRating(t.avgRating), p: fmt(t.positivePct) })}</p>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 border-t border-[#E8EAED] pt-3 text-[12px] text-[#5F6368]"><span className="font-medium text-[#202124]">{ih.nextLabel}</span> {ih.nextHurt}</p>
        </section>
      </div>

      {/* DRIVERS — heatmap style */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <h3 className="text-[14px] font-medium text-[#202124]">{ih.driversTitle}</h3>
        <p className="text-[12px] text-[#5F6368]">{ih.driversSub}</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[12px]">
            <thead>
              <tr className="text-left text-[#5F6368]">
                <th className="py-2 text-[11px] font-medium uppercase tracking-wide">{ih.themeCol}</th>
                <th className="text-center text-[11px] font-medium">5★</th>
                <th className="text-center text-[11px] font-medium">4★</th>
                <th className="text-center text-[11px] font-medium">3★</th>
                <th className="text-center text-[11px] font-medium">{ih.lowCol}</th>
              </tr>
            </thead>
            <tbody>
              {i.drivers.map((d) => (
                <tr key={d.theme} className="border-t border-[#E8EAED]">
                  <td className="py-2 pr-2 text-[13px] font-medium text-[#202124]">{d.theme}</td>
                  {[d.s5, d.s4, d.s3, d.low].map((v, idx) => {
                    const base = heatCell(v, driverMax);
                    // The 1–2★ column is complaints: keep it red-tinted so a
                    // dense cell reads as "bad" at a glance, intensity by count.
                    const cls =
                      idx === 3 && v > 0
                        ? v > 0
                          ? ["bg-[#F6C7C3] text-[#A50E0E]", "bg-[#EA4335] text-white", "bg-[#C5221F] text-white"][
                              Math.min(2, Math.max(0, Math.ceil((v / Math.max(1, driverMax)) * 3) - 1))
                            ]
                          : base.cls
                        : base.cls;
                    return (
                      <td key={idx} className="py-2 text-center">
                        <span
                          className={`inline-flex h-7 min-w-7 items-center justify-center rounded-full px-1.5 text-[12px] font-medium tabular-nums ${cls}`}
                          title={v === 0 ? ih.noReviewsTitle : v === 1 ? ih.reviewOne : fill(ih.reviewN, { n: fmt(v) })}
                        >
                          {fmt(v)}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* INTENSITY SCALE — the legend makes the shading readable */}
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-[#E8EAED] pt-3 text-[11px] text-[#5F6368]">
          <span className="font-medium text-[#202124]">{ih.scale}</span>
          <span className="text-[#5F6368]">{ih.scaleHint}</span>
          <span className="flex items-center gap-1.5">
            {HEAT_STEPS.map((s) => (
              <span key={s.label} className="flex items-center gap-1">
                <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-medium tabular-nums ${s.cls}`}>
                  {s.sample === "9+" ? s.sample : heatWord(s.label)}
                </span>
                <span className="text-[#5F6368]">{heatWord(s.label)}</span>
              </span>
            ))}
          </span>
          <span className="text-[#C5221F]">{ih.redNote}</span>
        </div>
      </div>

      {/* OPPORTUNITIES + STRENGTHS */}
      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            {ih.oppTitle}
            {isAI && <span className="rounded-full bg-[#E6F4EA] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#137333]">{ih.oppAi}</span>}
            {!isAI && <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#5F6368]">{ih.oppHeuristic}</span>}
          </h3>
          <div className="mt-3 space-y-2.5">
            {i.opportunities.map((o) => (
              <div key={o.title} className="rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-3">
                <p className="text-[13px] font-medium text-[#202124]">
                  <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-medium ${o.level === "HIGH" ? "bg-[#FCE8E6] text-[#C5221F] border border-[#FAD2CF]" : o.level === "MEDIUM" ? "bg-[#FEF7E0] text-[#EA8600] border border-[#FDE293]" : "bg-[#E6F4EA] text-[#137333] border border-[#CEEAD6]"}`}>{o.level}</span>
                  {o.title}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-[#5F6368]">{o.detail}</p>
                <p className="mt-1 text-[11px] font-medium text-[#1A73E8]">{fill(ih.impactLine, { impact: o.impact })}</p>
              </div>
            ))}
            {i.opportunities.length === 0 && <p className="text-[13px] text-[#5F6368]">{ih.oppEmpty}</p>}
          </div>
        </section>
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="text-[14px] font-medium text-[#202124]">{ih.strTitle}</h3>
          <p className="text-[12px] text-[#5F6368]">{ih.strSub}</p>
          <div className="mt-3 space-y-2">
            {i.strengths.map((s, idx) => (
              <div key={s.title} className="flex items-start gap-3 rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#E6F4EA] text-[12px] font-medium text-[#137333]">{fmt(idx + 1)}</span>
                <div>
                  <p className="text-[13px] font-medium text-[#202124]">{s.title}</p>
                  <p className="text-[12px] text-[#5F6368]">{fill(ih.strLine, { n: fmt(s.mentions), a: fmtRating(s.avg) })}</p>
                </div>
              </div>
            ))}
            {i.strengths.length === 0 && <p className="text-[13px] text-[#5F6368]">{ih.strEmpty}</p>}
          </div>
          <h3 className="mt-5 flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            {ih.planTitle} {isAI ? <span className="rounded-full bg-[#E6F4EA] px-2 py-0.5 text-[10px] font-medium text-[#137333]">{ih.planAi}</span> : null}
          </h3>
          <ol className="mt-2 space-y-2">
            {i.actions.map((a, idx) => (
              <li key={a.title} className="flex gap-2 rounded-lg border border-[#E8EAED] bg-white px-3 py-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#1A73E8] text-[11px] font-medium text-white">{fmt(idx + 1)}</span>
                <div>
                  <p className="text-[13px] font-medium text-[#202124]">{a.title}</p>
                  <p className="text-[12px] text-[#5F6368]">{a.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>

      {/* THEMES */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <h3 className="text-[14px] font-medium text-[#202124]">{ih.themesTitle}</h3>
        <p className="text-[12px] text-[#5F6368]">{ih.themesSub}</p>
        <div className="mt-3"><ThemeBars topics={i.topics} /></div>
        <div className="mt-3 flex flex-wrap gap-2">
          {i.topics.map((t) => (
            <span key={t.name} className="rounded-full border border-[#E8EAED] bg-[#F8F9FA] px-3 py-1.5 text-[12px] font-medium text-[#202124]">{fill(ih.themeChip, { name: t.name, n: fmt(t.count) })}</span>
          ))}
        </div>
      </div>

      {/* SENTIMENT SPLIT — quick visual for business health */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <h3 className="text-[14px] font-medium text-[#202124]">{ih.sentTitle}</h3>
        <div className="mt-3 flex h-3 overflow-hidden rounded-full">
          <div className="bg-[#34A853]" style={{ width: `${total ? (i.sentimentSplit.positive / total) * 100 : 0}%` }} title={fill(ih.sentPos, { n: fmt(i.sentimentSplit.positive) })} />
          <div className="bg-[#FBBC05]" style={{ width: `${total ? (i.sentimentSplit.neutral / total) * 100 : 0}%` }} title={fill(ih.sentNeu, { n: fmt(i.sentimentSplit.neutral) })} />
          <div className="bg-[#EA4335]" style={{ width: `${total ? (i.sentimentSplit.negative / total) * 100 : 0}%` }} title={fill(ih.sentNeg, { n: fmt(i.sentimentSplit.negative) })} />
        </div>
        <div className="mt-2 flex flex-wrap gap-4 text-[12px]">
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#34A853]" /> {ih.sentPos} {fmt(i.sentimentSplit.positive)}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#FBBC05]" /> {ih.sentNeu} {fmt(i.sentimentSplit.neutral)}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#EA4335]" /> {ih.sentNeg} {fmt(i.sentimentSplit.negative)}</span>
        </div>
      </div>

      <button onClick={onBack} className="text-[13px] font-medium text-[#1A73E8] hover:underline">{t.reviews.detail.back}</button>
      <p className="text-[11px] leading-4 text-[#5F6368]">
        {isAI ? fill(ih.footerAi, { m: aiMeta?.model ?? ih.modelFallback, rag: aiMeta?.ragUsed ? ih.footerRagYes : ih.footerRagNo }) : ih.footerHeuristic}
        {" "}• Sayvors-derived analytics • <span className="underline decoration-dotted">{ih.whyMatters}</span>
      </p>
    </div>
  );
}

function InsightCard({ review }: { review: ReviewItem }) {
  const { t, locale } = useI18n();
  const ix = t.reviews.insight;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmtRating = (n: number) =>
    n.toLocaleString(dateLocale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const insight = explainReview(review, ix, fmtRating);
  const created = (() => {
    const d = new Date(review.createdAt.length === 10 ? `${review.createdAt}T00:00:00` : review.createdAt);
    return Number.isNaN(d.getTime()) ? review.createdAt : d.toLocaleDateString(dateLocale, { month: "short", day: "numeric", year: "numeric" });
  })();
  return (
    <div className="rounded-lg border border-[#DADCE0] bg-white p-4" style={{ fontFamily: "Roboto, Arial, sans-serif" }}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-1.5 text-[13px] font-medium text-[#202124]">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#F1F3F4] text-[#5F6368]">
            <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5" aria-hidden>
              <path d="M12 16a1.2 1.2 0 1 0 0 2.4A1.2 1.2 0 0 0 12 16ZM11 8h2v6h-2z" fill="currentColor" />
              <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 16a7 7 0 1 1 0-14 7 7 0 0 1 0 14Z" stroke="currentColor" strokeWidth={1.2} />
            </svg>
          </span>
          {ix.title}
        </h3>
        <span
          className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
            insight.tone === "high"
              ? "border-[#CEEAD6] bg-[#E6F4EA] text-[#137333]"
              : insight.tone === "low"
                ? "border-[#FAD2CF] bg-[#FCE8E6] text-[#C5221F]"
                : "border-[#FDE293] bg-[#FEF7E0] text-[#EA8600]"
          }`}
        >
          {insight.tone === "high" ? ix.high : insight.tone === "low" ? ix.low : ix.mixed}
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-5 text-[#5F6368]">{insight.summary}</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-3">
          <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-[#137333]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#34A853]" /> {ix.lifted}
          </p>
          {insight.positives.length ? (
            <ul className="mt-2 space-y-1">
              {insight.positives.map((x) => (
                <li key={x} className="flex gap-1.5 text-[12px] leading-4 text-[#202124]">
                  <span className="text-[#34A853]">+</span> {x}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[12px] text-[#5F6368]">{ix.noPositives}</p>
          )}
        </div>
        <div className="rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-3">
          <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-[#C5221F]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#EA4335]" /> {ix.dragged}
          </p>
          {insight.negatives.length ? (
            <ul className="mt-2 space-y-1">
              {insight.negatives.map((x) => (
                <li key={x} className="flex gap-1.5 text-[12px] leading-4 text-[#202124]">
                  <span className="text-[#EA4335]">−</span> {x}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[12px] text-[#5F6368]">{ix.noNegatives}</p>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-[#E8EAED] bg-white p-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">{ix.result}</p>
        <p className="mt-1 text-[13px] leading-5 text-[#202124]">{insight.result}</p>
        <p className="mt-2 flex items-center gap-1.5 text-[12px] font-medium text-[#1A73E8]">
          <span className="text-[#1A73E8]">→</span> {fill(ix.next, { action: insight.action })}
        </p>
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[#E8EAED] pt-3 text-[11px] text-[#5F6368]">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#F1F3F4]">
          <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3" aria-hidden>
            <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 16a7 7 0 1 1 0-14 7 7 0 0 1 0 14Z" stroke="currentColor" strokeWidth={1.3} />
            <path d="M12 8v5l3 2" stroke="currentColor" strokeWidth={1.3} strokeLinecap="round" />
          </svg>
        </span>
        {fill(ix.foot, { loc: review.locationName, date: created })}
        <span className="text-[#DADCE0]">•</span>
        <span className={review.replied ? "text-[#137333]" : "text-[#5F6368]"}>{review.replied ? t.reviews.detail.replied : t.reviews.stats.unanswered}</span>
      </p>
    </div>
  );
}

function explainReview(r: ReviewItem, ix: InsightDict, fmtRating: (n: number) => string): { tone: "high" | "low" | "mixed"; summary: string; positives: string[]; negatives: string[]; result: string; action: string } {
  const text = r.comment.toLowerCase();
  const positives = Object.entries(ix.lexPos).filter(([k]) => text.includes(k)).map(([, v]) => v);
  const negatives = Object.entries(ix.lexNeg).filter(([k]) => text.includes(k)).map(([, v]) => v);
  if (r.rating >= 4 && negatives.length === 0) {
    return {
      tone: "high",
      summary: fill(positives.length ? ix.summaryHighPraise : ix.summaryHighBare, { s: fmtRating(r.rating) }),
      positives: positives.length ? positives : [ix.fbHighStar],
      negatives,
      result: fill(ix.resultHigh, { loc: r.locationName, tail: r.replied ? ix.resultHighReplied : ix.resultHighOpen }),
      action: r.replied ? ix.actionHighReplied : ix.actionHighOpen,
    };
  }
  if (r.rating <= 2) {
    return {
      tone: "low",
      summary: fill(negatives.length ? ix.summaryLowPain : ix.summaryLowBare, { s: fmtRating(r.rating) }),
      positives,
      negatives: negatives.length ? negatives : [ix.fbLowStar],
      result: fill(ix.resultLow, { loc: r.locationName, tail: r.replied ? ix.resultLowReplied : ix.resultLowOpen }),
      action: ix.actionLow,
    };
  }
  return {
    tone: "mixed",
    summary: fill(ix.summaryMixed, { s: fmtRating(r.rating) }),
    positives: positives.length ? positives : [ix.fbMidPos],
    negatives: negatives.length ? negatives : [ix.fbMidNeg],
    result: fill(ix.resultMixed, { loc: r.locationName }),
    action: ix.actionMixed,
  };
}

function Stars({ rating }: { rating: number }) {
  const { t, locale } = useI18n();
  const num = new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(rating);
  return (
    <span className="flex shrink-0 gap-0.5" aria-label={fill(t.reviews.star.ariaStars, { n: num })}>
      {[1, 2, 3, 4, 5].map((s) => (
        <svg key={s} viewBox="0 0 24 24" className={`h-3.5 w-3.5 ${s <= rating ? "text-[#FBBC05]" : "text-ink/15 dark:text-fog/15"}`} fill="currentColor">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
        </svg>
      ))}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-3 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">{label}</p>
      <p className="text-[18px] font-bold text-ink dark:text-fog">{value}</p>
    </div>
  );
}
