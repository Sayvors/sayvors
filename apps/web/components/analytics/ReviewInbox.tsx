"use client";

import { useEffect, useRef, useState } from "react";
import { fetchInsights, type ReviewInsight } from "@/lib/api-analytics";
import { ReplyComposer } from "./ReplyComposer";

const PAGE_SIZE = 20;

type SentimentFilter = "all" | "positive" | "neutral" | "negative";
type StatusFilter = "all" | "replied" | "unanswered";

const SENTIMENT_STYLES: Record<string, string> = {
  positive: "bg-emerald/10 text-emerald",
  neutral: "bg-ink/[0.05] text-ink/55",
  negative: "bg-coral/10 text-coral",
};

const SEVERITY_STYLES: Record<string, string> = {
  high: "bg-coral/10 text-coral",
  medium: "bg-amber/10 text-amber-600",
  low: "bg-ink/[0.05] text-ink/50",
};

function Stars({ rating }: { rating: number }) {
  return (
    <span className="flex items-center gap-0.5" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((s) => (
        <svg
          key={s}
          viewBox="0 0 24 24"
          fill="currentColor"
          className={`h-3.5 w-3.5 ${s <= Math.round(rating) ? "text-[#FBBC05]" : "text-[#E8EAED]"}`}
          aria-hidden
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
        </svg>
      ))}
    </span>
  );
}

const AVATAR_COLORS = ["#4285F4", "#EA4335", "#FBBC05", "#34A853", "#8E24AA", "#0097A7"];

function avatarColor(name: string | null): string {
  const s = (name ?? "").trim() || "?";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function initialsOf(name: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function relativeDate(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString("en", { month: "short", day: "numeric" });
}

function ReviewCard({ review, onReplied }: { review: ReviewInsight; onReplied: () => void }) {
  return (
    <article
      className="rounded-lg border border-[#DADCE0] bg-white text-left transition hover:bg-[#F8F9FA]"
      style={{ fontFamily: "Roboto, Arial, sans-serif" }}
    >
      {/* Header — avatar + name + time */}
      <div className="flex items-start gap-3 px-4 pt-4">
        <span
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-medium text-white"
          style={{ backgroundColor: avatarColor(review.reviewer_name) }}
        >
          {initialsOf(review.reviewer_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-medium leading-5 text-[#202124]">
            {review.reviewer_name ?? "Anonymous"}
          </p>
          <p className="mt-0.5 text-[12px] leading-4 text-[#5F6368]">
            {relativeDate(review.review_updated_at ?? review.created_at)}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${SENTIMENT_STYLES[review.sentiment] ?? SENTIMENT_STYLES.neutral}`}
        >
          {review.sentiment}
        </span>
      </div>

      {/* Stars */}
      <div className="px-4 pt-2.5">
        <Stars rating={review.rating} />
      </div>

      {/* Comment */}
      {review.review_text && (
        <p className="whitespace-pre-wrap break-words px-4 pt-2 text-[13px] leading-[20px] text-[#202124]">
          {review.review_text}
        </p>
      )}

      {/* Topics / problems / products */}
      {(review.topics.length > 0 || review.problems.length > 0 || review.products.length > 0) && (
        <div className="flex flex-wrap gap-1.5 px-4 pt-2.5">
          {(review.problems ?? []).map((p, i) => (
            <span key={`pr-${p.name}-${i}`} className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${SEVERITY_STYLES[p.severity] ?? SEVERITY_STYLES.low}`}>
              {p.name}
            </span>
          ))}
          {(review.topics ?? []).map((t, i) => (
            <span key={`t-${t.name}-${i}`} className="rounded-md bg-deep-violet/[0.05] px-1.5 py-0.5 text-[10px] text-ink/50">
              {t.name}
            </span>
          ))}
          {(review.products ?? []).map((p, i) => (
            <span key={`p-${p.name}-${i}`} className="rounded-md bg-magenta/[0.07] px-1.5 py-0.5 text-[10px] text-magenta">
              {p.name}
            </span>
          ))}
        </div>
      )}

      {/* Footer — status */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#E8EAED] px-4 py-3">
        {review.replied ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium leading-4 text-[#137333]">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#34A853]" />
            Replied
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium leading-4 text-[#5F6368]">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#FABB05]" />
            Needs reply
          </span>
        )}
      </div>

      {!review.replied && (
        <div className="px-4 pb-4">
          <ReplyComposer
            channelId={review.channel_id}
            reviewId={review.review_id}
            rating={review.rating}
            reviewText={review.review_text}
            reviewerName={review.reviewer_name}
            onPublished={onReplied}
          />
        </div>
      )}
    </article>
  );
}

export function ReviewInbox({ channelId, refreshToken }: { channelId: string | null; refreshToken: number }) {
  const [sentiment, setSentiment] = useState<SentimentFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [rating, setRating] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [items, setItems] = useState<ReviewInsight[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const onReplied = () => setRetryCount((c) => c + 1);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    // No-op when the query didn't actually change — notably on mount and
    // across StrictMode remounts (refs don't reset there, so a ref guard
    // can't be trusted). This kills the redundant refetch that flashed
    // skeletons over already-loaded content.
    if (searchInput.trim() === search) return;
    debounce.current = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(0);
      setLoading(true);
    }, 350);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [searchInput, search]);

  useEffect(() => {
    let cancelled = false;
    fetchInsights({
      channelId,
      sentiment: sentiment === "all" ? null : sentiment,
      status: status === "all" ? null : status,
      rating,
      search: search || null,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setTotal(data.total);
        setError(false);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, sentiment, status, rating, search, page, refreshToken, retryCount]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filterBtn = (active: boolean) =>
    `rounded-full px-2.5 py-1 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
      active ? "bg-deep-violet text-white shadow-sm" : "bg-deep-violet/[0.05] text-ink/50 hover:bg-deep-violet/[0.1]"
    }`;

  return (
    <section aria-label="AI Review Inbox" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-ink">
          AI Review Inbox
          <span className="ml-2 text-[11px] font-medium text-ink/40">{total} reviews</span>
        </h3>
        <div className="relative">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/25" aria-hidden>
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search reviews..."
            aria-label="Search reviews"
            className="h-8 w-44 rounded-lg border border-deep-violet/[0.08] bg-deep-violet/[0.03] pl-8 pr-3 text-[12px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.08]"
          />
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {(["all", "positive", "neutral", "negative"] as const).map((s) => (
          <button key={s} onClick={() => { setSentiment(s); setPage(0); setLoading(true); }} aria-pressed={sentiment === s} className={filterBtn(sentiment === s)}>
            {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-deep-violet/[0.1]" aria-hidden />
        {(["all", "unanswered", "replied"] as const).map((s) => (
          <button key={s} onClick={() => { setStatus(s); setPage(0); setLoading(true); }} aria-pressed={status === s} className={filterBtn(status === s)}>
            {s === "all" ? "Any status" : s === "unanswered" ? "Unanswered" : "Replied"}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-deep-violet/[0.1]" aria-hidden />
        <button onClick={() => { setRating(null); setPage(0); setLoading(true); }} aria-pressed={rating === null} className={filterBtn(rating === null)}>All stars</button>
        {[5, 4, 3, 2, 1].map((r) => (
          <button key={r} onClick={() => { setRating(rating === r ? null : r); setPage(0); setLoading(true); }} aria-pressed={rating === r} className={filterBtn(rating === r)} aria-label={`Filter ${r} stars`}>
            {r}★
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="grid items-start gap-3 md:grid-cols-2" role="status" aria-label="Loading reviews">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="rounded-lg border border-[#DADCE0] bg-white p-4">
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 animate-pulse rounded-full bg-ink/[0.07]" />
                <div className="h-3 w-40 animate-pulse rounded bg-ink/[0.07]" />
              </div>
              <div className="mt-3 h-3 w-full animate-pulse rounded bg-ink/[0.05]" />
              <div className="mt-1.5 h-3 w-2/3 animate-pulse rounded bg-ink/[0.05]" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <p className="text-[12px] text-ink/50">Couldn&apos;t load reviews.</p>
          <button onClick={() => { setError(false); setLoading(true); setRetryCount((c) => c + 1); }} className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-deep-violet/90">
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-1 py-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">No reviews match these filters</p>
          <p className="text-[11px] text-ink/35">Try clearing filters or connecting a channel to start collecting reviews.</p>
        </div>
      ) : (
        <div className="grid items-start gap-3 md:grid-cols-2">
          {items.map((r) => (
            <ReviewCard key={r.id} review={r} onReplied={onReplied} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && !loading && (
        <div className="mt-4 flex items-center justify-between">
          <button
            onClick={() => { setPage(Math.max(0, page - 1)); setLoading(true); }}
            disabled={page === 0}
            className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-deep-violet transition enabled:hover:bg-deep-violet/[0.06] disabled:opacity-30"
          >
            Previous
          </button>
          <span className="text-[11px] text-ink/40">Page {page + 1} of {pages}</span>
          <button
            onClick={() => { setPage(Math.min(pages - 1, page + 1)); setLoading(true); }}
            disabled={page >= pages - 1}
            className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-deep-violet transition enabled:hover:bg-deep-violet/[0.06] disabled:opacity-30"
          >
            Next
          </button>
        </div>
      )}
    </section>
  );
}
