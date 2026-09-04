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
          className={`h-3 w-3 ${s <= rating ? "text-amber" : "text-ink/15"}`}
          aria-hidden
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
        </svg>
      ))}
    </span>
  );
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
    <article className="group rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm transition hover:border-deep-violet/15 hover:shadow-md hover:shadow-deep-violet/[0.06]">
      <div className="flex flex-wrap items-center gap-2">
        <Stars rating={review.rating} />
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${SENTIMENT_STYLES[review.sentiment] ?? SENTIMENT_STYLES.neutral}`}
        >
          {review.sentiment}
        </span>
        {review.replied ? (
          <span className="flex items-center gap-1 rounded-full bg-deep-violet/[0.07] px-2 py-0.5 text-[10px] font-semibold text-deep-violet">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-2.5 w-2.5" aria-hidden>
              <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Replied
          </span>
        ) : (
          <span className="rounded-full bg-amber/10 px-2 py-0.5 text-[10px] font-semibold text-amber-600">Awaiting reply</span>
        )}
        <span className="ml-auto text-[10px] text-ink/35">
          {review.reviewer_name ?? "Anonymous"} · {relativeDate(review.review_updated_at ?? review.created_at)}
        </span>
      </div>

      {review.review_text && (
        <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed text-ink/70">{review.review_text}</p>
      )}

      {(review.topics.length > 0 || review.problems.length > 0 || review.products.length > 0) && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {review.problems.map((p) => (
            <span key={`pr-${p.name}`} className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${SEVERITY_STYLES[p.severity] ?? SEVERITY_STYLES.low}`}>
              {p.name}
            </span>
          ))}
          {review.topics.map((t) => (
            <span key={`t-${t.name}`} className="rounded-md bg-deep-violet/[0.05] px-1.5 py-0.5 text-[10px] text-ink/50">
              {t.name}
            </span>
          ))}
          {review.products.map((p) => (
            <span key={`p-${p.name}`} className="rounded-md bg-magenta/[0.07] px-1.5 py-0.5 text-[10px] text-magenta">
              {p.name}
            </span>
          ))}
        </div>
      )}

      {!review.replied && (
        <ReplyComposer
          channelId={review.channel_id}
          reviewId={review.review_id}
          rating={review.rating}
          reviewText={review.review_text}
          reviewerName={review.reviewer_name}
          onPublished={onReplied}
        />
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
    debounce.current = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(0);
      setLoading(true);
    }, 350);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [searchInput]);

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
        <div className="space-y-2.5" role="status" aria-label="Loading reviews">
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-2xl border-2 border-white bg-white/60 p-4">
              <div className="h-3 w-40 animate-pulse rounded bg-ink/[0.07]" />
              <div className="mt-2 h-3 w-full animate-pulse rounded bg-ink/[0.05]" />
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
        <div className="space-y-2.5">
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
