"use client";

import Image from "next/image";
import { useState } from "react";

export interface GoogleReview {
  id: string;
  reviewer: string;
  reviewerPhoto?: string;
  rating: number;
  comment: string;
  createdAt: string;
  locationName: string;
  replied: boolean;
  replyText?: string;
  replyAt?: string;
  skipped?: boolean;
  edited?: boolean;
  previousText?: string | null;
  previousRating?: number | null;
  sentiment?: string;
  reviewUrl?: string;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "G";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function relativeDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)} wk ago`;
  return d.toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: d.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  });
}

function exactDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" });
}

export function GoogleWordmark({ className = "text-[11px]" }: { className?: string }) {
  return (
    <span aria-hidden className={`font-medium tracking-tight ${className}`} style={{ fontFamily: "Roboto, Arial, sans-serif" }}>
      <span className="text-[#4285F4]">G</span>
      <span className="text-[#EA4335]">o</span>
      <span className="text-[#FBBC05]">o</span>
      <span className="text-[#4285F4]">g</span>
      <span className="text-[#34A853]">l</span>
      <span className="text-[#EA4335]">e</span>
    </span>
  );
}

export function GoogleStars({ rating, size = "h-3.5 w-3.5" }: { rating: number; size?: string }) {
  return (
    <span className="flex items-center gap-0.5" role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((s) => (
        <svg
          key={s}
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden
          className={`${size} ${s <= Math.round(rating) ? "text-[#FBBC05]" : "text-[#E8EAED]"}`}
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
        </svg>
      ))}
    </span>
  );
}

export function ReviewAvatar({ name, photoUrl }: { name: string; photoUrl?: string | null }) {
  const [imgFailed, setImgFailed] = useState(false);
  if (photoUrl && !imgFailed) {
    return (
      <Image
        src={photoUrl}
        alt=""
        aria-hidden
        width={32}
        height={32}
        className="h-8 w-8 shrink-0 rounded-full bg-[#F1F3F4] object-cover ring-1 ring-[#E8EAED]"
        onError={() => setImgFailed(true)}
      />
    );
  }
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#F1F3F4] text-[11px] font-medium text-[#5F6368] ring-1 ring-[#E8EAED]"
    >
      {initials(name)}
    </span>
  );
}

function OwnerAvatar() {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#F1F3F4] text-[#5F6368] ring-1 ring-[#E8EAED]"
    >
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4">
        <path d="M4 10h16v9H4v-9Z" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" />
        <path d="M3 10l1.6-4.5h14.8L21 10" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
        <path d="M9 19v-5h6v5" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function ExternalLinkIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden {...props}>
      <path d="M14 5h5v5M19 5l-8 8" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      <path d="M19 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 18.5v-12A1.5 1.5 0 0 1 5.5 5H10" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" />
    </svg>
  );
}

export default function GoogleReviewCard({
  review,
  onOpen,
  onFlag,
}: {
  review: GoogleReview;
  onOpen: (id: string) => void;
  onFlag?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const open = () => onOpen(review.id);
  const isLong = review.comment.length > 180;
  const displayText = expanded || !isLong ? review.comment : `${review.comment.slice(0, 180).trimEnd()}...`;
  const hasReply = review.replied && !!review.replyText?.trim();

  return (
    <article
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={`Review by ${review.reviewer}, ${review.rating} stars. Open details.`}
      style={{ fontFamily: "Roboto, Arial, sans-serif" }}
      className="group w-full cursor-pointer rounded-lg border border-[#DADCE0] bg-white text-left outline-none transition hover:border-[#BDC1C6] focus-visible:ring-2 focus-visible:ring-[#1A73E8]/30 focus-visible:ring-offset-1"
    >
      {/* Business / location header, mirroring the Google Business Profile list. */}
      <header className="border-b border-[#E8EAED] px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <h2 className="truncate text-[14px] font-medium leading-5 text-[#202124]">
                {review.locationName}
              </h2>
              {review.reviewUrl && (
                <a
                  href={review.reviewUrl}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  aria-label="Open this review on Google"
                  className="inline-flex shrink-0 items-center justify-center rounded p-0.5 text-[#1A73E8] hover:bg-[#E8F0FE] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#1A73E8]"
                >
                  <ExternalLinkIcon className="h-3.5 w-3.5" />
                </a>
              )}
            </div>
            <p className="mt-0.5 text-[12px] leading-4 text-[#5F6368]">Google review</p>
          </div>
          <span className="shrink-0 text-[11px] leading-4 text-[#5F6368]" title={exactDate(review.createdAt)}>
            {exactDate(review.createdAt)}
          </span>
        </div>
      </header>

      {/* Reviewer row. The rail line runs down to the owner avatar below. */}
      <div className="flex gap-3 px-4 pt-4">
        <div className="flex flex-col items-center">
          <ReviewAvatar name={review.reviewer} photoUrl={review.reviewerPhoto} />
          {hasReply && <span className="mt-1 w-px flex-1 bg-[#DADCE0]" aria-hidden />}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-[14px] font-medium leading-5 text-[#202124]">{review.reviewer}</h3>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] leading-4 text-[#5F6368]">
                <GoogleStars rating={review.rating} />
                <span title={exactDate(review.createdAt)}>{relativeDate(review.createdAt)}</span>
                {review.edited && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-[#FDE293] bg-[#FEF7E0] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#B45309]">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-2.5 w-2.5">
                      <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" />
                    </svg>
                    Edited
                  </span>
                )}
              </div>
            </div>

            {onFlag && !review.replied && !review.skipped && (
              <div className="relative shrink-0">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    setMenuOpen((v) => !v);
                  }}
                  className="rounded-full p-1 text-[#5F6368] hover:bg-[#F1F3F4] focus-visible:ring-2 focus-visible:ring-[#1A73E8]/30"
                  aria-label="Review actions"
                  tabIndex={0}
                >
                  <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                    <circle cx="12" cy="5" r="1.5" />
                    <circle cx="12" cy="12" r="1.5" />
                    <circle cx="12" cy="19" r="1.5" />
                  </svg>
                </button>
                {menuOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                    <div className="absolute right-0 top-full z-20 mt-1 w-48 rounded-lg border border-[#DADCE0] bg-white py-1 shadow-lg">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          e.preventDefault();
                          onFlag?.(review.id);
                          setMenuOpen(false);
                        }}
                        className="block w-full px-4 py-2 text-left text-[12px] font-medium text-[#5F6368] hover:bg-[#F1F3F4]"
                      >
                        Mark as unavailable on Google
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <p
            dir="auto"
            className="mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-[20px] text-[#202124]"
          >
            {displayText || <span className="italic text-[#5F6368]">No written comment - star rating only.</span>}
          </p>
          {isLong && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }}
              className="mt-1 text-[12px] font-medium leading-4 text-[#1A73E8] hover:text-[#174EA6] hover:underline underline-offset-2"
            >
              {expanded ? "Less" : "More"}
            </button>
          )}

          {review.edited && (review.previousText || review.previousRating != null) && (
            <div className="mt-2 rounded-lg border border-[#FDE293] bg-[#FEF7E0]/60 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-[#B45309]">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-3 w-3">
                    <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" />
                  </svg>
                  Before the edit
                </span>
                {review.previousRating != null && (
                  <span className="ml-auto inline-flex items-center gap-1.5">
                    <GoogleStars rating={review.previousRating} size="h-3 w-3" />
                    <span className="text-[11px] font-medium text-[#B45309]">{review.previousRating.toFixed(1)}</span>
                  </span>
                )}
              </div>
              <p className="mt-1 line-clamp-3 text-[12.5px] italic leading-[18px] text-[#8A6A3B] line-through decoration-[#D9B98C]/70 decoration-1">
                {review.previousText ? review.previousText : <span className="not-italic">No written comment - star rating only.</span>}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Owner response, connected to the reviewer avatar by the rail above. */}
      {hasReply && (
        <div className="flex gap-3 px-4 pb-4">
          <div className="flex flex-col items-center">
            <OwnerAvatar />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5 text-[12px] leading-4 text-[#5F6368]">
              <span className="font-medium text-[#202124]">(owner)</span>
              {review.replyAt && (
                <>
                  <span aria-hidden className="text-[#DADCE0]">·</span>
                  <span title={exactDate(review.replyAt)}>{relativeDate(review.replyAt)}</span>
                </>
              )}
            </div>
            <p
              dir="auto"
              className="mt-1 whitespace-pre-wrap break-words text-[13px] leading-[20px] text-[#202124]"
            >
              {review.replyText}
            </p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                open();
              }}
              className="mt-2 rounded-md border border-[#DADCE0] px-3 py-1.5 text-[12px] font-medium text-[#1A73E8] transition hover:bg-[#F8F9FA] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#1A73E8]"
            >
              Edit
            </button>
          </div>
        </div>
      )}

      <footer className="flex flex-wrap items-center gap-2 border-t border-[#E8EAED] px-4 py-2.5">
        {review.replied ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium leading-4 text-[#137333]">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#34A853]" />
            Replied
          </span>
        ) : review.skipped ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium leading-4 text-[#5F6368]">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#AAAAAA]" />
            Unavailable on Google
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium leading-4 text-[#5F6368]">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#FABB05]" />
            Needs reply
          </span>
        )}

        <span aria-hidden className="text-[#DADCE0]">·</span>
        <span className="text-[12px] leading-4 text-[#5F6368]" title={exactDate(review.createdAt)}>
          Updated {relativeDate(review.createdAt)}
        </span>

        <span className="flex-1" />

        {review.reviewUrl && (
          <a
            href={review.reviewUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-[12px] font-medium leading-4 text-[#1A73E8] hover:text-[#174EA6] hover:underline underline-offset-2"
          >
            View on Google
          </a>
        )}

        {review.sentiment && (
          <span className="hidden rounded-full border border-[#E8EAED] bg-[#F8F9FA] px-2 py-0.5 text-[11px] font-medium capitalize text-[#5F6368] sm:inline-flex">
            {review.sentiment}
          </span>
        )}
      </footer>
    </article>
  );
}
