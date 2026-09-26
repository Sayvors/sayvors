"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import GoogleReviewCard, { GoogleStars, ReviewAvatar } from "@/components/reviews/GoogleReviewCard";
import { streamReviewReply, type StreamEvent } from "@/lib/api-review-engine";
import { approveReply, dismissReviewEdit, editReply, generateReply, regenerateReply, type ReviewReplyDTO } from "@/lib/api-analytics";

type ReviewTab = "all" | "unanswered" | "replied" | "positive" | "negative" | "need_approval" | "flagged" | "edited";
type View = { kind: "list" } | { kind: "detail"; id: string } | { kind: "star"; stars: number; from: "list" | "intelligence" } | { kind: "intelligence" };

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
  reply_text?: string;
  status?: string;
  replyId?: string;
}

interface LocationOption {
  id: string;
  name: string;
  channelId?: string;
}

const PAGE_SIZE = 4;

const TAB_LABELS: Record<ReviewTab, string> = {
  all: "All",
  unanswered: "Unanswered",
  need_approval: "Need Approval",
  flagged: "Flagged",
  edited: "Edited",
  replied: "Replied",
  positive: "Positive",
  negative: "Negative",
};
const PRIMARY_TABS: ReviewTab[] = ["all", "need_approval", "edited"];
const MORE_TABS: ReviewTab[] = ["unanswered", "flagged", "replied", "positive", "negative"];

export default function ReviewsPage() {
  return (
    <Suspense>
      <ReviewsInner />
    </Suspense>
  );
}

const ALL_BRANCHES = "__all__";

function ReviewsInner() {
  const searchParams = useSearchParams();
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
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [replyDraft, setReplyDraft] = useState("");
  const [replying, setReplying] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [needApprovalPage, setNeedApprovalPage] = useState(1);
  const [approvingAllPending, setApprovingAllPending] = useState(false);
   const [approvingId, setApprovingId] = useState<string | null>(null);
   const [pendingReplies, setPendingReplies] = useState<ReviewReplyDTO[]>([]);
   const [skippingId, setSkippingId] = useState<string | null>(null);
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
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Real locations: every Localith-connected branch.
        try {
          const conns = (await apiFetch("/api/v1/integrations/localith/connections")) as { listing_id: string; listing_name: string }[];
          if (!cancelled && Array.isArray(conns) && conns.length > 0) {
            const locs = conns.map((c) => ({ id: c.listing_id, name: c.listing_name }));
            try {
              const ch = await apiFetch("/api/v1/channels/?limit=100");
              const names: Record<string, string> = {};
              for (const channel of ch.channels ?? []) {
                if (channel?.id) names[channel.id] = channel.display_name ?? "Google location";
              }
              if (!cancelled) setChannelNames(names);
            } catch {
              /* names stay empty — location name is used as fallback */
            }
            if (!cancelled) {
              setLocations(locs);
              setSelectedId(locs.length > 0 ? ALL_BRANCHES : null);
              return;
            }
          }
        } catch {
          /* no Localith connections — fall through to channels */
        }
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string }) => channel.platform === "google_reviews")
          .map((channel: { id: string; display_name: string | null }) => ({
            id: channel.id,
            name: channel.display_name ?? "Google location",
            channelId: channel.id,
          }));
        if (!cancelled) {
          const names: Record<string, string> = {};
          for (const channel of data.channels ?? []) {
            if (channel?.id) names[channel.id] = channel.display_name ?? "Google location";
          }
          setChannelNames(names);
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

  const loadInsights = async (channelId?: string) => {
    const q = channelId ? `?channel_id=${encodeURIComponent(channelId)}&limit=200` : "?limit=200";
    const data = await apiFetch(`/api/v1/analytics/reviews/insights${q}`);
    return mapInsights(data.items, channelNames, locations.find((l) => l.id === selectedId)?.name ?? "");
  };

  const loadPendingReplies = async () => {
    // Same source as the dashboard "Needs attention" queue: the
    // review_replies table via /channels/{id}/reviews?status=pending_approval.
    let ids: string[] = locations.map((l) => l.channelId).filter(Boolean) as string[];
    if (ids.length === 0) {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        ids = (data.channels ?? [])
          .filter((c: { platform: string }) => c.platform === "google_reviews")
          .map((c: { id: string }) => c.id);
      } catch {
        ids = [];
      }
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
  };

  const fetchReviews = async (withSync: boolean) => {
    setRefreshing(true);
    try {
      if (withSync) {
        try {
          await apiFetch("/api/v1/integrations/localith/sync", { method: "POST" });
        } catch {
          /* sync failed — still show whatever is stored */
        }
      }
      const loc = locations.find((l) => l.id === selectedId);
      const items = await loadInsights(loc?.channelId);
      setReviews(items);
      await loadPendingReplies();
      if (withSync) setBanner({ kind: "ok", text: "Reconciled with Localith." });
    } catch {
      setReviews([]);
      setBanner({ kind: "err", text: "Could not load reviews. Is the backend running?" });
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const loc = locations.find((l) => l.id === selectedId);
        const items = await loadInsights(loc?.channelId);
        if (!cancelled) setReviews(items);
        await loadPendingReplies();
      } catch {
        if (!cancelled) setReviews([]);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const counts = useMemo(() => ({
    all: reviews.length,
    unanswered: reviews.filter((r) => !r.replied && !r.skipped).length,
    replied: reviews.filter((r) => r.replied).length,
    positive: reviews.filter((r) => r.rating >= 4).length,
    negative: reviews.filter((r) => r.rating <= 2).length,
    // The approval queue is the source of truth for this count.
    need_approval: pendingReplies.length,
    flagged: reviews.filter((r) => r.skipped).length,
    edited: reviews.filter((r) => r.edited).length,
  }), [reviews, pendingReplies]);

  const filtered = reviews.filter((r) => {
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
  const starGroup = view.kind === "star" ? reviews.filter((r) => r.rating === view.stars) : [];
  const intelligence = useMemo(() => buildIntelligence(reviews), [reviews]);

  // Stored intelligence (analyze once, serve from DB; re-run on demand).
  const [aiIntel, setAiIntel] = useState<{
    intel: Intelligence; source: string; model: string | null; ragUsed: boolean;
    analyzedAt: string | null; stale: boolean; newCount: number;
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
        label: from.toLocaleDateString("en", { month: "long", year: "numeric", timeZone: "UTC" }),
      };
    }
    const labels: Record<number, string> = { 7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days", 365: "Last 12 months" };
    return { days: intelDays, date_from: null as string | null, date_to: null as string | null, label: labels[intelDays] ?? `Last ${intelDays} days` };
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
      setBanner({ kind: "ok", text: `Analysis updated and stored for ${intelInterval.label.toLowerCase()}.` });
    } catch {
      setBanner({ kind: "err", text: "Analysis failed — try again in a minute." });
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
      setBanner({ kind: "ok", text: engine ? "Rewritten by the full AI engine — strategies, databank and validation applied." : "Draft rewritten by the AI engine." });
      setTimeout(() => setBanner(null), 3000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, engine ? "Engine rewrite failed. Try again." : "Could not regenerate. Try again.") });
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
      setBanner({ kind: "ok", text: "Changes saved." });
      setTimeout(() => setBanner(null), 3000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, "Could not save edits.") });
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
      setBanner({ kind: "ok", text: "Updated reply published to Google." });
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, "Could not publish the updated reply.") });
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
      const saved = await editReply(item.locationId, item.replyId, responseText.trim());
      setReviews((prev) => prev.map((r) => r.id === item.id ? { ...r, reply_text: saved.reply_text, status: saved.status } : r));
      setEditingResponse(null);
      await loadPendingReplies();
      setBanner({
        kind: "ok",
        text: wasPosted
          ? "Response updated — sent back for approval; approving publishes the update to Google."
          : "Response updated.",
      });
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, "Could not save response.") });
      setTimeout(() => setBanner(null), 5000);
    } finally {
      setSavingResponse(false);
    }
  }

  function responseBadge(status?: string) {
    const base = "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide";
    if (status === "posted") return <span className={`${base} bg-emerald-100 text-emerald-700`}>Published</span>;
    if (status === "pending_approval") return <span className={`${base} bg-amber-100 text-amber-700`}>Pending approval</span>;
    if (status === "failed") return <span className={`${base} bg-red-100 text-red-700`}>Failed</span>;
    if (status === "approved") return <span className={`${base} bg-sky-100 text-sky-700`}>Approved</span>;
    return <span className={`${base} bg-ink/[0.05] text-ink/40`}>Response</span>;
  }

  async function approveDraft(d: ReviewReplyDTO) {
    setApprovingId(d.id);
    try {
      if (isDraftEdited(d)) await editReply(d.channel_id, d.id, getDraftText(d));
      await approveReply(d.channel_id, d.id);
      setPendingReplies((prev) => prev.filter((x) => x.id !== d.id));
      setBanner({ kind: "ok", text: "Reply approved and published to Google." });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch (e) {
      setBanner({ kind: "err", text: detailMsg(e, "Could not publish that reply. Try again.") });
      setTimeout(() => setBanner(null), 6000);
    } finally {
      setApprovingId(null);
    }
  }

  async function approveAllDrafts() {
    if (approvingAllPending || approvingId !== null) return;
    setApprovingAllPending(true);
    let ok = 0;
    for (const d of pendingReplies) {
      try {
        if (isDraftEdited(d)) await editReply(d.channel_id, d.id, getDraftText(d));
        await approveReply(d.channel_id, d.id);
        ok += 1;
      } catch {}
    }
    setBanner({
      kind: ok === pendingReplies.length ? "ok" : "err",
      text: ok === pendingReplies.length
        ? `Published all ${ok} repl${ok === 1 ? "y" : "ies"} to Google.`
        : `Published ${ok} of ${pendingReplies.length}. The rest failed — try again.`,
    });
    setTimeout(() => setBanner(null), 5000);
    await loadPendingReplies();
    void fetchReviews(false);
    setApprovingAllPending(false);
  }

  const handleSkip = async () => {
    if (view.kind !== "detail") return;
    setSkippingId(active!.id);
    try {
      await apiFetch(`/api/v1/analytics/reviews/insights/${active!.id}/skip`, { method: "POST" });
      setBanner({ kind: "ok", text: "Marked as unavailable on Google — removed from unanswered." });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch {
      setBanner({ kind: "err", text: "Could not mark as skipped — try again." });
      setTimeout(() => setBanner(null), 3000);
    } finally {
      setSkippingId(null);
    }
  };

  const handleFlag = async (reviewId: string) => {
    try {
      await apiFetch(`/api/v1/analytics/reviews/insights/${reviewId}/skip`, { method: "POST" });
      setBanner({ kind: "ok", text: "Review flagged as unavailable — it no longer appears in queues." });
      setTimeout(() => setBanner(null), 3000);
      void fetchReviews(false);
    } catch {
      setBanner({ kind: "err", text: "Could not flag — try again." });
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
          ? { ...r, edited: false, editedAt: null, previousRating: null, previousText: null }
          : r
      ));
    } catch {
      setBanner({ kind: "err", text: "Could not dismiss the edit — try again." });
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
      if (!reviewText) throw new Error("Star-only review — no text for AI engine; please write manually.");

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

      if (!finalText) throw new Error("Engine returned no response");
      setReplyDraft(finalText);

      // If the engine flagged it as possibly off-topic, surface it inline — same wording as playground.
      if (lastRelevance?.verdict === "off_topic") {
        setBanner({
          kind: "err",
          text: `Flagged: might be irrelevant to this business — ${lastRelevance.reason} Queued for human review. Please edit before publishing.`,
        });
        setTimeout(() => setBanner(null), 6000);
      } else if (finalStatus === "needs_review") {
        setBanner({ kind: "err", text: "Draft needs review — validation flagged issues. Please edit before publishing." });
        setTimeout(() => setBanner(null), 5000);
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      const msg = e instanceof Error ? e.message : "AI engine failed";
      // Surface engine's own 400 when Automations model is missing
      if (msg.includes("No reply model configured") || msg.includes("Channel not found")) {
        setAiError("AI replies aren't configured for this location yet. Open Automations and turn the engine on, then try again.");
        setBanner({ kind: "err", text: "AI engine isn't configured for this location." });
      } else if (msg.toLowerCase().includes("star-only")) {
        setAiError(msg);
      } else {
        // Brief fallback: keep pipeline honest — don't silently invent a template as if it were the engine.
        setAiError(msg.slice(0, 280));
        setBanner({ kind: "err", text: `AI engine error: ${msg.slice(0, 120)}` });
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
      setBanner({ kind: "ok", text: "Draft copied — paste it in Google or Localith to publish." });
    } catch {
      setBanner({ kind: "err", text: "Could not copy — select the text manually." });
    } finally {
      setReplying(false);
      setTimeout(() => setBanner(null), 3000);
    }
  };

  const analytics = useMemo(() => {
    const total = reviews.length;
    const dist = [5, 4, 3, 2, 1].map((s) => ({ stars: s, count: reviews.filter((r) => r.rating === s).length }));
    const avg = total ? reviews.reduce((a, r) => a + r.rating, 0) / total : 0;
    const replied = reviews.filter((r) => r.replied).length;
    const thisMonth = reviews.filter((r) => r.createdAt.slice(0, 7) === "2026-09").length;
    const lastMonth = reviews.filter((r) => r.createdAt.slice(0, 7) === "2026-08").length;
    const months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"].map((m) => ({
      label: m.slice(5),
      count: reviews.filter((r) => r.createdAt.slice(0, 7) === m).length,
    }));
    const maxMonth = Math.max(1, ...months.map((m) => m.count));
    return { total, dist, avg, replied, responseRate: total ? Math.round((replied / total) * 100) : 0, thisMonth, lastMonth, months, maxMonth };
  }, [reviews]);

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
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-4 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80" data-tour="reviews-header">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog">Reviews</h1>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">
              {counts.all} total · {counts.unanswered} unanswered · {counts.replied} replied
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <select value={selectedId ?? ""} onChange={(e) => { setSelectedId(e.target.value); setPage(1); setView({ kind: "list" }); }}
                className="w-52 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog">
                <option value={ALL_BRANCHES}>All branches{locations.length > 0 ? ` (${locations.length})` : ""}</option>
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <button onClick={() => fetchReviews(true)} disabled={refreshing} className="btn-secondary disabled:opacity-50">
              {refreshing ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Syncing...</span> : "Reconcile"}
            </button>
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{banner.text}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-6xl">
          {view.kind === "detail" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">Reviews</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">Review details</span>
            </nav>
          )}

          {view.kind === "star" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">Reviews</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              {view.from === "intelligence" ? (
                <>
                  <button onClick={() => setView({ kind: "intelligence" })} className="font-medium hover:text-deep-violet">Review Intelligence</button>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </>
              ) : null}
              <span className="font-semibold text-ink dark:text-fog">{view.stars}★ details</span>
            </nav>
          )}

          {view.kind === "intelligence" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">Reviews</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">Review Intelligence</span>
            </nav>
          )}

{view.kind === "list" && (
              <div className="mx-auto max-w-6xl px-4">
                <div className="grid grid-cols-12 gap-4">
                  {/* Left column: 3/4 - Reviews list */}
                  <div className="col-span-12 lg:col-span-8 space-y-4">
<div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Review filters">
                        {PRIMARY_TABS.map((t) => (
                          <button
                            key={t}
                            role="tab"
                            aria-selected={tab === t}
                            onClick={() => pickTab(t)}
                            className={`relative inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                              tab === t
                                ? t === "need_approval" && counts.need_approval > 0
                                  ? "border-coral/40 bg-coral/[0.06] text-coral"
                                  : "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet"
                                : "border-ink/[0.08] bg-white text-ink/60 hover:border-ink/[0.16] hover:text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60 dark:hover:text-fog"
                            }`}
                          >
                            {TAB_LABELS[t]} ({counts[t]})
                            {t === "need_approval" && counts.need_approval > 0 && (
                              <span aria-hidden className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
                                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-coral opacity-60" />
                                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-coral ring-2 ring-white dark:ring-ink" />
                              </span>
                            )}
                          </button>
                        ))}
                        <div className="relative">
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
                            {MORE_TABS.includes(tab) ? `${TAB_LABELS[tab]} (${counts[tab]})` : "More+"}
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden className={`h-3 w-3 transition ${moreOpen ? "rotate-180" : ""}`}>
                              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </button>
                          {moreOpen && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setMoreOpen(false)} />
                              <div role="menu" className="absolute left-0 top-full z-20 mt-1 w-44 rounded-xl border border-ink/[0.08] bg-white py-1 shadow-lg dark:border-fog/[0.1] dark:bg-ink">
                                {MORE_TABS.map((t) => (
                                  <button
                                    key={t}
                                    role="menuitem"
                                    onClick={() => { pickTab(t); setMoreOpen(false); }}
                                    className={`flex w-full items-center justify-between px-3 py-2 text-left text-[12px] font-medium outline-none transition hover:bg-ink/[0.03] focus-visible:bg-ink/[0.03] dark:hover:bg-fog/[0.05] ${
                                      tab === t ? "font-bold text-deep-violet" : "text-ink/70 dark:text-fog/70"
                                    }`}
                                  >
                                    {TAB_LABELS[t]}
                                    <span className="text-[11px] tabular-nums opacity-60">{counts[t]}</span>
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
                          <p className="mt-3 text-[14px] font-bold text-ink dark:text-fog">Queue is clear</p>
                          <p className="mt-1 max-w-xs text-[12px] leading-relaxed text-ink/45">
                            No replies waiting for approval. New AI drafts land here automatically when Automations writes them.
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
                                    Approval queue
                                    <span className="ml-2 rounded-full bg-deep-violet px-2 py-0.5 text-[11px] font-bold tabular-nums text-white">{pendingReplies.length}</span>
                                  </h3>
                                  <p className="text-[12px] text-ink/50 dark:text-fog/50">
                                    {pendingReplies.length === 1 ? "1 AI draft" : `${pendingReplies.length} AI drafts`} waiting — edit, rewrite, or publish to Google
                                  </p>
                                </div>
                              </div>
                              <button
                                onClick={() => void approveAllDrafts()}
                                disabled={approvingAllPending || approvingId !== null}
                                className="inline-flex items-center gap-1.5 rounded-xl bg-emerald px-4 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-emerald/25 outline-none transition hover:bg-emerald/90 focus-visible:ring-2 focus-visible:ring-emerald/40 active:scale-[0.98] disabled:opacity-50"
                              >
                                {approvingAllPending ? (
                                  <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Approving all…</>
                                ) : (
                                  <>
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5" aria-hidden>
                                      <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                    Approve all & publish
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
                              const when = days === null ? "" : days <= 0 ? "today" : days === 1 ? "yesterday" : days < 30 ? `${days}d ago` : new Date(d.created_at).toLocaleDateString("en", { month: "short", day: "numeric" });
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
                                        <p className="truncate text-[13px] font-bold text-ink dark:text-fog">{d.reviewer_name ?? "Anonymous"}</p>
                                        <GoogleStars rating={d.rating} />
                                      </div>
                                                                            <p className="mt-0.5 text-[11px] text-ink/40">
                                        left a {d.rating}★ review · {when}
                                        {(d as ReviewReplyDTO & { review_url?: string }).review_url && (
                                          <>
                                            {" · "}
                                            <a
                                              href={(d as ReviewReplyDTO & { review_url?: string }).review_url}
                                              target="_blank"
                                              rel="noreferrer"
                                              className="font-semibold text-deep-violet underline-offset-2 hover:underline"
                                            >
                                              View on Google
                                            </a>
                                          </>
                                        )}
                                      </p>
                                    </div>
                                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-600">
                                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                                      Pending
                                    </span>
                                  </div>

                                  {/* Original review */}
                                  {d.review_text && (
                                    <blockquote className="mt-3 rounded-r-lg border-l-[3px] border-deep-violet/30 bg-ink/[0.025] py-2 pl-3 pr-2 dark:bg-fog/[0.04]">
                                      <p className="line-clamp-3 text-[13px] italic leading-5 text-ink/65 dark:text-fog/60">“{d.review_text}”</p>
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
                                          AI draft
                                        </span>
                                        {(d.generation_attempt ?? 1) > 1 && (
                                          <span className="text-[10px] font-semibold text-ink/40 dark:text-fog/40">
                                            try #{d.generation_attempt}
                                          </span>
                                        )}
                                      </span>
                                      <span className="inline-flex shrink-0 items-center gap-1">
                                        <button
                                          onClick={() => void regenDraft(d, true)}
                                          disabled={regenId === d.id || busy || approvingAllPending}
                                          title="Re-run the full AI pipeline: analysis, strategies, databank tools, validation"
                                          className="inline-flex items-center gap-1 rounded-lg bg-deep-violet/[0.08] px-2 py-1 text-[11px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.15] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                                        >
                                          {regenId === d.id ? (
                                            <><span className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/30 border-t-deep-violet" /> Engine…</>
                                          ) : (
                                            <>
                                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3" aria-hidden>
                                                <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" strokeLinecap="round" strokeLinejoin="round" />
                                              </svg>
                                              Run engine
                                            </>
                                          )}
                                        </button>
                                        <button
                                          onClick={() => void regenDraft(d)}
                                          disabled={regenId === d.id || busy || approvingAllPending}
                                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-deep-violet outline-none transition hover:bg-deep-violet/[0.08] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                                        >
                                          {regenId === d.id ? (
                                            <><span className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/30 border-t-deep-violet" /> Rewriting…</>
                                          ) : (
                                            <>
                                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3" aria-hidden>
                                                <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" strokeLinecap="round" strokeLinejoin="round" />
                                              </svg>
                                              Rewrite
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
                                      aria-label="AI draft reply — editable"
                                      className="w-full resize-y rounded-lg border border-deep-violet/[0.15] bg-white p-3 text-[13px] leading-6 text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/50 focus:ring-2 focus:ring-deep-violet/[0.12] dark:bg-ink dark:text-fog"
                                    />
                                    <div className="mt-1.5 flex items-center justify-between text-[10px] font-medium">
                                      <span className={edited ? "text-amber-600" : "text-ink/35"}>
                                        {edited ? "Edited — not saved yet" : "Grounded in your business profile"}
                                      </span>
                                      <span className="tabular-nums text-ink/35">{text.length}/1000</span>
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
                                        <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Publishing…</>
                                      ) : (
                                        <>
                                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5" aria-hidden>
                                            <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
                                          </svg>
                                          Approve & publish
                                        </>
                                      )}
                                    </button>
                                    {edited && (
                                      <button
                                        onClick={() => void saveDraft(d)}
                                        disabled={busy}
                                        className="rounded-xl bg-deep-violet/[0.07] px-3.5 py-2 text-[12px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.12] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
                                      >
                                        Save edits
                                      </button>
                                    )}
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
                              See more drafts ({pendingReplies.length - visiblePending.length} left)
                            </button>
                          )}
                        </>
                      )
                    ) : filtered.length === 0 ? (
                      <div className="flex flex-col items-center rounded-2xl border border-dashed border-ink/[0.12] bg-white py-16 dark:border-fog/[0.12] dark:bg-ink">
                          <p className="text-[14px] font-medium text-ink/40">
                            {reviews.length === 0 && tab === "all"
                              ? "No reviews yet — press Reconcile after syncing your listing."
                              : tab === "flagged"
                                ? "No reviews flagged yet — use the flag button on any review."
                                : tab === "edited"
                                  ? "No edited reviews — review content is compared on every sync."
                                  : "No reviews in this view"}
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
                          <p className="text-[11px] text-ink/40">Page {safePage} of {totalPages} · {filtered.length} reviews</p>
                          <div className="flex gap-1">
                            <button onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1} className="btn-secondary !px-3 !py-1.5 disabled:opacity-40">Prev</button>
                            {Array.from({ length: totalPages }).slice(0, 5).map((_, i) => (
                              <button key={i} onClick={() => setPage(i + 1)}
                                className={`rounded-lg px-2.5 py-1.5 text-[12px] font-semibold ${safePage === i + 1 ? "bg-deep-violet text-white" : "text-ink/50 hover:bg-ink/[0.04]"}`}>
                                {i + 1}
                              </button>
                            ))}
                            <button onClick={() => setPage(Math.min(totalPages, safePage + 1))} disabled={safePage >= totalPages} className="btn-secondary !px-3 !py-1.5 disabled:opacity-40">Next</button>
                          </div>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Right column: 1/4 - Insights */}
                  <div className="col-span-12 lg:col-span-4 space-y-4">
                    {/* Rating breakdown leads the column: the star mix is the
                        fastest read on business health, and it is the way in
                        to the full intelligence view. */}
                    <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                      <button onClick={() => setView({ kind: "intelligence" })} className="block w-full text-left">
                        <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Rating breakdown</h3>
                        <p className="text-[11px] text-ink/35">Sayvors-derived · tap anywhere for full intelligence.</p>
                      </button>
                      <div className="mt-3 space-y-1">
                        {analytics.dist.map((d) => (
                          <button key={d.stars} onClick={() => setView({ kind: "star", stars: d.stars, from: "list" })}
                            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-deep-violet/[0.05] hover:ring-1 hover:ring-deep-violet/20">
                            <span className="w-8 text-[11px] font-medium text-ink/50">{d.stars} ★</span>
                            <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                              <span className="block h-full rounded-full bg-gradient-to-r from-[#FBBC05] to-[#EA4335]" style={{ width: `${analytics.total ? (d.count / analytics.total) * 100 : 0}%` }} />
                            </span>
                            <span className="w-8 text-right text-[11px] text-ink/50">{d.count}</span>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3 text-ink/30"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                          </button>
                        ))}
                      </div>
                      <button onClick={() => setView({ kind: "intelligence" })}
                        className="mt-3 w-full rounded-xl bg-deep-violet/[0.06] py-2 text-[12px] font-bold text-deep-violet transition hover:bg-deep-violet hover:text-white">
                        See more insights →
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <StatCard label="Average Rating" value={`${analytics.avg.toFixed(1)} ★`} />
                      <StatCard label="Total Reviews" value={String(analytics.total)} />
                      <StatCard label="Response Rate" value={`${analytics.responseRate}%`} />
                      <StatCard label="Unanswered" value={String(counts.unanswered)} />
                      <StatCard label="Flagged" value={String(counts.flagged)} />
                    </div>
                    <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                      <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Reviews trend</h3>
                      <p className="text-[11px] text-ink/35">Last 6 months · this {analytics.thisMonth} / last {analytics.lastMonth}.</p>
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
              total={reviews.length}
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
                        Posted on
                        <span className="font-medium tracking-tight">
                          <span className="text-[#4285F4]">G</span><span className="text-[#EA4335]">o</span><span className="text-[#FBBC05]">o</span><span className="text-[#4285F4]">g</span><span className="text-[#34A853]">l</span><span className="text-[#EA4335]">e</span>
                        </span>
                      </span>
                      <span aria-hidden className="text-[#DADCE0]">•</span>
                      <span title={active.createdAt}>{active.createdAt ? new Date(active.createdAt.length === 10 ? `${active.createdAt}T00:00:00` : active.createdAt).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" }) : "—"}</span>
                    </div>
                    <p className="mt-1 truncate text-[12px] leading-4 text-[#5F6368]">{active.locationName}</p>
                  </div>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-[#DADCE0]">
                    <img src="/google.svg" alt="Google" width={16} height={16} className="h-4 w-4" />
                  </span>
                </div>

                {/* Rating + status row — green for replied = In Progress pattern */}
                <div className="mx-4 mt-3 flex flex-wrap items-center gap-2 border-y border-[#E8EAED] py-3">
                  <span className="flex items-center gap-1.5">
                    <Stars rating={active.rating} />
                    <span className="text-[12px] font-medium text-[#202124]">{active.rating.toFixed(1)}</span>
                  </span>
                  <span aria-hidden className="text-[#DADCE0]">•</span>
                  {active.replied ? (
                    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#137333]">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#34A853]" /> Replied
                    </span>
                  ) : active.skipped ? (
                    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#5F6368]">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#AAAAAA]" /> Unavailable on Google
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#5F6368]">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#FABB05]" /> Needs reply
                    </span>
                  )}
                  <span aria-hidden className="text-[#DADCE0]">•</span>
                  <span className="text-[12px] text-[#5F6368]">Updated {active.createdAt ? (() => { const d = new Date(active.createdAt.length === 10 ? `${active.createdAt}T00:00:00` : active.createdAt); const days = Math.floor((Date.now() - d.getTime())/86400000); if (days<=0) return "today"; if (days===1) return "yesterday"; if (days<7) return `${days} days ago`; return d.toLocaleDateString("en", {month:"short", day:"numeric"}); })() : "—"}</span>
                  <span className="flex-1" />
                  {active.reviewUrl && (
                    <a href={active.reviewUrl} target="_blank" rel="noreferrer" className="text-[12px] font-medium text-[#1A73E8] hover:text-[#174EA6] hover:underline underline-offset-2">
                      View on Google
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
                        Review edited by the customer
                      </p>
                      <button
                        onClick={() => void handleDismissEdit()}
                        disabled={dismissingEdit}
                        className="shrink-0 rounded-full border border-[#FDE293] px-3 py-1 text-[12px] font-medium text-[#B45309] transition hover:bg-[#FEF7E0]/60 disabled:opacity-40"
                      >
                        {dismissingEdit ? "Dismissing…" : "Dismiss"}
                      </button>
                    </div>
                    <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
                      {/* Before */}
                      <div className="rounded-lg border border-[#F0DCA8] bg-white/70 px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-[#B45309]">Before</span>
                          {active.previousRating != null && (
                            <span className="ml-auto inline-flex items-center gap-1.5">
                              <GoogleStars rating={active.previousRating} size="h-3 w-3" />
                              <span className="text-[11px] font-medium text-[#B45309]">{active.previousRating.toFixed(1)}</span>
                            </span>
                          )}
                        </div>
                        <p className="mt-1.5 line-clamp-5 text-[12.5px] italic leading-[18px] text-[#8A6A3B] line-through decoration-[#D9B98C]/70 decoration-1">
                          {active.previousText || "No written comment — star rating only."}
                        </p>
                      </div>
                      {/* After */}
                      <div className="rounded-lg border border-[#DADCE0] bg-white px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-[#5F6368]">After</span>
                          <span className="ml-auto inline-flex items-center gap-1.5">
                            <GoogleStars rating={active.rating} size="h-3 w-3" />
                            <span className="text-[11px] font-medium text-[#202124]">{active.rating.toFixed(1)}</span>
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-5 text-[12.5px] leading-[18px] text-[#202124]">
                          {active.comment || "No written comment — star rating only."}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Comment — clean quote, no purple */}
                <div className="px-4 py-3">
                  <p className="whitespace-pre-wrap break-words text-[13px] leading-6 text-[#202124]">{active.comment ? `“${active.comment}”` : <span className="italic text-[#5F6368]">No written comment — star rating only.</span>}</p>
                  <ReviewMedia media={active.media} />
                </div>

                {/* Reply composer — Material, not violet */}
                <div className="mx-4 mb-4 rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-4">
                  <h3 className="text-[13px] font-medium text-[#202124]">Your reply</h3>
                  {active.reply_text && (
                    <div className="mt-3 rounded-md border border-[#DADCE0] bg-white px-3 py-3">
                      <div className="flex items-center gap-2">
                        <p className="text-[12px] font-medium text-[#202124]">Your response</p>
                        {responseBadge(active.status)}
                        <span className="flex-1" />
                        {editingResponse === active.id ? null : active.replyId ? (
                          <button
                            onClick={() => { setEditingResponse(active.id); setResponseText(active.reply_text ?? ""); }}
                            className="text-[12px] font-medium text-[#1A73E8] hover:underline"
                          >
                            Edit
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
                              Saving sends this back for approval — approving publishes the update to Google.
                            </p>
                          )}
                          <div className="mt-2 flex items-center justify-end gap-2">
                            <button
                              onClick={() => setEditingResponse(null)}
                              disabled={savingResponse}
                              className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[#5F6368] hover:bg-ink/[0.04] disabled:opacity-40"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => void saveResponse(active)}
                              disabled={!responseText.trim() || savingResponse}
                              className="rounded-md bg-[#1A73E8] px-4 py-1.5 text-[12px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50"
                            >
                              {savingResponse ? "Saving…" : "Save response"}
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
                        <p className="text-[12px] font-medium text-[#5F6368]">Removed from Google</p>
                        <p className="mt-0.5 text-[12px] leading-4 text-[#5F6368]/80">
                          The reviewer deleted this review, or Google took it down, so it is no longer on the listing and no reply is possible. We keep your copy for reference — it drops out of your averages, and comes back on its own if the review returns.
                        </p>
                      </div>
                    </div>
                  ) : active.replied ? (
                     <>
                       <div className="mt-2 flex items-start gap-2 rounded-md border border-[#CEEAD6] bg-[#E6F4EA] px-3 py-2.5">
                         <span aria-hidden className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-[#34A853]" />
                         <div>
                           <p className="text-[12px] font-medium text-[#137333]">Replied on Google</p>
                           <p className="mt-0.5 text-[12px] leading-4 text-[#137333]/80">
                             {active.reply_text
                               ? "This review already has a published reply. You can replace it below — the original stays in Google's edit history."
                               : "Replied on Google, but the reply text wasn't returned to us, so there is nothing to edit yet. Type the reply you want live below."}
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
                           Edit &amp; Republish
                         </button>
                       )}
                       {!active.replyId && editingResponse === active.id && (
                         <div className="mt-3">
                           <label className="text-[12px] font-medium text-[#202124]" htmlFor="update-reply">
                             Your live reply on Google
                           </label>
                           <textarea
                             id="update-reply"
                             value={responseText}
                             onChange={(e) => setResponseText(e.target.value)}
                             rows={4}
                             maxLength={1000}
                             placeholder="Write the reply that should be live on Google…"
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
                               {savingResponse ? "Publishing…" : "Republish to Google"}
                             </button>
                           </div>
                           <p className="mt-1.5 text-[11px] leading-4 text-[#5F6368]">
                             Publishing replaces the reply currently live on Google.
                           </p>
                         </div>
                       )}
                     </>
                   ) : active.skipped ? (
                     <div className="mt-2 flex items-start gap-2 rounded-md border border-[#E8EAED] bg-[#F8F9FA] px-3 py-2.5">
                       <span aria-hidden className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-[#AAAAAA]" />
                       <div>
                         <p className="text-[12px] font-medium text-[#5F6368]">Unavailable on Google</p>
                         <p className="mt-0.5 text-[12px] leading-4 text-[#5F6368]/80">The reviewer deleted this review or Google removed it. No reply is possible. You can still view it via the link below.</p>
                       </div>
                     </div>
                   ) : (
                     <>
                       <div className="mt-3 inline-flex rounded-full border border-[#DADCE0] bg-white p-1">
                         <button
                           onClick={() => setReplyMode("manual")}
                           className={`rounded-full px-3 py-1 text-[12px] font-medium transition ${replyMode === "manual" ? "bg-[#1A73E8] text-white shadow-sm" : "text-[#5F6368] hover:text-[#202124]"}`}
                         >
                           Write myself
                         </button>
                         <button
                           onClick={() => generateAiReply()}
                           className={`rounded-full px-3 py-1 text-[12px] font-medium transition ${replyMode === "ai" ? "bg-[#1A73E8] text-white shadow-sm" : "text-[#5F6368] hover:text-[#202124]"}`}
                         >
                           Write with AI
                         </button>
                       </div>
                       <button
                         onClick={() => void handleSkip()}
                         disabled={skippingId === active?.id}
                         className="mt-2 inline-flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-medium text-[#5F6368] transition hover:bg-ink/[0.04] disabled:opacity-40"
                       >
                         {skippingId === active?.id ? "Marking…" : "Mark as unavailable on Google"}
                       </button>
                      {aiLoading ? (
                        <div className="mt-3 space-y-2 rounded-md border border-[#DADCE0] bg-white px-3 py-3">
                          <div className="flex items-center gap-2">
                            <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#DADCE0] border-t-[#1A73E8]" />
                            <p className="text-[12px] font-medium text-[#202124]">Engine is analyzing • validating • grounding</p>
                          </div>
                          <p className="text-[11px] leading-4 text-[#5F6368]">
                            Same pipeline as <a href="/dashboard/reviews/playground" target="_blank" rel="noreferrer" className="font-medium text-[#1A73E8] hover:underline">Playground</a> — relevance → strategies → databank lookups → grounded generation.
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
                            placeholder={replyMode === "ai" ? "AI draft — edit if you like, then copy…" : "Write your reply…"}
                            className="mt-3 min-h-[96px] w-full resize-y rounded-md border border-[#DADCE0] bg-white px-3 py-2.5 text-[13px] leading-5 text-[#202124] placeholder:text-[#5F6368]/60 outline-none focus:border-[#1A73E8] focus:ring-1 focus:ring-[#1A73E8]"
                          />
                          {aiError && (
                            <p className="mt-2 rounded-md border border-[#FAD2CF] bg-[#FCE8E6] px-2.5 py-2 text-[12px] leading-4 text-[#C5221F]">{aiError}</p>
                          )}
                          {aiTrace && aiTrace.length > 0 && !aiError && (
                            <details className="mt-2 rounded-md border border-[#E8EAED] bg-white" open>
                              <summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-medium text-[#1A73E8] hover:underline">
                                Engine trace — same as Playground ({aiTrace.length} steps) — scroll to see all tools & results
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
                                  Open full Playground →
                                </a>
                              </div>
                            </details>
                          )}
                        </>
                      )}
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {replyMode === "ai" && !aiLoading && (
                          <button onClick={() => generateAiReply()} className="text-[12px] font-medium text-[#1A73E8] hover:underline">
                            {replyDraft ? "Regenerate with engine" : "Generate with engine"}
                          </button>
                        )}
                        <span className="flex-1" />
                        <span className="text-[11px] text-[#5F6368]">{replyDraft.length}/1000</span>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button onClick={() => copyDraft()} disabled={!replyDraft.trim() || replying || aiLoading} className="inline-flex items-center justify-center rounded-md bg-[#1A73E8] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50">
                          {replying ? <span className="inline-flex items-center gap-1.5"><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Copying…</span> : "Copy draft"}
                        </button>
                        <span className="inline-flex items-center text-[11px] leading-4 text-[#5F6368]">Copy & publish from Google or Localith</span>
                      </div>
                      <p className="mt-2 text-[11px] leading-4 text-[#5F6368]">Powered by the review strategy engine — grounded in your databank, validated before it reaches you. Full trace in Playground.</p>
                    </>
                  )}
                </div>

                {/* Meta — subtle gray, icon style */}
                <div className="flex flex-wrap gap-4 border-t border-[#E8EAED] px-4 py-3 text-[12px]">
                  <span className="inline-flex items-center gap-1.5 text-[#5F6368]">
                    <span aria-hidden className="text-[11px]">◐</span> Sentiment <span className="font-medium capitalize text-[#202124]">{active.sentiment ?? "—"}</span>
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
              <button onClick={() => setView({ kind: "list" })} className="text-[13px] font-medium text-[#1A73E8] hover:underline">← Back to reviews</button>
            </div>
          )}

          {view.kind === "intelligence" && (
            <IntelligencePage
              intelligence={aiIntel?.intel ?? intelligence}
              total={reviews.length}
              locationName={locations.find((l) => l.id === selectedId)?.name ?? ""}
              aiMeta={aiIntel ? { source: aiIntel.source, model: aiIntel.model, ragUsed: aiIntel.ragUsed, analyzedAt: aiIntel.analyzedAt, stale: aiIntel.stale, newCount: aiIntel.newCount } : null}
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
  const photos = (media ?? []).filter((m) => m && m.kind !== "video" && m.url);
  const videos = (media ?? []).filter((m) => m && m.kind === "video");
  if (photos.length === 0 && videos.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {photos.map((m, i) => {
        const src = String(m.url).startsWith("http") ? String(m.url) : `${API_ORIGIN}${m.url}`;
        return (
          <a key={i} href={src} target="_blank" rel="noreferrer" className="group relative block">
            {/* eslint-disable-next-line @next/next/no-img-element -- our own
                already-validated raster copy; the optimizer would re-encode it */}
            <img
              src={src}
              alt={m.label || `Photo from the reviewer (${i + 1})`}
              loading="lazy"
              className="h-24 w-24 rounded-lg border border-[#E8EAED] object-cover transition group-hover:opacity-80"
            />
          </a>
        );
      })}
      {videos.map((m, i) => (
        <span
          key={`v${i}`}
          title={m.label || "Video attached to the review"}
          className="inline-flex h-24 w-24 items-center justify-center rounded-lg border border-[#E8EAED] bg-[#F8F9FA] text-[11px] text-[#5F6368]"
        >
          ▶ Video
        </span>
      ))}
    </div>
  );
}

function mapInsights(raw: unknown, channelNames: Record<string, string>, fallbackName: string): ReviewItem[] {  if (!Array.isArray(raw)) return [];
  return raw.map((it: unknown, i: number) => {
    const r = (it ?? {}) as Record<string, unknown>;
    const channelId = String(r.channel_id ?? "");
    return {
      id: String(r.id ?? r.review_id ?? `insight_${i}`),
      review_id: String(r.review_id ?? r.id ?? ""),
      locationId: channelId,
      locationName: channelNames[channelId] ?? fallbackName,
      reviewer: String(r.reviewer_name ?? "Google user"),
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
      reply_text: typeof r.reply_text === "string" ? r.reply_text : undefined,
      // The API sends the response row's state as `reply_status`; reading
      // `status` always yielded undefined, so the badge and the
      // "sends this back for approval" hint never rendered.
      status: typeof r.reply_status === "string" ? r.reply_status : undefined,
      replyId: typeof r.reply_id === "string" ? r.reply_id : undefined,
    };
  });
}

function StarInsightPage({ stars, group, total, onBack, onOpen }: { stars: number; group: ReviewItem[]; total: number; onBack: () => void; onOpen: (id: string) => void }) {
  const share = total ? Math.round((group.length / total) * 100) : 0;
  const replied = group.filter((r) => r.replied).length;
  const signals = topSignals(group.map((r) => r.comment));
  const verdict = stars >= 4
    ? "Strength — protect what earns these ratings."
    : stars === 3
      ? "Swing zone — small fixes convert these to 4–5★."
      : "Risk zone — reply fast and fix the root cause.";
  const action = stars >= 4
    ? "Thank them quickly and invite them back."
    : stars === 3
      ? "Acknowledge the friction and state one concrete fix."
      : "Apologize with a concrete fix, then address the root cause operationally.";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[17px] font-bold text-ink dark:text-fog">{stars}★ insights</h2>
          <p className="text-[12px] text-ink/55 dark:text-fog/60">{group.length} reviews · {share}% of total · replied {replied}/{group.length}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${stars >= 4 ? "bg-emerald-100 text-emerald-700" : stars === 3 ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"}`}>
          {stars >= 4 ? "High" : stars === 3 ? "Mixed" : "Low"}
        </span>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">Overview</h3>
          <p className="text-[12px] leading-relaxed text-ink/60">{verdict}</p>
          <p className="mt-3 text-[12px] text-ink/60">Share <span className="font-bold text-ink">{share}%</span> · response <span className="font-bold text-ink">{group.length ? Math.round((replied / group.length) * 100) : 0}%</span></p>
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">Top signals</h3>
          {signals.length ? (
            <ul className="space-y-2">
              {signals.map((s) => (
                <li key={s} className="rounded-lg bg-ink/[0.04] px-2.5 py-1.5 text-[12px] font-semibold text-ink/70">{s}</li>
              ))}
            </ul>
          ) : <p className="text-[12px] text-ink/40">{group.length ? "No strong word signals in these reviews." : "No reviews at this rating yet."}</p>}
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">Recommended action</h3>
          <p className="text-[12px] leading-relaxed text-ink/60">{action}</p>
          <p className="mt-3 text-[11px] text-ink/40">Sayvors-derived from retrieved reviews.</p>
        </section>
      </div>
      <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
        <h3 className="mb-2 text-[13px] font-semibold text-ink dark:text-fog">Matching reviews</h3>
        {group.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-ink/40">No reviews at this rating yet.</p>
        ) : (
          <div className="space-y-1.5">
            {group.map((r) => (
              <button key={r.id} onClick={() => onOpen(r.id)} className="block w-full truncate rounded-lg px-2.5 py-2 text-left text-[12px] text-ink/70 ring-1 ring-ink/[0.05] hover:ring-deep-violet/30 dark:text-fog/70">
                <span className="font-semibold text-ink dark:text-fog">{r.reviewer}</span> — “{r.comment}”
              </button>
            ))}
          </div>
        )}
      </div>
      <button onClick={onBack} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to reviews</button>
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

function buildIntelligence(reviews: ReviewItem[]): Intelligence {
  const total = reviews.length;
  const avg = total ? reviews.reduce((a, r) => a + r.rating, 0) / total : 0;
  const pos = reviews.filter((r) => r.rating >= 4).length;
  const neu = reviews.filter((r) => r.rating === 3).length;
  const neg = reviews.filter((r) => r.rating <= 2).length;
  const sentimentScore = total ? Math.round((pos / total) * 5 * 10) / 10 : 0;
  const sentimentLabel = !total ? "No data" : pos / total >= 0.6 ? "Positive" : neg / total >= 0.4 ? "Negative" : "Mixed";

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
    ? "No reviews analyzed yet."
    : `Overall sentiment is ${sentimentLabel.toLowerCase()}. Customers consistently praise ${(love.map((t) => t.name.toLowerCase()).slice(0, 3).join(", ") || "service")}. The biggest drag is ${(dislike.map((t) => t.name.toLowerCase()).slice(0, 2).join(" and ") || "isolated complaints")}. ${waitTheme && waitTheme.mentions > 0 ? "Reducing waiting time looks like the biggest lever for more 4–5★ reviews." : "Protect current strengths while tightening response time."}`;

  return {
    avg, sentimentScore, sentimentLabel,
    confidence: total ? Math.min(96, 70 + total * 3) : 0,
    summary, love, dislike, drivers,
    opportunities: [
      ...(waitTheme && waitTheme.mentions > 0 ? [{ level: "HIGH" as const, title: "Reduce waiting time", detail: `${waitTheme.mentions} mentions · avg ${waitTheme.avgRating.toFixed(1)}★. Review peak-hour staffing and set wait expectations.`, impact: "HIGH" }] : []),
      ...(valueTheme && valueTheme.mentions > 0 ? [{ level: "MEDIUM" as const, title: "Improve price/value communication", detail: `${valueTheme.mentions} mentions. Clarify inclusions and highlight value-added benefits.`, impact: "MEDIUM" }] : []),
      ...(staffTheme && staffTheme.mentions > 0 ? [{ level: "MAINTAIN" as const, title: "Maintain staff friendliness", detail: `${staffTheme.mentions} positive mentions · ${staffTheme.avgRating.toFixed(1)}★ average. Keep training as-is.`, impact: "GUARD" }] : []),
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
          verdict: `${posN ? `${posN} review(s) praise it` : ""}${posN && negN ? " · " : ""}${negN ? `${negN} review(s) criticise it` : ""} (avg ${t.avgRating.toFixed(1)}★).`.replace(/^ · /, ""),
          evidence: m.slice(0, 2).map((r) => ({ quote: r.comment.slice(0, 140), rating: r.rating })),
        };
      }),
    competitive: { wins: [], gaps: [], scope: null },
    actions: [
      ...(waitTheme && waitTheme.mentions > 0 ? [{ title: "Fix waiting time", detail: `${waitTheme.mentions} reviews affected · HIGH impact` }] : []),
      { title: `Respond to ${reviews.filter((r) => !r.replied).length} unanswered reviews`, detail: "Immediate action" },
      ...(staffTheme ? [{ title: "Protect staff training", detail: "Strong positive driver" }] : []),
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
}, base: Intelligence): {
  intel: Intelligence; source: string; model: string | null; ragUsed: boolean;
  analyzedAt: string | null; stale: boolean; newCount: number;
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
  };
}

function ThemeBars({ topics }: { topics: { name: string; count: number }[] }) {
  const max = Math.max(1, ...topics.map((t) => t.count));
  if (!topics.length) return <p className="text-[12px] text-ink/40">No themes detected yet.</p>;
  return (
    <div className="space-y-1.5">
      {topics.slice(0, 8).map((t) => (
        <div key={t.name} className="flex items-center gap-2">
          <span className="w-32 truncate text-[11px] font-semibold capitalize text-ink/70">{t.name}</span>
          <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-ink/[0.06]">
            <span className="block h-full rounded-full bg-gradient-to-r from-deep-violet to-magenta" style={{ width: `${Math.max(4, (t.count / max) * 100)}%` }} />
          </span>
          <span className="w-8 text-right text-[11px] tabular-nums text-ink/50">×{t.count}</span>
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
  aiMeta: { source: string; model: string | null; ragUsed: boolean; analyzedAt: string | null; stale: boolean; newCount: number } | null;
  aiLoading: boolean;
  analyzing: boolean;
  onAnalyze: () => void;
  onBack: () => void; onOpenStar: (s: number) => void;
  intelDays: number; intelMonth: string;
  intelInterval: { days: number; date_from: string | null; date_to: string | null; label: string };
  setIntelDays: (d: number) => void; setIntelMonth: (m: string) => void;
}) {
  const i = intel;
  const isAI = aiMeta?.source === "ai";
  const isLoading = aiLoading || analyzing;

  const badge = isLoading
    ? { text: analyzing ? "Analyzing with AI…" : "Loading…", icon: "◐", cls: "bg-[#1A73E8]/10 text-[#1A73E8] border border-[#1A73E8]/20" }
    : isAI
      ? { text: `AI • ${aiMeta?.model ?? "LLM"}${aiMeta?.ragUsed ? " • RAG" : ""}`, icon: "✦", cls: "bg-[#E6F4EA] text-[#137333] border border-[#CEEAD6]" }
      : aiMeta
        ? { text: "Heuristic • Instant", icon: "◈", cls: "bg-[#F1F3F4] text-[#5F6368] border border-[#DADCE0]" }
        : { text: "Not analyzed", icon: "○", cls: "bg-[#FEF7E0] text-[#EA8600] border border-[#FDE293]" };

  const analyzedLabel = aiMeta?.analyzedAt
    ? `${new Date(aiMeta.analyzedAt).toLocaleString()}${aiMeta.stale ? ` • ${aiMeta.newCount} new since` : " • fresh"}`
    : null;

  // Derived business impact
  const unanswered = total - Math.round((intel as unknown as { avg: number }).avg ? total * 0.6 : 0); // placeholder, will use real replied count if available
  const atRiskPct = total ? Math.round(((i.dislike.reduce((a, b) => a + b.mentions, 0) / Math.max(1, total)) * 100)) : 0;
  const revenueRisk = i.dislike.length ? `${atRiskPct}% of reviews signal churn risk` : "Low churn risk";
  const sentimentDelta = i.sentimentScore >= 3.5 ? "Positive momentum" : i.sentimentScore >= 2.5 ? "Mixed — fixable friction" : "Needs attention";

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
              <h2 className="text-[16px] font-medium leading-6 text-[#202124]">Review Intelligence</h2>
              <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium leading-none ${badge.cls}`}>
                <span aria-hidden>{badge.icon}</span> {badge.text}
              </span>
              {isAI && !isLoading && (
                <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-[11px] text-[#5F6368] ring-1 ring-[#DADCE0]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#34A853]" /> Verified numbers
                </span>
              )}
            </div>
            <p className="mt-1 text-[13px] leading-5 text-[#5F6368]">
              <span className="font-medium text-[#202124]">{locationName || "All locations"}</span>
              <span className="mx-1.5 text-[#DADCE0]">•</span>
              <span className="font-medium text-[#202124]">{intelInterval.label}</span>
              <span className="mx-1.5 text-[#DADCE0]">•</span>
              {total} reviews • {isAI ? `AI analysis${aiMeta?.model ? ` • ${aiMeta.model}` : ""}` : "Instant heuristic — AI adds deeper opportunities & citations"}
            </p>
            {analyzedLabel && <p className="mt-1 text-[12px] text-[#5F6368]">Updated {analyzedLabel}</p>}
            {aiMeta?.stale && (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-[#FEF7E0] px-2.5 py-1 text-[12px] font-medium text-[#EA8600]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#EA8600]" /> {aiMeta.newCount} new review(s) since last AI run — re-analyze for fresh insights
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="hidden sm:inline-flex rounded-md border border-[#DADCE0] bg-white px-3 py-2 text-[13px] font-medium text-[#1A73E8] hover:bg-[#F8F9FA]"
            >
              Back
            </button>
            <button
              onClick={onAnalyze}
              disabled={analyzing || aiLoading}
              className="inline-flex items-center gap-1.5 rounded-md bg-[#1A73E8] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#1765CC] disabled:opacity-50"
            >
              {analyzing ? (
                <>
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Analyzing…
                </>
              ) : isAI ? "Re-analyze with AI" : "Analyze with AI"}
            </button>
          </div>
        </div>

        {/* INTERVAL — scopes every number on this page to the selected window */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#E8EAED] pt-3">
          <span className="text-[12px] font-medium text-[#5F6368]">Period</span>
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
                  {p.label}
                </button>
              );
            })}
            <label className="ml-1 inline-flex items-center gap-1.5 text-[12px] text-[#5F6368]">
              <span className="sr-only">Specific month</span>
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
                Clear
              </button>
            )}
          </div>
          {isLoading && <span className="text-[12px] text-[#5F6368]">Loading {intelInterval.label.toLowerCase()}…</span>}
        </div>

        {/* Source transparency — makes AI vs heuristic crystal clear */}
        <div className="mt-3 flex flex-wrap gap-2 border-t border-[#E8EAED] pt-3 text-[12px]">
          <span className={`inline-flex items-center gap-1.5 ${isAI ? "text-[#137333]" : "text-[#5F6368]"}`}>
            <span className={`h-2 w-2 rounded-full ${isAI ? "bg-[#34A853]" : "bg-[#5F6368]"}`} />
            {isAI ? "Numbers are clamped to your real review stats — AI cannot invent counts" : "Counts are exact — insights are rule-based until AI runs"}
          </span>
          <span className="text-[#DADCE0]">•</span>
          <span className="text-[#5F6368]">{isAI && aiMeta?.ragUsed ? "Grounded in your databank + reviews" : isAI ? "Based on reviews (no databank context)" : "Add a databank to enable RAG grounding"}</span>
        </div>
      </div>

      {/* HERO KPIs — Material cards, neutral + one green accent */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">Avg rating</p>
          <p className="mt-1 text-[22px] font-normal leading-7 text-[#202124]">{i.avg.toFixed(1)} <span className="text-[#FBBC05]">★</span></p>
          <p className="mt-1 text-[12px] text-[#5F6368]">{i.sentimentLabel} • {total} reviews</p>
        </div>
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">Sentiment</p>
          <div className="mt-1 flex items-baseline gap-2">
            <p className="text-[22px] font-normal leading-7 text-[#202124]">{i.sentimentScore.toFixed(1)}</p>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${i.sentimentScore >= 3.5 ? "bg-[#E6F4EA] text-[#137333]" : i.sentimentScore >= 2.5 ? "bg-[#FEF7E0] text-[#EA8600]" : "bg-[#FCE8E6] text-[#C5221F]"}`}>
              {sentimentDelta}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#E8EAED]">
            <div className="h-full rounded-full bg-[#1A73E8]" style={{ width: `${Math.min(100, (i.sentimentScore / 5) * 100)}%` }} />
          </div>
        </div>
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">Confidence</p>
          <p className="mt-1 text-[22px] font-normal leading-7 text-[#202124]">{i.confidence}%</p>
          <p className="mt-1 text-[12px] text-[#5F6368]">{total >= 20 ? "High — strong sample" : total >= 8 ? "Medium — growing sample" : "Low — more reviews needed"}</p>
        </div>
        <div className="rounded-lg border border-[#DADCE0] bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">Risk signal</p>
          <p className="mt-1 text-[14px] font-medium leading-5 text-[#202124]">{revenueRisk}</p>
          <p className="mt-1 text-[12px] text-[#5F6368]">Fix top 1-sided theme first</p>
        </div>
      </div>

      {/* BUSINESS HEALTH SCORECARD — standard dimensions, evidence-cited.
          Only dimensions someone actually mentioned reach this view. */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F1F3F4] text-[#5F6368]">▦</span>
          <h3 className="text-[14px] font-medium text-[#202124]">Business Health Scorecard</h3>
          <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[11px] font-medium text-[#5F6368]">
            {i.dimensions.length} dimension{i.dimensions.length === 1 ? "" : "s"} in this period
          </span>
        </div>
        {i.dimensions.length === 0 ? (
          <p className="mt-3 text-[13px] text-[#5F6368]">
            No review in this period mentions any tracked dimension yet. Collect a few more reviews
            mentioning staff, speed, quality, value or cleanliness and the scorecard fills in.
          </p>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {i.dimensions.map((d) => {
              const tone =
                d.signal === "strong"
                  ? { chip: "bg-[#E6F4EA] text-[#137333]", bar: "#34A853", word: "Strong" }
                  : d.signal === "weak"
                    ? { chip: "bg-[#FCE8E6] text-[#C5221F]", bar: "#EA4335", word: "Weak" }
                    : { chip: "bg-[#FEF7E0] text-[#EA8600]", bar: "#FBBC05", word: "Mixed" };
              return (
                <div key={d.key} className="rounded-lg border border-[#E8EAED] p-3.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium leading-5 text-[#202124]">{d.label}</p>
                      {!d.standard && (
                        <span className="mt-0.5 inline-block rounded bg-[#E8F0FE] px-1.5 py-0.5 text-[10px] font-medium text-[#1967D2]">
                          Discovered in your reviews
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
                      <span aria-hidden>👍</span> {d.positive} positive
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <span aria-hidden>👎</span> {d.negative} negative
                    </span>
                    <span className="tabular-nums">avg {d.avg_rating.toFixed(1)}★</span>
                    <span className="rounded bg-[#F1F3F4] px-1.5 py-0.5 font-medium">
                      {d.confidence} confidence
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
            <h3 className="text-[14px] font-medium text-[#202124]">Where you stand vs other businesses</h3>
            {i.competitive.scope && (
              <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[11px] font-medium text-[#5F6368]">
                {i.competitive.scope}
              </span>
            )}
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {i.competitive.wins.length > 0 && (
              <div className="rounded-lg border border-[#CEEAD6] bg-[#F6FEF8] p-3.5">
                <p className="text-[12px] font-medium uppercase tracking-wide text-[#137333]">You lead on</p>
                <ul className="mt-2 space-y-1.5">
                  {i.competitive.wins.map((w, idx) => (
                    <li key={idx} className="text-[12px] leading-5 text-[#202124]">• {w}</li>
                  ))}
                </ul>
              </div>
            )}
            {i.competitive.gaps.length > 0 && (
              <div className="rounded-lg border border-[#F6C7C3] bg-[#FEF7F6] p-3.5">
                <p className="text-[12px] font-medium uppercase tracking-wide text-[#C5221F]">You trail on</p>
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
          <h3 className="text-[14px] font-medium text-[#202124]">{isAI ? "AI Executive Summary" : "Executive Summary (heuristic)"}</h3>
          {!isAI && <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[11px] font-medium text-[#5F6368]">Run AI for citations & verified opportunities</span>}
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
              {s}★ detail →
            </button>
          ))}
        </div>
      </div>

      {/* LOVE / DISLIKE — balanced, actionable */}
      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            <span className="h-2 w-2 rounded-full bg-[#34A853]" /> What customers love
            <span className="ml-auto text-[11px] font-normal text-[#5F6368]">{i.love.length ? `${i.love.length} themes` : ""}</span>
          </h3>
          {i.love.length === 0 ? <p className="mt-3 text-[13px] text-[#5F6368]">Not enough positive signals yet — keep collecting 4–5★ reviews with specific praise.</p> : (
            <div className="mt-3 space-y-3">
              {i.love.map((t) => (
                <div key={t.name}>
                  <div className="flex justify-between text-[13px]">
                    <span className="font-medium text-[#202124]">{t.name}</span>
                    <span className="font-medium text-[#137333]">{t.positivePct}% positive</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#E8EAED]"><div className="h-full rounded-full bg-[#34A853]" style={{ width: `${t.positivePct}%` }} /></div>
                  <p className="mt-1 text-[12px] text-[#5F6368]">{t.mentions} mentions · {t.avgRating.toFixed(1)}★ avg {t.phrases[0] ? `· “${t.phrases[0].slice(0, 60)}”` : ""}</p>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 border-t border-[#E8EAED] pt-3 text-[12px] text-[#5F6368]"><span className="font-medium text-[#202124]">Next:</span> Double down in replies & posts — quote this praise back to future customers.</p>
        </section>
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            <span className="h-2 w-2 rounded-full bg-[#EA4335]" /> What hurts your rating
            <span className="ml-auto text-[11px] font-normal text-[#5F6368]">{i.dislike.length ? `${i.dislike.length} themes` : "No major drag"}</span>
          </h3>
          {i.dislike.length === 0 ? <p className="mt-3 rounded-md bg-[#E6F4EA] px-3 py-2 text-[13px] text-[#137333]">No major complaints detected. Protect this — reply fast when one appears.</p> : (
            <div className="mt-3 space-y-3">
              {i.dislike.map((t) => (
                <div key={t.name}>
                  <div className="flex justify-between text-[13px]"><span className="font-medium text-[#202124]">{t.name}</span><span className="text-[#5F6368]">{t.mentions} mentions</span></div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#E8EAED]"><div className="h-full rounded-full bg-[#EA4335]" style={{ width: `${Math.min(100, t.mentions * 12)}%` }} /></div>
                  <p className="mt-1 text-[12px] text-[#5F6368]">{t.avgRating.toFixed(1)}★ avg · {t.positivePct}% positive — needs playbook</p>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 border-t border-[#E8EAED] pt-3 text-[12px] text-[#5F6368]"><span className="font-medium text-[#202124]">Next:</span> Pick the top theme → standardize a 2-sentence recovery reply → track weekly.</p>
        </section>
      </div>

      {/* DRIVERS — heatmap style */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <h3 className="text-[14px] font-medium text-[#202124]">What drives each star rating?</h3>
        <p className="text-[12px] text-[#5F6368]">Where praise and complaints cluster · helps you prioritize fixes that move stars.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[12px]">
            <thead>
              <tr className="text-left text-[#5F6368]">
                <th className="py-2 text-[11px] font-medium uppercase tracking-wide">Theme</th>
                <th className="text-center text-[11px] font-medium">5★</th>
                <th className="text-center text-[11px] font-medium">4★</th>
                <th className="text-center text-[11px] font-medium">3★</th>
                <th className="text-center text-[11px] font-medium">1–2★</th>
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
                          title={v === 0 ? "No reviews" : `${v} review${v === 1 ? "" : "s"}`}
                        >
                          {v}
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
          <span className="font-medium text-[#202124]">Scale</span>
          <span className="text-[#5F6368]">More reviews = deeper colour (relative to the busiest cell)</span>
          <span className="flex items-center gap-1.5">
            {HEAT_STEPS.map((s) => (
              <span key={s.label} className="flex items-center gap-1">
                <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-medium tabular-nums ${s.cls}`}>
                  {s.sample}
                </span>
                <span className="text-[#5F6368]">{s.label}</span>
              </span>
            ))}
          </span>
          <span className="text-[#C5221F]">1–2★ column stays red-tinted (complaints)</span>
        </div>
      </div>

      {/* OPPORTUNITIES + STRENGTHS */}
      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            Improvement opportunities
            {isAI && <span className="rounded-full bg-[#E6F4EA] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#137333]">AI-verified</span>}
            {!isAI && <span className="rounded-full bg-[#F1F3F4] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#5F6368]">Heuristic</span>}
          </h3>
          <div className="mt-3 space-y-2.5">
            {i.opportunities.map((o) => (
              <div key={o.title} className="rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-3">
                <p className="text-[13px] font-medium text-[#202124]">
                  <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-medium ${o.level === "HIGH" ? "bg-[#FCE8E6] text-[#C5221F] border border-[#FAD2CF]" : o.level === "MEDIUM" ? "bg-[#FEF7E0] text-[#EA8600] border border-[#FDE293]" : "bg-[#E6F4EA] text-[#137333] border border-[#CEEAD6]"}`}>{o.level}</span>
                  {o.title}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-[#5F6368]">{o.detail}</p>
                <p className="mt-1 text-[11px] font-medium text-[#1A73E8]">Impact: {o.impact} → reply to these reviews first</p>
              </div>
            ))}
            {i.opportunities.length === 0 && <p className="text-[13px] text-[#5F6368]">Nothing urgent — keep the current playbook.</p>}
          </div>
        </section>
        <section className="rounded-lg border border-[#DADCE0] bg-white p-5">
          <h3 className="text-[14px] font-medium text-[#202124]">Strengths to protect</h3>
          <p className="text-[12px] text-[#5F6368]">Your moat — mention these in posts & replies.</p>
          <div className="mt-3 space-y-2">
            {i.strengths.map((s, idx) => (
              <div key={s.title} className="flex items-start gap-3 rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#E6F4EA] text-[12px] font-medium text-[#137333]">{idx + 1}</span>
                <div>
                  <p className="text-[13px] font-medium text-[#202124]">{s.title}</p>
                  <p className="text-[12px] text-[#5F6368]">{s.mentions} mentions · {s.avg.toFixed(1)}★ — keep training & staffing as-is</p>
                </div>
              </div>
            ))}
            {i.strengths.length === 0 && <p className="text-[13px] text-[#5F6368]">No clear strengths yet — collect more 4–5★ detail.</p>}
          </div>
          <h3 className="mt-5 flex items-center gap-2 text-[14px] font-medium text-[#202124]">
            AI action plan {isAI ? <span className="rounded-full bg-[#E6F4EA] px-2 py-0.5 text-[10px] font-medium text-[#137333]">AI</span> : null}
          </h3>
          <ol className="mt-2 space-y-2">
            {i.actions.map((a, idx) => (
              <li key={a.title} className="flex gap-2 rounded-lg border border-[#E8EAED] bg-white px-3 py-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#1A73E8] text-[11px] font-medium text-white">{idx + 1}</span>
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
        <h3 className="text-[14px] font-medium text-[#202124]">Review themes</h3>
        <p className="text-[12px] text-[#5F6368]">Mentions per theme · numbers are exact · themes mix AI + heuristic</p>
        <div className="mt-3"><ThemeBars topics={i.topics} /></div>
        <div className="mt-3 flex flex-wrap gap-2">
          {i.topics.map((t) => (
            <span key={t.name} className="rounded-full border border-[#E8EAED] bg-[#F8F9FA] px-3 py-1.5 text-[12px] font-medium text-[#202124]">{t.name} · {t.count}</span>
          ))}
        </div>
      </div>

      {/* SENTIMENT SPLIT — quick visual for business health */}
      <div className="rounded-lg border border-[#DADCE0] bg-white p-5">
        <h3 className="text-[14px] font-medium text-[#202124]">Sentiment split</h3>
        <div className="mt-3 flex h-3 overflow-hidden rounded-full">
          <div className="bg-[#34A853]" style={{ width: `${total ? (i.sentimentSplit.positive / total) * 100 : 0}%` }} title={`Positive ${i.sentimentSplit.positive}`} />
          <div className="bg-[#FBBC05]" style={{ width: `${total ? (i.sentimentSplit.neutral / total) * 100 : 0}%` }} title={`Neutral ${i.sentimentSplit.neutral}`} />
          <div className="bg-[#EA4335]" style={{ width: `${total ? (i.sentimentSplit.negative / total) * 100 : 0}%` }} title={`Negative ${i.sentimentSplit.negative}`} />
        </div>
        <div className="mt-2 flex flex-wrap gap-4 text-[12px]">
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#34A853]" /> Positive {i.sentimentSplit.positive}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#FBBC05]" /> Neutral {i.sentimentSplit.neutral}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#EA4335]" /> Negative {i.sentimentSplit.negative}</span>
        </div>
      </div>

      <button onClick={onBack} className="text-[13px] font-medium text-[#1A73E8] hover:underline">← Back to reviews</button>
      <p className="text-[11px] leading-4 text-[#5F6368]">
        {isAI ? `AI model ${aiMeta?.model ?? "unknown"} • ${aiMeta?.ragUsed ? "RAG-grounded in your databank" : "No databank context"} • Verified counts` : "Heuristic analysis — counts exact, insights rule-based. Run AI for cited opportunities."}
        {" "}• Sayvors-derived analytics • <span className="underline decoration-dotted">Why this matters: reply fast to negatives = +0.2★ avg in 30 days (industry avg)</span>
      </p>
    </div>
  );
}

function InsightCard({ review }: { review: ReviewItem }) {
  const insight = explainReview(review);
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
          Why this rating?
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
          {insight.tone === "high" ? "High" : insight.tone === "low" ? "Low" : "Mixed"}
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-5 text-[#5F6368]">{insight.summary}</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-3">
          <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-[#137333]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#34A853]" /> What lifted it
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
            <p className="mt-2 text-[12px] text-[#5F6368]">No clear positive signals.</p>
          )}
        </div>
        <div className="rounded-lg border border-[#E8EAED] bg-[#F8F9FA] p-3">
          <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-[#C5221F]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#EA4335]" /> What dragged it
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
            <p className="mt-2 text-[12px] text-[#5F6368]">No clear negative signals.</p>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-[#E8EAED] bg-white p-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-[#5F6368]">Overall result</p>
        <p className="mt-1 text-[13px] leading-5 text-[#202124]">{insight.result}</p>
        <p className="mt-2 flex items-center gap-1.5 text-[12px] font-medium text-[#1A73E8]">
          <span className="text-[#1A73E8]">→</span> Next: {insight.action}
        </p>
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[#E8EAED] pt-3 text-[11px] text-[#5F6368]">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#F1F3F4]">
          <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3" aria-hidden>
            <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 16a7 7 0 1 1 0-14 7 7 0 0 1 0 14Z" stroke="currentColor" strokeWidth={1.3} />
            <path d="M12 8v5l3 2" stroke="currentColor" strokeWidth={1.3} strokeLinecap="round" />
          </svg>
        </span>
        Explainable heuristics · {review.locationName} · {review.createdAt}
        <span className="text-[#DADCE0]">•</span>
        <span className={review.replied ? "text-[#137333]" : "text-[#5F6368]"}>{review.replied ? "Replied" : "Unanswered"}</span>
      </p>
    </div>
  );
}

function explainReview(r: ReviewItem): { tone: "high" | "low" | "mixed"; summary: string; positives: string[]; negatives: string[]; result: string; action: string } {
  const text = r.comment.toLowerCase();
  const posLex: Record<string, string> = {
    great: "praised overall service", excellent: "called service excellent", helpful: "mentioned helpful staff",
    quick: "liked fast response", friendly: "found staff friendly", clean: "liked cleanliness",
    recommend: "would recommend", good: "positive overall tone", fast: "liked speed",
  };
  const negLex: Record<string, string> = {
    wait: "complained about waiting", slow: "felt service was slow", rude: "felt staff was rude",
    bad: "negative overall tone", poor: "rated support poorly", long: "mentioned long delays",
    busy: "felt staff was too busy", dirty: "flagged cleanliness", expensive: "felt pricing was high",
    unhappy: "expressed unhappiness",
  };
  const positives = Object.entries(posLex).filter(([k]) => text.includes(k)).map(([, v]) => v);
  const negatives = Object.entries(negLex).filter(([k]) => text.includes(k)).map(([, v]) => v);
  if (r.rating >= 4 && negatives.length === 0) {
    return {
      tone: "high",
      summary: `This is high because the customer gave ${r.rating}★ with${positives.length ? "" : "out"} explicit praise signals. High ratings like this lift the location average and response-rate health.`,
      positives: positives.length ? positives : ["high star rating itself"],
      negatives,
      result: `Positive outcome for ${r.locationName}. ${r.replied ? "Already replied — good for trust." : "Reply to lock in loyalty."}`,
      action: r.replied ? "No urgent fix; thank them and invite them back." : "Post a warm thank-you reply today.",
    };
  }
  if (r.rating <= 2) {
    return {
      tone: "low",
      summary: `This is low because the customer gave ${r.rating}★${negatives.length ? " and the text points at specific pain" : " even without detailed text"}. Low ratings drag the average and need a fast, empathetic reply.`,
      positives,
      negatives: negatives.length ? negatives : ["low star rating without detail"],
      result: `At-risk signal for ${r.locationName}. ${r.replied ? "Reply exists — monitor for follow-up." : "Unanswered — highest priority."}`,
      action: "Reply with apology + concrete fix, then address the root cause operationally.",
    };
  }
  return {
    tone: "mixed",
    summary: `This sits in the middle at ${r.rating}★ — not angry, not delighted. These reviews usually hide one fixable friction point.`,
    positives: positives.length ? positives : ["neutral-to-positive tone"],
    negatives: negatives.length ? negatives : ["no strong complaint detected"],
    result: `Neutral outcome. Small fix at ${r.locationName} could convert this customer to 4–5★.`,
    action: "Acknowledge the feedback and state one specific improvement.",
  };
}

function Stars({ rating }: { rating: number }) {
  return (
    <span className="flex shrink-0 gap-0.5" aria-label={`${rating} stars`}>
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
