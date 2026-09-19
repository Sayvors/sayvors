"use client";

import Image from "next/image";
import { useState } from "react";

export interface GoogleReview {
  id: string;
  reviewer: string;
  rating: number;
  comment: string;
  createdAt: string;
  locationName: string;
  replied: boolean;
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
  return d.toLocaleDateString("en", { month: "short", day: "numeric", year: d.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined });
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

function EnvelopeIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden {...props}>
      <path
        d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5v-11Z"
        stroke="currentColor"
        strokeWidth={1.5}
      />
      <path d="M4.5 7.5 12 13l7.5-5.5" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function GoogleGIcon() {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-[#DADCE0]">
      <Image src="/google.svg" alt="Google" width={16} height={16} className="h-4 w-4" />
    </span>
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
  const displayText = expanded || !isLong ? review.comment : `${review.comment.slice(0, 180).trimEnd()}…`;

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
      className="group w-full cursor-pointer rounded-lg border border-[#DADCE0] bg-white text-left outline-none transition hover:bg-[#F8F9FA] focus-visible:ring-2 focus-visible:ring-[#1A73E8]/30 focus-visible:ring-offset-1"
    >
      {/* Top row — reviewer + Google mark */}
      <div className="flex items-start gap-3 px-4 pt-4">
        {/* Avatar — neutral Material style */}
        <span
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#F1F3F4] text-[11px] font-medium text-[#5F6368] ring-1 ring-[#E8EAED]"
        >
          {initials(review.reviewer)}
        </span>

        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-medium leading-5 text-[#202124]">{review.reviewer}</h3>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] leading-4 text-[#5F6368]">
            <span className="inline-flex items-center gap-1">
              <EnvelopeIcon className="h-3.5 w-3.5 text-[#5F6368]" />
              Posted on <GoogleWordmark className="text-[12px]" />
            </span>
            <span aria-hidden className="text-[#DADCE0]">
              •
            </span>
            <span title={exactDate(review.createdAt)}>{relativeDate(review.createdAt)}</span>
          </div>
        </div>

        <GoogleGIcon />
        {onFlag && !review.replied && !review.skipped && (
          <div className="relative ml-1">
            <button
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); setMenuOpen((v) => !v); }}
              className="rounded-full p-1 text-[#5F6368] hover:bg-[#F1F3F4] focus-visible:ring-2 focus-visible:ring-[#1A73E8]/30"
              aria-label="Review actions"
              tabIndex={0}
            >
              <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
              </svg>
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-full z-20 mt-1 w-48 rounded-lg border border-[#DADCE0] bg-white py-1 shadow-lg">
                  <button
                    onClick={(e) => { e.stopPropagation(); e.preventDefault(); onFlag?.(review.id); setMenuOpen(false); }}
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

      {/* Location — secondary row */}
      <div className="px-4 pt-2">
        <p className="truncate text-[12px] leading-4 text-[#5F6368]">{review.locationName}</p>
      </div>

      {/* Stars */}
      <div className="flex items-center gap-2 px-4 pt-2.5">
        <GoogleStars rating={review.rating} />
        <span className="text-[12px] font-medium text-[#202124]">{review.rating.toFixed(1)}</span>
        <span className="flex-1" />
        {review.edited && (
          <span className="inline-flex items-center gap-1 rounded-full border border-[#FDE293] bg-[#FEF7E0] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#B45309]">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-2.5 w-2.5">
              <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" />
            </svg>
            After the edit
          </span>
        )}
      </div>

      {/* Before-the-edit snapshot — reviewer changed this review */}
      {review.edited && (review.previousText || review.previousRating != null) && (
        <div className="px-4 pt-2">
          <div
            className="rounded-lg border border-[#FDE293] bg-[#FEF7E0]/60 px-3 py-2.5"
            style={{ fontFamily: "Roboto, Arial, sans-serif" }}
          >
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
              {review.previousText ? `“${review.previousText}”` : <span className="not-italic">No written comment — star rating only.</span>}
            </p>
          </div>
        </div>
      )}

      {/* Comment — expandable */}
      <div className="px-4 pt-2">
        <p className="whitespace-pre-wrap break-words text-[13px] leading-[20px] text-[#202124]">
          {displayText ? `“${displayText}”` : <span className="italic text-[#5F6368]">No written comment — star rating only.</span>}
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
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
      </div>

      {/* Footer — status + timestamp + action */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#E8EAED] px-4 py-3">
        {/* Status indicator — Google green for completed */}
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

        <span aria-hidden className="text-[#DADCE0]">
          •
        </span>

        {/* Updated timestamp */}
        <span className="text-[12px] leading-4 text-[#5F6368]" title={exactDate(review.createdAt)}>
          Updated {relativeDate(review.createdAt)}
        </span>

        <span className="flex-1" />

        {/* Reviewer edited this review after the first sync — amber chip */}
        {review.edited && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-[#FDE293] bg-[#FEF7E0] px-2 py-0.5 text-[11px] font-medium text-[#B45309]"
            title="The customer changed this review after it was first synced"
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden className="h-3 w-3">
              <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
            </svg>
            Edited
          </span>
        )}

        {/* Optional external link — blue Material link */}
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

        {/* Minimal sentiment tag when available — neutral chip */}
        {review.sentiment && (
          <span className="hidden rounded-full border border-[#E8EAED] bg-[#F8F9FA] px-2 py-0.5 text-[11px] font-medium capitalize text-[#5F6368] sm:inline-flex">
            {review.sentiment}
          </span>
        )}
      </div>
    </article>
  );
}
